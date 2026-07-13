"""Resolve logical Agent Manifest tool references for Claude Agent SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from types import MappingProxyType
from typing import Any, cast

from claude_agent_sdk import (
    McpServerConfig,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from harness.core.manifest import AgentManifest


class ToolResolutionError(ValueError):
    """Raised when a logical tool reference cannot be resolved safely."""


@dataclass(frozen=True)
class McpServerRegistration:
    """Server-owned MCP configuration referenced by a logical Manifest ID."""

    server_name: str
    config: McpServerConfig
    allowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedTools:
    """Deterministic Claude SDK tool configuration for one Agent Manifest."""

    builtin_tools: tuple[str, ...]
    mcp_servers: Mapping[str, McpServerConfig]
    allowed_tools: tuple[str, ...]


class ToolResolver:
    """Resolve builtins, installed Python SDK tools and registered MCP servers."""

    def __init__(
        self,
        *,
        mcp_registry: Mapping[str, McpServerRegistration] | None = None,
    ) -> None:
        self._mcp_registry = MappingProxyType(dict(mcp_registry or {}))

    def resolve(self, manifest: AgentManifest) -> ResolvedTools:
        builtins: list[str] = []
        python_tools: list[SdkMcpTool[Any]] = []
        mcp_servers: dict[str, McpServerConfig] = {}
        allowed_tools: list[str] = []

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
            mcp_servers[registration.server_name] = registration.config
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
