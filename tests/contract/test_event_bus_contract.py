from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryEventBus, InMemoryEventRepository
from harness.core.errors import ConflictError
from harness.core.events import RunEvent


def event(event_id: str, sequence: int) -> RunEvent:
    return RunEvent(
        event_id=event_id,
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        sequence=sequence,
        type="run.status",
        timestamp=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_event_repository_enforces_order_and_idempotency() -> None:
    repository = InMemoryEventRepository()
    first = event("event-1", 1)

    await repository.append(first)
    await repository.append(first)

    assert await repository.list_after("tenant-a", "run-1", 0) == [first]
    with pytest.raises(ConflictError, match="sequence"):
        await repository.append(event("event-3", 3))


@pytest.mark.asyncio
async def test_event_bus_replays_after_sequence() -> None:
    bus = InMemoryEventBus()
    first = event("event-1", 1)
    second = event("event-2", 2)
    await bus.publish(first)
    await bus.publish(second)

    assert await bus.read("tenant-a", "run-1", after_sequence=1) == [second]

