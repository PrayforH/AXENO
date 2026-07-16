"""Resolve logical Agent Manifest tool references for Claude Agent SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from claude_agent_sdk import (
    McpServerConfig,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from harness.core.manifest import AgentManifest
from harness.core.models import ExecutionIdentity
from harness.runtime.mcp_credentials import (
    DynamicMcpCredentialProvider,
    EmptyMcpCredentialProvider,
    McpCredentialError,
)


class ToolResolutionError(ValueError):
    """Raised when a logical tool reference cannot be resolved safely."""


@dataclass(frozen=True)
class McpServerRegistration:
    """Server-owned MCP configuration referenced by a logical Manifest ID."""

    server_name: str
    config: McpServerConfig
    allowed_tools: tuple[str, ...] = ()
    credential_headers: tuple[tuple[str, str], ...] = ()
    credential_environment: tuple[tuple[str, str], ...] = ()
    credential_query_parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        public_config = cast(dict[str, object], self.config)
        if public_config.get("headers") or public_config.get("env"):
            raise ToolResolutionError(
                "MCP registrations cannot contain inline headers or environment"
            )
        targets = [name for name, _ in self.credential_headers]
        targets.extend(name for name, _ in self.credential_environment)
        targets.extend(name for name, _ in self.credential_query_parameters)
        if len(targets) != len(set(targets)):
            raise ToolResolutionError("duplicate MCP credential target")


@dataclass(frozen=True)
class ResolvedTools:
    """Deterministic Claude SDK tool configuration for one Agent Manifest."""

    builtin_tools: tuple[str, ...]
    mcp_servers: Mapping[str, McpServerConfig]
    allowed_tools: tuple[str, ...]
    sensitive_names: frozenset[str] = frozenset()
    sensitive_values: frozenset[str] = frozenset()


class ToolResolver:
    """Resolve builtins, installed Python SDK tools and registered MCP servers."""

    def __init__(
        self,
        *,
        mcp_registry: Mapping[str, McpServerRegistration] | None = None,
        credential_provider: DynamicMcpCredentialProvider | None = None,
    ) -> None:
        self._mcp_registry = MappingProxyType(dict(mcp_registry or {}))
        self._credential_provider = credential_provider or EmptyMcpCredentialProvider()

    async def resolve(
        self,
        manifest: AgentManifest,
        identity: ExecutionIdentity | None = None,
    ) -> ResolvedTools:
        builtins: list[str] = []
        python_tools: list[SdkMcpTool[Any]] = []
        mcp_servers: dict[str, McpServerConfig] = {}
        allowed_tools: list[str] = []
        sensitive_names: set[str] = set()
        sensitive_values: set[str] = set()

        for tool_spec in manifest.spec.tools:
            if tool_spec.builtin is not None:
                if tool_spec.builtin not in builtins:
                    builtins.append(tool_spec.builtin)
                continue
            if tool_spec.python_entry is not None:
                python_tools.extend(self._load_python_tools(tool_spec.python_entry))
                continue

            reference = cast(str, tool_spec.mcp)
            registration = self._mcp_registry.get(reference)
            if registration is None:
                raise ToolResolutionError(
                    f"MCP tool registration is not configured: {reference}"
                )
            if registration.server_name in mcp_servers:
                raise ToolResolutionError(
                    f"duplicate MCP server name: {registration.server_name}"
                )
            bindings = (
                registration.credential_headers
                + registration.credential_environment
                + registration.credential_query_parameters
            )
            required_keys = frozenset(key for _, key in bindings)
            if required_keys and identity is None:
                raise McpCredentialError(
                    f"execution identity is required for MCP credentials: {reference}"
                )
            credentials = await self._credential_provider.resolve(
                reference,
                identity
                if identity is not None
                else ExecutionIdentity(
                    tenant_id="none",
                    user_id="none",
                    project_id="none",
                    session_id="none",
                    run_id="none",
                    agent_name=manifest.metadata.name,
                    agent_version=manifest.metadata.version,
                ),
                required_keys,
            )
            config = dict(cast(dict[str, object], registration.config))
            if registration.credential_headers:
                headers = {
                    target: credentials[key].get_secret_value()
                    for target, key in registration.credential_headers
                }
                config["headers"] = headers
                sensitive_names.update(headers)
                sensitive_values.update(headers.values())
            if registration.credential_environment:
                environment = {
                    target: credentials[key].get_secret_value()
                    for target, key in registration.credential_environment
                }
                config["env"] = environment
                sensitive_names.update(environment)
                sensitive_values.update(environment.values())
            if registration.credential_query_parameters:
                raw_url = config.get("url")
                if not isinstance(raw_url, str):
                    raise ToolResolutionError(
                        f"MCP query credentials require an HTTP URL: {reference}"
                    )
                parsed = urlsplit(raw_url)
                query = parse_qsl(parsed.query, keep_blank_values=True)
                existing_names = {name for name, _ in query}
                requested_names = {
                    name for name, _ in registration.credential_query_parameters
                }
                duplicates = existing_names.intersection(requested_names)
                if duplicates:
                    names = ", ".join(sorted(duplicates))
                    raise ToolResolutionError(
                        f"MCP query credential already present: {reference}.{names}"
                    )
                injected = {
                    target: credentials[key].get_secret_value()
                    for target, key in registration.credential_query_parameters
                }
                config["url"] = urlunsplit(
                    parsed._replace(query=urlencode([*query, *injected.items()]))
                )
                sensitive_names.update(injected)
                sensitive_values.update(injected.values())
            mcp_servers[registration.server_name] = cast(McpServerConfig, config)
            for allowed_tool in registration.allowed_tools:
                if allowed_tool not in allowed_tools:
                    allowed_tools.append(allowed_tool)

        self._assert_unique_python_tool_names(python_tools)
        if python_tools:
            server_name = "harness-python"
            if server_name in mcp_servers:
                raise ToolResolutionError(f"duplicate MCP server name: {server_name}")
            mcp_servers[server_name] = create_sdk_mcp_server(
                server_name,
                tools=python_tools,
            )

        return ResolvedTools(
            builtin_tools=tuple(builtins),
            mcp_servers=MappingProxyType(mcp_servers),
            allowed_tools=tuple(allowed_tools),
            sensitive_names=frozenset(sensitive_names),
            sensitive_values=frozenset(sensitive_values),
        )

    @staticmethod
    def _load_python_tools(reference: str) -> tuple[SdkMcpTool[Any], ...]:
        module_name, separator, attribute_name = reference.partition(":")
        if not separator or not module_name or not attribute_name or ":" in attribute_name:
            raise ToolResolutionError(f"invalid python tool reference: {reference}")
        try:
            exported = getattr(import_module(module_name), attribute_name)
        except Exception:
            raise ToolResolutionError(f"cannot load python tool: {reference}") from None

        if isinstance(exported, SdkMcpTool):
            return (cast(SdkMcpTool[Any], exported),)
        if isinstance(exported, Sequence) and not isinstance(exported, (str, bytes)):
            values = tuple(cast(Sequence[object], exported))
            if values and all(isinstance(value, SdkMcpTool) for value in values):
                return cast(tuple[SdkMcpTool[Any], ...], values)
        raise ToolResolutionError(
            "python tool export must be an SdkMcpTool or a sequence of SdkMcpTool: "
            f"{reference}"
        )

    @staticmethod
    def _assert_unique_python_tool_names(tools: Sequence[SdkMcpTool[Any]]) -> None:
        names: set[str] = set()
        for sdk_tool in tools:
            if sdk_tool.name in names:
                raise ToolResolutionError(
                    f"duplicate python tool name: {sdk_tool.name}"
                )
            names.add(sdk_tool.name)
