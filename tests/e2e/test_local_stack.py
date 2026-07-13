from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from harness.api.dependencies import build_memory_container
from harness.core.models import ApprovalStatus, RunStatus
from scripts.bootstrap_local_agent import (
    DEFAULT_MANIFEST,
    bootstrap_local_agent,
    bootstrap_local_agents,
    local_client_options,
)
from scripts.e2e_fake_runtime import run_fake_e2e


@pytest.mark.asyncio
async def test_local_fake_runtime_stack() -> None:
    report = await run_fake_e2e()

    assert report["status"] == "succeeded"
    assert report["otel_enabled"] is False
    assert report["agui_events"] >= 10


@pytest.mark.asyncio
async def test_local_bootstrap_publishes_default_agent_for_agui() -> None:
    assert DEFAULT_MANIFEST == Path("agents/echo-agent/agent.yaml")
    app = create_memory_app(auto_execute=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await bootstrap_local_agent(client)
        await bootstrap_local_agent(client)
        response = await client.post(
            "/v1/agui?agent_name=echo-agent&agent_version=0.2.0",
            headers={"X-Tenant-ID": "local", "X-User-ID": "developer"},
            json={
                "threadId": "bootstrap-thread",
                "runId": "bootstrap-run",
                "state": {},
                "messages": [{"id": "message-1", "role": "user", "content": "hello"}],
                "tools": [],
                "context": [],
                "forwardedProps": {},
            },
        )

    assert response.status_code == 200
    assert '"type":"RUN_FINISHED"' in response.text


@pytest.mark.asyncio
async def test_local_bootstrap_publishes_referenced_helper_agent() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await bootstrap_local_agents(client)
        response = await client.post(
            "/v1/sessions",
            headers={"X-Tenant-ID": "local", "X-User-ID": "developer"},
            json={"agent_name": "helper", "agent_version": "1.0.0"},
        )

    assert response.status_code == 201


def test_local_bootstrap_does_not_route_loopback_through_system_proxy() -> None:
    assert local_client_options("http://127.0.0.1:8000") == {
        "base_url": "http://127.0.0.1:8000",
        "timeout": 10,
        "trust_env": False,
    }


def test_dev_up_routes_web_to_published_validation_agent_version() -> None:
    script = Path("scripts/dev_up.sh").read_text()

    assert "HARNESS_AGENT_VERSION=0.2.0" in script
    assert "Local Agent: echo-agent@0.2.0" in script


@pytest.mark.asyncio
async def test_approval_resume_closes_message_and_uses_a_new_message_id() -> None:
    container = build_memory_container()
    await container.agents.publish("local", "tests/fixtures/agents/echo-agent/agent.yaml")
    session = await container.sessions.create(
        "local", "developer", "echo-agent", "0.1.0"
    )
    run = await container.runs.create(
        "local",
        session.session_id,
        "approval-message-lifecycle",
        input={"prompt": "[approval] [artifact] verify"},
    )

    paused = await container.worker.execute("local", run.run_id)
    assert paused.status is RunStatus.WAITING_APPROVAL
    paused_events = await container.events.list_after("local", run.run_id, 0)
    assert paused_events[-1].type == "message.completed"

    approval_event = next(
        item for item in paused_events if item.type == "approval.requested"
    )
    await container.approvals.decide(
        tenant_id="local",
        approval_id=str(approval_event.payload["approval_id"]),
        decision=ApprovalStatus.APPROVED,
    )
    completed = await container.worker.execute("local", run.run_id)
    assert completed.status is RunStatus.SUCCEEDED

    all_events = await container.events.list_after("local", run.run_id, 0)
    message_ids = [
        str(item.payload["message_id"])
        for item in all_events
        if item.type == "message.start"
    ]
    assert len(message_ids) == 2
    assert len(set(message_ids)) == 2
