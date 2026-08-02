import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.storage.database import SessionFactory
from harness.storage.mcp_credential_repository import PostgresMcpCredentialRepository
from harness.studio.mcp_credential_store import (
    ConfigureMcpCredentialRequest,
    McpCredentialCipher,
    McpCredentialService,
)

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest.mark.asyncio
async def test_postgres_mcp_credentials_are_durable_and_user_scoped(
    database: DatabaseFixture,
) -> None:
    _engine, sessions = database
    cipher = McpCredentialCipher(SecretStr("mcp-credential-test-encryption-key"))
    service = McpCredentialService(PostgresMcpCredentialRepository(sessions), cipher)
    await service.configure(
        "tenant-a",
        "alice",
        "company-search",
        ConfigureMcpCredentialRequest(authKey="authorization", value=SecretStr("alice-secret")),
    )
    await service.configure(
        "tenant-a",
        "bob",
        "company-search",
        ConfigureMcpCredentialRequest(authKey="authorization", value=SecretStr("bob-secret")),
    )

    restarted = PostgresMcpCredentialRepository(sessions)
    alice = await restarted.get("tenant-a", "alice", "company-search")
    bob = await restarted.get("tenant-a", "bob", "company-search")

    assert alice is not None and bob is not None
    assert cipher.decrypt(alice)["authorization"].get_secret_value() == "alice-secret"
    assert cipher.decrypt(bob)["authorization"].get_secret_value() == "bob-secret"
    assert [item.reference for item in await restarted.list_for_user("tenant-a", "alice")] == [
        "company-search"
    ]
    assert await restarted.delete("tenant-a", "alice", "company-search") is True
    assert await restarted.get("tenant-a", "alice", "company-search") is None
    assert await restarted.get("tenant-a", "bob", "company-search") == bob
