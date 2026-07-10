from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock

from harness.core.manifest import load_manifest
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

    runtime = ClaudeSdkRuntime(
        agent_version=version,
        routes=[route],
        route_secrets={"new-api-default": "super-secret"},
        query_factory=fake_query,
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
    assert [event.type for event in events] == [
        "model.route.selected",
        "message.delta",
        "runtime.result",
    ]
    assert "super-secret" not in repr(events)
