"""Resolve a published AgentVersion before delegating to Claude Agent SDK."""

from collections.abc import AsyncIterator, Callable

from harness.application.agent_assets import resolve_published_agent_versions
from harness.application.memory import UserMemoryService
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import ModelRoute, Session
from harness.core.ports import AgentRegistry
from harness.deployments.boundaries import enforce_runtime_environment
from harness.execution.credentials import (
    CredentialBroker,
    CredentialLease,
    CredentialResourceKind,
)
from harness.memory_bank.service import MemoryBankService
from harness.memory_bank.workload import RemoteMemoryMcpProvider
from harness.observability.provider import Observability
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
        fallback_config: CcSwitchClaudeConfig | None = None,
        query_factory: QueryFactory | None = None,
        tool_resolver: ToolResolver | None = None,
        mcp_credential_provider: DynamicMcpCredentialProvider | None = None,
        tool_gate: ToolGate | None = None,
        memory_service: UserMemoryService | None = None,
        memory_bank: MemoryBankService | None = None,
        remote_memory_mcp: RemoteMemoryMcpProvider | None = None,
        session_store_factory: Callable[[Session], object] | None = None,
        observability: Observability | None = None,
        credential_broker: CredentialBroker | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._fallback_config = fallback_config
        self._query_factory = query_factory
        self._tool_resolver = tool_resolver or ToolResolver(
            credential_provider=mcp_credential_provider
        )
        self._tool_gate = tool_gate
        self._memory_service = memory_service
        self._memory_bank = memory_bank
        self._remote_memory_mcp = remote_memory_mcp
        self._session_store_factory = session_store_factory
        self._observability = observability
        self._credential_broker = credential_broker

    def _config_for_route(
        self,
        route_id: str,
        *,
        legacy_fallback: bool = False,
    ) -> CcSwitchClaudeConfig:
        candidates = tuple(
            config
            for config in (self._config, self._fallback_config)
            if config is not None
        )
        exact = next(
            (config for config in candidates if config.route_id == route_id),
            None,
        )
        if exact is not None:
            return exact
        if legacy_fallback and self._fallback_config is not None:
            return self._fallback_config
        return self._config

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        session = context.session
        agent_version, subagent_versions = await resolve_published_agent_versions(
            self._registry,
            tenant_id=session.tenant_id,
            agent_name=session.agent_name,
            agent_version=session.agent_version,
        )
        snapshot = AgentManifestSnapshot.model_validate(agent_version.snapshot)
        enforce_runtime_environment(session, snapshot)
        route_id = snapshot.manifest.spec.model.route
        selected_config = self._config_for_route(route_id)
        route = ModelRoute(
            route_id=route_id,
            provider=selected_config.provider,
            base_url=selected_config.base_url,
            model=selected_config.model,
            compatibility=selected_config.compatibility,
            capabilities=selected_config.capabilities,
            auth_scheme=selected_config.resolved_auth_scheme,
        )
        routes = [route]
        issued_leases: list[CredentialLease] = []
        if self._credential_broker is None:
            route_secret = selected_config.credential.get_secret_value()
        else:
            assert context.identity is not None
            lease = await self._credential_broker.issue(
                identity=context.identity,
                resource_kind=CredentialResourceKind.MODEL,
                resource_reference=route_id,
                required_keys=frozenset({"api_key"}),
            )
            issued_leases.append(lease)
            values = await self._credential_broker.resolve(
                lease.lease_id, context.identity
            )
            route_secret = values["api_key"].get_secret_value()
        route_secrets = {route_id: route_secret}
        fallback_route_id = snapshot.manifest.spec.model.fallback_route
        if fallback_route_id is not None and self._fallback_config is not None:
            selected_fallback = self._config_for_route(
                fallback_route_id,
                legacy_fallback=True,
            )
            fallback_route = ModelRoute(
                route_id=fallback_route_id,
                provider=selected_fallback.provider,
                base_url=selected_fallback.base_url,
                model=selected_fallback.model,
                compatibility=selected_fallback.compatibility,
                capabilities=selected_fallback.capabilities,
                auth_scheme=selected_fallback.resolved_auth_scheme,
            )
            routes.append(fallback_route)
            if self._credential_broker is None:
                fallback_secret = selected_fallback.credential.get_secret_value()
            else:
                assert context.identity is not None
                fallback_lease = await self._credential_broker.issue(
                    identity=context.identity,
                    resource_kind=CredentialResourceKind.MODEL,
                    resource_reference=fallback_route_id,
                    required_keys=frozenset({"api_key"}),
                )
                issued_leases.append(fallback_lease)
                fallback_values = await self._credential_broker.resolve(
                    fallback_lease.lease_id, context.identity
                )
                fallback_secret = fallback_values["api_key"].get_secret_value()
            route_secrets[fallback_route_id] = fallback_secret
        if self._query_factory is None:
            runtime = ClaudeSdkRuntime(
                agent_version=agent_version,
                routes=routes,
                route_secrets=route_secrets,
                subagent_versions=subagent_versions,
                tool_resolver=self._tool_resolver,
                tool_gate=self._tool_gate,
                memory_service=self._memory_service,
                memory_bank=self._memory_bank,
                remote_memory_mcp=self._remote_memory_mcp,
                observability=self._observability,
                session_store=(
                    self._session_store_factory(session)
                    if self._session_store_factory is not None
                    else None
                ),
            )
        else:
            runtime = ClaudeSdkRuntime(
                agent_version=agent_version,
                routes=routes,
                route_secrets=route_secrets,
                subagent_versions=subagent_versions,
                query_factory=self._query_factory,
                tool_resolver=self._tool_resolver,
                tool_gate=self._tool_gate,
                memory_service=self._memory_service,
                memory_bank=self._memory_bank,
                remote_memory_mcp=self._remote_memory_mcp,
                observability=self._observability,
                session_store=(
                    self._session_store_factory(session)
                    if self._session_store_factory is not None
                    else None
                ),
            )
        for lease in issued_leases:
            yield RuntimeEvent(
                type="credential.lease.issued",
                payload=lease.audit_record(),
            )
        async for event in runtime.execute(context):
            yield event
