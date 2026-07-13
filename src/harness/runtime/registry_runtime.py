"""Resolve a published AgentVersion before delegating to Claude Agent SDK."""

from collections.abc import AsyncIterator

from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import AgentVersion, ModelCompatibility, ModelRoute
from harness.core.ports import AgentRegistry
from harness.runtime.base import RuntimeContext, RuntimeEvent
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.claude_sdk import ClaudeSdkRuntime, QueryFactory


class RegistryClaudeRuntime:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        config: CcSwitchClaudeConfig,
        query_factory: QueryFactory | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._query_factory = query_factory

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
            )
        else:
            runtime = ClaudeSdkRuntime(
                agent_version=agent_version,
                routes=[route],
                route_secrets=route_secrets,
                subagent_versions=subagent_versions,
                query_factory=self._query_factory,
            )
        async for event in runtime.execute(context):
            yield event
