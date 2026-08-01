import json

import pytest
from pydantic import SecretStr

from harness.auth.audit import AuditService
from harness.auth.repositories import InMemoryAuditRepository
from harness.core.models import ExecutionIdentity
from harness.runtime.mcp_credentials import EmptyMcpCredentialProvider, McpCredentialError
from harness.studio.mcp_credential_store import (
    ConfigureMcpCredentialRequest,
    InMemoryMcpCredentialRepository,
    McpCredentialCipher,
    McpCredentialService,
    StoredMcpCredentialProvider,
)


def identity(tenant_id: str = "tenant-a") -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id=tenant_id,
        user_id="owner-a",
        project_id="project-a",
        session_id="session-a",
        run_id="run-a",
        agent_name="agent-a",
        agent_version="1",
    )


@pytest.mark.asyncio
async def test_credentials_are_encrypted_tenant_scoped_and_never_audited() -> None:
    repository = InMemoryMcpCredentialRepository()
    audit_repository = InMemoryAuditRepository()
    service = McpCredentialService(
        repository,
        McpCredentialCipher(SecretStr("encryption-key-for-tests")),
        audit=AuditService(audit_repository),
    )
    secret = "top-secret-mcp-token"

    status = await service.configure(
        "tenant-a",
        "owner-a",
        "company-search",
        ConfigureMcpCredentialRequest(authKey="authorization", value=SecretStr(secret)),
    )
    stored = await repository.get("tenant-a", "company-search")
    provider = StoredMcpCredentialProvider(service, EmptyMcpCredentialProvider())
    resolved = await provider.resolve("company-search", identity(), frozenset({"authorization"}))

    assert stored is not None
    assert secret not in stored.ciphertext
    serialized = status.model_dump(mode="json", by_alias=True)
    assert serialized["reference"] == "company-search"
    assert serialized["configured"] is True
    assert serialized["keyNames"] == ["authorization"]
    assert serialized["revision"] == 1
    assert serialized["updatedBy"] == "owner-a"
    assert serialized["updatedAt"] is not None
    assert secret not in json.dumps(serialized)
    assert resolved["authorization"].get_secret_value() == secret
    assert secret not in json.dumps(
        [entry.model_dump(mode="json") for entry in audit_repository.entries]
    )
    with pytest.raises(McpCredentialError, match="missing MCP credentials"):
        await provider.resolve("company-search", identity("tenant-b"), frozenset({"authorization"}))

    assert await service.delete("tenant-a", "owner-a", "company-search") is True
    assert await repository.get("tenant-a", "company-search") is None
