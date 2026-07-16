from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.api.app import create_app
from harness.api.dependencies import ApiContainer
from harness.composition import build_production_container
from harness.config import Settings
from harness.storage.database import SessionFactory

DatabaseFixture = tuple[AsyncEngine, SessionFactory]
SERVICE_TOKEN = "studio-production-token-with-at-least-32-characters"


def production_settings() -> Settings:
    return Settings(
        environment="production",
        runtime="claude-sdk",
        api_bearer_token=SecretStr(SERVICE_TOKEN),
        database_url="postgresql+asyncpg://harness:harness@localhost:5432/harness",
        redis_url="redis://localhost:6379/0",
        minio_access_key=SecretStr("test-minio-access"),
        minio_secret_key=SecretStr("test-minio-secret"),
    )


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "builder-a",
    }


def draft_request() -> dict[str, str]:
    return {
        "name": "durable-researcher",
        "domain": "policy-research",
        "displayName": "持久化研究助手",
        "description": "验证生产组合根重建后的草稿恢复。",
        "template": "analyst",
    }


async def close(container: ApiContainer) -> None:
    assert container.close is not None
    await container.close()


@pytest.mark.asyncio
async def test_production_studio_api_restores_draft_after_container_restart(
    database: DatabaseFixture,
) -> None:
    _engine, _sessions = database
    first = build_production_container(production_settings(), execution_enabled=False)
    first_app: FastAPI = create_app(first)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/v1/studio/drafts", headers=headers(), json=draft_request()
            )
    finally:
        await close(first)

    assert created.status_code == 201
    draft_id = cast(str, created.json()["draftId"])

    second = build_production_container(production_settings(), execution_enabled=False)
    second_app: FastAPI = create_app(second)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=second_app), base_url="http://test"
        ) as client:
            restored = await client.get(
                f"/v1/studio/drafts/{draft_id}", headers=headers()
            )
    finally:
        await close(second)

    assert restored.status_code == 200
    assert restored.json() == created.json()
