import asyncio
from typing import cast

import pytest
from claude_agent_sdk import McpServerConfig
from pydantic import SecretStr

from harness.core.models import ExecutionIdentity
from harness.runtime.mcp_credentials import (
    EmptyMcpCredentialProvider,
    McpCredentialError,
    RequestMcpCredentialProvider,
    ServerSecretReferenceProvider,
    redact_mcp_credentials,
)
from harness.runtime.tools import McpServerRegistration, ToolResolver
from tests.unit.runtime.test_tools import manifest_fixture


def identity(user_id: str, run_id: str) -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id=user_id,
        project_id="project-a",
        session_id=f"session-{user_id}",
        run_id=run_id,
        agent_name="domain-agent",
        agent_version="0.1.0",
    )


def resolver(provider: object) -> ToolResolver:
    config = cast(
        McpServerConfig,
        {"type": "http", "url": "https://mcp.example.test"},
    )
    return ToolResolver(
        mcp_registry={
            "crm": McpServerRegistration(
                server_name="crm-prod",
                config=config,
                credential_headers=(("Authorization", "access_token"),),
            )
        },
        credential_provider=provider,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_concurrent_execution_identities_receive_isolated_headers() -> None:
    alice = identity("alice", "run-alice")
    bob = identity("bob", "run-bob")
    provider = RequestMcpCredentialProvider(
        {
            RequestMcpCredentialProvider.scope(alice): {
                "crm": {"access_token": SecretStr("alice-token")}
            },
            RequestMcpCredentialProvider.scope(bob): {
                "crm": {"access_token": SecretStr("bob-token")}
            },
        }
    )
    tool_resolver = resolver(provider)

    alice_tools, bob_tools = await asyncio.gather(
        tool_resolver.resolve(manifest_fixture({"mcp": "crm"}), alice),
        tool_resolver.resolve(manifest_fixture({"mcp": "crm"}), bob),
    )

    alice_mcp = cast(dict[str, object], alice_tools.mcp_servers["crm-prod"])
    bob_mcp = cast(dict[str, object], bob_tools.mcp_servers["crm-prod"])
    assert alice_mcp["headers"] == {"Authorization": "alice-token"}
    assert bob_mcp["headers"] == {"Authorization": "bob-token"}
    assert "bob-token" not in str(alice_mcp)
    assert "alice-token" not in str(bob_mcp)


@pytest.mark.asyncio
async def test_missing_required_credentials_fail_before_resolution() -> None:
    with pytest.raises(McpCredentialError, match="missing MCP credentials: crm.access_token"):
        await resolver(EmptyMcpCredentialProvider()).resolve(
            manifest_fixture({"mcp": "crm"}), identity("alice", "run-a")
        )


@pytest.mark.asyncio
async def test_server_secret_references_are_resolved_without_exposing_values() -> None:
    provider = ServerSecretReferenceProvider(
        references={"crm": {"access_token": "CRM_ACCESS_TOKEN"}},
        secrets={"CRM_ACCESS_TOKEN": SecretStr("server-token")},
    )

    resolved = await provider.resolve(
        "crm", identity("service", "run-service"), frozenset({"access_token"})
    )

    assert resolved["access_token"].get_secret_value() == "server-token"
    assert "server-token" not in repr(provider)
    assert "server-token" not in repr(resolved)


def test_redaction_removes_header_names_and_values_recursively() -> None:
    payload = {
        "Authorization": "alice-token",
        "message": "request failed with alice-token",
        "nested": ["Authorization", {"safe": "ok"}],
    }

    redacted = redact_mcp_credentials(
        payload,
        sensitive_names=frozenset({"Authorization"}),
        sensitive_values=frozenset({"alice-token"}),
    )

    assert redacted == {
        "Authorization": "[REDACTED]",
        "message": "request failed with [REDACTED]",
        "nested": ["[REDACTED]", {"safe": "ok"}],
    }
