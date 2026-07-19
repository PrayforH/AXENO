import hashlib
import os

import pytest

from harness.storage.minio import MinioArtifactStore


@pytest.mark.asyncio
async def test_minio_artifact_is_promoted_from_temporary_object() -> None:
    store = MinioArtifactStore(
        endpoint=os.getenv("HARNESS_TEST_MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.getenv("HARNESS_TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("HARNESS_TEST_MINIO_SECRET_KEY", "minioadmin"),
        bucket=os.getenv("HARNESS_TEST_MINIO_BUCKET", "harness-artifacts"),
        secure=False,
    )
    content = b"durable artifact"

    stored = await store.put("tenant-a", "artifact-1", content)

    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.object_key == "tenant-a/artifact-1"
    assert await store.get("tenant-a", "artifact-1") == content
