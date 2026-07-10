from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.adapters.memory import InMemoryAgentRegistry, InMemorySessionRepository
from harness.application.agents import AgentService
from harness.application.sessions import SessionService
from harness.core.errors import ConflictError
from harness.core.models import AgentVersion, AgentVersionStatus

FIXTURE = Path("tests/fixtures/agents/echo-agent/agent.yaml")
NOW = datetime(2026, 7, 11, tzinfo=UTC)


@pytest.mark.asyncio
async def test_publishes_an_immutable_manifest_snapshot() -> None:
    registry = InMemoryAgentRegistry()
    service = AgentService(registry, clock=lambda: NOW)

    version = await service.publish("tenant-a", FIXTURE)

    assert version.status is AgentVersionStatus.PUBLISHED
    assert version.manifest_hash == version.snapshot["content_hash"]
    assert (await registry.get("tenant-a", "echo-agent", "0.1.0")) == version


@pytest.mark.asyncio
async def test_session_requires_a_published_agent_version() -> None:
    registry = InMemoryAgentRegistry()
    sessions = InMemorySessionRepository()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="echo-agent",
            version="0.1.0",
            status=AgentVersionStatus.VALIDATED,
            manifest_hash="a" * 64,
            created_at=NOW,
        )
    )
    service = SessionService(
        registry,
        sessions,
        clock=lambda: NOW,
        id_generator=lambda prefix: f"{prefix}-1",
    )

    with pytest.raises(ConflictError, match="published"):
        await service.create("tenant-a", "user-1", "echo-agent", "0.1.0")

