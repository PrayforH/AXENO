from typing import cast

import pytest
from claude_agent_sdk import McpSdkServerConfig, McpServerConfig

from harness.core.manifest import AgentManifest
from harness.runtime.tools import McpServerRegistration, ToolResolutionError, ToolResolver


def _manifest(*tools: dict[str, str]) -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "apiVersion": "harness/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "domain-agent", "version": "0.1.0"},
            "spec": {
                "runtime": "claude-agent-sdk",
                "model": {"route": "default", "model": "gateway-model"},
                "prompt": {"system": "prompts/system.md"},
                "tools": list(tools),
                "permissions": {"policy": "policies/default.yaml"},
            },
        }
    )


def test_preserves_unique_builtin_tools_in_declaration_order() -> None:
    resolved = ToolResolver().resolve(
        _manifest({"builtin": "Read"}, {"builtin": "Bash"}, {"builtin": "Read"})
    )

    assert resolved.builtin_tools == ("Read", "Bash")
    assert resolved.mcp_servers == {}
    assert resolved.allowed_tools == ()


def test_wraps_python_sdk_tools_in_one_in_process_server() -> None:
    resolved = ToolResolver().resolve(
        _manifest({"python": "tests.fixtures.runtime.domain_tools:tool_list"})
    )

    server = cast(McpSdkServerConfig, resolved.mcp_servers["harness-python"])
    assert server["type"] == "sdk"
    assert server["name"] == "harness-python"
    assert resolved.allowed_tools == ()


def test_resolves_external_mcp_from_server_owned_registry() -> None:
    config = cast(
        McpServerConfig,
        {"type": "http", "url": "https://mcp.example.test", "headers": {"X-Key": "secret"}},
    )
    resolver = ToolResolver(
        mcp_registry={
            "crm": McpServerRegistration(
                server_name="crm-prod",
                config=config,
                allowed_tools=("mcp__crm-prod__search",),
            )
        }
    )

    resolved = resolver.resolve(_manifest({"mcp": "crm"}))

    assert resolved.mcp_servers == {"crm-prod": config}
    assert resolved.allowed_tools == ("mcp__crm-prod__search",)


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("missing", "MCP tool registration is not configured: missing"),
        ("no-colon", "invalid python tool reference: no-colon"),
        (
            "tests.fixtures.runtime.domain_tools:missing",
            "cannot load python tool: tests.fixtures.runtime.domain_tools:missing",
        ),
        (
            "tests.fixtures.runtime.domain_tools:not_a_tool",
            "python tool export must be an SdkMcpTool or a sequence of SdkMcpTool",
        ),
    ],
)
def test_rejects_unresolvable_tool_references(reference: str, message: str) -> None:
    key = "mcp" if reference == "missing" else "python"

    with pytest.raises(ToolResolutionError, match=message):
        ToolResolver().resolve(_manifest({key: reference}))


def test_rejects_duplicate_python_tool_names() -> None:
    with pytest.raises(
        ToolResolutionError,
        match="duplicate python tool name: lookup_customer",
    ):
        ToolResolver().resolve(
            _manifest({"python": "tests.fixtures.runtime.domain_tools:duplicate_tools"})
        )


def test_errors_do_not_include_registry_secrets() -> None:
    secret = "registry-super-secret"
    config = cast(
        McpServerConfig,
        {"type": "http", "url": "https://mcp.example.test", "headers": {"X-Key": secret}},
    )
    resolver = ToolResolver(
        mcp_registry={
            "first": McpServerRegistration(server_name="same", config=config),
            "second": McpServerRegistration(server_name="same", config=config),
        }
    )

    with pytest.raises(ToolResolutionError) as captured:
        resolver.resolve(_manifest({"mcp": "first"}, {"mcp": "second"}))

    assert str(captured.value) == "duplicate MCP server name: same"
    assert secret not in repr(captured.value)
