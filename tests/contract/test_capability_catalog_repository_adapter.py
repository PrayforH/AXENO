import pytest

from harness.studio.catalog_repository import InMemoryCapabilityCatalogRepository
from tests.contracts.capability_catalog_repository import (
    exercise_catalog_concurrent_replace,
    exercise_catalog_repository_contract,
)


@pytest.mark.asyncio
async def test_in_memory_capability_catalog_repository_contract() -> None:
    await exercise_catalog_repository_contract(InMemoryCapabilityCatalogRepository())


@pytest.mark.asyncio
async def test_in_memory_capability_catalog_concurrent_replace() -> None:
    await exercise_catalog_concurrent_replace(InMemoryCapabilityCatalogRepository())
