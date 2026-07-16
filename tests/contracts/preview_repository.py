import asyncio
from datetime import UTC, datetime, timedelta

from harness.core.errors import ConflictError, NotFoundError
from harness.studio.preview_models import PreviewDeployment, PreviewStatus
from harness.studio.preview_repositories import PreviewRepository

NOW = datetime(2026, 7, 16, 8, tzinfo=UTC)


def preview(
    *,
    tenant_id: str = "tenant-a",
    preview_id: str = "preview-shared",
    idempotency_key: str = "preview-key",
    expires_at: datetime = NOW + timedelta(minutes=10),
) -> PreviewDeployment:
    return PreviewDeployment(
        previewId=preview_id,
        tenantId=tenant_id,
        draftId="draft-a",
        draftRevision=2,
        contentHash="a" * 64,
        packageHash="b" * 64,
        requestedBy="builder-a",
        idempotencyKey=idempotency_key,
        status=PreviewStatus.QUEUED,
        createdAt=NOW,
        updatedAt=NOW,
        expiresAt=expires_at,
    )


async def exercise_repository_contract(repository: PreviewRepository) -> None:
    tenant_a = preview()
    tenant_b = preview(tenant_id="tenant-b")
    expired = preview(
        preview_id="preview-expired",
        idempotency_key="expired-key",
        expires_at=NOW - timedelta(seconds=1),
    )
    await repository.add(tenant_a)
    await repository.add(tenant_b)
    await repository.add(expired)

    assert await repository.get("tenant-a", tenant_a.preview_id) == tenant_a
    assert await repository.get("tenant-b", tenant_b.preview_id) == tenant_b
    assert await repository.find_by_idempotency("tenant-a", "preview-key") == tenant_a
    assert len(await repository.list_for_tenant("tenant-a")) == 2
    assert await repository.list_for_tenant("tenant-c") == []
    assert await repository.list_expired_active(NOW, limit=10) == [expired]

    try:
        await repository.get("tenant-c", tenant_a.preview_id)
    except NotFoundError:
        pass
    else:
        raise AssertionError("cross-tenant Preview get must not leak")

    duplicate = preview(preview_id="preview-other")
    try:
        await repository.add(duplicate)
    except ConflictError:
        pass
    else:
        raise AssertionError("tenant/idempotency key must be unique")

    ready = tenant_a.model_copy(
        update={
            "status": PreviewStatus.READY,
            "fencing_token": 1,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    assert await repository.compare_and_set(PreviewStatus.QUEUED, ready)
    assert not await repository.compare_and_set(PreviewStatus.QUEUED, ready)
    assert await repository.get("tenant-a", tenant_a.preview_id) == ready


async def exercise_concurrent_cas(repository: PreviewRepository) -> None:
    original = preview(preview_id="preview-concurrent", idempotency_key="concurrent")
    await repository.add(original)
    ready = original.model_copy(
        update={"status": PreviewStatus.READY, "fencing_token": 1}
    )
    cancelling = original.model_copy(
        update={"status": PreviewStatus.CANCELLING, "fencing_token": 1}
    )

    results = await asyncio.gather(
        repository.compare_and_set(PreviewStatus.QUEUED, ready),
        repository.compare_and_set(PreviewStatus.QUEUED, cancelling),
    )

    assert sorted(results) == [False, True]
    assert (await repository.get("tenant-a", original.preview_id)) in (
        ready,
        cancelling,
    )
