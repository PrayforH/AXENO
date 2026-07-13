import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from scripts.bootstrap_local_agent import bootstrap_local_agent
from scripts.e2e_fake_runtime import run_fake_e2e


@pytest.mark.asyncio
async def test_local_fake_runtime_stack() -> None:
    report = await run_fake_e2e()

    assert report["status"] == "succeeded"
    assert report["otel_enabled"] is False
    assert report["agui_events"] >= 10


@pytest.mark.asyncio
async def test_local_bootstrap_publishes_default_agent_for_agui() -> None:
    app = create_memory_app(auto_execute=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await bootstrap_local_agent(client)
        await bootstrap_local_agent(client)
        response = await client.post(
            "/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
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
