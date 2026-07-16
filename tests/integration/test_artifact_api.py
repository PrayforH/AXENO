import hashlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from harness.quota.models import QuotaResource, ReplaceQuotaPolicyRequest

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
        cross_user_headers = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-2"}
        cross_user_run = await client.get(f"/v1/runs/{run_id}", headers=cross_user_headers)
        assert cross_user_run.status_code == 404
        cross_user_create = await client.post(
            f"/v1/sessions/{session.json()['session_id']}/runs",
            json={"prompt": "not mine"},
            headers={**cross_user_headers, "Idempotency-Key": "cross-user"},
        )
        assert cross_user_create.status_code == 404
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

        for method, url in (
            ("GET", f"/v1/runs/{run_id}/artifacts"),
            ("GET", f"/v1/artifacts/{artifact['artifact_id']}/content"),
            ("POST", f"/v1/runs/{run_id}/cancel"),
            ("GET", f"/v1/runs/{run_id}/events"),
            ("GET", f"/v1/agui/runs/{run_id}/events"),
        ):
            response = await client.request(method, url, headers=cross_user_headers)
            assert response.status_code == 404

        cross_tenant = await client.get(
            f"/v1/artifacts/{artifact['artifact_id']}/content",
            headers={"X-Tenant-ID": "tenant-b", "X-User-ID": "user-2"},
        )
        assert cross_tenant.status_code == 404


@pytest.mark.asyncio
async def test_artifact_upload_stops_at_configured_size_limit() -> None:
    app = create_memory_app()
    app.state.container.artifacts.max_file_bytes = 4
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
            headers={**HEADERS, "Idempotency-Key": "artifact-limit"},
        )
        response = await client.post(
            f"/v1/runs/{run.json()['run_id']}/artifacts",
            files={"file": ("large.txt", b"12345", "text/plain")},
            headers=HEADERS,
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "artifact_too_large"


@pytest.mark.asyncio
async def test_artifact_quota_is_checked_before_pending_metadata_is_created() -> None:
    app = create_memory_app()
    await app.state.container.quotas.replace_policy(
        tenant_id="tenant-a",
        user_id="owner-a",
        policy_id="tenant-default",
        request=ReplaceQuotaPolicyRequest(
            expectedRevision=0,
            limits={QuotaResource.ARTIFACT_BYTES: 4},
        ),
    )
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
            headers={**HEADERS, "Idempotency-Key": "artifact-quota"},
        )
        run_id = run.json()["run_id"]
        rejected = await client.post(
            f"/v1/runs/{run_id}/artifacts",
            files={"file": ("too-large.txt", b"12345", "text/plain")},
            headers=HEADERS,
        )
        listed = await client.get(f"/v1/runs/{run_id}/artifacts", headers=HEADERS)

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "quota_exceeded"
    assert "artifact_bytes" in rejected.json()["error"]["message"]
    assert listed.json() == []
