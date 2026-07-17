from datetime import UTC, datetime

import pytest

from harness.studio.catalog import default_capability_catalog
from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.models import CapabilityCatalogRecord
from harness.studio.repositories import InMemoryAgentDraftRepository

NOW = datetime(2026, 7, 17, tzinfo=UTC)


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
