import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from harness.api.dependencies import Identity, require_identity


@pytest.mark.asyncio
async def test_reliability_overview_is_readable_but_reconcile_is_admin_only() -> None:
    app = create_memory_app()
    app.dependency_overrides[require_identity] = lambda: Identity(
        tenant_id="tenant-a",
        user_id="viewer-a",
        roles=frozenset({"viewer"}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        overview = await client.get("/v1/operations/overview")
        denied = await client.post("/v1/operations/reconcile")

    assert overview.status_code == 200
    assert len(overview.json()["objectives"]) == 6
    assert overview.json()["capacity"]["queueReady"] == 0
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_reconcile_and_prometheus_endpoint_is_text_format() -> None:
    app = create_memory_app()
    app.dependency_overrides[require_identity] = lambda: Identity(
        tenant_id="tenant-a",
        user_id="admin-a",
        roles=frozenset({"admin"}),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        reconciled = await client.post("/v1/operations/reconcile")
        metrics = await client.get("/metrics")

    assert reconciled.status_code == 200
    assert reconciled.json() == {"reaped": 0}
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith(
        "text/plain; version=0.0.4"
    )
    assert "# HELP harness_api_request_duration_seconds" in metrics.text
