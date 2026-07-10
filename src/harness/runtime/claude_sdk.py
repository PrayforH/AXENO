"""Claude Agent SDK runtime adapter with explicit gateway routing."""

from collections.abc import AsyncIterator, Callable
from typing import cast

from claude_agent_sdk import ClaudeAgentOptions, SessionStore, query

from harness.core.errors import ConflictError
from harness.core.manifest import AgentManifestSnapshot
from harness.core.models import AgentVersion, ModelRoute
from harness.runtime.base import RuntimeContext, RuntimeEvent
from harness.runtime.hooks import discard_sdk_stderr
from harness.runtime.message_mapper import map_sdk_message
from harness.runtime.model_router import ModelRouter

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
        query_factory: QueryFactory = _default_query,
        session_store: object | None = None,
    ) -> None:
        self._agent_version = agent_version
        self._snapshot = AgentManifestSnapshot.model_validate(agent_version.snapshot)
        self._router = ModelRouter(routes)
        self._route_secrets = route_secrets
        self._query = query_factory
        self._session_store = session_store

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
        tools = [tool.builtin for tool in manifest.spec.tools if tool.builtin is not None]
        store = cast(SessionStore, self._session_store) if self._session_store is not None else None
        return ClaudeAgentOptions(
            tools=tools,
            system_prompt=self._snapshot.system_prompt,
            model=route.model,
            fallback_model=None,
            cwd=context.workspace,
            max_turns=manifest.spec.limits.max_turns,
            max_budget_usd=manifest.spec.limits.max_budget_usd,
            permission_mode="dontAsk",
            include_partial_messages=True,
            strict_mcp_config=True,
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
        async for message in self._query(prompt, options):
            for event in map_sdk_message(message):
                yield event
