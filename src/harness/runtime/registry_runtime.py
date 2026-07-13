"""Resolve a published AgentVersion before delegating to Claude Agent SDK."""

from collections.abc import AsyncIterator, Callable

from harness.application.memory import UserMemoryService
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import AgentVersion, ModelCompatibility, ModelRoute
from harness.core.ports import AgentRegistry
from harness.runtime.base import RuntimeContext, RuntimeEvent
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.claude_sdk import ClaudeSdkRuntime, QueryFactory
from harness.runtime.mcp_credentials import DynamicMcpCredentialProvider
from harness.runtime.sdk_tool_gate import ToolGate
from harness.runtime.tools import ToolResolver


class RegistryClaudeRuntime:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        config: CcSwitchClaudeConfig,
        query_factory: QueryFactory | None = None,
        tool_resolver: ToolResolver | None = None,
        mcp_credential_provider: DynamicMcpCredentialProvider | None = None,
        tool_gate: ToolGate | None = None,
        memory_service: UserMemoryService | None = None,
        session_store_factory: Callable[[str], object] | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._query_factory = query_factory
        self._tool_resolver = tool_resolver or ToolResolver(
            credential_provider=mcp_credential_provider
        )
        self._tool_gate = tool_gate
        self._memory_service = memory_service
        self._session_store_factory = session_store_factory

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        session = context.session
        agent_version = await self._registry.get(
            session.tenant_id,
            session.agent_name,
            session.agent_version,
        )
        snapshot = AgentManifestSnapshot.model_validate(agent_version.snapshot)
        route_id = snapshot.manifest.spec.model.route
        subagent_versions: dict[str, AgentVersion] = {}
        for subagent in snapshot.manifest.spec.subagents:
            name, separator, version = subagent.ref.rpartition("@")
            if not separator or not name or not version:
                raise ValueError(
                    f"subagent reference requires name@version: {subagent.ref}"
                )
            subagent_versions[name] = await self._registry.get(
                session.tenant_id,
                name,
                version,
            )
        route = ModelRoute(
            route_id=route_id,
            provider=self._config.provider,
            base_url=self._config.base_url,
            model=self._config.model,
            compatibility=ModelCompatibility.FULL,
            capabilities=frozenset({"streaming", "tool_use"}),
        )
        route_secrets = {route_id: self._config.credential.get_secret_value()}
        if self._query_factory is None:
            runtime = ClaudeSdkRuntime(
                agent_version=agent_version,
                routes=[route],
                route_secrets=route_secrets,
                subagent_versions=subagent_versions,
                tool_resolver=self._tool_resolver,
                tool_gate=self._tool_gate,
                memory_service=self._memory_service,
                session_store=(
                    self._session_store_factory(session.tenant_id)
                    if self._session_store_factory is not None
                    else None
                ),
            )
        else:
            runtime = ClaudeSdkRuntime(
                agent_version=agent_version,
                routes=[route],
                route_secrets=route_secrets,
                subagent_versions=subagent_versions,
                query_factory=self._query_factory,
                tool_resolver=self._tool_resolver,
                tool_gate=self._tool_gate,
                memory_service=self._memory_service,
                session_store=(
                    self._session_store_factory(session.tenant_id)
                    if self._session_store_factory is not None
                    else None
                ),
            )
        async for event in runtime.execute(context):
            yield event
