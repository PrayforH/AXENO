from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.core.events import RunEvent
from harness.core.models import Run, RunStatus
from harness.storage.database import SessionFactory
from harness.storage.repositories import PostgresEventRepository, PostgresRunRepository

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_run_fencing_and_idempotency(database: DatabaseFixture) -> None:
    _, sessions = database
    repository = PostgresRunRepository(sessions)
    now = datetime.now(UTC)
    run = Run(
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        status=RunStatus.QUEUED,
        idempotency_key="idem-1",
        created_at=now,
        updated_at=now,
    )
    await repository.add(run)

    assert await repository.find_by_idempotency_key("tenant-a", "session-1", "idem-1") == run
    updated = run.model_copy(update={"status": RunStatus.PROVISIONING, "fencing_token": 1})
    assert await repository.compare_and_set(RunStatus.QUEUED, updated) is True
    assert await repository.compare_and_set(RunStatus.QUEUED, updated) is False


@pytest.mark.asyncio
async def test_postgres_outbox_events_remain_ordered(database: DatabaseFixture) -> None:
    _, sessions = database
    repository = PostgresEventRepository(sessions)
    now = datetime.now(UTC)
    first = RunEvent(
        event_id="event-1",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        sequence=1,
        type="run.queued",
        timestamp=now,
    )
    second = first.model_copy(update={"event_id": "event-2", "sequence": 2, "type": "run.running"})
    await repository.append(first)
    await repository.append(second)

    assert await repository.list_after("tenant-a", "run-1", 0) == [first, second]
