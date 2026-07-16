import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryEventBus, InMemoryEventRepository
from harness.application.events import EventService
from harness.core.events import RunEvent

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _ids() -> Callable[[str], str]:
    count = 0

    def generate(prefix: str) -> str:
        nonlocal count
        count += 1
        return f"{prefix}-{count}"

    return generate


class RacingEventRepository:
    """Make the first two sequence reads observe the same empty stream."""

    def __init__(self) -> None:
        self._repository = InMemoryEventRepository()
        self._readers = 0
        self._both_reading = asyncio.Event()

    async def append(self, event: RunEvent) -> None:
        await self._repository.append(event)

    async def list_after(
        self,
        tenant_id: str,
        run_id: str,
        after_sequence: int,
    ) -> list[RunEvent]:
        if self._readers < 2:
            self._readers += 1
            if self._readers == 2:
                self._both_reading.set()
            await self._both_reading.wait()
            return []
        return await self._repository.list_after(tenant_id, run_id, after_sequence)


@pytest.mark.asyncio
async def test_concurrent_appends_retry_sequence_conflicts_in_order() -> None:
    repository = RacingEventRepository()
    service = EventService(
        repository,
        InMemoryEventBus(),
        clock=lambda: NOW,
        id_generator=_ids(),
    )

    emitted = await asyncio.gather(
        service.append(
            tenant_id="tenant-a",
            run_id="run-1",
            session_id="session-1",
            event_type="tool.result",
        ),
        service.append(
            tenant_id="tenant-a",
            run_id="run-1",
            session_id="session-1",
            event_type="tool.request",
        ),
    )

    stored = await repository.list_after("tenant-a", "run-1", 0)
    assert sorted(event.sequence for event in emitted) == [1, 2]
    assert [event.sequence for event in stored] == [1, 2]
