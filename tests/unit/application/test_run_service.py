from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from harness.adapters.memory import (
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
    InMemorySessionRepository,
    InMemoryTaskQueue,
)
from harness.application.events import EventService
from harness.application.runs import RunService
from harness.core.models import RunStatus, Session

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
async def test_cancel_moves_run_to_cancelling_and_emits_event() -> None:
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

    assert cancelled.status is RunStatus.CANCELLING
    stored_events = await events.list_after("tenant-a", run.run_id, 0)
    assert [(item.sequence, item.type) for item in stored_events] == [
        (1, "run.queued"),
        (2, "run.cancelling"),
    ]
