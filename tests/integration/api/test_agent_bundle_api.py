from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from harness.agent_package import pack_agent_package
from harness.api.app import create_memory_app
from harness.api.routes import agents as agent_routes
from harness.config import Settings

API_TOKEN = "bundle-test-service-token-with-32-characters"
HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "X-Tenant-ID": "tenant-a",
    "X-User-ID": "publisher",
}
MANIFEST = Path("agents/public-opinion-agent/agent.yaml")


def production_settings() -> Settings:
    return Settings(
        environment="production",
        api_bearer_token=SecretStr(API_TOKEN),
        allow_unsafe_local_sandbox=True,
    )


@pytest.mark.asyncio
async def test_production_api_accepts_bundle_and_rejects_server_local_path(
    tmp_path: Path,
) -> None:
    archive, report = pack_agent_package(MANIFEST, output_directory=tmp_path)
    app = create_memory_app(settings=production_settings())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        local_path = await client.post("/v1/agents", json={"path": str(MANIFEST)}, headers=HEADERS)
        published = await client.post(
            "/v1/agents/bundles",
            content=archive.read_bytes(),
            headers={**HEADERS, "Content-Type": "application/zip"},
        )
        repeated = await client.post(
            "/v1/agents/bundles",
            content=archive.read_bytes(),
            headers={**HEADERS, "Content-Type": "application/zip"},
        )

    assert local_path.status_code == 403
    assert published.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json() == published.json()
    assert published.json()["manifest_hash"] == report.snapshot.content_hash


@pytest.mark.asyncio
async def test_published_bundle_is_available_in_the_task_agent_catalog(
    tmp_path: Path,
) -> None:
    archive, _report = pack_agent_package(MANIFEST, output_directory=tmp_path)
    app = create_memory_app(settings=production_settings())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        published = await client.post(
            "/v1/agents/bundles",
            content=archive.read_bytes(),
            headers={**HEADERS, "Content-Type": "application/zip"},
        )
        catalog = await client.get("/v1/agents", headers=HEADERS)

    assert published.status_code == 201
    assert catalog.status_code == 200
    assert catalog.json() == [
        {
            "name": "public-opinion-agent",
            "version": "0.3.5",
            "display_name": "舆情分析",
            "domain": "public-opinion",
            "model_route": "deepseek-v4-pro",
            "model": "deepseek-v4-pro",
            "model_capabilities": [],
            "owner_user_id": "publisher",
            "scope": "personal",
            "space_id": None,
            "space_name": None,
            "runnable_by_viewer": True,
        }
    ]


@pytest.mark.asyncio
async def test_bundle_api_returns_structured_validation_error() -> None:
    app = create_memory_app(settings=production_settings())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents/bundles",
            content=b"not-a-bundle",
            headers={**HEADERS, "Content-Type": "application/zip"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "agent_package_invalid"


@pytest.mark.asyncio
async def test_bundle_api_rejects_oversized_content_length_before_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "MAX_AGENT_BUNDLE_UPLOAD_BYTES", 4)
    app = create_memory_app(settings=production_settings())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents/bundles",
            content=b"x",
            headers={
                **HEADERS,
                "Content-Type": "application/zip",
                "Content-Length": "5",
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "agent_bundle_too_large"


@pytest.mark.asyncio
async def test_bundle_api_stops_chunked_upload_at_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "MAX_AGENT_BUNDLE_UPLOAD_BYTES", 4)
    app = create_memory_app(settings=production_settings())

    async def chunks():
        yield b"123"
        yield b"45"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents/bundles",
            content=chunks(),
            headers={**HEADERS, "Content-Type": "application/zip"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "agent_bundle_too_large"


@pytest.mark.asyncio
async def test_bundle_api_requires_zip_media_type() -> None:
    app = create_memory_app(settings=production_settings())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents/bundles",
            content=b"not-a-bundle",
            headers={**HEADERS, "Content-Type": "application/octet-stream"},
        )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "agent_bundle_media_type_invalid"
