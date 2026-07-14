"""Opt-in smoke test for the real model gateway and Tavily remote MCP."""

import json
import os
import re
from typing import cast

import pytest

from harness.api.dependencies import build_memory_container
from harness.config import Settings
from harness.core.models import RunStatus
from harness.runtime.default_tools import TAVILY_ALLOWED_TOOLS, TAVILY_REFERENCE


def _live_tests_enabled() -> bool:
    return os.getenv("HARNESS_RUN_LIVE_TESTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def test_live_smoke_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_RUN_LIVE_TESTS", raising=False)
    assert not _live_tests_enabled()
    monkeypatch.setenv("HARNESS_RUN_LIVE_TESTS", "1")
    assert _live_tests_enabled()


def _configured_tavily_credential(settings: Settings) -> str | None:
    references_raw: object = json.loads(settings.mcp_secret_references_json)
    secrets_raw: object = json.loads(settings.mcp_server_secrets_json.get_secret_value())
    if not isinstance(references_raw, dict) or not isinstance(secrets_raw, dict):
        return None
    references = cast(dict[object, object], references_raw)
    secrets = cast(dict[object, object], secrets_raw)
    tavily = references.get(TAVILY_REFERENCE)
    if not isinstance(tavily, dict):
        return None
    tavily_values = cast(dict[object, object], tavily)
    secret_name = tavily_values.get("authorization")
    if not isinstance(secret_name, str):
        return None
    value = secrets.get(secret_name)
    return value if isinstance(value, str) and value else None


@pytest.mark.asyncio
async def test_tavily_live_search_returns_cited_current_information() -> None:
    if not _live_tests_enabled():
        pytest.skip("set HARNESS_RUN_LIVE_TESTS=1 to run external model smoke tests")
    settings = Settings()
    credential = _configured_tavily_credential(settings)
    if credential is None:
        pytest.skip("Tavily generic MCP secret reference is not configured")

    live_settings = settings.model_copy(
        update={
            "runtime": "claude-sdk",
            "sandbox_provider": "local",
            "otel_enabled": False,
        }
    )
    container = build_memory_container(settings=live_settings)
    try:
        await container.agents.publish(
            "local", "tests/fixtures/agents/tavily-live-agent/agent.yaml"
        )
        session = await container.sessions.create(
            "local", "live-smoke", "tavily-live-agent", "1.0.0"
        )
        run = await container.runs.create(
            "local",
            session.session_id,
            "tavily-live-current-info",
            input={
                "prompt": (
                    "Find the current stable Python release from python.org and include "
                    "the source title and full https URL."
                )
            },
        )

        completed = await container.worker.execute("local", run.run_id)
        events = await container.events.list_after("local", run.run_id, 0)

        event_summary = [
            (
                event.type,
                event.payload.get("name"),
                event.payload.get("error_type"),
                event.payload.get("subtype"),
            )
            for event in events
        ]
        if completed.status is not RunStatus.SUCCEEDED:
            pytest.fail(
                "live run failed; event sequence:\n"
                + "\n".join(map(str, event_summary)),
                pytrace=False,
            )
        tool_names = {
            str(event.payload.get("name"))
            for event in events
            if event.type == "tool.request"
        }
        assert tool_names.intersection(TAVILY_ALLOWED_TOOLS)
        answer = "".join(
            str(event.payload.get("text", ""))
            for event in events
            if event.type == "message.delta"
        )
        assert re.search(r"https://\S+", answer)
        if credential in repr(events):
            pytest.fail("Tavily credential leaked into durable runtime events")
    finally:
        if container.close is not None:
            await container.close()
