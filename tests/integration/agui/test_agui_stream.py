from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app

FIXTURE_MANIFEST = Path("tests/fixtures/agents/echo-agent/agent.yaml")
HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


@pytest.mark.asyncio
async def test_agui_stream_preserves_harness_event_id_for_reconnect() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        session = await client.post(
            "/v1/sessions",
            json={"agent_name": "echo-agent", "agent_version": "0.1.0"},
            headers=HEADERS,
        )
        run = await client.post(
            f"/v1/sessions/{session.json()['session_id']}/runs",
            json={"prompt": "hello"},
            headers={**HEADERS, "Idempotency-Key": "agui-run"},
        )
        run_id = run.json()["run_id"]
        await client.post(f"/v1/runs/{run_id}/cancel", headers=HEADERS)

        response = await client.get(
            f"/v1/agui/runs/{run_id}/events",
            headers={**HEADERS, "Last-Event-ID": "1"},
        )

    assert response.status_code == 200
    assert "id: 2:1\n" in response.text
    assert "id: 2:2\n" in response.text
    assert '"type":"STATE_SNAPSHOT"' in response.text
    assert '"type":"ACTIVITY_DELTA"' in response.text
    assert "id: 1\n" not in response.text


@pytest.mark.asyncio
async def test_agui_stream_resumes_inside_a_multi_event_projection() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        session = await client.post(
            "/v1/sessions",
            json={"agent_name": "echo-agent", "agent_version": "0.1.0"},
            headers=HEADERS,
        )
        run = await client.post(
            f"/v1/sessions/{session.json()['session_id']}/runs",
            json={"prompt": "hello"},
            headers={**HEADERS, "Idempotency-Key": "agui-child-resume"},
        )
        run_id = run.json()["run_id"]
        await client.post(f"/v1/runs/{run_id}/cancel", headers=HEADERS)

        response = await client.get(
            f"/v1/agui/runs/{run_id}/events",
            headers={**HEADERS, "Last-Event-ID": "2:1"},
        )

    assert response.status_code == 200
    assert "id: 2:1\n" not in response.text
    assert "id: 2:2\n" in response.text
