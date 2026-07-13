from collections.abc import Callable
from importlib import import_module, util
from typing import cast

import pytest
from pydantic import SecretStr

from harness.core.manifest import AgentManifest
from harness.core.models import ExecutionIdentity
from harness.runtime.mcp_credentials import (
    DynamicMcpCredentialProvider,
    McpCredentialError,
    ServerSecretReferenceProvider,
)
from harness.runtime.tools import ToolResolver


def _manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "apiVersion": "harness/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "web-agent", "version": "1.0.0"},
            "spec": {
                "runtime": "claude-agent-sdk",
                "model": {"route": "default", "model": "gateway-model"},
                "prompt": {"system": "prompts/system.md"},
                "tools": [{"mcp": "tavily-readonly"}],
                "permissions": {"policy": "default"},
            },
        }
    )


def _identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="web-agent",
        session_id="session-a",
        run_id="run-a",
        agent_name="web-agent",
        agent_version="1.0.0",
    )


def _factory() -> Callable[[DynamicMcpCredentialProvider | None], ToolResolver]:
    assert util.find_spec("harness.runtime.default_tools") is not None
    module = import_module("harness.runtime.default_tools")
    return cast(
        Callable[[DynamicMcpCredentialProvider | None], ToolResolver],
        vars(module)["default_tool_resolver"],
    )


@pytest.mark.asyncio
async def test_default_resolver_injects_tavily_authorization_and_exact_allowlist() -> None:
    provider = ServerSecretReferenceProvider(
        references={"tavily-readonly": {"authorization": "TAVILY_AUTHORIZATION"}},
        secrets={"TAVILY_AUTHORIZATION": SecretStr("Bearer test-key")},
    )

    resolved = await _factory()(provider).resolve(_manifest(), _identity())

    assert resolved.allowed_tools == (
        "mcp__tavily__tavily-search",
        "mcp__tavily__tavily-extract",
    )
    assert resolved.mcp_servers["tavily"] == {
        "type": "http",
        "url": "https://mcp.tavily.com/mcp/",
        "headers": {"Authorization": "Bearer test-key"},
    }
    assert resolved.sensitive_names == frozenset({"Authorization"})
    assert resolved.sensitive_values == frozenset({"Bearer test-key"})


@pytest.mark.asyncio
async def test_default_resolver_fails_before_execution_without_tavily_credentials() -> None:
    with pytest.raises(
        McpCredentialError,
        match=r"missing MCP credentials: tavily-readonly\.authorization",
    ):
        await _factory()(None).resolve(_manifest(), _identity())
