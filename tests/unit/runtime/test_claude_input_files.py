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
async def test_runtime_adds_staged_input_inventory_to_prompt(tmp_path: Path) -> None:
    snapshot = load_manifest("tests/fixtures/agents/echo-agent/agent.yaml")
    now = datetime.now(UTC)
    version = AgentVersion(
        tenant_id="tenant-a",
        name="echo-agent",
        version="0.1.0",
        status=AgentVersionStatus.PUBLISHED,
        manifest_hash=snapshot.content_hash,
        snapshot=snapshot.model_dump(mode="json"),
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
    prompts: list[str] = []

    async def fake_query(
        prompt: str, _options: ClaudeAgentOptions
    ) -> AsyncIterator[object]:
        prompts.append(prompt)
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
    )
    context = RuntimeContext(
        run=Run(
            run_id="run-file",
            session_id="session-file",
            tenant_id="tenant-a",
            status=RunStatus.RUNNING,
            idempotency_key="file",
            created_at=now,
            updated_at=now,
            input={"prompt": "Find the unique fact."},
        ),
        session=Session(
            session_id="session-file",
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=now,
        ),
        workspace=tmp_path,
        input_files=("inputs/abc-facts.txt", "inputs/def-table.csv"),
        processed_input_paths=("inputs/def-table.csv",),
    )

    _events = [event async for event in runtime.execute(context)]

    assert prompts == [
        "Find the unique fact.\n\n"
        "Browser-uploaded input files are available in this run workspace:\n"
        "Preferred model-readable representations:\n"
        "- inputs/def-table.csv\n"
        "Read these exact relative paths first. When a processed representation "
        "is listed, do not call Read on its source PDF or Office binary.\n\n"
        "Original uploads:\n"
        "- inputs/abc-facts.txt\n"
        "Read an original directly only when no processed representation exists, "
        "such as for an image.\n"
        "Use the available file tools to inspect them when relevant."
    ]
