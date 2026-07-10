"""Coordinates one Run across repositories, Sandbox and Agent runtime."""

from typing import Any

from harness.application.events import EventService
from harness.application.types import Clock
from harness.core.errors import ConflictError
from harness.core.models import Run, RunStatus
from harness.core.ports import RunRepository, SessionRepository
from harness.core.state_machine import transition
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
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._events = events
        self._runtime = runtime
        self._sandbox = sandbox
        self._clock = clock

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
        run = await self._runs.get(tenant_id, run_id)
        if run.status.is_terminal:
            return run
        if run.status is RunStatus.CANCELLING:
            return await self._move(run, RunStatus.CANCELLED)
        if run.status is not RunStatus.QUEUED:
            raise ConflictError(f"run is already owned or paused: {run_id} ({run.status.value})")

        handle: SandboxHandle | None = None
        try:
            run = await self._move(run, RunStatus.PROVISIONING)
            handle = await self._sandbox.provision(run)
            session = await self._sessions.get(tenant_id, run.session_id)
            run = await self._move(run, RunStatus.RUNNING)
            context = RuntimeContext(run=run, session=session, workspace=handle.path)
            async for runtime_event in self._runtime.execute(context):
                await self._events.append(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    session_id=run.session_id,
                    event_type=runtime_event.type,
                    payload=runtime_event.payload,
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

