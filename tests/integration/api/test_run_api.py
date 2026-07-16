from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app

FIXTURE_MANIFEST = Path("tests/fixtures/agents/echo-agent/agent.yaml")
IDENTITY_HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


@pytest.mark.asyncio
async def test_publish_create_run_query_and_cancel_are_tenant_scoped() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        published = await client.post(
            "/v1/agents",
            json={"path": str(FIXTURE_MANIFEST)},
            headers=IDENTITY_HEADERS,
        )
        assert published.status_code == 201
        assert published.json()["name"] == "echo-agent"

        session = await client.post(
            "/v1/sessions",
            json={"agent_name": "echo-agent", "agent_version": "0.1.0"},
            headers=IDENTITY_HEADERS,
        )
        assert session.status_code == 201
        session_id = session.json()["session_id"]

        first = await client.post(
            f"/v1/sessions/{session_id}/runs",
            json={"prompt": "hello"},
            headers={**IDENTITY_HEADERS, "Idempotency-Key": "request-1"},
        )
        repeated = await client.post(
            f"/v1/sessions/{session_id}/runs",
            json={"prompt": "ignored on replay"},
            headers={**IDENTITY_HEADERS, "Idempotency-Key": "request-1"},
        )
        assert first.status_code == 202
        assert repeated.status_code == 202
        assert repeated.json()["run_id"] == first.json()["run_id"]
        assert first.json()["input"] == {"prompt": "hello"}

        run_id = first.json()["run_id"]
        fetched = await client.get(f"/v1/runs/{run_id}", headers=IDENTITY_HEADERS)
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "queued"

        cancelled = await client.post(f"/v1/runs/{run_id}/cancel", headers=IDENTITY_HEADERS)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_identity_headers_are_required_and_errors_are_structured() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)})

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "identity_required",
            "message": "Sign in with a valid access token",
        }
    }


@pytest.mark.asyncio
async def test_local_console_origin_is_allowed() -> None:
    app = create_memory_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/v1/agents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-tenant-id,x-user-id",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
