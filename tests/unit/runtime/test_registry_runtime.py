from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
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
from harness.core.manifest import load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus, Run, RunStatus, Session
from harness.observability.provider import build_observability
from harness.runtime.base import RuntimeContext
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.registry_runtime import RegistryClaudeRuntime


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

    async def fake_query(
        _prompt: str, _options: ClaudeAgentOptions
    ) -> AsyncIterator[object]:
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
    assert model_span.attributes["gen_ai.request.model"] == "gateway-model"
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
    assert captured[0][1].model == "cc-switch-model"
    assert captured[0][1].env["ANTHROPIC_BASE_URL"] == "https://gateway.example"
    assert captured[0][1].env["ANTHROPIC_AUTH_TOKEN"] == "registry-secret"
    assert captured[0][1].env["CLAUDE_CONFIG_DIR"] == str(
        tmp_path / ".harness-runtime" / "claude-config"
    )
    assert not (tmp_path / ".harness-runtime").exists()
    assert captured[0][1].agents is not None
    helper = captured[0][1].agents["helper-agent"]
    assert helper.prompt == helper_snapshot.system_prompt
    assert helper.tools == ["Read", "Glob", "Grep"]
    assert helper.skills == ["delegated-investigation"]
    assert helper.model == "inherit"
    assert (
        tmp_path / ".claude/skills/delegated-investigation/SKILL.md"
    ).is_file()
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

    async def unexpected_query(
        _prompt: str, _options: ClaudeAgentOptions
    ) -> AsyncIterator[object]:
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

    with pytest.raises(ConflictError, match="fallback route is not configured"):
        _events = [event async for event in runtime.execute(context)]

    assert query_called is False


@pytest.mark.asyncio
async def test_incompatible_direct_gateway_uses_configured_anthropic_fallback(
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
