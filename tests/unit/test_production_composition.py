from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from harness.api.app import create_app, create_configured_app
from harness.api.dependencies import build_memory_container
from harness.composition import build_production_container
from harness.config import Settings
from harness.storage.redis import RedisTaskQueue
from harness.storage.repositories import PostgresEventRepository


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "runtime": "claude-sdk",
        "sandbox_provider": "local",
        "new_api_base_url": "https://gateway.example",
        "new_api_model": "deepseek-chat",
        "new_api_key": SecretStr("model-secret"),
        "minio_access_key": SecretStr("minio-access"),
        "minio_secret_key": SecretStr("minio-secret"),
    }
    values.update(overrides)
    return Settings(**values)  # pyright: ignore[reportArgumentType]


@pytest.mark.asyncio
async def test_production_container_uses_durable_event_and_queue_adapters() -> None:
    container = build_production_container(production_settings())

    try:
        assert isinstance(container.events, PostgresEventRepository)
        assert isinstance(container.task_queue, RedisTaskQueue)
        assert container.auto_execute is False
    finally:
        assert container.close is not None
        await container.close()


def test_production_container_fails_fast_without_gateway_credentials() -> None:
    with pytest.raises(ValueError, match="production requires HARNESS_NEW_API"):
        build_production_container(
            production_settings(new_api_key=SecretStr(""), new_api_model="")
        )


def test_configured_app_selects_production_composition() -> None:
    app = create_configured_app(production_settings())

    assert isinstance(app.state.container.events, PostgresEventRepository)
    assert app.state.container.auto_execute is False


def test_app_lifespan_closes_composed_resources() -> None:
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    container = replace(build_memory_container(), close=close)

    with TestClient(create_app(container)):
        pass

    assert closed is True
