"""Ordered event persistence and fan-out."""

from typing import Any

from harness.application.types import Clock, IdGenerator
from harness.core.events import RunEvent
from harness.core.ports import EventBus, EventRepository


class EventService:
    def __init__(
        self,
        repository: EventRepository,
        bus: EventBus,
        *,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._repository = repository
        self._bus = bus
        self._clock = clock
        self._id_generator = id_generator

    async def append(
        self,
        *,
        tenant_id: str,
        run_id: str,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        current = await self._repository.list_after(tenant_id, run_id, 0)
        sequence = current[-1].sequence + 1 if current else 1
        event = RunEvent(
            event_id=self._id_generator("event"),
            run_id=run_id,
            session_id=session_id,
            tenant_id=tenant_id,
            sequence=sequence,
            type=event_type,
            timestamp=self._clock(),
            payload=payload or {},
        )
        await self._repository.append(event)
        await self._bus.publish(event)
        return event

