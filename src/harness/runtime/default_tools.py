"""Server-owned registrations for capabilities exposed by Agent Manifests."""

import json
from typing import cast

from claude_agent_sdk import McpServerConfig
from pydantic import SecretStr

from harness.runtime.mcp_credentials import (
    DynamicMcpCredentialProvider,
    ServerSecretReferenceProvider,
)
from harness.runtime.tools import McpServerRegistration, ToolResolver

TAVILY_REFERENCE = "tavily-readonly"
TAVILY_ALLOWED_TOOLS = (
    "mcp__tavily__tavily-search",
    "mcp__tavily__tavily-extract",
)


def server_secret_credential_provider(
    *,
    references_json: str,
    secrets_json: str,
) -> ServerSecretReferenceProvider:
    """Parse generic logical MCP secret references from server-owned settings."""

    references_raw: object = json.loads(references_json)
    secrets_raw: object = json.loads(secrets_json)
    if not isinstance(references_raw, dict) or not isinstance(secrets_raw, dict):
        raise ValueError("MCP credential settings must be JSON objects")
    references: dict[str, dict[str, str]] = {}
    for server, raw_values in cast(dict[object, object], references_raw).items():
        if not isinstance(raw_values, dict):
            continue
        references[str(server)] = {
            str(key): str(value)
            for key, value in cast(dict[object, object], raw_values).items()
        }
    secrets = {
        str(key): SecretStr(str(value))
        for key, value in cast(dict[object, object], secrets_raw).items()
    }
    return ServerSecretReferenceProvider(references=references, secrets=secrets)


def default_tool_resolver(
    credential_provider: DynamicMcpCredentialProvider | None = None,
) -> ToolResolver:
    """Build the reviewed capability registry shared by every composition root."""

    return ToolResolver(
        mcp_registry={
            TAVILY_REFERENCE: McpServerRegistration(
                server_name="tavily",
                config=cast(
                    McpServerConfig,
                    {"type": "http", "url": "https://mcp.tavily.com/mcp/"},
                ),
                allowed_tools=TAVILY_ALLOWED_TOOLS,
                credential_headers=(("Authorization", "authorization"),),
            )
        },
        credential_provider=credential_provider,
    )
