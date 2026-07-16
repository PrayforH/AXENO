"""Claude Agent SDK runtime adapter with explicit gateway routing."""

import asyncio
import shutil
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractContextManager, ExitStack, nullcontext
from pathlib import Path
from typing import Any, cast

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SessionStore,
    StreamEvent,
    TaskUpdatedMessage,
    Transport,
    query,
)

from harness.application.memory import UserMemoryService
from harness.core.errors import ConflictError
from harness.core.manifest import (
    AgentManifestSnapshot,
    materialize_skill_snapshot_set,
)
from harness.core.models import AgentVersion, ModelRoute
from harness.observability.provider import Observability
from harness.runtime.artifact_tools import (
    artifact_execution_context,
    create_artifact_mcp_server,
)
from harness.runtime.base import (
    RuntimeContext,
    RuntimeEvent,
    RuntimeExecutionTimeoutError,
    RuntimeResultError,
)
from harness.runtime.hooks import discard_sdk_stderr
from harness.runtime.mcp_credentials import redact_mcp_credentials
from harness.runtime.memory_tools import create_memory_mcp_server, memory_execution_context
from harness.runtime.message_mapper import map_sdk_message, result_subtype, result_usage
from harness.runtime.model_router import ModelRouter
from harness.runtime.sdk_tool_gate import ToolGate
from harness.runtime.subagent_governance import SubagentRuntimeGovernor
from harness.runtime.tools import ResolvedTools, ToolResolutionError, ToolResolver

