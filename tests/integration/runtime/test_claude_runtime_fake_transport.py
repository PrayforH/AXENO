from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    McpServerConfig,
    ResultMessage,
    StreamEvent,
    TextBlock,
)
from claude_agent_sdk.types import HookEvent

from harness.core.manifest import ToolSpec, load_manifest
from harness.core.models import (
    AgentVersion,
    AgentVersionStatus,
    ModelCompatibility,
    ModelRoute,
    Run,
    RunStatus,
    Session,
)
from harness.runtime.base import RuntimeContext
from harness.runtime.claude_sdk import ClaudeSdkRuntime
from harness.runtime.tools import (
    McpServerRegistration,
    ToolResolutionError,
    ToolResolver,
)


class RecordingToolGate:
    def __init__(self) -> None:
        self.contexts: list[RuntimeContext] = []

    def hooks(self, context: RuntimeContext) -> dict[HookEvent, list[HookMatcher]]:
        self.contexts.append(context)
        return {"PreToolUse": []}


@pytest.mark.asyncio
async def test_runtime_builds_new_api_options_and_maps_fake_sdk_messages(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    version = AgentVersion(
        tenant_id="tenant-a",
        name="echo-agent",
        version="0.1.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=snapshot.content_hash,
        snapshot=snapshot.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )
    route = ModelRoute(
        route_id="new-api-default",
        provider="new-api",
        base_url="https://new-api.example/v1",
        model="claude-sonnet-4-6",
        compatibility=ModelCompatibility.FULL,
        capabilities=frozenset({"streaming", "tool_use"}),
    )
    captured: list[tuple[str, ClaudeAgentOptions]] = []

    async def fake_query(prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append((prompt, options))
        yield AssistantMessage(content=[TextBlock(text="fake response")], model=options.model or "")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    gate = RecordingToolGate()
    runtime = ClaudeSdkRuntime(
        agent_version=version,
        routes=[route],
        route_secrets={"new-api-default": "super-secret"},
        query_factory=fake_query,
        tool_gate=gate,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-1",
            session_id="session-1",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="idem-1",
            created_at=now,
            updated_at=now,
            input={"prompt": "hello"},
        ),
        session=Session(
            session_id="session-1",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert captured[0][0] == "hello"
    options = captured[0][1]
    assert options.env["ANTHROPIC_BASE_URL"] == "https://new-api.example/v1"
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "super-secret"
    assert options.model == "claude-sonnet-4-6"
    assert options.cwd == tmp_path
    assert options.hooks is not None
    assert "PreToolUse" in options.hooks
    assert gate.contexts == [context]
    assert [event.type for event in events] == [
        "model.route.selected",
        "message.start",
        "message.delta",
        "message.completed",
        "runtime.result",
    ]
    assert "super-secret" not in repr(events)


@pytest.mark.asyncio
async def test_runtime_uses_partial_lifecycle_without_repeating_final_assistant_text(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    version = AgentVersion(
        tenant_id="tenant-a",
        name="echo-agent",
        version="0.1.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=snapshot.content_hash,
        snapshot=snapshot.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )
    route = ModelRoute(
        route_id="new-api-default",
        provider="new-api",
        base_url="https://new-api.example/v1",
        model="gateway-model",
        compatibility=ModelCompatibility.FULL,
        capabilities=frozenset({"streaming", "tool_use"}),
    )

    async def streaming_query(
        _prompt: str,
        _options: ClaudeAgentOptions,
    ) -> AsyncIterator[object]:
        yield StreamEvent(
            uuid="start",
            session_id="sdk-session",
            parent_tool_use_id=None,
            event={"type": "message_start", "message": {}},
        )
        yield StreamEvent(
            uuid="delta",
            session_id="sdk-session",
            parent_tool_use_id=None,
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "streamed"},
            },
        )
        yield StreamEvent(
            uuid="stop",
            session_id="sdk-session",
            parent_tool_use_id=None,
            event={"type": "message_stop"},
        )
        yield AssistantMessage(content=[TextBlock(text="streamed")], model="gateway-model")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = ClaudeSdkRuntime(
        agent_version=version,
        routes=[route],
        route_secrets={"new-api-default": "secret"},
        query_factory=streaming_query,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-stream",
            session_id="session-stream",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="stream",
            created_at=now,
            updated_at=now,
            input={"prompt": "hello"},
        ),
        session=Session(
            session_id="session-stream",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert [event.type for event in events] == [
        "model.route.selected",
        "message.start",
        "message.delta",
        "message.completed",
        "runtime.result",
    ]
    assert [event.payload.get("text") for event in events].count("streamed") == 1


@pytest.mark.asyncio
async def test_runtime_wires_resolved_python_and_mcp_tools_into_sdk_options(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    tools = snapshot.manifest.spec.tools + (
        ToolSpec.model_validate(
            {"python": "tests.fixtures.runtime.domain_tools:lookup_tool"}
        ),
        ToolSpec.model_validate({"mcp": "crm"}),
    )
    spec = snapshot.manifest.spec.model_copy(update={"tools": tools})
    manifest = snapshot.manifest.model_copy(update={"spec": spec})
    snapshot = snapshot.model_copy(update={"manifest": manifest})
    version = AgentVersion(
        tenant_id="tenant-a",
        name="echo-agent",
        version="0.1.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=snapshot.content_hash,
        snapshot=snapshot.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )
    route = ModelRoute(
        route_id="new-api-default",
        provider="new-api",
        base_url="https://new-api.example/v1",
        model="gateway-model",
        compatibility=ModelCompatibility.FULL,
        capabilities=frozenset({"streaming", "tool_use"}),
    )
    mcp_config = cast(
        McpServerConfig,
        {"type": "http", "url": "https://mcp.example.test"},
    )
    resolver = ToolResolver(
        mcp_registry={
            "crm": McpServerRegistration(
                server_name="crm-prod",
                config=mcp_config,
                allowed_tools=("mcp__crm-prod__search",),
            )
        }
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(
        _prompt: str,
        options: ClaudeAgentOptions,
    ) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = ClaudeSdkRuntime(
        agent_version=version,
        routes=[route],
        route_secrets={"new-api-default": "secret"},
        query_factory=fake_query,
        tool_resolver=resolver,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-tools",
            session_id="session-tools",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="tools",
            created_at=now,
            updated_at=now,
            input={"prompt": "use domain tools"},
        ),
        session=Session(
            session_id="session-tools",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    _events = [event async for event in runtime.execute(context)]

    options = captured[0]
    assert options.tools == ["Read", "Task"]
    assert isinstance(options.mcp_servers, dict)
    assert set(options.mcp_servers) == {"harness-python", "crm-prod"}
    assert options.allowed_tools == ["mcp__crm-prod__search"]


@pytest.mark.asyncio
async def test_runtime_rejects_custom_tools_declared_by_subagents(tmp_path: Path) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    helper_snapshot = load_manifest("tests/fixtures/agents/helper-agent/agent.yaml")
    helper_spec = helper_snapshot.manifest.spec.model_copy(
        update={
            "tools": helper_snapshot.manifest.spec.tools
            + (
                ToolSpec.model_validate(
                    {"python": "tests.fixtures.runtime.domain_tools:lookup_tool"}
                ),
            )
        }
    )
    helper_manifest = helper_snapshot.manifest.model_copy(update={"spec": helper_spec})
    helper_snapshot = helper_snapshot.model_copy(update={"manifest": helper_manifest})
    now = datetime.now(UTC)
    main_version = AgentVersion(
        tenant_id="tenant-a",
        name="echo-agent",
        version="0.1.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=snapshot.content_hash,
        snapshot=snapshot.model_dump(mode="json"),
        created_at=now,
    )
    helper_version = AgentVersion(
        tenant_id="tenant-a",
        name="helper",
        version="1.0.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=helper_snapshot.content_hash,
        snapshot=helper_snapshot.model_dump(mode="json"),
        created_at=now,
    )
    route = ModelRoute(
        route_id="new-api-default",
        provider="new-api",
        base_url="https://new-api.example/v1",
        model="gateway-model",
        compatibility=ModelCompatibility.FULL,
        capabilities=frozenset({"streaming", "tool_use"}),
    )

    async def should_not_query(
        _prompt: str,
        _options: ClaudeAgentOptions,
    ) -> AsyncIterator[object]:
        raise AssertionError("subagent custom tools must fail before the SDK query")
        yield

    runtime = ClaudeSdkRuntime(
        agent_version=main_version,
        routes=[route],
        route_secrets={"new-api-default": "secret"},
        subagent_versions={"helper": helper_version},
        query_factory=should_not_query,
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-subagent",
            session_id="session-subagent",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="subagent-tools",
            created_at=now,
            updated_at=now,
            input={"prompt": "delegate"},
        ),
        session=Session(
            session_id="session-subagent",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    with pytest.raises(
        ToolResolutionError,
        match="subagent custom tools are not supported: helper",
    ):
        async for _event in runtime.execute(context):
            pass
