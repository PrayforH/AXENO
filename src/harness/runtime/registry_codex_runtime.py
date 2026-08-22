"""Resolve a published AgentVersion before delegating to Codex app-server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

from harness.core.errors import ConflictError
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import AgentRuntimeType
from harness.core.ports import AgentRegistry
from harness.deployments.boundaries import (
    enforce_runtime_environment,
    enforce_runtime_model_route,
)
from harness.runtime.base import AgentRuntime, RuntimeContext, RuntimeEvent
from harness.runtime.codex_runtime import (
    CodexAppServerRuntime,
    CodexProcessFactory,
    CodexRuntimeConfig,
    CodexServerRequestHandler,
)
from harness.runtime.execution_contract import VISIBLE_EXECUTION_CONTRACT
from harness.studio.model_configuration import ModelConfigurationService

_CONTROL_PLANE_PROVIDER_ID = "agent_studio"
_CONTROL_PLANE_API_KEY_ENV = "HARNESS_CODEX_PROVIDER_API_KEY"


def _toml_string(value: str) -> str:
    """Encode an untrusted control-plane string as a TOML basic string."""

    return json.dumps(value, ensure_ascii=False)


class RegistryCodexRuntime:
    """Build a per-Agent Codex runtime from the immutable published snapshot."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        codex_path: Path,
        model_configurations: ModelConfigurationService | None = None,
        model_by_route: Mapping[str, str] | None = None,
        provider_by_route: Mapping[str, str] | None = None,
        environment: Mapping[str, str] | None = None,
        approval_policy: str = "untrusted",
        sandbox_mode: str = "workspace-write",
        network_access: bool = False,
        process_factory: CodexProcessFactory | None = None,
        server_request_handler: CodexServerRequestHandler | None = None,
    ) -> None:
        self._registry = registry
        self._codex_path = codex_path
        self._model_configurations = model_configurations
        self._model_by_route = dict(model_by_route or {})
        self._provider_by_route = dict(provider_by_route or {})
        self._environment = environment
        self._approval_policy = approval_policy
        self._sandbox_mode = sandbox_mode
        self._network_access = network_access
        self._process_factory = process_factory
        self._server_request_handler = server_request_handler

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        session = context.session
        version = await self._registry.get(
            session.tenant_id,
            session.resolved_agent_owner_user_id,
            session.agent_name,
            session.agent_version,
        )
        snapshot = AgentManifestSnapshot.model_validate(version.snapshot)
        if snapshot.manifest.spec.runtime != "codex-app-server":
            raise ConflictError("Agent manifest is not configured for Codex app-server")
        if session.runtime_type != "codex-app-server":
            raise ConflictError("Session runtime does not match the Agent manifest")
        enforce_runtime_environment(session, snapshot)
        model_spec = snapshot.manifest.spec.model
        raw_override = context.run.input.get("model_route_override")
        route_override = raw_override if isinstance(raw_override, str) else None
        route_id = route_override or model_spec.route
        provider_config_overrides: tuple[str, ...] = ()
        environment = self._environment
        if self._model_configurations is not None:
            selected_config = await self._model_configurations.resolve_runtime(
                session.tenant_id,
                session.agent_name,
                route_id,
                apply_agent_binding=route_override is None,
            )
            if selected_config is None or selected_config.route_id is None:
                raise ConflictError(
                    f"task model route is unavailable in the control plane: {route_id}"
                )
            route_id = selected_config.route_id
            if selected_config.resolved_auth_scheme != "bearer":
                raise ConflictError(
                    "Codex app-server requires a Responses-compatible bearer model route"
                )
            model = selected_config.model
            provider = _CONTROL_PLANE_PROVIDER_ID
            environment = {
                **dict(self._environment or {}),
                _CONTROL_PLANE_API_KEY_ENV: selected_config.credential.get_secret_value(),
            }
            provider_config_overrides = (
                f"model_provider={_toml_string(provider)}",
                (f"model_providers.{provider}.name={_toml_string('Agent Studio control plane')}"),
                (f"model_providers.{provider}.base_url={_toml_string(selected_config.base_url)}"),
                (f"model_providers.{provider}.env_key={_toml_string(_CONTROL_PLANE_API_KEY_ENV)}"),
                f'model_providers.{provider}.wire_api="responses"',
                f"model_providers.{provider}.requires_openai_auth=false",
            )
            event_provider = selected_config.provider
        else:
            model = self._model_by_route.get(route_id, model_spec.model)
            provider = self._provider_by_route.get(route_id)
            event_provider = provider or "codex"
        enforce_runtime_model_route(session, route_id)
        runtime = CodexAppServerRuntime(
            CodexRuntimeConfig(
                codex_path=self._codex_path,
                model=model,
                model_provider=provider,
                developer_instructions=(
                    f"{snapshot.system_prompt.rstrip()}\n\n{VISIBLE_EXECUTION_CONTRACT}"
                ),
                environment=environment,
                config_overrides=provider_config_overrides,
                approval_policy=self._approval_policy,
                sandbox_mode=self._sandbox_mode,
                network_access=self._network_access,
                turn_timeout_seconds=snapshot.manifest.spec.limits.timeout_seconds,
            ),
            **(
                {"process_factory": self._process_factory}
                if self._process_factory is not None
                else {}
            ),
            server_request_handler=self._server_request_handler,
        )
        yield RuntimeEvent(
            type="model.route.selected",
            payload={
                "route_id": route_id,
                "provider": event_provider,
                "model": model,
                "runtime": "codex-app-server",
            },
        )
        async for event in runtime.execute(context):
            yield event


class RegistryRuntimeRouter:
    """Dispatch a pinned Session to one of the installed Agent runtimes."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        runtimes: Mapping[AgentRuntimeType, AgentRuntime],
    ) -> None:
        self._registry = registry
        self._runtimes = dict(runtimes)

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        session = context.session
        version = await self._registry.get(
            session.tenant_id,
            session.resolved_agent_owner_user_id,
            session.agent_name,
            session.agent_version,
        )
        snapshot = AgentManifestSnapshot.model_validate(version.snapshot)
        runtime_type = snapshot.manifest.spec.runtime
        if session.runtime_type != runtime_type:
            raise ConflictError("Session runtime does not match the Agent manifest")
        runtime = self._runtimes.get(runtime_type)
        if runtime is None:
            raise ConflictError(f"Agent runtime is not installed: {runtime_type}")
        async for event in runtime.execute(context):
            yield event
