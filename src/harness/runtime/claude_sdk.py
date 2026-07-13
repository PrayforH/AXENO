"""Claude Agent SDK runtime adapter with explicit gateway routing."""

from collections.abc import AsyncIterator, Callable
from typing import cast

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    SessionStore,
    StreamEvent,
    query,
)

from harness.core.errors import ConflictError
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import AgentVersion, ModelRoute
from harness.runtime.base import RuntimeContext, RuntimeEvent
from harness.runtime.hooks import discard_sdk_stderr
from harness.runtime.message_mapper import map_sdk_message
from harness.runtime.model_router import ModelRouter
from harness.runtime.tools import ToolResolutionError, ToolResolver

QueryFactory = Callable[[str, ClaudeAgentOptions], AsyncIterator[object]]


async def _default_query(prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
    async for message in query(prompt=prompt, options=options):
        yield message


class ClaudeSdkRuntime:
    def __init__(
        self,
        *,
        agent_version: AgentVersion,
        routes: list[ModelRoute],
        route_secrets: dict[str, str],
        subagent_versions: dict[str, AgentVersion] | None = None,
        query_factory: QueryFactory = _default_query,
        session_store: object | None = None,
        tool_resolver: ToolResolver | None = None,
    ) -> None:
        self._agent_version = agent_version
        self._snapshot = AgentManifestSnapshot.model_validate(agent_version.snapshot)
        self._router = ModelRouter(routes)
        self._route_secrets = route_secrets
        self._subagent_versions = subagent_versions or {}
        self._query = query_factory
        self._session_store = session_store
        self._tool_resolver = tool_resolver or ToolResolver()

    def _options(self, context: RuntimeContext, route: ModelRoute) -> ClaudeAgentOptions:
        manifest = self._snapshot.manifest
        secret = self._route_secrets.get(route.route_id)
        if not secret:
            raise ConflictError(f"credentials are not configured for route: {route.route_id}")
        environment = {
            "ANTHROPIC_BASE_URL": route.base_url,
            "CLAUDE_AGENT_SDK_CLIENT_APP": "claude-agent-harness/0.1.0",
        }
        if route.provider == "new-api":
            environment["ANTHROPIC_AUTH_TOKEN"] = secret
        else:
            environment["ANTHROPIC_API_KEY"] = secret
        resolved_tools = self._tool_resolver.resolve(manifest)
        agents: dict[str, AgentDefinition] = {}
        for name, version in self._subagent_versions.items():
            snapshot = AgentManifestSnapshot.model_validate(version.snapshot)
            subagent_manifest = snapshot.manifest
            if any(tool.builtin is None for tool in subagent_manifest.spec.tools):
                raise ToolResolutionError(
                    f"subagent custom tools are not supported: {name}"
                )
            subagent_tools = [
                tool.builtin
                for tool in subagent_manifest.spec.tools
                if tool.builtin is not None
            ]
            agents[name] = AgentDefinition(
                description=f"Delegated {name} agent",
                prompt=snapshot.system_prompt,
                tools=subagent_tools,
                model="inherit",
                maxTurns=subagent_manifest.spec.limits.max_turns,
            )
        store = cast(SessionStore, self._session_store) if self._session_store is not None else None
        return ClaudeAgentOptions(
            tools=list(resolved_tools.builtin_tools),
            allowed_tools=list(resolved_tools.allowed_tools),
            mcp_servers=dict(resolved_tools.mcp_servers),
            system_prompt=self._snapshot.system_prompt,
            model=route.model,
            fallback_model=None,
            cwd=context.workspace,
            max_turns=manifest.spec.limits.max_turns,
            max_budget_usd=manifest.spec.limits.max_budget_usd,
            permission_mode="dontAsk",
            include_partial_messages=True,
            strict_mcp_config=True,
            agents=agents or None,
            skills=list(manifest.spec.skills),
            env=environment,
            session_store=store,
            resume=context.session.claude_session_id,
            stderr=discard_sdk_stderr,
        )

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        model = self._snapshot.manifest.spec.model
        decision = self._router.resolve(
            model.route,
            required_capabilities=frozenset(model.required_capabilities),
            fallback_route_id=model.fallback_route,
        )
        yield RuntimeEvent(type="model.route.selected", payload=decision.event_payload)
        prompt = str(context.run.input.get("prompt", ""))
        options = self._options(context, decision.route)
        partial_text_seen = False
        stream_message_open = False
        async for message in self._query(prompt, options):
            mapped = map_sdk_message(message)
            if isinstance(message, StreamEvent):
                for event in mapped:
                    if event.type == "message.start":
                        if not stream_message_open:
                            stream_message_open = True
                            yield event
                    elif event.type == "message.delta":
                        partial_text_seen = True
                        if not stream_message_open:
                            stream_message_open = True
                            yield RuntimeEvent(type="message.start")
                        yield event
                    elif event.type == "message.completed":
                        if stream_message_open:
                            stream_message_open = False
                            yield event
                    else:
                        yield event
                continue
            if isinstance(message, AssistantMessage):
                if partial_text_seen:
                    for event in mapped:
                        if event.type != "message.delta":
                            yield event
                    partial_text_seen = False
                    continue
                contains_text = any(event.type == "message.delta" for event in mapped)
                if contains_text:
                    yield RuntimeEvent(type="message.start")
                for event in mapped:
                    yield event
                if contains_text:
                    yield RuntimeEvent(type="message.completed")
                continue
            for event in mapped:
                yield event
        if stream_message_open:
            yield RuntimeEvent(type="message.completed")
