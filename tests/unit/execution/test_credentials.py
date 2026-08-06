from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from harness.core.models import ExecutionIdentity
from harness.execution.credentials import (
    BrokerMcpCredentialProvider,
    CredentialLeaseError,
    CredentialResourceKind,
    InMemoryCredentialBroker,
)

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def identity(run_id: str = "run-one") -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="agent-a",
        session_id="session-a",
        run_id=run_id,
        agent_name="agent-a",
        agent_version="1.0.0",
    )


@pytest.mark.asyncio
async def test_lease_is_run_scoped_short_lived_and_audit_safe() -> None:
    current = NOW
    secret = "private-tavily-value"
    broker = InMemoryCredentialBroker(
        {
            ("tenant-a", CredentialResourceKind.MCP, "tavily"): (
                "vault://tenant-a/tavily",
                {"api_key": SecretStr(secret)},
            )
        },
        clock=lambda: current,
        id_generator=lambda: "lease-one",
    )
    lease = await broker.issue(
        identity=identity(),
        resource_kind=CredentialResourceKind.MCP,
        resource_reference="tavily",
        required_keys=frozenset({"api_key"}),
        ttl_seconds=60,
    )

    values = await broker.resolve(lease.lease_id, identity())

    assert values["api_key"].get_secret_value() == secret
    assert lease.model_dump() == {
        "lease_id": "lease-one",
        "tenant_id": "tenant-a",
        "run_id": "run-one",
        "resource_kind": CredentialResourceKind.MCP,
        "resource_reference": "tavily",
        "secret_reference": "vault://tenant-a/tavily",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=60),
        "revoked_at": None,
    }
    assert secret not in repr(lease.audit_record())
    with pytest.raises(CredentialLeaseError, match="identity mismatch"):
        await broker.resolve(lease.lease_id, identity("run-two"))

    current = NOW + timedelta(seconds=60)
    with pytest.raises(CredentialLeaseError, match="expired"):
        await broker.resolve(lease.lease_id, identity())


@pytest.mark.asyncio
async def test_run_revocation_invalidates_mcp_lease_and_adapter_returns_only_values() -> None:
    broker = InMemoryCredentialBroker(
        {
            ("tenant-a", CredentialResourceKind.MCP, "tavily"): (
                "vault://tenant-a/tavily",
                {"api_key": SecretStr("private")},
            )
        },
        clock=lambda: NOW,
        id_generator=lambda: "lease-mcp",
    )
    provider = BrokerMcpCredentialProvider(broker)

    values = await provider.resolve(
        "tavily", identity(), frozenset({"api_key"})
    )
    lease_id = provider.issued_lease_ids[("run-one", "tavily")]

    assert values["api_key"].get_secret_value() == "private"
    await broker.revoke_run("tenant-a", "run-one")
    with pytest.raises(CredentialLeaseError, match="revoked"):
        await broker.resolve(lease_id, identity())
