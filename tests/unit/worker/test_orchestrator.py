import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness.adapters.memory import (
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
)
from harness.application.events import EventService
from harness.config import Settings
from harness.core.models import Run, RunStatus, Session
from harness.observability.provider import Observability, build_observability
from harness.policy.rules import PolicyEngine, default_policy_rules
from harness.runtime.base import RuntimeContext, RuntimeEvent
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


class ToolRuntime(FakeRuntime):
    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        yield RuntimeEvent(type="message.start")
        yield RuntimeEvent(
            type="tool.request",
            payload={
                "tool_call_id": "task-1",
                "name": "Task",
                "arguments": {"subagent_type": "helper"},
            },
        )
        yield RuntimeEvent(
            type="tool.result",
            payload={"tool_call_id": "task-1", "content": "done", "is_error": False},
        )
        yield RuntimeEvent(type="message.completed")


async def arrange(
    tmp_path: Path,
    *,
    fail_runtime: bool = False,
    runtime_override: FakeRuntime | None = None,
    policy: PolicyEngine | None = None,
    observability: Observability | None = None,
):
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    event_repository = InMemoryEventRepository()
    runtime = runtime_override or FakeRuntime(fail=fail_runtime)
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
        policy=policy,
        observability=observability,
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
async def test_executes_run_with_stage_level_traces(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )
    orchestrator, _, _, _ = await arrange(
        tmp_path, observability=observability
    )

    await orchestrator.execute("tenant-a", "run-1")

    assert {span.name for span in exporter.get_finished_spans()} >= {
        "harness.worker.run",
        "harness.sandbox.provision",
        "harness.memory.load",
        "harness.input.process",
        "harness.sandbox.prepare",
        "harness.runtime.execute",
        "harness.sandbox.collect",
        "harness.sandbox.destroy",
    }


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


class PausableRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.resume = asyncio.Event()

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        del context
        self.started.set()
        yield RuntimeEvent(type="message.start")
        await self.resume.wait()
        yield RuntimeEvent(type="message.delta", payload={"text": "too late"})


@pytest.mark.asyncio
async def test_policy_keeps_tool_request_for_ui_before_decision(tmp_path: Path) -> None:
    orchestrator, _, _, event_repository = await arrange(
        tmp_path,
        runtime_override=ToolRuntime(),
        policy=PolicyEngine(default_policy_rules()),
    )

    result = await orchestrator.execute("tenant-a", "run-1")

    events = await event_repository.list_after("tenant-a", "run-1", 0)
    tool_events = [event.type for event in events if event.type.startswith("tool.")]
    request = next(event for event in events if event.type == "tool.request")
    assert result.status is RunStatus.SUCCEEDED
    assert tool_events == ["tool.request", "tool.allowed", "tool.result"]
    assert request.payload["message_id"] == next(
        event.payload["message_id"] for event in events if event.type == "message.start"
    )


@pytest.mark.asyncio
async def test_cancellation_during_runtime_stops_at_next_event_boundary(
    tmp_path: Path,
) -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    runtime = PausableRuntime()
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
        idempotency_key="cancel-boundary",
        created_at=NOW,
        updated_at=NOW,
    )
    await sessions.add(session)
    await runs.add(run)
    orchestrator = RunOrchestrator(
        sessions=sessions,
        runs=runs,
        events=EventService(events, InMemoryEventBus(), clock=lambda: NOW, id_generator=ids()),
        runtime=runtime,
        sandbox=LocalSandboxProvider(root=tmp_path),
        clock=lambda: NOW,
    )

    execution = asyncio.create_task(orchestrator.execute("tenant-a", "run-1"))
    await runtime.started.wait()
    while (await runs.get("tenant-a", "run-1")).status is not RunStatus.RUNNING:
        await asyncio.sleep(0)
    current = await runs.get("tenant-a", "run-1")
    cancelling = current.model_copy(update={"status": RunStatus.CANCELLING})
    assert await runs.compare_and_set(RunStatus.RUNNING, cancelling)
    runtime.resume.set()

    result = await execution
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert result.status is RunStatus.CANCELLED
    assert "message.delta" not in [item.type for item in emitted]
