from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    McpServerConfig,
    ResultMessage,
    TextBlock,
)
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from harness.adapters.memory import InMemoryAgentRegistry
from harness.cli import main
from harness.config import Settings
from harness.core.errors import ConflictError
from harness.core.manifest import SubagentSpec, ToolSpec, load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus, Run, RunStatus, Session
from harness.execution.credentials import CredentialResourceKind, InMemoryCredentialBroker
from harness.observability.provider import build_observability
from harness.runtime.base import RuntimeContext
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.tools import McpServerRegistration, ToolResolver
from harness.studio.catalog import default_capability_catalog
from harness.studio.compiler import AgentDraftCompiler
from harness.studio.factory import create_draft_spec
from harness.studio.models import AgentDraft, AgentTemplate


@pytest.mark.asyncio
async def test_model_route_uses_run_scoped_broker_lease_without_secret_events(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("agents/helper-agent/agent.yaml")
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="helper-agent",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    broker_secret = "broker-model-secret"
    broker = InMemoryCredentialBroker(
        {
            ("tenant-a", CredentialResourceKind.MODEL, "new-api-default"): (
                "vault://tenant-a/model/default",
                {"api_key": SecretStr(broker_secret)},
            )
        },
        id_generator=lambda: "model-lease-one",
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(_prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="gateway-model",
            provider="new-api",
            credential=SecretStr("static-secret-must-not-be-used"),
        ),
        query_factory=fake_query,
        credential_broker=broker,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-broker",
            session_id="session-broker",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="broker",
            created_at=now,
            updated_at=now,
            input={"prompt": "private request"},
        ),
        session=Session(
            session_id="session-broker",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="helper-agent",
            agent_version="1.0.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert captured[0].model == "deepseek-v4-flash"
    assert captured[0].max_buffer_size == 32 * 1024 * 1024
    assert "Every final deliverable must exist" in str(captured[0].system_prompt)
    assert captured[0].env["ANTHROPIC_AUTH_TOKEN"] == broker_secret
    selected_event = next(event for event in events if event.type == "model.route.selected")
    assert selected_event.payload["model"] == "deepseek-v4-flash"
    lease_event = events[0]
    assert lease_event.type == "credential.lease.issued"
    assert lease_event.payload["lease_id"] == "model-lease-one"
    assert lease_event.payload["secret_reference"] == "vault://tenant-a/model/default"
    assert broker_secret not in repr(events)
    assert "static-secret-must-not-be-used" not in repr(captured[0].env)


@pytest.mark.asyncio
async def test_on_demand_runtime_enables_native_tool_search_and_emits_safe_directory_fact(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    base_spec = create_draft_spec(
        name="directory-agent",
        domain="operations",
        display_name="目录 Agent",
        description="验证运行时按需工具发现。",
        template=AgentTemplate.ANALYST,
    )
    draft = AgentDraft(
        draftId="draft-directory",
        tenantId="tenant-a",
        revision=1,
        spec=base_spec.model_copy(
            update={
                "model": base_spec.model.model_copy(
                    update={
                        "route_id": "anthropic-official",
                        "model": "claude-sonnet-4-6",
                        "required_capabilities": (
                            "streaming",
                            "tool_use",
                            "tool_search",
                        ),
                    }
                ),
                "mcp_servers": ("tavily-readonly",),
                "tool_exposure_mode": "on_demand",
            }
        ),
        createdBy="builder-a",
        updatedBy="builder-a",
        createdAt=now,
        updatedAt=now,
    )
    compiled = AgentDraftCompiler(
        default_capability_catalog(),
        catalog_revision=4,
    ).compile(draft)
    snapshot = compiled.report.snapshot
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="directory-agent",
            version="0.1.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            package_hash=compiled.report.package_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=now,
        )
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(_prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-6",
            provider="anthropic",
            credential=SecretStr("directory-route-secret"),
            capabilities=frozenset({"streaming", "tool_use", "tool_search"}),
        ),
        query_factory=fake_query,
        tool_resolver=ToolResolver(
            mcp_registry={
                "tavily-readonly": McpServerRegistration(
                    server_name="tavily",
                    config={"type": "http", "url": "https://mcp.example.test"},
                    allowed_tools=(
                        "mcp__tavily__tavily_search",
                        "mcp__tavily__tavily_extract",
                    ),
                )
            }
        ),
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-directory",
            session_id="session-directory",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="directory",
            created_at=now,
            updated_at=now,
            input={"prompt": "inspect the workspace"},
        ),
        session=Session(
            session_id="session-directory",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="directory-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert captured[0].env["ENABLE_TOOL_SEARCH"] == "true"
    assert snapshot.tool_directory is not None
    directory_event = next(event for event in events if event.type == "tool.directory.loaded")
    assert directory_event.payload == {
        "exposure_mode": "on_demand",
        "catalog_revision": 4,
        "content_hash": snapshot.tool_directory.content_hash,
        "entry_count": 5,
    }
    assert "directory-route-secret" not in repr(events)
    assert "api.anthropic.com" not in repr(directory_event.payload)


@pytest.mark.asyncio
async def test_manifest_primary_route_selects_its_route_bound_gateway(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    base_spec = create_draft_spec(
        name="route-bound-agent",
        domain="operations",
        display_name="路由绑定 Agent",
        description="验证逻辑路由不会被配置顺序覆盖。",
        template=AgentTemplate.ANALYST,
    )
    draft = AgentDraft(
        draftId="draft-route-bound",
        tenantId="tenant-a",
        revision=1,
        spec=base_spec.model_copy(
            update={
                "model": base_spec.model.model_copy(
                    update={
                        "route_id": "anthropic-official",
                        "model": "claude-sonnet-4-6",
                    }
                )
            }
        ),
        createdBy="builder-a",
        updatedBy="builder-a",
        createdAt=now,
        updatedAt=now,
    )
    compiled = AgentDraftCompiler(default_capability_catalog()).compile(draft)
    snapshot = compiled.report.snapshot
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="route-bound-agent",
            version="0.1.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            package_hash=compiled.report.package_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=now,
        )
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(_prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="route-bound-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            route_id="new-api-default",
            base_url="https://new-api.example",
            model="gateway-model",
            provider="new-api",
            credential=SecretStr("new-api-secret"),
        ),
        fallback_config=CcSwitchClaudeConfig(
            route_id="anthropic-official",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-6",
            provider="anthropic",
            credential=SecretStr("anthropic-secret"),
            capabilities=frozenset({"streaming", "tool_use", "tool_search"}),
        ),
        query_factory=fake_query,
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-route-bound",
            session_id="session-route-bound",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="route-bound",
            created_at=now,
            updated_at=now,
            input={"prompt": "read a file"},
        ),
        session=Session(
            session_id="session-route-bound",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="route-bound-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert captured[0].env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert captured[0].model == "claude-sonnet-4-6"
    assert captured[0].env["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "ANTHROPIC_AUTH_TOKEN" not in captured[0].env
    assert (
        next(event for event in events if event.type == "model.route.selected").payload["route_id"]
        == "anthropic-official"
    )

    override_context = RuntimeContext(
        run=Run(
            run_id="run-route-override",
            session_id="session-route-override",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="route-override",
            created_at=now,
            updated_at=now,
            input={
                "prompt": "use the task model",
                "model_route_override": "new-api-default",
            },
        ),
        session=Session(
            session_id="session-route-override",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="route-bound-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    override_events = [event async for event in runtime.execute(override_context)]

    assert captured[1].env["ANTHROPIC_BASE_URL"] == "https://new-api.example"
    assert captured[1].model == "gateway-model"
    selected = next(event for event in override_events if event.type == "model.route.selected")
    assert selected.payload["route_id"] == "new-api-default"
    assert selected.payload["selection_source"] == "task_override"
    assert selected.payload["agent_default_route"] == "anthropic-official"


@pytest.mark.asyncio
async def test_runtime_materializes_immutable_skills_and_enables_them_by_name(
    tmp_path: Path,
) -> None:
    agent_root = tmp_path / "agents"
    assert (
        main(
            [
                "agent",
                "init",
                "domain-agent",
                "--root",
                str(agent_root),
                "--domain",
                "operations",
            ]
        )
        == 0
    )
    snapshot = load_manifest(agent_root / "domain-agent" / "agent.yaml")
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="domain-agent",
            version="0.1.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(_prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="gateway-model",
            provider="new-api",
            credential=SecretStr("secret"),
        ),
        query_factory=fake_query,
    )
    now = datetime.now(UTC)
    workspace = tmp_path / "workspace"
    context = RuntimeContext(
        run=Run(
            run_id="run-skill",
            session_id="session-skill",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="skill",
            created_at=now,
            updated_at=now,
            input={"prompt": "use the domain workflow"},
        ),
        session=Session(
            session_id="session-skill",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="domain-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=workspace,
    )

    _events = [event async for event in runtime.execute(context)]

    assert captured[0].skills == ["domain-agent-core"]
    assert (workspace / ".claude/skills/domain-agent-core/SKILL.md").is_file()


@pytest.mark.asyncio
async def test_model_span_has_safe_agent_route_and_policy_dimensions(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("agents/helper-agent/agent.yaml")
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="helper-agent",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            package_hash="b" * 64,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    exporter = InMemorySpanExporter()
    observability = build_observability(
        Settings(otel_enabled=True, otlp_endpoint="http://unused/v1/traces"),
        exporter=exporter,
        processor_factory=SimpleSpanProcessor,
    )

    async def fake_query(_prompt: str, _options: ClaudeAgentOptions) -> AsyncIterator[object]:
        yield ResultMessage(
            subtype="success",
            duration_ms=120,
            duration_api_ms=90,
            is_error=False,
            num_turns=2,
            session_id="sdk-session",
            total_cost_usd=0.012,
            stop_reason="end_turn",
            usage={
                "input_tokens": 100,
                "output_tokens": 25,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 40,
                "private": "do-not-export",
            },
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="gateway-model",
            provider="new-api",
            credential=SecretStr("secret"),
        ),
        query_factory=fake_query,
        observability=observability,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-trace",
            session_id="session-trace",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="trace",
            created_at=now,
            updated_at=now,
            input={"prompt": "private business request"},
        ),
        session=Session(
            session_id="session-trace",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="helper-agent",
            agent_version="1.0.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    _events = [event async for event in runtime.execute(context)]
    model_span = next(
        span for span in exporter.get_finished_spans() if span.name == "harness.model.run"
    )

    assert model_span.attributes is not None
    assert model_span.attributes["agent.name"] == "helper-agent"
    assert model_span.attributes["gen_ai.provider.name"] == "new-api"
    assert model_span.attributes["gen_ai.request.model"] == "deepseek-v4-flash"
    assert model_span.attributes["harness.policy.profile"] == "production-read-only"
    assert model_span.attributes["agent.package_hash"] == "b" * 64
    assert model_span.attributes["gen_ai.usage.input_tokens"] == 100
    assert model_span.attributes["gen_ai.usage.output_tokens"] == 25
    assert model_span.attributes["harness.usage.cache_creation_input_tokens"] == 10
    assert model_span.attributes["harness.usage.cache_read_input_tokens"] == 40
    assert model_span.attributes["harness.model.turns"] == 2
    assert model_span.attributes["harness.model.cost_usd"] == 0.012
    assert model_span.attributes["harness.model.duration_ms"] == 120
    assert model_span.attributes["harness.model.api_duration_ms"] == 90
    assert model_span.attributes["harness.model.stop_reason"] == "end_turn"
    assert "do-not-export" not in repr(model_span.attributes)
    assert "private business request" not in repr(model_span.attributes)


@pytest.mark.asyncio
async def test_resolves_agent_version_and_delegates_to_claude_sdk(tmp_path: Path) -> None:
    snapshot = load_manifest("agents/echo-agent/agent.yaml")
    helper_snapshot = load_manifest("agents/helper-agent/agent.yaml")
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="echo-agent",
            version="0.4.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="helper-agent",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=helper_snapshot.content_hash,
            snapshot=helper_snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    captured: list[tuple[str, ClaudeAgentOptions]] = []
    captured_store_sessions: list[Session] = []
    session_store = object()

    async def fake_query(prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append((prompt, options))
        yield AssistantMessage(content=[TextBlock(text="real adapter")], model=options.model or "")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="cc-switch-model",
            provider="new-api",
            credential=SecretStr("registry-secret"),
        ),
        query_factory=fake_query,
        session_store_factory=lambda session: (
            captured_store_sessions.append(session) or session_store
        ),
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
            input={"prompt": "hello registry"},
        ),
        session=Session(
            session_id="session-1",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="echo-agent",
            agent_version="0.4.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert captured[0][0] == "hello registry"
    assert captured[0][1].model == "deepseek-v4-flash"
    assert captured[0][1].env["ANTHROPIC_BASE_URL"] == "https://gateway.example"
    assert captured[0][1].env["ANTHROPIC_AUTH_TOKEN"] == "registry-secret"
    assert captured[0][1].env["CLAUDE_CONFIG_DIR"] == str(
        tmp_path / ".harness-runtime" / "claude-config"
    )
    assert not (tmp_path / ".harness-runtime").exists()
    assert captured[0][1].agents is not None
    helper = captured[0][1].agents["helper-agent"]
    assert helper.prompt.startswith(helper_snapshot.system_prompt)
    assert "Never quote, reproduce or reveal" in helper.prompt
    assert helper.tools == ["Read", "Glob", "Grep"]
    assert helper.skills == ["delegated-investigation"]
    assert helper.model == "inherit"
    assert (tmp_path / ".claude/skills/delegated-investigation/SKILL.md").is_file()
    assert isinstance(captured[0][1].tools, list)
    assert "Task" in captured[0][1].tools
    assert isinstance(captured[0][1].mcp_servers, dict)
    assert captured[0][1].mcp_servers == {}
    assert captured[0][1].allowed_tools == []
    assert captured[0][1].session_store is session_store
    assert captured[0][1].session_store_flush == "eager"
    assert captured_store_sessions == [context.session]
    assert [event.type for event in events] == [
        "model.route.selected",
        "message.start",
        "message.delta",
        "message.completed",
        "runtime.result",
    ]
    assert "registry-secret" not in repr(events)


@pytest.mark.asyncio
async def test_role_aliases_configure_multiple_sdk_agents_from_one_version(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    helper_snapshot = load_manifest("tests/fixtures/agents/helper-agent/agent.yaml")
    bindings = (
        SubagentSpec(
            ref="helper@1.0.0",
            alias="fact-checker",
            description="Verify claims and return source-backed facts.",
            background=True,
        ),
        SubagentSpec(
            ref="helper@1.0.0",
            alias="risk-reviewer",
            description="Challenge conclusions and identify uncertainty.",
        ),
    )
    manifest = snapshot.manifest.model_copy(
        update={"spec": snapshot.manifest.spec.model_copy(update={"subagents": bindings})}
    )
    snapshot = snapshot.model_copy(update={"manifest": manifest})
    registry = InMemoryAgentRegistry()
    now = datetime.now(UTC)
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="echo-agent",
            version="0.1.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=now,
        )
    )
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="helper",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=helper_snapshot.content_hash,
            snapshot=helper_snapshot.model_dump(mode="json"),
            created_at=now,
        )
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(_prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="gateway-model",
            provider="new-api",
            credential=SecretStr("secret"),
        ),
        query_factory=fake_query,
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-collaboration",
            session_id="session-collaboration",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="collaboration",
            created_at=now,
            updated_at=now,
            input={"prompt": "delegate independent checks"},
        ),
        session=Session(
            session_id="session-collaboration",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    _events = [event async for event in runtime.execute(context)]

    assert captured[0].agents is not None
    assert set(captured[0].agents) == {"fact-checker", "risk-reviewer"}
    assert captured[0].agents["fact-checker"].description.startswith("Verify claims")
    assert captured[0].agents["fact-checker"].background is True
    assert captured[0].agents["risk-reviewer"].background is False
    assert captured[0].agents["fact-checker"].prompt.startswith(
        helper_snapshot.system_prompt
    )
    assert "Never quote, reproduce or reveal" in captured[0].agents[
        "fact-checker"
    ].prompt


@pytest.mark.asyncio
async def test_subagent_receives_its_declared_mcp_tools(tmp_path: Path) -> None:
    root_snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    child_snapshot = load_manifest("tests/fixtures/agents/helper-agent/agent.yaml")
    child_manifest = child_snapshot.manifest.model_copy(
        update={
            "spec": child_snapshot.manifest.spec.model_copy(
                update={
                    "tools": (
                        *child_snapshot.manifest.spec.tools,
                        ToolSpec(mcp="crm-readonly"),
                    )
                }
            )
        }
    )
    child_snapshot = child_snapshot.model_copy(update={"manifest": child_manifest})
    registry = InMemoryAgentRegistry()
    now = datetime.now(UTC)
    for name, version, snapshot in (
        ("echo-agent", "0.1.0", root_snapshot),
        ("helper", "1.0.0", child_snapshot),
    ):
        await registry.add(
            AgentVersion(
                tenant_id="tenant-a",
                name=name,
                version=version,
                status=AgentVersionStatus.PUBLISHED,
                manifest_hash=snapshot.content_hash,
                snapshot=snapshot.model_dump(mode="json"),
                created_at=now,
            )
        )
    config = cast(
        McpServerConfig,
        {"type": "http", "url": "https://mcp.example.test"},
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(
        _prompt: str, options: ClaudeAgentOptions
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

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="gateway-model",
            provider="new-api",
            credential=SecretStr("secret"),
        ),
        query_factory=fake_query,
        tool_resolver=ToolResolver(
            mcp_registry={
                "crm-readonly": McpServerRegistration(
                    server_name="crm",
                    config=config,
                    allowed_tools=("mcp__crm__search",),
                )
            }
        ),
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-subagent-mcp",
            session_id="session-subagent-mcp",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="subagent-mcp",
            created_at=now,
            updated_at=now,
            input={"prompt": "delegate crm lookup"},
        ),
        session=Session(
            session_id="session-subagent-mcp",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    _events = [event async for event in runtime.execute(context)]

    options = captured[0]
    assert options.agents is not None
    assert "mcp__crm__search" in options.agents["helper"].tools
    assert options.allowed_tools == ["mcp__crm__search"]
    assert options.mcp_servers == {"crm": config}


@pytest.mark.asyncio
async def test_declared_gateway_capabilities_fail_closed_before_query(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("agents/helper-agent/agent.yaml")
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="helper-agent",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    query_called = False

    async def unexpected_query(_prompt: str, _options: ClaudeAgentOptions) -> AsyncIterator[object]:
        nonlocal query_called
        query_called = True
        if False:
            yield object()

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://gateway.example",
            model="text-only-model",
            provider="new-api",
            credential=SecretStr("secret"),
            capabilities=frozenset({"streaming"}),
        ),
        query_factory=unexpected_query,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-incompatible",
            session_id="session-incompatible",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="incompatible",
            created_at=now,
            updated_at=now,
            input={"prompt": "use a tool"},
        ),
        session=Session(
            session_id="session-incompatible",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="helper-agent",
            agent_version="1.0.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    with pytest.raises(ConflictError, match="does not satisfy required capabilities"):
        _events = [event async for event in runtime.execute(context)]

    assert query_called is False


@pytest.mark.asyncio
async def test_incompatible_direct_gateway_uses_configured_anthropic_fallback(
    tmp_path: Path,
) -> None:
    base_snapshot = load_manifest("agents/helper-agent/agent.yaml")
    snapshot = base_snapshot.model_copy(
        update={
            "manifest": base_snapshot.manifest.model_copy(
                update={
                    "spec": base_snapshot.manifest.spec.model_copy(
                        update={
                            "model": base_snapshot.manifest.spec.model.model_copy(
                                update={
                                    "fallback_route": "anthropic-official",
                                    "fallback_model": "claude-fallback",
                                }
                            )
                        }
                    )
                }
            )
        }
    )
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="helper-agent",
            version="1.0.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    captured: list[ClaudeAgentOptions] = []

    async def fake_query(_prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(options)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="fallback-session",
        )

    runtime = RegistryClaudeRuntime(
        registry=registry,
        config=CcSwitchClaudeConfig(
            base_url="https://new-api.example",
            model="text-only-model",
            provider="new-api",
            credential=SecretStr("new-api-secret"),
            capabilities=frozenset({"streaming"}),
        ),
        fallback_config=CcSwitchClaudeConfig(
            base_url="https://api.anthropic.com",
            model="claude-fallback",
            provider="anthropic",
            credential=SecretStr("anthropic-secret"),
        ),
        query_factory=fake_query,
    )
    now = datetime.now(UTC)
    context = RuntimeContext(
        run=Run(
            run_id="run-fallback",
            session_id="session-fallback",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="fallback",
            created_at=now,
            updated_at=now,
            input={"prompt": "use a tool"},
        ),
        session=Session(
            session_id="session-fallback",
            tenant_id="tenant-a",
            user_id="developer",
            agent_name="helper-agent",
            agent_version="1.0.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert events[0].type == "model.route.selected"
    assert events[0].payload["route_id"] == "anthropic-official"
    assert events[0].payload["used_fallback"] is True
    assert captured[0].model == "claude-fallback"
    assert captured[0].env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert captured[0].env["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "ANTHROPIC_AUTH_TOKEN" not in captured[0].env
    assert "new-api-secret" not in repr(events)
    assert "anthropic-secret" not in repr(events)
