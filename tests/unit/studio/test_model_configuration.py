from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from harness.core.errors import ConflictError
from harness.core.models import ModelCompatibility
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.mcp_credential_store import (
    InMemoryMcpCredentialRepository,
    McpCredentialCipher,
    McpCredentialService,
)
from harness.studio.model_configuration import (
    BindAgentModelRequest,
    ConfigureModelRequest,
    GenerateImageRequest,
    ModelConfigurationService,
)
from harness.studio.repositories import InMemoryAgentDraftRepository


def service(
    *,
    environment: str = "test",
    client: httpx.AsyncClient | None = None,
    server_routes: tuple[CcSwitchClaudeConfig, ...] = (),
) -> tuple[ModelConfigurationService, CapabilityCatalogService, InMemoryMcpCredentialRepository]:
    catalogs = CapabilityCatalogService(
        InMemoryCapabilityCatalogRepository(),
        InMemoryAgentDraftRepository(),
        clock=lambda: datetime(2026, 8, 13, tzinfo=UTC),
    )
    credentials = InMemoryMcpCredentialRepository()
    credential_service = McpCredentialService(
        credentials,
        McpCredentialCipher(SecretStr("test-encryption-key")),
    )
    return (
        ModelConfigurationService(
            catalogs,
            credential_service,
            environment=environment,
            server_routes=server_routes,
            http_client=client,
        ),
        catalogs,
        credentials,
    )


def request(**updates: object) -> ConfigureModelRequest:
    values: dict[str, object] = {
        "expectedRevision": 1,
        "label": "视觉主模型",
        "modelType": "vision",
        "provider": "Example AI",
        "model": "example-vision-1",
        "baseUrl": "https://models.example.test/v1",
        "apiFormat": "openai_compatible",
        "authScheme": "bearer",
        "apiKey": "secret-value-never-returned",
        "enabled": True,
    }
    values.update(updates)
    return ConfigureModelRequest.model_validate(values)


@pytest.mark.asyncio
async def test_configure_encrypts_key_and_redacts_runtime_catalog() -> None:
    models, catalogs, credentials = service()

    configured = await models.configure(
        "tenant-a", "admin-a", "vision-primary", request()
    )

    view = next(item for item in configured.models if item.route_id == "vision-primary")
    assert view.credential_configured is True
    assert "secret-value-never-returned" not in view.model_dump_json()
    stored = await credentials.get(
        "tenant-a", "tenant:model-control-plane", "vision-primary"
    )
    assert stored is not None
    assert "secret-value-never-returned" not in stored.ciphertext
    runtime_catalog = await catalogs.get_for_user("tenant-a", "member-a")
    route = next(
        item
        for item in runtime_catalog.catalog.model_routes
        if item.route_id == "vision-primary"
    )
    assert route.base_url is None
    assert route.model_type == "vision"


@pytest.mark.asyncio
async def test_agent_binding_changes_runtime_route_without_manifest_edit() -> None:
    models, _catalogs, _credentials = service()
    configured = await models.configure(
        "tenant-a", "admin-a", "vision-primary", request()
    )
    bound = await models.bind_agent(
        "tenant-a",
        "admin-a",
        "helper-agent",
        BindAgentModelRequest(
            expectedRevision=configured.revision,
            routeId="vision-primary",
        ),
    )

    resolved = await models.resolve_runtime(
        "tenant-a", "helper-agent", "manifest-route"
    )

    assert bound.agent_model_bindings == {"helper-agent": "vision-primary"}
    assert resolved is not None
    assert resolved.route_id == "vision-primary"
    assert resolved.model == "example-vision-1"
    assert resolved.base_url == "https://models.example.test/v1"
    assert resolved.credential.get_secret_value() == "secret-value-never-returned"