QueryFactory = Callable[[str, ClaudeAgentOptions], AsyncIterator[object]]
_TEXT_DELTA_FLUSH_CHARS = 64
_TEXT_DELTA_PUNCTUATION_CHARS = 16
_TEXT_DELTA_BOUNDARIES = frozenset("\n。！？.!?")


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
        tool_gate: ToolGate | None = None,
        memory_service: UserMemoryService | None = None,
        observability: Observability | None = None,
    ) -> None:
        self._agent_version = agent_version
        self._snapshot = AgentManifestSnapshot.model_validate(agent_version.snapshot)
        self._router = ModelRouter(routes)
        self._route_secrets = route_secrets
        self._subagent_versions = subagent_versions or {}
        self._query = query_factory
        self._session_store = session_store
        self._tool_resolver = tool_resolver or ToolResolver()
        self._tool_gate = tool_gate
        self._memory_service = memory_service
        self._observability = observability

    def _span(
        self,
        name: str,
        *,
        run_id: str,
        attributes: Mapping[str, str | bool | int | float] | None = None,
    ) -> AbstractContextManager[None]:
        if self._observability is None:
            return nullcontext()
        return self._observability.span(
            name,
            attributes={"run.id": run_id, **dict(attributes or {})},
        )

    async def _model_messages(
        self,
        messages: AsyncIterator[object],
        *,
        run_id: str,
        route: ModelRoute,
    ) -> AsyncIterator[object]:
        manifest = self._snapshot.manifest
        base_attributes: dict[str, str | bool | int | float] = {
            "agent.name": manifest.metadata.name,
            "agent.version": manifest.metadata.version,
            "agent.content_hash": self._snapshot.content_hash,
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": route.provider,
            "gen_ai.request.model": route.model,
            "harness.model.route": route.route_id,
            "harness.policy.profile": manifest.spec.permissions.policy,
            "harness.skill.count": len(self._snapshot.skill_snapshots),
        }
        if self._agent_version.package_hash is not None:
            base_attributes["agent.package_hash"] = self._agent_version.package_hash
        with self._span(
            "harness.model.run",
            run_id=run_id,
            attributes=base_attributes,
        ):
            async for message in messages:
                if isinstance(message, ResultMessage) and self._observability is not None:
                    subtype = result_subtype(message)
                    usage = result_usage(message)
                    result_attributes: dict[str, str | bool | int | float] = {
                        "harness.model.duration_ms": message.duration_ms,
                        "harness.model.api_duration_ms": message.duration_api_ms,
                        "harness.model.turns": message.num_turns,
                        "harness.model.is_error": message.is_error,
                    }
                    if message.total_cost_usd is not None:
                        result_attributes["harness.model.cost_usd"] = (
                            message.total_cost_usd
                        )
                    if message.stop_reason is not None:
                        result_attributes["harness.model.stop_reason"] = (
                            message.stop_reason
                        )
                    if message.api_error_status is not None:
                        result_attributes["harness.model.api_error_status"] = (
                            message.api_error_status
                        )
                    for source, target in (
                        ("input_tokens", "gen_ai.usage.input_tokens"),
                        ("output_tokens", "gen_ai.usage.output_tokens"),
                        (
                            "cache_creation_input_tokens",
                            "harness.usage.cache_creation_input_tokens",
                        ),
                        (
                            "cache_read_input_tokens",
                            "harness.usage.cache_read_input_tokens",
                        ),
                    ):
                        if source in usage:
                            result_attributes[target] = usage[source]
                    self._observability.annotate_current_span(result_attributes)
                    if message.is_error:
                        self._observability.mark_current_span_error(subtype)
                yield message
                if isinstance(message, ResultMessage) and message.is_error:
                    raise RuntimeResultError(
                        result_subtype(message),
                        api_error_status=message.api_error_status,
                    )

    async def _options(
        self, context: RuntimeContext, route: ModelRoute
    ) -> tuple[ClaudeAgentOptions, ResolvedTools]:
        manifest = self._snapshot.manifest
        subagent_snapshots = {
            name: AgentManifestSnapshot.model_validate(version.snapshot)
            for name, version in self._subagent_versions.items()
        }
        skill_names = (
            materialize_skill_snapshot_set(
                (self._snapshot, *subagent_snapshots.values()), context.workspace
            )
            if self._snapshot.skill_snapshots
            or any(snapshot.skill_snapshots for snapshot in subagent_snapshots.values())
            else tuple(Path(skill).name for skill in manifest.spec.skills)
        )
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
        resolved_tools = await self._tool_resolver.resolve(manifest, context.identity)
        mcp_servers = dict(resolved_tools.mcp_servers)
        allowed_tools = list(resolved_tools.allowed_tools)
        remote_transport = context.runtime_transport_factory is not None
        if not remote_transport:
            # The production container runs as an unprivileged user whose HOME
            # is the read-only application directory. Claude CLI needs a
            # writable config directory to create the transcript files that
            # back SessionStore mirror frames. Keep it inside the disposable
            # Run workspace and remove it before workspace archival.
            runtime_config_dir = (
                context.workspace / ".harness-runtime" / "claude-config"
            )
            runtime_config_dir.mkdir(parents=True, exist_ok=True)
            environment["CLAUDE_CONFIG_DIR"] = str(runtime_config_dir)
        in_process_servers = tuple(
            name
            for name, config in mcp_servers.items()
            if cast(dict[str, object], config).get("type") == "sdk"
        )
        if remote_transport and in_process_servers:
            names = ", ".join(sorted(in_process_servers))
            raise ToolResolutionError(
                "in-process Python SDK MCP tools cannot run through a remote "
                f"sandbox transport ({names}); expose them as authenticated HTTP MCP"
            )
        # SDK MCP servers hold live Python objects and are valid only when the
        # Claude CLI is a child of this worker. A Daytona CLI is a separate
        # process on a separate host, so durable memory is projected read-only
        # and artifacts are collected from files unless an HTTP MCP is used.
        if self._memory_service is not None and not remote_transport:
            if "harness-memory" in mcp_servers:
                raise ToolResolutionError("duplicate MCP server name: harness-memory")
            mcp_servers["harness-memory"] = create_memory_mcp_server()
            allowed_tools.append("mcp__harness-memory__update_user_memory")
        if context.artifact_publisher is not None and not remote_transport:
            if "harness-artifacts" in mcp_servers:
                raise ToolResolutionError("duplicate MCP server name: harness-artifacts")
            mcp_servers["harness-artifacts"] = create_artifact_mcp_server()
            allowed_tools.append("mcp__harness-artifacts__publish_artifact")
        agents: dict[str, AgentDefinition] = {}
        subagent_bindings = {
            subagent.runtime_name: subagent
            for subagent in manifest.spec.subagents
        }
        for name in self._subagent_versions:
            snapshot = subagent_snapshots[name]
            subagent_manifest = snapshot.manifest
            binding = subagent_bindings.get(name)
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
                description=(
                    binding.description
                    if binding is not None and binding.description is not None
                    else f"Delegated {name} agent"
                ),
                prompt=snapshot.system_prompt,
                tools=subagent_tools,
                model="inherit",
                maxTurns=subagent_manifest.spec.limits.max_turns,
                skills=[skill.name for skill in snapshot.skill_snapshots] or None,
                background=binding.background if binding is not None else False,
            )
        store = cast(SessionStore, self._session_store) if self._session_store is not None else None
        options = ClaudeAgentOptions(
            tools=list(resolved_tools.builtin_tools),
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
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
            hooks=(
                self._tool_gate.hooks(
                    context,
                    policy_id=manifest.spec.permissions.policy,
                    subagent_policy_ids={
                        name: snapshot.manifest.spec.permissions.policy
                        for name, snapshot in subagent_snapshots.items()
                    },
                )
                if self._tool_gate is not None
                else None
            ),
            skills=list(skill_names),
            env=environment,
            session_store=store,
            session_store_flush="eager",
            resume=context.session.claude_session_id,
            stderr=discard_sdk_stderr,
        )
        return options, resolved_tools

    @staticmethod
    def _redact_event(event: RuntimeEvent, resolved_tools: ResolvedTools) -> RuntimeEvent:
        if not resolved_tools.sensitive_names and not resolved_tools.sensitive_values:
            return event
        payload = cast(
            dict[str, Any],
            redact_mcp_credentials(
                event.payload,
                sensitive_names=resolved_tools.sensitive_names,
                sensitive_values=resolved_tools.sensitive_values,
            ),
        )
        return event.model_copy(update={"payload": payload})

    async def execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        timeout_seconds = self._snapshot.manifest.spec.limits.timeout_seconds
        timeout = asyncio.timeout(timeout_seconds)
        try:
            async with timeout:
                async for event in self._execute(context):
                    yield event
        except TimeoutError as error:
            if not timeout.expired():
                raise
            raise RuntimeExecutionTimeoutError(
                f"Agent runtime exceeded {timeout_seconds} seconds"
            ) from error

    async def _execute(self, context: RuntimeContext) -> AsyncIterator[RuntimeEvent]:
        model = self._snapshot.manifest.spec.model
        decision = self._router.resolve(
            model.route,
            required_capabilities=frozenset(model.required_capabilities),
            fallback_route_id=model.fallback_route,
        )
        yield RuntimeEvent(type="model.route.selected", payload=decision.event_payload)
        prompt = str(context.run.input.get("prompt", ""))
        if context.memory_projection:
            prompt = (
                "<user_memory>\n"
                f"{context.memory_projection}\n"
                "</user_memory>\n\n"
                f"{prompt}"
            )
        if context.input_files:
            inventory = "\n".join(f"- {path}" for path in context.input_files)
            prompt = (
                f"{prompt}\n\n"
                "Browser-uploaded input files are available in this run workspace:\n"
                f"{inventory}\n"
                "Use the available file tools to inspect them when relevant."
            )
        with self._span(
            "harness.mcp.resolve",
            run_id=context.run.run_id,
            attributes={
                "harness.policy.profile": self._snapshot.manifest.spec.permissions.policy,
                "harness.declared_tool.count": len(
                    self._snapshot.manifest.spec.tools
                ),
            },
        ):
            options, resolved_tools = await self._options(context, decision.route)
            if self._observability is not None:
                self._observability.annotate_current_span(
                    {
                        "harness.resolved_builtin.count": len(
                            resolved_tools.builtin_tools
                        ),
                        "harness.resolved_mcp.count": len(
                            resolved_tools.mcp_servers
                        ),
                    }
                )
        subagent_governor = SubagentRuntimeGovernor(
            root=self._snapshot,
            subagent_versions=self._subagent_versions,
            observability=self._observability,
        )
        partial_text_seen = False
        stream_message_open = False
        pending_text = ""
        pending_task_terminals: dict[str, RuntimeEvent] = {}
        with ExitStack() as execution_context:
            execution_context.callback(
                shutil.rmtree,
                context.workspace / ".harness-runtime",
                ignore_errors=True,
            )
            if self._memory_service is not None and context.identity is not None:
                execution_context.enter_context(
                    memory_execution_context(self._memory_service, context.identity)
                )
            if context.artifact_publisher is not None:
                execution_context.enter_context(
                    artifact_execution_context(context.artifact_publisher)
                )
            if context.runtime_transport_factory is None:
                query_messages = self._query(prompt, options)
            else:
                transport = context.runtime_transport_factory(options)
                if not isinstance(transport, Transport):
                    raise TypeError("runtime transport factory did not return an SDK Transport")
                query_messages = query(
                    prompt=prompt,
                    options=options,
                    transport=transport,
                )
            async for message in self._model_messages(
                query_messages,
                run_id=context.run.run_id,
                route=decision.route,
            ):
                mapped = [
                    self._redact_event(event, resolved_tools)
                    for event in map_sdk_message(message)
                ]
                if isinstance(message, TaskUpdatedMessage):
                    immediate: list[RuntimeEvent] = []
                    for event in mapped:
                        if event.type in {"subagent.completed", "subagent.failed"}:
                            task_id = str(event.payload.get("task_id", ""))
                            if task_id:
                                pending_task_terminals[task_id] = event
                                continue
                        immediate.append(event)
                    mapped = immediate
                else:
                    for event in mapped:
                        if event.type in {"subagent.completed", "subagent.failed"}:
                            task_id = str(event.payload.get("task_id", ""))
                            if task_id:
                                pending_task_terminals.pop(task_id, None)
                if isinstance(message, ResultMessage) and pending_task_terminals:
                    mapped = [*pending_task_terminals.values(), *mapped]
                    pending_task_terminals.clear()
                governed: list[RuntimeEvent] = []
                for event in mapped:
                    governed.extend(
                        subagent_governor.process(
                            event,
                            run_id=context.run.run_id,
                        )
                    )
                mapped = governed
                if isinstance(message, ResultMessage) and subagent_governor.active_tasks:
                    mapped = [
                        *subagent_governor.fail_unfinished(
                            reason="missing_terminal_event",
                            run_id=context.run.run_id,
                        ),
                        *mapped,
                    ]
                if self._tool_gate is not None:
                    mapped = [event for event in mapped if event.type != "tool.request"]
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
                            pending_text += str(event.payload.get("text", ""))
                            should_flush = len(pending_text) >= _TEXT_DELTA_FLUSH_CHARS or (
                                len(pending_text) >= _TEXT_DELTA_PUNCTUATION_CHARS
                                and pending_text[-1:] in _TEXT_DELTA_BOUNDARIES
                            )
                            if should_flush:
                                yield RuntimeEvent(
                                    type="message.delta",
                                    payload={"text": pending_text},
                                )
                                pending_text = ""
                        elif event.type == "message.completed":
                            if stream_message_open:
                                if pending_text:
                                    yield RuntimeEvent(
                                        type="message.delta",
                                        payload={"text": pending_text},
                                    )
                                    pending_text = ""
                                stream_message_open = False
                                yield event
                        else:
                            if pending_text:
                                yield RuntimeEvent(
                                    type="message.delta",
                                    payload={"text": pending_text},
                                )
                                pending_text = ""
                            yield event
                    continue
                if isinstance(message, ResultMessage) and stream_message_open:
                    if pending_text:
                        yield RuntimeEvent(
                            type="message.delta", payload={"text": pending_text}
                        )
                        pending_text = ""
                    stream_message_open = False
                    yield RuntimeEvent(type="message.completed")
                if isinstance(message, AssistantMessage):
                    if partial_text_seen:
                        if pending_text:
                            yield RuntimeEvent(
                                type="message.delta", payload={"text": pending_text}
                            )
                            pending_text = ""
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
        for event in pending_task_terminals.values():
            for governed_event in subagent_governor.process(
                event,
                run_id=context.run.run_id,
            ):
                yield governed_event
        for event in subagent_governor.fail_unfinished(
            reason="stream_closed",
            run_id=context.run.run_id,
        ):
            yield event
        if stream_message_open:
            if pending_text:
                yield RuntimeEvent(type="message.delta", payload={"text": pending_text})
            yield RuntimeEvent(type="message.completed")
