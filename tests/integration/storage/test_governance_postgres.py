from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.execution.credentials import CredentialResourceKind
from harness.governance.models import (
    ConnectionScope,
    CreateCredentialConnectionRequest,
    CreateGovernedPolicyRequest,
    GovernedCallRule,
)
from harness.governance.service import GovernanceService
from harness.policy.models import PolicyDecision
from harness.policy.profiles import default_policy_profiles
from harness.storage.database import SessionFactory
from harness.storage.governance_repository import PostgresGovernanceRepository

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_governance_state_is_durable_and_tenant_scoped(
    database: DatabaseFixture,
) -> None:
    _, sessions = database
    first = GovernanceService(
        PostgresGovernanceRepository(sessions),
        static_profiles=default_policy_profiles(),
    )
    await first.create_connection(
        "tenant-a",
        "owner-a",
        CreateCredentialConnectionRequest(
            connection_id="personal-search",
            display_name="Personal search",
            resource_kind=CredentialResourceKind.MCP,
            resource_reference="tavily",
            scope=ConnectionScope.PERSONAL,
            principal_id="user-a",
            secret_reference="settings://mcp/tavily",
            required_keys=("api_key",),
        ),
    )
    policy = await first.create_policy(
        "tenant-a",
        "owner-a",
        CreateGovernedPolicyRequest(
            policy_id="reviewed-tools",
            display_name="Reviewed tools",
            call_rules=(
                GovernedCallRule(
                    name="allow-read",
                    tool="Read",
                    decision=PolicyDecision.ALLOW,
                ),
            ),
        ),
    )
    publication = await first.publish_policy(
        "tenant-a",
        "owner-a",
        policy.policy_id,
        expected_revision=policy.revision,
    )

    restarted = GovernanceService(
        PostgresGovernanceRepository(sessions),
        static_profiles=default_policy_profiles(),
    )

    assert len(await restarted.list_connections("tenant-a")) == 1
    assert await restarted.list_connections("tenant-b") == ()
    resolved = await restarted.resolve_runtime("tenant-a", policy.policy_id)
    assert resolved.revision == publication.revision
    assert resolved.content_hash == publication.content_hash
