import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from harness.core.errors import NotFoundError
from harness.core.models import ExecutionIdentity
from harness.memory_bank.models import MemoryStatus
from harness.memory_bank.service import MemoryBankService
from harness.storage.database import SessionFactory, create_database, create_schema, drop_schema
from harness.storage.memory_bank_repository import PostgresMemoryBankRepository

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
DATABASE_URL = os.getenv(
    "HARNESS_TEST_DATABASE_URL",
    "postgresql+asyncpg://harness:harness@127.0.0.1:5432/harness_test",
)


@pytest_asyncio.fixture
async def memory_database() -> AsyncIterator[SessionFactory]:
    engine, sessions = create_database(DATABASE_URL)
    await drop_schema(engine)
    await create_schema(engine)
    try:
        yield sessions
    finally:
        await engine.dispose()


def identity(user: str = "user-a") -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id=user,
        project_id="agent-a",
        session_id="session-a",
        run_id="run-a",
        agent_name="agent-a",
        agent_version="1.0.0",
    )


@pytest.mark.asyncio
async def test_memory_bank_is_durable_scoped_and_fenced(
    memory_database: SessionFactory,
) -> None:
    first = MemoryBankService(PostgresMemoryBankRepository(memory_database), clock=lambda: NOW)
    proposal = await first.propose_agent(identity(), "用户偏好中文月报")
    confirmed = await first.confirm("tenant-a", "user-a", proposal.entry_id, proposal.version)

    restarted = MemoryBankService(PostgresMemoryBankRepository(memory_database), clock=lambda: NOW)
    hits = await restarted.search("tenant-a", "user-a", "agent-a", "中文月报")
    assert len(hits) == 1 and hits[0].entry.status is MemoryStatus.ACTIVE
    with pytest.raises(NotFoundError):
        await restarted.repository.get_entry("tenant-a", "user-b", proposal.entry_id)

    edited = await restarted.update(
        "tenant-a",
        "user-a",
        proposal.entry_id,
        expected_version=confirmed.version,
        content="用户偏好中文周报",
        confidence=0.9,
    )
    stale = confirmed.model_copy(update={"content": "stale", "version": confirmed.version + 1})
    assert not await restarted.repository.compare_and_set_entry(confirmed.version, stale)
    assert edited.version == 3


@pytest.mark.asyncio
async def test_consent_policy_is_durable_and_never_auto_accepts_sensitive_memory(
    memory_database: SessionFactory,
) -> None:
    service = MemoryBankService(PostgresMemoryBankRepository(memory_database), clock=lambda: NOW)
    await service.replace_consent(
        "tenant-a",
        "user-a",
        "agent-a",
        expected_version=0,
        allow_agent_personal=True,
    )

    personal = await service.propose_agent(identity(), "用户喜欢简洁回答")
    sensitive = await service.propose_agent(identity(), "用户病历记录有花粉过敏")

    assert personal.status is MemoryStatus.ACTIVE
    assert sensitive.status is MemoryStatus.PENDING
