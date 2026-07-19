"""Use cases for managed Agent triggers and webhook invocation."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hmac import compare_digest

from harness.application.runs import RunService
from harness.application.sessions import SessionService
from harness.auth.audit import AuditService
from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import Run, Session
from harness.triggers.models import (
    AgentTrigger,
    CreateAgentTriggerRequest,
    CreatedAgentTrigger,
    StoredAgentTrigger,
    TriggerInvocation,
    TriggerKind,
    UpdateAgentTriggerRequest,
)
from harness.triggers.repositories import AgentTriggerRepository


class TriggerAuthenticationError(Exception):
    """A public trigger could not be authenticated without revealing why."""


def _default_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


class AgentTriggerService:
    def __init__(
        self,
        repository: AgentTriggerRepository,
        *,
        sessions: SessionService,
        runs: RunService,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
        secret_generator: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._sessions = sessions
        self._runs = runs
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or _default_id
        self._secrets = secret_generator or (lambda: secrets.token_urlsafe(32))

    async def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        request: CreateAgentTriggerRequest,
    ) -> CreatedAgentTrigger:
        secret = self._secrets()
        now = self._clock()
        stored = StoredAgentTrigger(
            tenantId=tenant_id,
            triggerId=self._ids("trigger"),
            name=request.name.strip(),
            kind=request.kind,
            agentName=agent_name,
            environment=request.environment,
            enabled=True,
            revision=1,
            createdBy=user_id,
            createdAt=now,
            updatedAt=now,
            schedule=request.schedule,
            chatops=request.chatops,
            nextFireAt=(
                now + timedelta(seconds=request.schedule.interval_seconds)
                if request.schedule is not None
                else None
            ),
            secretDigest=self._digest(secret),
        )
        await self._repository.add(stored)
        await self._record(
            stored,
            user_id=user_id,
            action="studio.trigger.create",
            details={"environment": stored.environment.value},
        )
        return CreatedAgentTrigger(trigger=stored.public(), secret=secret)

    async def list(self, tenant_id: str, agent_name: str) -> list[AgentTrigger]:
        return [
            trigger.public()
            for trigger in await self._repository.list_for_agent(tenant_id, agent_name)
        ]

    async def public_card(self, trigger_id: str) -> AgentTrigger:
        trigger = await self._repository.get_public(trigger_id)
        if not trigger.enabled:
            raise NotFoundError(f"Agent Trigger not found: {trigger_id}")
        return trigger.public()

    async def update(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trigger_id: str,
        request: UpdateAgentTriggerRequest,
    ) -> AgentTrigger:
        current = await self._repository.get(tenant_id, trigger_id)
        updated = current.model_copy(
            update={
                "name": request.name.strip(),
                "enabled": request.enabled,
                "revision": current.revision + 1,
                "updated_at": self._clock(),
            }
        )
        await self._repository.replace(request.expected_revision, updated)
        await self._record(
            updated,
            user_id=user_id,
            action="studio.trigger.update",
            details={"enabled": updated.enabled},
        )
        return updated.public()

    async def rotate_secret(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trigger_id: str,
        expected_revision: int,
    ) -> CreatedAgentTrigger:
        current = await self._repository.get(tenant_id, trigger_id)
        secret = self._secrets()
        updated = current.model_copy(
            update={
                "secret_digest": self._digest(secret),
                "revision": current.revision + 1,
                "updated_at": self._clock(),
            }
        )
        await self._repository.replace(expected_revision, updated)
        await self._record(
            updated,
            user_id=user_id,
            action="studio.trigger.rotate_secret",
        )
        return CreatedAgentTrigger(trigger=updated.public(), secret=secret)

    async def invoke(
        self,
        *,
        trigger_id: str,
        secret: str,
        idempotency_key: str,
        prompt: str,
    ) -> tuple[TriggerInvocation, Run]:
        trigger = await self._authenticate(trigger_id, secret)
        return await self._invoke_stored(
            trigger,
            idempotency_key=idempotency_key,
            prompt=prompt,
        )

    async def _invoke_stored(
        self,
        trigger: StoredAgentTrigger,
        *,
        idempotency_key: str,
        prompt: str,
    ) -> tuple[TriggerInvocation, Run]:
        trigger_id = trigger.trigger_id
        session_id = self._session_id(trigger_id, idempotency_key)
        workload_id = f"trigger:{trigger_id}"
        session = await self._existing_session(trigger, session_id, workload_id)
        if session is None:
            session = await self._sessions.create(
                trigger.tenant_id,
                workload_id,
                trigger.agent_name,
                None,
                session_id=session_id,
                environment=trigger.environment,
                api_key_id=trigger.trigger_id,
            )
        run = await self._runs.create(
            trigger.tenant_id,
            session.session_id,
            idempotency_key,
            input={
                "prompt": prompt,
                "trigger_id": trigger_id,
                "trigger_kind": trigger.kind,
            },
        )
        if run.input.get("prompt") != prompt or run.input.get("trigger_id") != trigger_id:
            raise ConflictError("Trigger idempotency key was reused with another payload")
        trigger = await self._repository.touch_invoked(trigger_id, self._clock())
        await self._record(
            trigger,
            user_id=workload_id,
            action="trigger.invoke",
            details={"run_id": run.run_id, "session_id": session.session_id},
        )
        if session.deployment_snapshot_id is None:
            raise ConflictError("Trigger Session did not resolve a deployment snapshot")
        return (
            TriggerInvocation(
                triggerId=trigger_id,
                sessionId=session.session_id,
                runId=run.run_id,
                status=run.status,
                environment=trigger.environment,
                agentName=session.agent_name,
                agentVersion=session.agent_version,
                deploymentSnapshotId=session.deployment_snapshot_id,
            ),
            run,
        )

    async def invoke_chatops(
        self,
        *,
        trigger_id: str,
        secret: str,
        message_id: str,
        channel_id: str,
        prompt: str,
    ) -> tuple[TriggerInvocation, Run]:
        trigger = await self._authenticate(trigger_id, secret)
        if trigger.kind is not TriggerKind.CHATOPS or trigger.chatops is None:
            raise TriggerAuthenticationError
        allowed = trigger.chatops.allowed_channel_ids
        if allowed and channel_id not in allowed:
            raise TriggerAuthenticationError
        return await self._invoke_stored(
            trigger,
            idempotency_key=f"chatops:{message_id}",
            prompt=prompt,
        )

    async def dispatch_due(self, *, limit: int = 50) -> int:
        now = self._clock()
        dispatched = 0
        for trigger in await self._repository.list_due(now, limit=limit):
            if trigger.schedule is None or trigger.next_fire_at is None:
                continue
            scheduled_at = trigger.next_fire_at
            next_fire_at = scheduled_at + timedelta(
                seconds=trigger.schedule.interval_seconds
            )
            advanced = await self._repository.advance_schedule(
                trigger.trigger_id,
                expected_next_fire_at=scheduled_at,
                next_fire_at=next_fire_at,
            )
            if not advanced:
                continue
            try:
                await self._invoke_stored(
                    trigger,
                    idempotency_key=f"schedule:{scheduled_at.isoformat()}",
                    prompt=trigger.schedule.prompt,
                )
            except Exception:
                # Make the deterministic slot eligible for retry when dispatch
                # fails before a worker can own the resulting Run.
                await self._repository.advance_schedule(
                    trigger.trigger_id,
                    expected_next_fire_at=next_fire_at,
                    next_fire_at=scheduled_at,
                )
                raise
            dispatched += 1
        return dispatched

    async def run(
        self, *, trigger_id: str, secret: str, run_id: str
    ) -> Run:
        trigger = await self._authenticate(trigger_id, secret)
        run = await self._runs.get(trigger.tenant_id, run_id)
        if run.input.get("trigger_id") != trigger_id:
            raise TriggerAuthenticationError
        return run

    async def _authenticate(
        self, trigger_id: str, secret: str
    ) -> StoredAgentTrigger:
        supplied = self._digest(secret)
        try:
            trigger = await self._repository.get_public(trigger_id)
        except NotFoundError as error:
            compare_digest(supplied, "0" * 64)
            raise TriggerAuthenticationError from error
        if not trigger.enabled or not compare_digest(supplied, trigger.secret_digest):
            raise TriggerAuthenticationError
        return trigger

    async def _existing_session(
        self, trigger: StoredAgentTrigger, session_id: str, workload_id: str
    ) -> Session | None:
        try:
            session = await self._sessions.get(trigger.tenant_id, session_id)
        except NotFoundError:
            return None
        if (
            session.user_id != workload_id
            or session.agent_name != trigger.agent_name
            or session.environment != trigger.environment.value
        ):
            raise ConflictError("Trigger idempotency key resolved to another Session")
        return session

    async def _record(
        self,
        trigger: StoredAgentTrigger,
        *,
        user_id: str,
        action: str,
        details: dict[str, object] | None = None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            tenant_id=trigger.tenant_id,
            user_id=user_id,
            action=action,
            resource_type="agent_trigger",
            resource_id=trigger.trigger_id,
            details=details,
        )

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()

    @staticmethod
    def _session_id(trigger_id: str, idempotency_key: str) -> str:
        digest = hashlib.sha256(f"{trigger_id}:{idempotency_key}".encode()).hexdigest()
        return f"trigger_session_{digest[:32]}"
