from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from harness.api.dependencies import Identity, require_identity

HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


@pytest.mark.asyncio
async def test_data_export_can_be_polled_and_downloaded() -> None:
    app = create_memory_app(auto_execute=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/data-lifecycle/jobs",
            headers=HEADERS,
            json={
                "kind": "export",
                "scope": {"kind": "user", "subjectId": "user-1"},
                "idempotencyKey": "export-user-1",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["jobId"]

        job = await client.get(f"/v1/data-lifecycle/jobs/{job_id}", headers=HEADERS)
        assert job.json()["status"] == "succeeded"
        artifact = await client.get(f"/v1/data-lifecycle/jobs/{job_id}/artifact", headers=HEADERS)
        assert artifact.status_code == 200
        assert artifact.headers["content-type"] == "application/zip"
        assert "data-export-user-user-1.zip" in artifact.headers["content-disposition"]


@pytest.mark.asyncio
async def test_tenant_scope_is_bound_to_authenticated_tenant() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/data-lifecycle/jobs",
            headers=HEADERS,
            json={
                "kind": "delete",
                "scope": {"kind": "tenant", "subjectId": "tenant-b"},
                "idempotencyKey": "bad-scope",
            },
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_member_can_manage_only_their_own_lifecycle_scope() -> None:
    app = create_memory_app()
    app.dependency_overrides[require_identity] = lambda: Identity(
        tenant_id="tenant-a",
        user_id="member-a",
        roles=frozenset({"member"}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        own = await client.post(
            "/v1/data-lifecycle/jobs",
            json={
                "kind": "export",
                "scope": {"kind": "user", "subjectId": "member-a"},
                "idempotencyKey": "member-own-export",
            },
        )
        other = await client.post(
            "/v1/data-lifecycle/jobs",
            json={
                "kind": "export",
                "scope": {"kind": "user", "subjectId": "member-b"},
                "idempotencyKey": "member-other-export",
            },
        )
        overview = await client.get("/v1/data-lifecycle/overview")
    assert own.status_code == 202
    assert other.status_code == 403
    assert overview.status_code == 403
