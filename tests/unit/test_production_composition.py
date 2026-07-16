import json
import os
import subprocess
import sys
from dataclasses import replace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from harness.api.app import create_app, create_configured_app
from harness.api.dependencies import build_memory_container
from harness.composition import build_production_container
from harness.config import Settings
from harness.core.manifest import AgentManifest
from harness.core.models import ExecutionIdentity
from harness.runtime.registry_runtime import RegistryClaudeRuntime
from harness.runtime.tools import ToolResolver
from harness.storage.catalog_repository import PostgresCapabilityCatalogRepository
from harness.storage.redis import RedisTaskQueue
from harness.storage.repositories import PostgresEventRepository
from harness.storage.studio_repository import PostgresAgentDraftRepository


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "runtime": "claude-sdk",
        "sandbox_provider": "local",
        "allow_unsafe_local_sandbox": True,
        "api_bearer_token": SecretStr("a" * 32),
        "new_api_base_url": "https://gateway.example",
        "new_api_model": "deepseek-chat",
        "new_api_key": SecretStr("model-secret"),
        "minio_access_key": SecretStr("minio-access"),
        "minio_secret_key": SecretStr("minio-secret"),
    }
    values.update(overrides)
    return Settings(**values)  # pyright: ignore[reportArgumentType]


def tavily_manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "apiVersion": "harness/v1alpha1",
            "kind": "Agent",
            "metadata": {"name": "web-agent", "version": "1.0.0"},
            "spec": {
                "runtime": "claude-agent-sdk",
                "model": {"route": "default", "model": "gateway-model"},
                "prompt": {"system": "prompts/system.md"},
                "tools": [{"mcp": "tavily-readonly"}],
                "permissions": {"policy": "default"},
            },
        }
    )


def execution_identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        project_id="web-agent",
        session_id="session-a",
        run_id="run-a",
        agent_name="web-agent",
        agent_version="1.0.0",
    )


@pytest.mark.asyncio
async def test_production_container_uses_durable_event_and_queue_adapters() -> None:
    container = build_production_container(
        production_settings(
            new_api_compatibility="degraded",
            new_api_capabilities="streaming",
        )
    )

    try:
        assert isinstance(container.events, PostgresEventRepository)
        assert isinstance(container.agent_drafts, PostgresAgentDraftRepository)
        assert isinstance(
            vars(container.capability_catalogs)["_repository"],
            PostgresCapabilityCatalogRepository,
        )
        assert isinstance(container.task_queue, RedisTaskQueue)
        assert container.auto_execute is False
        runtime = cast(RegistryClaudeRuntime, container.runtime)
        gateway = vars(runtime)["_config"]
        assert gateway.compatibility.value == "degraded"
        assert gateway.capabilities == frozenset({"streaming"})
    finally:
        assert container.close is not None
        await container.close()


@pytest.mark.asyncio
async def test_production_composition_uses_server_owned_mcp_registry() -> None:
    container = build_production_container(
        production_settings(
            mcp_secret_references_json=json.dumps(
                {"tavily-readonly": {"api_key": "TAVILY_API_KEY"}}
            ),
            mcp_server_secrets_json=SecretStr(
                json.dumps({"TAVILY_API_KEY": "production-key"})
            ),
        )
    )
    try:
        runtime = cast(RegistryClaudeRuntime, container.runtime)
        resolver = cast(ToolResolver, vars(runtime)["_tool_resolver"])

        resolved = await resolver.resolve(tavily_manifest(), execution_identity())

        tavily = cast(dict[str, object], resolved.mcp_servers["tavily"])
        assert tavily.get("url") == (
            "https://mcp.tavily.com/mcp/?tavilyApiKey=production-key"
        )
    finally:
        assert container.close is not None
        await container.close()


def test_production_container_fails_fast_without_gateway_credentials() -> None:
    with pytest.raises(ValueError, match="production requires HARNESS_NEW_API"):
        build_production_container(
            production_settings(new_api_key=SecretStr(""), new_api_model="")
        )


def test_production_container_rejects_empty_gateway_capabilities() -> None:
    with pytest.raises(ValueError, match="CAPABILITIES must not be empty"):
        build_production_container(production_settings(new_api_capabilities=" , "))


def test_production_container_rejects_implicit_local_sandbox() -> None:
    with pytest.raises(ValueError, match="ALLOW_UNSAFE_LOCAL_SANDBOX"):
        build_production_container(
            production_settings(allow_unsafe_local_sandbox=False)
        )


@pytest.mark.asyncio
async def test_production_composition_configures_optional_anthropic_fallback() -> None:
    container = build_production_container(
        production_settings(
            anthropic_api_key=SecretStr("anthropic-secret"),
            anthropic_model="claude-fallback",
        )
    )
    try:
        runtime = cast(RegistryClaudeRuntime, container.runtime)
        fallback = vars(runtime)["_fallback_config"]
        assert fallback is not None
        assert fallback.provider == "anthropic"
        assert fallback.model == "claude-fallback"
        assert "anthropic-secret" not in repr(fallback)
    finally:
        assert container.close is not None
        await container.close()


def test_configured_app_selects_production_composition() -> None:
    app = create_configured_app(production_settings())

    assert isinstance(app.state.container.events, PostgresEventRepository)
    assert app.state.container.auto_execute is False


def test_production_app_fails_fast_without_strong_api_credential() -> None:
    with pytest.raises(ValueError, match="HARNESS_API_BEARER_TOKEN"):
        create_configured_app(production_settings(api_bearer_token=SecretStr("short")))


def test_app_lifespan_closes_composed_resources() -> None:
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    container = replace(build_memory_container(), close=close)

    with TestClient(create_app(container)):
        pass

    assert closed is True


def test_production_composition_imports_in_clean_worker_process() -> None:
    environment = {
        **os.environ,
        "HARNESS_ENVIRONMENT": "production",
        "HARNESS_RUNTIME": "claude-sdk",
        "HARNESS_NEW_API_BASE_URL": "https://gateway.example",
        "HARNESS_NEW_API_MODEL": "deepseek-chat",
        "HARNESS_NEW_API_KEY": "model-secret",
        "HARNESS_MINIO_ACCESS_KEY": "minio-access",
        "HARNESS_MINIO_SECRET_KEY": "minio-secret",
    }

    result = subprocess.run(
        [sys.executable, "-c", "import harness.composition"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
