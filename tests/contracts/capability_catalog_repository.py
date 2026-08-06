import asyncio
from datetime import UTC, datetime, timedelta

from harness.core.errors import ConflictError
from harness.studio.catalog import default_capability_catalog
from harness.studio.catalog_repository import CapabilityCatalogRepository
from harness.studio.models import CapabilityCatalogRecord

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def record(
    tenant_id: str = "tenant-a", *, revision: int = 1, user_id: str = "system"
) -> CapabilityCatalogRecord:
    return CapabilityCatalogRecord(
        tenantId=tenant_id,
        revision=revision,
        catalog=default_capability_catalog(),
        updatedBy=user_id,
        updatedAt=NOW + timedelta(seconds=revision - 1),
    )


async def exercise_catalog_repository_contract(
    repository: CapabilityCatalogRepository,
) -> None:
    initial = record()
    assert await repository.seed(initial) == initial
    assert await repository.seed(record(user_id="second-seed")) == initial
    tenant_b = record("tenant-b")
    assert await repository.seed(tenant_b) == tenant_b
    assert await repository.get("tenant-a") == initial
    assert await repository.get("tenant-b") == tenant_b

    updated = record(revision=2, user_id="admin-a")
    await repository.replace(1, updated)
    assert await repository.get("tenant-a") == updated
    assert await repository.get("tenant-b") == tenant_b

    try:
        await repository.replace(1, updated)
    except ConflictError:
        pass
    else:
        raise AssertionError("stale catalog revision must conflict")


async def exercise_catalog_concurrent_replace(
    repository: CapabilityCatalogRepository,
) -> None:
    await repository.seed(record())
    first = record(revision=2, user_id="admin-first")
    second = record(revision=2, user_id="admin-second")
    results = await asyncio.gather(
        repository.replace(1, first),
        repository.replace(1, second),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    assert await repository.get("tenant-a") in (first, second)
