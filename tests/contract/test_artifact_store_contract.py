import hashlib

import pytest

from harness.adapters.memory import InMemoryArtifactStore
from harness.core.errors import NotFoundError


@pytest.mark.asyncio
async def test_artifact_store_round_trips_bytes_and_hash() -> None:
    store = InMemoryArtifactStore()
    content = b"artifact-content"

    stored = await store.put("tenant-a", "artifact-1", content)

    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.size_bytes == len(content)
    assert await store.get("tenant-a", "artifact-1") == content
    with pytest.raises(NotFoundError):
        await store.get("tenant-b", "artifact-1")

