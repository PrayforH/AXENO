from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.core.errors import ConflictError
from harness.deployments.models import EnvironmentName
from harness.storage.database import SessionFactory
from harness.storage.trigger_repository import PostgresAgentTriggerRepository
from harness.triggers.models import StoredAgentTrigger

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_trigger_is_tenant_scoped_durable_and_fenced(
    database: DatabaseFixture,
) -> None:
    _engine, sessions = database
    repository = PostgresAgentTriggerRepository(sessions)
    now = datetime.now(UTC)
    original = StoredAgentTrigger(
        tenantId="tenant-a",
        triggerId="trigger-durable",
        name="工单入口",
        agentName="support-agent",
        environment=EnvironmentName.PRODUCTION,
        enabled=True,
        revision=1,
        createdBy="admin-a",
        createdAt=now,
        updatedAt=now,
        secretDigest="a" * 64,
    )
    await repository.add(original)

    updated = original.model_copy(
        update={"enabled": False, "revision": 2, "secret_digest": "b" * 64}
    )
    await repository.replace(1, updated)

    restarted = PostgresAgentTriggerRepository(sessions)
    assert await restarted.get("tenant-a", original.trigger_id) == updated
    assert await restarted.get_public(original.trigger_id) == updated
    assert await restarted.list_for_agent("tenant-a", "support-agent") == [updated]
    assert await restarted.list_for_agent("tenant-b", "support-agent") == []
    with pytest.raises(ConflictError, match="revision changed"):
        await restarted.replace(1, updated.model_copy(update={"revision": 2}))