@pytest.mark.asyncio
async def test_image_generation_uses_dedicated_endpoint_and_never_chat_route() -> None:
    captured: list[httpx.Request] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        captured.append(incoming)
        return httpx.Response(
            200,
            json={"data": [{"url": "https://cdn.example.test/image.png"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models, _catalogs, _credentials = service(client=client)
        configured = await models.configure(
            "tenant-a",
            "admin-a",
            "image-primary",
            request(
                label="图像生成",
                modelType="image_generation",
                model="image-1",
                apiFormat="openai_images",
            ),
        )
        result = await models.generate_image(
            "tenant-a",
            "image-primary",
            GenerateImageRequest(prompt="A safe product illustration"),
        )

    image = next(item for item in configured.models if item.route_id == "image-primary")
    assert image.capabilities == ("image_generation",)
    assert image.deletable is True
    assert result.images[0].url == "https://cdn.example.test/image.png"
    assert captured[0].url.path.endswith("/v1/images/generations")
    assert captured[0].headers["authorization"] == "Bearer secret-value-never-returned"


@pytest.mark.asyncio
async def test_delete_permanently_removes_workspace_model_and_credential() -> None:
    models, _catalogs, credentials = service()
    configured = await models.configure(
        "tenant-a", "admin-a", "minimax-h3", request()
    )

    deleted = await models.delete(
        "tenant-a", "admin-a", "minimax-h3", configured.revision
    )

    assert "minimax-h3" not in {item.route_id for item in deleted.models}
    assert await credentials.get(
        "tenant-a", "tenant:model-control-plane", "minimax-h3"
    ) is None


@pytest.mark.asyncio
async def test_delete_of_platform_model_route_persists() -> None:
    models, _catalogs, _credentials = service()

    deleted = await models.delete(
        "tenant-a", "admin-a", "deepseek-v4-flash", 1
    )
    repeated = await models.list("tenant-a")

    assert "deepseek-v4-flash" not in {item.route_id for item in deleted.models}
    assert repeated == deleted


@pytest.mark.asyncio
async def test_delete_rejects_model_still_bound_to_an_agent() -> None:
    models, _catalogs, _credentials = service()
    configured = await models.configure(
        "tenant-a", "admin-a", "minimax-h3", request()
    )
    bound = await models.bind_agent(
        "tenant-a",
        "admin-a",
        "helper-agent",
        BindAgentModelRequest(
            expectedRevision=configured.revision,
            routeId="minimax-h3",
        ),
    )

    with pytest.raises(ConflictError, match="agent:helper-agent"):
        await models.delete(
            "tenant-a", "admin-a", "minimax-h3", bound.revision
        )


@pytest.mark.asyncio
async def test_production_allows_private_models_but_rejects_unsafe_endpoints() -> None:
    models, _catalogs, _credentials = service(environment="production")

    configured = await models.configure(
        "tenant-a",
        "admin-a",
        "private-model",
        request(baseUrl="http://172.20.109.112:31300/v1"),
    )
    assert next(
        item for item in configured.models if item.route_id == "private-model"
    ).base_url == "http://172.20.109.112:31300/v1"

    with pytest.raises(ConflictError, match="require HTTPS"):
        await models.configure(
            "tenant-a",
            "admin-a",
            "public-http-model",
            request(
                expectedRevision=configured.revision,
                baseUrl="http://8.8.8.8/v1",
            ),
        )

    with pytest.raises(ConflictError, match="loopback or link-local"):
        await models.configure(
            "tenant-a",
            "admin-a",
            "loopback-model",
            request(
                expectedRevision=configured.revision,
                baseUrl="https://127.0.0.1/v1",
            ),
        )


@pytest.mark.asyncio
async def test_server_route_is_imported_testable_and_does_not_expose_secret() -> None:
    captured: list[httpx.Request] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        captured.append(incoming)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}]})

    route = CcSwitchClaudeConfig(
        route_id="minimax-m3",
        base_url="https://api.minimaxi.com/anthropic",
        model="MiniMax-M3",
        provider="anthropic",
        credential=SecretStr("server-only-secret"),
        auth_scheme="x-api-key",
        compatibility=ModelCompatibility.FULL,
        capabilities=frozenset({"streaming", "tool_use", "vision"}),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models, _catalogs, credentials = service(
            environment="production", client=client, server_routes=(route,)
        )
        listed = await models.list("tenant-a")
        result = await models.test("tenant-a", "minimax-m3")

    view = next(item for item in listed.models if item.route_id == "minimax-m3")
    assert view.base_url == "https://api.minimaxi.com/anthropic/v1"
    assert view.model_type == "vision"
    assert view.credential_configured is True
    assert view.deletable is True
    assert "server-only-secret" not in listed.model_dump_json()
    stored = await credentials.get(
        "tenant-a", "tenant:model-control-plane", "minimax-m3"
    )
    assert stored is not None
    assert result.ok is True
    assert captured[0].url == "https://api.minimaxi.com/anthropic/v1/messages"
    assert captured[0].headers["x-api-key"] == "server-only-secret"
    assert captured[0].headers["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_trusted_server_route_may_use_private_http_but_workspace_override_cannot() -> None:
    route = CcSwitchClaudeConfig(
        route_id="glm-5-2",
        base_url="http://172.20.109.174:4000",
        model="shdata-glm",
        provider="new-api",
        credential=SecretStr("server-only-secret"),
        auth_scheme="bearer",
    )
    models, _catalogs, _credentials = service(
        environment="production", server_routes=(route,)
    )

    resolved = await models.resolve_runtime("tenant-a", "helper-agent", "glm-5-2")

    assert resolved is not None
    assert resolved.base_url == "http://172.20.109.174:4000"


@pytest.mark.asyncio
async def test_imported_server_model_runs_without_server_fallback_after_import() -> None:
    route = CcSwitchClaudeConfig(
        route_id="minimax-m3",
        base_url="https://api.minimaxi.com/anthropic",
        model="MiniMax-M3",
        provider="anthropic",
        credential=SecretStr("server-only-secret"),
        auth_scheme="x-api-key",
        capabilities=frozenset({"streaming", "tool_use", "vision"}),
    )
    models, catalogs, credentials = service(server_routes=(route,))
    imported = await models.list("tenant-a")
    database_only = ModelConfigurationService(
        catalogs,
        McpCredentialService(
            credentials,
            McpCredentialCipher(SecretStr("test-encryption-key")),
        ),
    )

    listed = await database_only.list("tenant-a")
    resolved = await database_only.resolve_runtime(
        "tenant-a", "helper-agent", "minimax-m3"
    )

    view = next(item for item in listed.models if item.route_id == "minimax-m3")
    assert listed == imported
    assert view.base_url == "https://api.minimaxi.com/anthropic/v1"
    assert view.model == "MiniMax-M3"
    assert resolved is not None
    assert resolved.base_url == "https://api.minimaxi.com/anthropic"
    assert resolved.credential.get_secret_value() == "server-only-secret"
