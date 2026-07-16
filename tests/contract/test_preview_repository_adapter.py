import pytest

from harness.studio.preview_repositories import InMemoryPreviewRepository
from tests.contracts.preview_repository import (
    exercise_concurrent_cas,
    exercise_repository_contract,
)


@pytest.mark.asyncio
async def test_in_memory_preview_repository_contract() -> None:
    await exercise_repository_contract(InMemoryPreviewRepository())


@pytest.mark.asyncio
async def test_in_memory_preview_repository_concurrent_cas() -> None:
    await exercise_concurrent_cas(InMemoryPreviewRepository())
