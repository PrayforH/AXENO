from datetime import UTC, datetime

import pytest

from harness.core.errors import ConflictError
from harness.studio.catalog import default_capability_catalog
from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.models import (
    AgentTemplate,
    CapabilityCatalogRecord,
    CreateAgentDraftRequest,
    McpCapability,
    ModelRouteCapability,
    NetworkAccess,
    UpsertCatalogResourceRequest,
)
from harness.studio.repositories import InMemoryAgentDraftRepository
from harness.studio.service import AgentStudioService

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_default_catalog_exposes_separate_deepseek_v4_routes() -> None:
    routes = {item.route_id: item for item in default_capability_catalog().model_routes}

    assert routes["deepseek-v4-flash"].models == ("deepseek-v4-flash",)
    assert routes["deepseek-v4-pro"].models == ("deepseek-v4-pro",)
    assert routes["new-api-default"].enabled is False
    assert routes["glm-5-2"].models == ("shdata-glm",)


def previous_system_catalog():
    catalog = default_capability_catalog()
    return catalog.model_copy(
        update={
            "execution_profiles": tuple(
                profile
                for profile in catalog.execution_profiles
                if profile.profile_id != "local-development"
            )
        }
    )


@pytest.mark.asyncio
async def test_get_upgrades_an_untouched_system_catalog() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    await repository.seed(
        CapabilityCatalogRecord(
            tenantId="tenant-a",
            revision=1,
            catalog=previous_system_catalog(),
            updatedBy="system",
            updatedAt=NOW,
        )
    )
    service = CapabilityCatalogService(
        repository,
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )

    upgraded = await service.get("tenant-a")

    assert upgraded.revision == 2
    assert upgraded.updated_by == "system-route-migration"
    assert "local-development" in {
        profile.profile_id for profile in upgraded.catalog.execution_profiles
    }


@pytest.mark.asyncio
async def test_get_never_drops_tenant_mcp_from_a_system_authored_catalog() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    catalog = previous_system_catalog()
    tenant_mcp = McpCapability(
        reference="sentiment_query_mcp",
        serverName="sentiment_query_mcp",
        label="Sentiment query",
        description="Read-only internal sentiment data.",
        endpointUrl="http://sentiment-mcp:8001/mcp",
        tools=("mcp__sentiment_query_mcp__search_risk_subjects",),
        risk="medium",
        networkAccess="internal",
        sendsUserData=True,
        readOnly=True,
        executionLocation="external-mcp",
    )
    catalog = catalog.model_copy(
        update={"mcp_servers": (*catalog.mcp_servers, tenant_mcp)}
    )
    await repository.seed(
        CapabilityCatalogRecord(
            tenantId="tenant-a",
            revision=4,
            catalog=catalog,
            updatedBy="system",
            updatedAt=NOW,
        )
    )
    service = CapabilityCatalogService(
        repository,
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )

    upgraded = await service.get("tenant-a")

    assert upgraded.revision == 5
    assert {item.reference for item in upgraded.catalog.mcp_servers} == {
        "tavily-readonly",
        "sentiment_query_mcp",
    }


@pytest.mark.asyncio
async def test_get_preserves_a_tenant_managed_catalog() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    previous = CapabilityCatalogRecord(
        tenantId="tenant-a",
        revision=7,
        catalog=previous_system_catalog(),
        updatedBy="tenant-admin",
        updatedAt=NOW,
    )
    await repository.seed(previous)
    service = CapabilityCatalogService(
        repository,
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )

    current = await service.get("tenant-a")

    assert current == previous
    assert "local-development" not in {
        profile.profile_id for profile in current.catalog.execution_profiles
    }


@pytest.mark.asyncio
async def test_get_splits_legacy_deepseek_route_in_system_migrated_catalog() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    catalog = default_capability_catalog()
    legacy_route = ModelRouteCapability(
        routeId="new-api-default",
        label="DeepSeek V4",
        provider="deepseek",
        models=("deepseek-v4-flash", "deepseek-v4-pro"),
        capabilities=("streaming", "tool_use"),
        credentialReference="CUSTOM_NEW_API_KEY",
    )
    old_catalog = catalog.model_copy(
        update={
            "model_routes": (
                legacy_route,
                *(
                    route
                    for route in catalog.model_routes
                    if route.route_id
                    not in {
                        "new-api-default",
                        "deepseek-v4-flash",
                        "deepseek-v4-pro",
                    }
                ),
            )
        }
    )
    await repository.seed(
        CapabilityCatalogRecord(
            tenantId="tenant-a",
            revision=24,
            catalog=old_catalog,
            updatedBy="system-profile-compatibility",
            updatedAt=NOW,
        )
    )
    service = CapabilityCatalogService(
        repository,
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )

    upgraded = await service.get("tenant-a")

    routes = {route.route_id: route for route in upgraded.catalog.model_routes}
    assert upgraded.revision == 25
    assert upgraded.updated_by == "system-route-migration"
    assert routes["new-api-default"].enabled is False
    assert routes["deepseek-v4-flash"].models == ("deepseek-v4-flash",)
    assert routes["deepseek-v4-pro"].models == ("deepseek-v4-pro",)
    assert routes["deepseek-v4-flash"].credential_reference == "CUSTOM_NEW_API_KEY"
    assert routes["glm-5-2"].models == ("shdata-glm",)


