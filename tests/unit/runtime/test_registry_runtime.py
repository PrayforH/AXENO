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
from pydantic import SecretStr

from harness.adapters.memory import InMemoryAgentRegistry
from harness.core.manifest import load_manifest
from harness.core.models import AgentVersion, AgentVersionStatus, Run, RunStatus, Session
from harness.runtime.base import RuntimeContext
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.runtime.default_tools import default_tool_resolver
from harness.runtime.mcp_credentials import ServerSecretReferenceProvider
from harness.runtime.registry_runtime import RegistryClaudeRuntime


@pytest.mark.asyncio
async def test_resolves_agent_version_and_delegates_to_claude_sdk(tmp_path: Path) -> None:
    snapshot = load_manifest("agents/echo-agent/agent.yaml")
    helper_snapshot = load_manifest("agents/helper-agent/agent.yaml")
    registry = InMemoryAgentRegistry()
    await registry.add(
        AgentVersion(
            tenant_id="tenant-a",
            name="echo-agent",
            version="0.3.0",
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
        tool_resolver=default_tool_resolver(
            ServerSecretReferenceProvider(
                references={
                    "tavily-readonly": {"authorization": "TAVILY_AUTHORIZATION"}
                },
                secrets={"TAVILY_AUTHORIZATION": SecretStr("Bearer tavily-test-key")},
            )
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
            agent_version="0.3.0",
            created_at=now,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert captured[0][0] == "hello registry"
    assert captured[0][1].model == "cc-switch-model"
    assert captured[0][1].env["ANTHROPIC_BASE_URL"] == "https://gateway.example"
    assert captured[0][1].env["ANTHROPIC_AUTH_TOKEN"] == "registry-secret"
    assert captured[0][1].agents is not None
    helper = captured[0][1].agents["helper-agent"]
    assert helper.prompt == helper_snapshot.system_prompt
    assert helper.tools == ["Read", "Glob", "Grep"]
    assert helper.model == "inherit"
    assert isinstance(captured[0][1].tools, list)
    assert "Task" in captured[0][1].tools
    assert isinstance(captured[0][1].mcp_servers, dict)
    assert set(captured[0][1].mcp_servers) == {"tavily"}
    assert captured[0][1].allowed_tools == [
        "mcp__tavily__tavily-search",
        "mcp__tavily__tavily-extract",
    ]
    assert [event.type for event in events] == [
        "model.route.selected",
        "message.start",
        "message.delta",
        "message.completed",
        "runtime.result",
    ]
    assert "registry-secret" not in repr(events)
