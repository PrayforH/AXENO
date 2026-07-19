"""Run creation, lookup and cancellation use cases."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from harness.application.events import EventService
from harness.application.types import Clock, IdGenerator
from harness.core.errors import ConflictError
from harness.core.models import Run, RunStatus, Session
from harness.core.ports import RunRepository, RunTask, SessionRepository, TaskQueue
from harness.core.state_machine import transition
from harness.deployments.boundaries import environment_quota_boundary
from harness.observability.provider import Observability


@dataclass(frozen=True)
class RunQuotaPlan:
    max_budget_usd: float | None
    max_model_tokens: int | None
    ttl_seconds: int


class RunAdmission(Protocol):
    async def admit_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        agent_name: str,
        environment: str | None,
        max_budget_usd: float | None,
        max_model_tokens: int | None,
        ttl_seconds: int,
    ) -> tuple[object, ...]: ...

    async def release_subject(self, tenant_id: str, subject_id: str) -> int: ...


RunQuotaPlanResolver = Callable[[str, str, str], Awaitable[RunQuotaPlan]]


def apply_environment_quota(plan: RunQuotaPlan, session: Session) -> RunQuotaPlan:
    boundary = environment_quota_boundary(session)
    if boundary is None:
        return plan

    budget = plan.max_budget_usd
    if boundary.max_run_budget_usd is not None:
        budget = (
            boundary.max_run_budget_usd
            if budget is None
            else min(budget, boundary.max_run_budget_usd)
        )
    tokens = plan.max_model_tokens
    if boundary.max_model_tokens is not None:
        tokens = (
            boundary.max_model_tokens
            if tokens is None
            else min(tokens, boundary.max_model_tokens)
        )

    return RunQuotaPlan(
        max_budget_usd=budget,
        max_model_tokens=tokens,
        ttl_seconds=plan.ttl_seconds,
    )


class RunService:
    def __init__(
        self,
        sessions: SessionRepository,
        runs: RunRepository,
        queue: TaskQueue,
        events: EventService,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        observability: Observability | None = None,
        admission: RunAdmission | None = None,
        quota_plan_resolver: RunQuotaPlanResolver | None = None,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._queue = queue
        self._events = events
        self._clock = clock
        self._id_generator = id_generator
        self._observability = observability
        self._admission = admission
        self._quota_plan_resolver = quota_plan_resolver

    async def create(
        self,
        tenant_id: str,
        session_id: str,
        idempotency_key: str,
        *,
        input: dict[str, object] | None = None,
    ) -> Run:
        session = await self._sessions.get(tenant_id, session_id)
        existing = await self._runs.find_by_idempotency_key(tenant_id, session_id, idempotency_key)
        if existing is not None:
            self._annotate_trace(
                session_id,
                existing.run_id,
                existing.input.get("prompt"),
            )
            return existing
        timestamp = self._clock()
        run_id = self._id_generator("run")
        run_input = input or {}
        self._annotate_trace(session_id, run_id, run_input.get("prompt"))
        run = Run(
            run_id=run_id,
            session_id=session_id,
            tenant_id=tenant_id,
            status=RunStatus.QUEUED,
            idempotency_key=idempotency_key,
            created_at=timestamp,
            updated_at=timestamp,
            input=run_input,
            trace_context=(self._observability.inject() if self._observability is not None else {}),
        )
        admitted = False
        if self._admission is not None:
            plan = (
                await self._quota_plan_resolver(
                    tenant_id, session.agent_name, session.agent_version
                )
                if self._quota_plan_resolver is not None
                else RunQuotaPlan(None, None, 3600)
            )
            plan = apply_environment_quota(plan, session)
            await self._admission.admit_run(
                tenant_id=tenant_id,
                run_id=run_id,
                agent_name=session.agent_name,
                environment=session.environment,
                max_budget_usd=plan.max_budget_usd,
                max_model_tokens=plan.max_model_tokens,
                ttl_seconds=plan.ttl_seconds,
            )
            admitted = True
        try:
            await self._runs.add(run)
        except Exception:
            if admitted and self._admission is not None:
                await self._admission.release_subject(tenant_id, run_id)
            raise
        await self._events.append(
            tenant_id=tenant_id,
            run_id=run.run_id,
            session_id=session_id,
            event_type="run.queued",
        )
        await self._queue.enqueue(RunTask(tenant_id=tenant_id, run_id=run.run_id))
        return run

    def _annotate_trace(
        self,
        session_id: str,
        run_id: str,
        prompt: object | None = None,
    ) -> None:
        if self._observability is None:
            return
        self._observability.annotate_current_span(
            {
                "langfuse.session.id": session_id,
                "langfuse.trace.metadata.run_id": run_id,
                "session.id": session_id,
                "run.id": run_id,
            }
        )
        self._observability.annotate_current_io(
            input_value=prompt,
            trace_level=True,
        )

    async def get(self, tenant_id: str, run_id: str) -> Run:
        return await self._runs.get(tenant_id, run_id)

    async def list_for_sessions(
        self, tenant_id: str, session_ids: list[str], *, limit: int = 200
    ) -> list[Run]:
        return await self._runs.list_for_sessions(tenant_id, session_ids, limit=limit)

    async def cancel(self, tenant_id: str, run_id: str) -> Run:
        current = await self._runs.get(tenant_id, run_id)
        if current.status.is_terminal:
            if self._admission is not None:
                await self._admission.release_subject(tenant_id, run_id)
            return current
        if current.status is not RunStatus.CANCELLING:
            cancelling = current.model_copy(
                update={
                    "status": transition(current.status, RunStatus.CANCELLING),
                    "updated_at": self._clock(),
                    "fencing_token": current.fencing_token + 1,
                }
            )
            if not await self._runs.compare_and_set(current.status, cancelling):
                current = await self._runs.get(tenant_id, run_id)
                if current.status.is_terminal:
                    return current
                if current.status is not RunStatus.CANCELLING:
                    raise ConflictError(f"run changed while cancellation was requested: {run_id}")
            else:
                current = cancelling
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=current.session_id,
                    event_type="run.cancelling",
                )

        cancelled = current.model_copy(
            update={
                "status": transition(current.status, RunStatus.CANCELLED),
                "updated_at": self._clock(),
                "fencing_token": current.fencing_token + 1,
            }
        )
        if not await self._runs.compare_and_set(RunStatus.CANCELLING, cancelled):
            latest = await self._runs.get(tenant_id, run_id)
            if latest.status.is_terminal:
                return latest
            raise ConflictError(f"run changed while cancellation completed: {run_id}")
        await self._events.append(
            tenant_id=tenant_id,
            run_id=run_id,
            session_id=current.session_id,
            event_type="run.cancelled",
        )
        if self._admission is not None:
            await self._admission.release_subject(tenant_id, run_id)
        return cancelled
