"""Coordinates one Run across repositories, Sandbox and Agent runtime."""

from typing import Any, cast
from uuid import uuid4

from harness.application.approvals import ApprovalService
from harness.application.artifacts import ArtifactService
from harness.application.events import EventService
from harness.application.types import Clock
from harness.application.workspaces import WorkspaceService
from harness.core.errors import ConflictError
from harness.core.models import Run, RunStatus
from harness.core.ports import RunRepository, SessionRepository
from harness.core.state_machine import transition
from harness.observability.provider import Observability
from harness.policy.models import PolicyContext, PolicyDecision
from harness.policy.rules import PolicyEngine
from harness.runtime.base import AgentRuntime, RuntimeContext
from harness.sandbox.base import SandboxHandle, SandboxProvider


class RunOrchestrator:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        runs: RunRepository,
        events: EventService,
        runtime: AgentRuntime,
        sandbox: SandboxProvider,
        clock: Clock,
        policy: PolicyEngine | None = None,
        approvals: ApprovalService | None = None,
        workspaces: WorkspaceService | None = None,
        observability: Observability | None = None,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._events = events
        self._runtime = runtime
        self._sandbox = sandbox
        self._clock = clock
        self._policy = policy
        self._approvals = approvals
        self._workspaces = workspaces
        self._observability = observability
        self._artifacts = artifacts

    async def _move(
        self,
        current: Run,
        target: RunStatus,
        *,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Run:
        next_status = transition(current.status, target)
        updated = current.model_copy(
            update={
                "status": next_status,
                "updated_at": self._clock(),
                "fencing_token": current.fencing_token + 1,
                "error_code": error_code,
            }
        )
        if not await self._runs.compare_and_set(current.status, updated):
            raise ConflictError(f"stale worker attempted to update run: {current.run_id}")
        await self._events.append(
            tenant_id=current.tenant_id,
            run_id=current.run_id,
            session_id=current.session_id,
            event_type=f"run.{target.value}",
            payload=payload,
        )
        return updated

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        if self._observability is None:
            return await self._execute(tenant_id, run_id)
        run = await self._runs.get(tenant_id, run_id)
        with self._observability.span(
            "harness.worker.run",
            carrier=run.trace_context,
            attributes={"run.id": run_id, "tenant.id": tenant_id},
        ):
            return await self._execute(tenant_id, run_id)

    async def _execute(self, tenant_id: str, run_id: str) -> Run:
        run = await self._runs.get(tenant_id, run_id)
        if run.status.is_terminal:
            return run
        if run.status is RunStatus.CANCELLING:
            return await self._move(run, RunStatus.CANCELLED)
        is_resume = run.status is RunStatus.RUNNING
        if run.status is not RunStatus.QUEUED and not is_resume:
            raise ConflictError(f"run is already owned or paused: {run_id} ({run.status.value})")

        handle: SandboxHandle | None = None
        try:
            if not is_resume:
                run = await self._move(run, RunStatus.PROVISIONING)
            handle = await self._sandbox.provision(run)
            session = await self._sessions.get(tenant_id, run.session_id)
            if not is_resume:
                run = await self._move(run, RunStatus.RUNNING)
            else:
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type="run.resumed",
                )
            context = RuntimeContext(run=run, session=session, workspace=handle.path)
            active_message_id: str | None = None
            async for runtime_event in self._runtime.execute(context):
                payload = dict(runtime_event.payload)
                if runtime_event.type == "message.start":
                    active_message_id = str(
                        payload.get("message_id")
                        or f"assistant-{run_id}-{uuid4().hex}"
                    )
                    payload["message_id"] = active_message_id
                elif runtime_event.type in {"message.delta", "message.completed"}:
                    active_message_id = str(
                        payload.get("message_id")
                        or active_message_id
                        or f"assistant-{run_id}-{uuid4().hex}"
                    )
                    payload["message_id"] = active_message_id
                if runtime_event.type == "artifact.output" and self._artifacts is not None:
                    relative_path = str(payload.get("path", ""))
                    artifact_path = (handle.path / relative_path).resolve()
                    if not artifact_path.is_relative_to(handle.path.resolve()):
                        raise ValueError("runtime artifact path escaped the workspace")
                    artifact = await self._artifacts.upload(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        name=str(payload.get("name", artifact_path.name)),
                        media_type=str(
                            payload.get("media_type", "application/octet-stream")
                        ),
                        content=artifact_path.read_bytes(),
                    )
                    artifact_payload = artifact.model_dump(mode="json")
                    if active_message_id is not None:
                        artifact_payload["message_id"] = active_message_id
                    await self._events.append(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        session_id=run.session_id,
                        event_type="artifact.ready",
                        payload=artifact_payload,
                    )
                    continue
                if runtime_event.type == "tool.request" and self._policy is not None:
                    tool_name = str(payload.get("name", ""))
                    tool_call_id = str(payload.get("tool_call_id", ""))
                    arguments = payload.get("arguments", {})
                    if not isinstance(arguments, dict):
                        arguments = {}
                    typed_arguments = cast(dict[str, Any], arguments)
                    result = self._policy.evaluate(
                        PolicyContext(
                            tenant_id=tenant_id,
                            agent_name=session.agent_name,
                            tool_name=tool_name,
                            arguments=typed_arguments,
                        )
                    )
                    if result.decision is PolicyDecision.DENY:
                        await self._events.append(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            session_id=run.session_id,
                            event_type="tool.result",
                            payload={
                                "tool_call_id": tool_call_id,
                                "is_error": True,
                                "error": {
                                    "code": "policy_denied",
                                    "message": result.reason,
                                },
                            },
                        )
                        continue
                    if result.decision is PolicyDecision.ASK:
                        if self._approvals is None:
                            raise RuntimeError("approval service is not configured")
                        approval = await self._approvals.request(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            tool_call_id=tool_call_id,
                            reason=result.reason,
                            message_id=active_message_id,
                        )
                        if approval.status.value == "pending":
                            if active_message_id is not None:
                                await self._events.append(
                                    tenant_id=tenant_id,
                                    run_id=run_id,
                                    session_id=run.session_id,
                                    event_type="message.completed",
                                    payload={"message_id": active_message_id},
                                )
                            return await self._runs.get(tenant_id, run_id)
                    await self._events.append(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        session_id=run.session_id,
                        event_type="tool.allowed",
                        payload={"tool_call_id": tool_call_id},
                    )
                    continue
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type=runtime_event.type,
                    payload=payload,
                )
                if runtime_event.type == "message.completed":
                    active_message_id = None
            if self._workspaces is not None:
                snapshot = await self._workspaces.archive(
                    tenant_id=tenant_id,
                    session_id=run.session_id,
                    workspace=handle.path,
                )
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type="workspace.archived",
                    payload=snapshot.model_dump(mode="json"),
                )
            return await self._move(run, RunStatus.SUCCEEDED)
        except Exception as error:  # noqa: BLE001 - boundary converts failures to Run state
            latest = await self._runs.get(tenant_id, run_id)
            if latest.status.is_terminal:
                return latest
            return await self._move(
                latest,
                RunStatus.FAILED,
                error_code="runtime_error",
                payload={"error_type": type(error).__name__},
            )
        finally:
            if handle is not None:
                await self._sandbox.destroy(handle)
