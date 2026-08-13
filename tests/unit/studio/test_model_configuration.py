from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from harness.core.errors import ConflictError
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
    *, environment: str = "test", client: httpx.AsyncClient | None = None
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
    assert result.images[0].url == "https://cdn.example.test/image.png"
    assert captured[0].url.path.endswith("/v1/images/generations")
    assert captured[0].headers["authorization"] == "Bearer secret-value-never-returned"


@pytest.mark.asyncio
async def test_production_rejects_insecure_or_private_model_endpoints() -> None:
    models, _catalogs, _credentials = service(environment="production")

    with pytest.raises(ConflictError, match="require HTTPS"):
        await models.configure(
            "tenant-a",
            "admin-a",
            "unsafe-model",
            request(baseUrl="http://127.0.0.1:8080/v1"),
        )

    with pytest.raises(ConflictError, match="private IP"):
        await models.configure(
            "tenant-a",
            "admin-a",
            "unsafe-model",
            request(baseUrl="https://127.0.0.1/v1"),
        )
