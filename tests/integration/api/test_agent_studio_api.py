from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from harness.adapters.memory import InMemoryAgentRegistry
from harness.api.app import create_app
from harness.api.dependencies import build_memory_container
from harness.application.agents import AgentService
from harness.studio.api import router
from harness.studio.catalog import default_capability_catalog
from harness.studio.compiler import AgentDraftCompiler
from harness.studio.repositories import InMemoryAgentDraftRepository
from harness.studio.service import AgentStudioService

NOW = datetime(2026, 7, 16, tzinfo=UTC)
SERVICE_TOKEN = "studio-service-token-with-at-least-32-characters"


def app() -> FastAPI:
    container = replace(
        build_memory_container(),
        environment="production",
        api_bearer_token=SecretStr(SERVICE_TOKEN),
    )
    catalog = default_capability_catalog()
    registry = InMemoryAgentRegistry()
    publisher = AgentService(registry, clock=lambda: NOW, environment="production")
    service = AgentStudioService(
        InMemoryAgentDraftRepository(),
        AgentDraftCompiler(catalog),
        catalog,
        publisher=publisher,
        clock=lambda: NOW,
        id_generator=lambda: "draft_api",
    )
    application = create_app(container)
    application.state.agent_studio = service
    application.include_router(router)
    return application


async def register(client: AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "SecurePass123",
            "display_name": "Studio Builder",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def draft_request(name: str = "policy-researcher") -> dict[str, str]:
    return {
        "name": name,
        "domain": "policy-research",
        "displayName": "政策研究助手",
        "description": "整理政策材料并输出有出处的研究结论。",
        "template": "analyst",
    }


@pytest.mark.asyncio
async def test_studio_rejects_unauthenticated_and_self_reported_identity() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        anonymous = await client.get("/v1/studio/capabilities")
        spoofed = await client.get(
            "/v1/studio/capabilities",
            headers={"X-Tenant-ID": "tenant-evil", "X-User-ID": "user-evil"},
        )

    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "api_auth_required"
    assert spoofed.status_code == 401
    assert spoofed.json()["error"]["code"] == "api_auth_required"


@pytest.mark.asyncio
async def test_service_identity_can_build_and_publish_existing_bundle() -> None:
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "builder-a",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        capabilities = await client.get("/v1/studio/capabilities", headers=headers)
        created = await client.post(
            "/v1/studio/drafts", headers=headers, json=draft_request()
        )
        validation = await client.post(
            "/v1/studio/drafts/draft_api/validate", headers=headers
        )
        bundle = await client.get(
            "/v1/studio/drafts/draft_api/bundle", headers=headers
        )
        published = await client.post(
            "/v1/studio/drafts/draft_api/publish", headers=headers
        )
        drafts = await client.get("/v1/studio/drafts", headers=headers)

    assert capabilities.status_code == 200
    assert capabilities.json()["mcpServers"][0]["reference"] == "tavily-readonly"
    assert created.status_code == 201
    assert created.json()["tenantId"] == "tenant-a"
    assert created.json()["createdBy"] == "builder-a"
    assert validation.status_code == 200
    assert validation.json()["ready"] is True
    assert validation.json()["contract"]["sandbox"] == "isolated"
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    assert "policy-researcher-0.1.0" in bundle.headers["content-disposition"]
    assert published.status_code == 200
    assert published.json()["name"] == "policy-researcher"
    assert drafts.json()[0]["publishedVersion"] == "0.1.0"


@pytest.mark.asyncio
async def test_jwt_identity_ignores_spoofed_tenant_and_user_headers() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        owner = await register(client, "owner@example.com")
        body_spoofed = await client.post(
            "/v1/studio/drafts",
            headers={"Authorization": f"Bearer {owner['access_token']}"},
            json={
                **draft_request(),
                "tenantId": "tenant-evil",
                "createdBy": "user-evil",
            },
        )
        created = await client.post(
            "/v1/studio/drafts",
            headers={
                "Authorization": f"Bearer {owner['access_token']}",
                "X-Tenant-ID": "tenant-evil",
                "X-User-ID": "user-evil",
            },
            json=draft_request(),
        )

    assert body_spoofed.status_code == 422
    assert created.status_code == 201
    assert created.json()["tenantId"] == owner["membership"]["tenant_id"]
    assert created.json()["createdBy"] == owner["user"]["user_id"]
    assert created.json()["tenantId"] != "tenant-evil"
    assert created.json()["createdBy"] != "user-evil"


@pytest.mark.asyncio
async def test_member_can_write_and_validate_but_cannot_publish() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        await register(client, "owner@example.com")
        member = await register(client, "member@example.com")
        headers = {"Authorization": f"Bearer {member['access_token']}"}
        created = await client.post(
            "/v1/studio/drafts", headers=headers, json=draft_request()
        )
        validation = await client.post(
            "/v1/studio/drafts/draft_api/validate", headers=headers
        )
        published = await client.post(
            "/v1/studio/drafts/draft_api/publish", headers=headers
        )

    assert member["membership"]["role"] == "member"
    assert created.status_code == 201
    assert validation.status_code == 200
    assert published.status_code == 403
    assert published.json()["error"]["code"] == "permission_denied"
