from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

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
async def test_memory_projection_is_delimited_and_not_emitted_in_events(
    tmp_path: Path,
) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    now = datetime.now(UTC)
    captured: list[str] = []

    async def fake_query(prompt: str, _options: ClaudeAgentOptions) -> AsyncIterator[object]:
        captured.append(prompt)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-session",
        )

    runtime = ClaudeSdkRuntime(
        agent_version=AgentVersion(
            tenant_id="tenant-a",
            owner_user_id="user-a",
            name="echo-agent",
            version="0.1.0",
            status=AgentVersionStatus.PUBLISHED,
            manifest_hash=snapshot.content_hash,
            snapshot=snapshot.model_dump(mode="json"),
            created_at=now,
        ),
        routes=[
            ModelRoute(
                route_id="new-api-default",
                provider="new-api",
                base_url="https://new-api.example/v1",
                model="gateway-model",
                compatibility=ModelCompatibility.FULL,
                capabilities=frozenset({"streaming", "tool_use"}),
            )
        ],
        route_secrets={"new-api-default": "secret"},
        query_factory=fake_query,
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-a",
            session_id="session-a",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="memory",
            created_at=now,
            updated_at=now,
            input={"prompt": "Write a report"},
        ),
        session=Session(
            session_id="session-a",
            tenant_id="tenant-a",
            user_id="alice",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
        memory_projection="PRIVATE-MEMORY-MARKER",
    )

    events = [event async for event in runtime.execute(context)]

    assert captured == ["<user_memory>\nPRIVATE-MEMORY-MARKER\n</user_memory>\n\nWrite a report"]
    assert "PRIVATE-MEMORY-MARKER" not in repr(events)
