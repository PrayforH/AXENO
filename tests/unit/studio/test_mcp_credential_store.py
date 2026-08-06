import base64
import hashlib
import json
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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
    StoredMcpCredential,
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
async def test_credentials_are_encrypted_user_scoped_and_never_audited() -> None:
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
    stored = await repository.get("tenant-a", "owner-a", "company-search")
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
    other_user = identity().model_copy(update={"user_id": "owner-b"})
    with pytest.raises(McpCredentialError, match="missing MCP credentials"):
        await provider.resolve("company-search", other_user, frozenset({"authorization"}))

    assert await service.delete("tenant-a", "owner-a", "company-search") is True
    assert await repository.get("tenant-a", "owner-a", "company-search") is None


def test_cipher_can_read_pre_isolation_tenant_scoped_ciphertext() -> None:
    secret = "encryption-key-for-tests"
    cipher = McpCredentialCipher(SecretStr(secret))
    nonce = b"0" * 12
    plaintext = b'{"authorization":"legacy-token"}'
    key = hashlib.sha256(b"harness-mcp-v1\0" + secret.encode()).digest()
    sealed = AESGCM(key).encrypt(nonce, plaintext, b"tenant-a\0company-search")
    stored = StoredMcpCredential(
        tenant_id="tenant-a",
        owner_user_id="owner-a",
        reference="company-search",
        revision=1,
        key_names=("authorization",),
        ciphertext=base64.urlsafe_b64encode(nonce + sealed).decode(),
        updated_by="owner-a",
        updated_at=datetime.now(UTC),
    )

    assert cipher.decrypt(stored)["authorization"].get_secret_value() == "legacy-token"
