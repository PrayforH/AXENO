from datetime import UTC, datetime

import pytest

from harness.adapters.memory import InMemoryUserMemoryRepository
from harness.application.memory import UserMemoryService
from harness.core.models import ExecutionIdentity
from harness.runtime.memory_tools import memory_execution_context, update_user_memory_tool

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="alice",
        project_id="project-a",
        session_id="session-a",
        run_id="run-a",
        agent_name="research-agent",
        agent_version="1.0.0",
    )


@pytest.mark.asyncio
async def test_update_tool_uses_task_local_identity_and_resets_it() -> None:
    service = UserMemoryService(InMemoryUserMemoryRepository(), clock=lambda: NOW)

    with memory_execution_context(service, identity()):
        result = await update_user_memory_tool.handler(
            {"content": "Prefer Chinese.", "expected_version": 0}
        )

    assert result["content"][0]["text"] == '{"version":1}'
    assert await service.projection(identity()) == "Prefer Chinese."
    with pytest.raises(RuntimeError, match="memory execution context is not active"):
        await update_user_memory_tool.handler({"content": "leak"})


@pytest.mark.asyncio
async def test_update_tool_validates_payload() -> None:
    service = UserMemoryService(InMemoryUserMemoryRepository(), clock=lambda: NOW)

    with memory_execution_context(service, identity()):
        result = await update_user_memory_tool.handler({"content": ""})

    assert result["isError"] is True
    assert "non-empty" in result["content"][0]["text"]

