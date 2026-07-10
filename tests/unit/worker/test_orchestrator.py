from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.adapters.memory import (
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
)
from harness.application.events import EventService
from harness.core.models import Run, RunStatus, Session
from harness.runtime.fake import FakeRuntime
from harness.sandbox.local import LocalSandboxProvider
from harness.worker.orchestrator import RunOrchestrator

NOW = datetime(2026, 7, 11, tzinfo=UTC)


def ids() -> Callable[[str], str]:
    counters: dict[str, int] = {}

    def generate(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    return generate


async def arrange(tmp_path: Path, *, fail_runtime: bool = False):
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    event_repository = InMemoryEventRepository()
    runtime = FakeRuntime(fail=fail_runtime)
    sandbox = LocalSandboxProvider(root=tmp_path)
    session = Session(
        session_id="session-1",
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="1.0.0",
        created_at=NOW,
    )
    run = Run(
        run_id="run-1",
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        status=RunStatus.QUEUED,
        idempotency_key="idem-1",
        created_at=NOW,
        updated_at=NOW,
        input={"prompt": "hello harness"},
    )
    await sessions.add(session)
    await runs.add(run)
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(
            event_repository,
            InMemoryEventBus(),
            clock=lambda: NOW,
            id_generator=ids(),
        ),
        runtime=runtime,
        sandbox=sandbox,
        clock=lambda: NOW,
    )
    return orchestrator, runtime, runs, event_repository


@pytest.mark.asyncio
async def test_executes_run_and_cleans_sandbox(tmp_path: Path) -> None:
    orchestrator, runtime, runs, event_repository = await arrange(tmp_path)

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.SUCCEEDED
    assert runtime.execution_count == 1
    assert list(tmp_path.iterdir()) == []
    events = await event_repository.list_after("tenant-a", "run-1", 0)
    assert [event.type for event in events] == [
        "run.provisioning",
        "run.running",
        "message.start",
        "message.delta",
        "message.completed",
        "run.succeeded",
    ]
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_execute_twice(tmp_path: Path) -> None:
    orchestrator, runtime, _, _ = await arrange(tmp_path)

    first = await orchestrator.execute("tenant-a", "run-1")
    second = await orchestrator.execute("tenant-a", "run-1")

    assert first == second
    assert runtime.execution_count == 1


@pytest.mark.asyncio
async def test_runtime_failure_marks_run_failed_and_cleans_sandbox(tmp_path: Path) -> None:
    orchestrator, runtime, _, event_repository = await arrange(tmp_path, fail_runtime=True)

    result = await orchestrator.execute("tenant-a", "run-1")

    assert result.status is RunStatus.FAILED
    assert result.error_code == "runtime_error"
    assert runtime.execution_count == 1
    assert list(tmp_path.iterdir()) == []
    events = await event_repository.list_after("tenant-a", "run-1", 0)
    assert events[-1].type == "run.failed"

