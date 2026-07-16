from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from harness.adapters.memory import InMemoryAgentRegistry
from harness.application.agents import AgentService
from harness.studio.api import StudioActor, router
from harness.studio.catalog import default_capability_catalog
from harness.studio.compiler import AgentDraftCompiler
from harness.studio.repositories import InMemoryAgentDraftRepository
from harness.studio.service import AgentStudioService

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def app(*, authenticated: bool) -> FastAPI:
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
    application = FastAPI()
    application.state.agent_studio = service
    if authenticated:
        async def authenticated_builder(
            request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            request.state.studio_actor = StudioActor(
                tenant_id="tenant-a", user_id="builder-a"
            )
            return await call_next(request)

        application.middleware("http")(authenticated_builder)

    application.include_router(router)
    return application


@pytest.mark.asyncio
async def test_studio_contract_requires_authenticated_builder_state() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app(authenticated=False)),
        base_url="http://test",
    ) as client:
        response = await client.get("/v1/studio/capabilities")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "studio_auth_required"


@pytest.mark.asyncio
async def test_builder_can_create_validate_download_and_publish_existing_bundle() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app(authenticated=True)),
        base_url="http://test",
    ) as client:
        capabilities = await client.get("/v1/studio/capabilities")
        created = await client.post(
            "/v1/studio/drafts",
            json={
                "name": "policy-researcher",
                "domain": "policy-research",
                "displayName": "政策研究助手",
                "description": "整理政策材料并输出有出处的研究结论。",
                "template": "analyst",
            },
        )
        validation = await client.post("/v1/studio/drafts/draft_api/validate")
        bundle = await client.get("/v1/studio/drafts/draft_api/bundle")
        published = await client.post("/v1/studio/drafts/draft_api/publish")
        drafts = await client.get("/v1/studio/drafts")

    assert capabilities.status_code == 200
    assert capabilities.json()["mcpServers"][0]["reference"] == "tavily-readonly"
    assert created.status_code == 201
    assert validation.status_code == 200
    assert validation.json()["ready"] is True
    assert validation.json()["contract"]["sandbox"] == "isolated"
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    assert "policy-researcher-0.1.0" in bundle.headers["content-disposition"]
    assert published.status_code == 200
    assert published.json()["name"] == "policy-researcher"
    assert drafts.json()[0]["publishedVersion"] == "0.1.0"
