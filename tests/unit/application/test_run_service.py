from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness.adapters.memory import (
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTaskQueue,
)
from harness.application.events import EventService
from harness.application.runs import RunService
from harness.config import Settings
from harness.core.models import RunStatus, Session
from harness.observability.provider import build_observability

NOW = datetime(2026, 7, 11, tzinfo=UTC)


def id_generator() -> Callable[[str], str]:
    counters: dict[str, int] = {}

    def generate(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    return generate


@pytest.mark.asyncio
async def test_create_run_is_idempotent_and_queues_once() -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    queue = InMemoryTaskQueue()
    events = InMemoryEventRepository()
    bus = InMemoryEventBus()
    ids = id_generator()
    await sessions.add(
        Session(
            session_id="session-1",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="1.0.0",
            created_at=NOW,
        )
    )
    service = RunService(
        sessions,
        runs,
        queue,
        EventService(events, bus, clock=lambda: NOW, id_generator=ids),
        clock=lambda: NOW,
        id_generator=ids,
    )

    first = await service.create("tenant-a", "session-1", "idem-1")
    second = await service.create("tenant-a", "session-1", "idem-1")

    assert first == second
    assert first.status is RunStatus.QUEUED
    assert (await queue.dequeue()).run_id == first.run_id  # type: ignore[union-attr]
    assert await queue.dequeue() is None
    stored_events = await events.list_after("tenant-a", first.run_id, 0)
    assert [(item.sequence, item.type) for item in stored_events] == [(1, "run.queued")]


@pytest.mark.asyncio
async def test_create_run_annotates_the_api_trace_with_session_identity() -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    queue = InMemoryTaskQueue()
    events = InMemoryEventRepository()
    bus = InMemoryEventBus()
    ids = id_generator()
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(
            otel_enabled=True,
            otlp_endpoint="http://unused/v1/traces",
            otel_content_capture="redacted",
        ),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )
    await sessions.add(
        Session(
            session_id="session-1",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="1.0.0",
            created_at=NOW,
        )
    )
    service = RunService(
        sessions,
        runs,
        queue,
        EventService(events, bus, clock=lambda: NOW, id_generator=ids),
        clock=lambda: NOW,
        id_generator=ids,
        observability=observability,
    )

    with observability.span("harness.api.request"):
        run = await service.create(
            "tenant-a",
            "session-1",
            "idem-1",
            input={"prompt": "用户问题 token=private-value"},
        )

    span = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert span.attributes["langfuse.session.id"] == "session-1"
    assert span.attributes["langfuse.trace.metadata.run_id"] == run.run_id
    assert span.attributes["session.id"] == "session-1"
    assert span.attributes["run.id"] == run.run_id
    assert span.attributes["langfuse.trace.input"] == (
        "用户问题 token=[REDACTED]"
    )
    assert "traceparent" in run.trace_context


@pytest.mark.asyncio
async def test_cancel_reaches_cancelled_and_emits_both_lifecycle_events() -> None:
    sessions = InMemorySessionRepository()
    runs = InMemoryRunRepository()
    queue = InMemoryTaskQueue()
    events = InMemoryEventRepository()
    bus = InMemoryEventBus()
    ids = id_generator()
    await sessions.add(
        Session(
            session_id="session-1",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="1.0.0",
            created_at=NOW,
        )
    )
    service = RunService(
        sessions,
        runs,
        queue,
        EventService(events, bus, clock=lambda: NOW, id_generator=ids),
        clock=lambda: NOW,
        id_generator=ids,
    )
    run = await service.create("tenant-a", "session-1", "idem-1")

    cancelled = await service.cancel("tenant-a", run.run_id)

    assert cancelled.status is RunStatus.CANCELLED
    stored_events = await events.list_after("tenant-a", run.run_id, 0)
    assert [(item.sequence, item.type) for item in stored_events] == [
        (1, "run.queued"),
        (2, "run.cancelling"),
        (3, "run.cancelled"),
    ]

    assert await service.cancel("tenant-a", run.run_id) == cancelled
