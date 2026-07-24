from datetime import UTC, datetime

import pytest

from harness.core.errors import ConflictError
from harness.studio.catalog import default_capability_catalog
from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.models import (
    CapabilityCatalogRecord,
    ModelRouteCapability,
    NetworkAccess,
    UpsertCatalogResourceRequest,
)
from harness.studio.repositories import InMemoryAgentDraftRepository

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_default_catalog_exposes_separate_deepseek_v4_routes() -> None:
    routes = {item.route_id: item for item in default_capability_catalog().model_routes}

    assert routes["deepseek-v4-flash"].models == ("deepseek-v4-flash",)
    assert routes["deepseek-v4-pro"].models == ("deepseek-v4-pro",)
    assert routes["new-api-default"].enabled is False


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
    assert upgraded.updated_by == "system"
    assert "local-development" in {
        profile.profile_id for profile in upgraded.catalog.execution_profiles
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
    assert profiles["local-development"].version == 2
    assert "knowledge-search" not in profiles["isolated-default"].allowed_mcp_references


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
