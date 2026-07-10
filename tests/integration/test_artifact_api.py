import hashlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app

FIXTURE_MANIFEST = Path("tests/fixtures/agents/echo-agent/agent.yaml")
HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


@pytest.mark.asyncio
async def test_upload_list_and_download_artifact_are_tenant_scoped() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/v1/agents",
            json={"path": str(FIXTURE_MANIFEST)},
            headers=HEADERS,
        )
        session = await client.post(
            "/v1/sessions",
            json={"agent_name": "echo-agent", "agent_version": "0.1.0"},
            headers=HEADERS,
        )
        run = await client.post(
            f"/v1/sessions/{session.json()['session_id']}/runs",
            json={"prompt": "hello"},
            headers={**HEADERS, "Idempotency-Key": "artifact-run"},
        )
        run_id = run.json()["run_id"]
        content = b"artifact bytes"
        uploaded = await client.post(
            f"/v1/runs/{run_id}/artifacts",
            files={"file": ("result.txt", content, "text/plain")},
            headers=HEADERS,
        )
        assert uploaded.status_code == 201
        artifact = uploaded.json()
        assert artifact["status"] == "ready"
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()

        listed = await client.get(f"/v1/runs/{run_id}/artifacts", headers=HEADERS)
        assert [item["artifact_id"] for item in listed.json()] == [artifact["artifact_id"]]
        downloaded = await client.get(
            f"/v1/artifacts/{artifact['artifact_id']}/content", headers=HEADERS
        )
        assert downloaded.content == content

        cross_tenant = await client.get(
            f"/v1/artifacts/{artifact['artifact_id']}/content",
            headers={"X-Tenant-ID": "tenant-b", "X-User-ID": "user-2"},
        )
        assert cross_tenant.status_code == 404
