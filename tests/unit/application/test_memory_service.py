from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryUserMemoryRepository
from harness.application.memory import UserMemoryService
from harness.core.models import ExecutionIdentity

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def identity(user_id: str, run_id: str = "run-a") -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id=user_id,
        project_id="project-a",
        session_id=f"session-{run_id}",
        run_id=run_id,
        agent_name="research-agent",
        agent_version="1.0.0",
    )


@pytest.mark.asyncio
async def test_memory_is_user_agent_scoped_and_projection_is_bounded() -> None:
    service = UserMemoryService(
        InMemoryUserMemoryRepository(), clock=lambda: NOW, projection_limit=12
    )
    alice = identity("alice")
    bob = identity("bob")

    saved = await service.update(alice, "0123456789ABCDEF", expected_version=0)

    assert saved.version == 1
    assert await service.projection(alice) == "0123456789AB"
    assert await service.projection(identity("alice", "run-b")) == "0123456789AB"
    assert await service.projection(bob) == ""


@pytest.mark.asyncio
async def test_memory_update_rejects_stale_version_without_overwriting() -> None:
    service = UserMemoryService(InMemoryUserMemoryRepository(), clock=lambda: NOW)
    scope = identity("alice")
    await service.update(scope, "first", expected_version=0)

    with pytest.raises(ValueError, match="user memory version conflict"):
        await service.update(scope, "stale", expected_version=0)

    assert await service.projection(scope) == "first"
