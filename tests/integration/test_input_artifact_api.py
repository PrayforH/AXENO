import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_app, create_memory_app
from harness.api.dependencies import build_memory_container

HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


@pytest.mark.asyncio
async def test_upload_and_download_input_artifact_are_user_scoped() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        content = b"browser-selected bytes"
        uploaded = await client.post(
            "/v1/input-artifacts",
            files={"file": ("notes.txt", content, "text/plain")},
            headers=HEADERS,
        )

        assert uploaded.status_code == 201
        artifact = uploaded.json()
        assert artifact["input_artifact_id"].startswith("input_artifact_")
        assert artifact["name"] == "notes.txt"
        assert artifact["media_type"] == "text/plain"
        assert artifact["status"] == "ready"
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
        assert artifact["size_bytes"] == len(content)

        downloaded = await client.get(
            f"/v1/input-artifacts/{artifact['input_artifact_id']}/content",
            headers=HEADERS,
        )
        assert downloaded.status_code == 200
        assert downloaded.content == content

        cross_user = await client.get(
            f"/v1/input-artifacts/{artifact['input_artifact_id']}/content",
            headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "user-2"},
        )
        assert cross_user.status_code == 404


@pytest.mark.asyncio
async def test_upload_rejects_oversized_input_without_returning_an_id() -> None:
    container = build_memory_container()
    container.input_artifacts.max_file_bytes = 4
    app = create_app(container)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/input-artifacts",
            files={"file": ("large.txt", b"12345", "text/plain")},
            headers=HEADERS,
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "input_artifact_too_large"
    assert "input_artifact_id" not in response.text
