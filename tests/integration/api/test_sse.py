from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app

FIXTURE_MANIFEST = Path("tests/fixtures/agents/echo-agent/agent.yaml")
IDENTITY_HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


@pytest.mark.asyncio
async def test_sse_replays_only_events_after_last_event_id() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/v1/agents",
            json={"path": str(FIXTURE_MANIFEST)},
            headers=IDENTITY_HEADERS,
        )
        session = await client.post(
            "/v1/sessions",
            json={"agent_name": "echo-agent", "agent_version": "0.1.0"},
            headers=IDENTITY_HEADERS,
        )
        run = await client.post(
            f"/v1/sessions/{session.json()['session_id']}/runs",
            json={"prompt": "hello"},
            headers={**IDENTITY_HEADERS, "Idempotency-Key": "request-1"},
        )
        run_id = run.json()["run_id"]
        await client.post(f"/v1/runs/{run_id}/cancel", headers=IDENTITY_HEADERS)

        response = await client.get(
            f"/v1/runs/{run_id}/events",
            headers={**IDENTITY_HEADERS, "Last-Event-ID": "1"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\n" in response.text
    assert "event: run.cancelling\n" in response.text
    assert "id: 1\n" not in response.text