@pytest.mark.asyncio
async def test_mcp_upsert_atomically_authorizes_selected_execution_profiles() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    service = CapabilityCatalogService(
        repository,
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )
    catalog = default_capability_catalog()
    resource = catalog.mcp_servers[0].model_copy(
        update={
            "reference": "knowledge-search",
            "label": "Knowledge search",
            "network_access": NetworkAccess.INTERNAL,
        }
    )

    result = await service.upsert(
        tenant_id="tenant-a",
        user_id="admin-a",
        resource_type="mcp",
        resource_id="knowledge-search",
        request=UpsertCatalogResourceRequest(
            expectedRevision=1,
            resource=resource,
            allowedExecutionProfileIds=("local-development",),
        ),
    )

    profiles = {profile.profile_id: profile for profile in result.record.catalog.execution_profiles}
    assert "knowledge-search" in profiles["local-development"].allowed_mcp_references
    assert profiles["local-development"].version == 1
    assert "knowledge-search" not in profiles["isolated-default"].allowed_mcp_references
    capability = next(
        item for item in result.record.catalog.mcp_servers if item.reference == "knowledge-search"
    )
    assert capability.allowed_execution_profile_ids == ("local-development",)


@pytest.mark.asyncio
async def test_personal_mcp_capabilities_are_visible_only_to_their_owner() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    service = CapabilityCatalogService(
        repository,
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )
    resource = (
        default_capability_catalog()
        .mcp_servers[0]
        .model_copy(update={"reference": "company-search", "label": "Company search"})
    )

    first = await service.upsert(
        tenant_id="tenant-a",
        user_id="user-a",
        resource_type="mcp",
        resource_id="company-search",
        request=UpsertCatalogResourceRequest(
            expectedRevision=1,
            resource=resource,
        ),
    )
    await service.upsert(
        tenant_id="tenant-a",
        user_id="user-b",
        resource_type="mcp",
        resource_id="company-search",
        request=UpsertCatalogResourceRequest(
            expectedRevision=first.record.revision,
            resource=resource.model_copy(update={"label": "My company search"}),
        ),
    )

    user_a = await service.get_for_user("tenant-a", "user-a")
    user_b = await service.get_for_user("tenant-a", "user-b")
    visible_a = {item.reference: item for item in user_a.catalog.mcp_servers}
    visible_b = {item.reference: item for item in user_b.catalog.mcp_servers}

    assert visible_a["company-search"].label == "Company search"
    assert visible_a["company-search"].owner_user_id == "user-a"
    assert visible_b["company-search"].label == "My company search"
    assert visible_b["company-search"].owner_user_id == "user-b"


@pytest.mark.asyncio
async def test_platform_mcp_cannot_be_mutated_as_a_personal_capability() -> None:
    service = CapabilityCatalogService(
        InMemoryCapabilityCatalogRepository(),
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )
    platform = default_capability_catalog().mcp_servers[0]

    with pytest.raises(ConflictError, match="cannot be overwritten"):
        await service.upsert(
            tenant_id="tenant-a",
            user_id="user-a",
            resource_type="mcp",
            resource_id=platform.reference,
            request=UpsertCatalogResourceRequest(
                expectedRevision=1,
                resource=platform,
            ),
        )
    with pytest.raises(ConflictError, match="cannot be disabled"):
        await service.disable(
            tenant_id="tenant-a",
            user_id="user-a",
            resource_type="mcp",
            resource_id=platform.reference,
            expected_revision=1,
        )


@pytest.mark.asyncio
async def test_legacy_custom_mcp_is_assigned_to_referencing_draft_owner() -> None:
    repository = InMemoryCapabilityCatalogRepository()
    drafts = InMemoryAgentDraftRepository()
    studio = AgentStudioService(drafts, catalog=default_capability_catalog())
    draft = await studio.create(
        tenant_id="tenant-a",
        user_id="user-a",
        request=CreateAgentDraftRequest(
            name="business-agent",
            domain="business",
            displayName="Business Agent",
            description="Uses a legacy personal MCP.",
            template=AgentTemplate.ANALYST,
        ),
    )
    await drafts.replace(
        draft.revision,
        draft.model_copy(
            update={
                "revision": draft.revision + 1,
                "spec": draft.spec.model_copy(update={"mcp_servers": ("legacy-business",)}),
            }
        ),
    )
    catalog = default_capability_catalog()
    legacy = catalog.mcp_servers[0].model_copy(
        update={"reference": "legacy-business", "label": "Legacy business"}
    )
    await repository.seed(
        CapabilityCatalogRecord(
            tenantId="tenant-a",
            revision=3,
            catalog=catalog.model_copy(update={"mcp_servers": (*catalog.mcp_servers, legacy)}),
            updatedBy="codex-deployer",
            updatedAt=NOW,
        )
    )
    service = CapabilityCatalogService(repository, drafts, clock=lambda: NOW)

    owner = await service.get_for_user("tenant-a", "user-a")
    other = await service.get_for_user("tenant-a", "user-b")

    assert "legacy-business" in {item.reference for item in owner.catalog.mcp_servers}
    assert "legacy-business" not in {item.reference for item in other.catalog.mcp_servers}


@pytest.mark.asyncio
async def test_mcp_upsert_rejects_profile_without_required_network_access() -> None:
    service = CapabilityCatalogService(
        InMemoryCapabilityCatalogRepository(),
        InMemoryAgentDraftRepository(),
        clock=lambda: NOW,
    )
    resource = (
        default_capability_catalog()
        .mcp_servers[0]
        .model_copy(
            update={
                "reference": "knowledge-search",
                "network_access": NetworkAccess.INTERNAL,
            }
        )
    )

    with pytest.raises(ConflictError, match="e2b-public-egress"):
        await service.upsert(
            tenant_id="tenant-a",
            user_id="admin-a",
            resource_type="mcp",
            resource_id="knowledge-search",
            request=UpsertCatalogResourceRequest(
                expectedRevision=1,
                resource=resource,
                allowedExecutionProfileIds=("e2b-public-egress",),
            ),
        )
