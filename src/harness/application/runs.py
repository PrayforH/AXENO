"""Run creation, lookup and cancellation use cases."""

from harness.application.events import EventService
from harness.application.types import Clock, IdGenerator
from harness.core.errors import ConflictError
from harness.core.models import Run, RunStatus
from harness.core.ports import RunRepository, RunTask, SessionRepository, TaskQueue
from harness.core.state_machine import transition
from harness.observability.provider import Observability


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
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._queue = queue
        self._events = events
        self._clock = clock
        self._id_generator = id_generator
        self._observability = observability

    async def create(
        self,
        tenant_id: str,
        session_id: str,
        idempotency_key: str,
        *,
        input: dict[str, object] | None = None,
    ) -> Run:
        await self._sessions.get(tenant_id, session_id)
        existing = await self._runs.find_by_idempotency_key(tenant_id, session_id, idempotency_key)
        if existing is not None:
            self._annotate_trace(session_id, existing.run_id)
            return existing
        timestamp = self._clock()
        run_id = self._id_generator("run")
        self._annotate_trace(session_id, run_id)
        run = Run(
            run_id=run_id,
            session_id=session_id,
            tenant_id=tenant_id,
            status=RunStatus.QUEUED,
            idempotency_key=idempotency_key,
            created_at=timestamp,
            updated_at=timestamp,
            input=input or {},
            trace_context=(self._observability.inject() if self._observability is not None else {}),
        )
        await self._runs.add(run)
        await self._events.append(
            tenant_id=tenant_id,
            run_id=run.run_id,
            session_id=session_id,
            event_type="run.queued",
        )
        await self._queue.enqueue(RunTask(tenant_id=tenant_id, run_id=run.run_id))
        return run

    def _annotate_trace(self, session_id: str, run_id: str) -> None:
        if self._observability is None:
            return
        self._observability.annotate_current_span(
            {
                "langfuse.session.id": session_id,
                "session.id": session_id,
                "run.id": run_id,
            }
        )

    async def get(self, tenant_id: str, run_id: str) -> Run:
        return await self._runs.get(tenant_id, run_id)

    async def list_for_sessions(
        self, tenant_id: str, session_ids: list[str], *, limit: int = 200
    ) -> list[Run]:
        return await self._runs.list_for_sessions(
            tenant_id, session_ids, limit=limit
        )

    async def cancel(self, tenant_id: str, run_id: str) -> Run:
        current = await self._runs.get(tenant_id, run_id)
        if current.status.is_terminal:
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
                    raise ConflictError(
                        f"run changed while cancellation was requested: {run_id}"
                    )
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
        return cancelled
