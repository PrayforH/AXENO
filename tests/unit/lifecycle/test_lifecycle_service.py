from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest

from harness.adapters.memory import InMemoryArtifactStore
from harness.core.errors import ConflictError, NotFoundError
from harness.lifecycle.adapters import LifecycleAdapter
from harness.lifecycle.controller import DataLifecycleController
from harness.lifecycle.models import (
    CreateLegalHoldRequest,
    CreateLifecycleJobRequest,
    DataLifecycleJob,
    LifecycleAdapterStatus,
    LifecycleJobKind,
    LifecycleJobStatus,
    LifecycleScope,
    LifecycleScopeKind,
    ReplaceRetentionPolicyRequest,
)
from harness.lifecycle.repositories import InMemoryDataLifecycleRepository
from harness.lifecycle.service import DataLifecycleService

NOW = datetime(2026, 7, 16, 8, tzinfo=UTC)


class RecordingAdapter:
    def __init__(
        self,
        name: str,
        *,
        fragment: object | None = None,
        fail_deletes: int = 0,
    ) -> None:
        self.name = name
        self.fragment = fragment or {"adapter": name}
        self.fail_deletes = fail_deletes
        self.delete_calls = 0

    async def export(self, job: DataLifecycleJob) -> tuple[object, int]:
        del job
        return self.fragment, 1

    async def delete(self, job: DataLifecycleJob) -> int:
        del job
        self.delete_calls += 1
        if self.delete_calls <= self.fail_deletes:
            raise RuntimeError("private upstream failure")
        return 1


def build(
    *adapters: LifecycleAdapter,
) -> tuple[
    DataLifecycleService,
    DataLifecycleController,
    InMemoryDataLifecycleRepository,
    InMemoryArtifactStore,
]:
    repository = InMemoryDataLifecycleRepository()
    store = InMemoryArtifactStore()
    service = DataLifecycleService(
        repository,
        adapters,
        export_store=store,
        clock=lambda: NOW,
        id_generator=lambda prefix: f"{prefix}-1",
    )
    controller = DataLifecycleController(
        repository,
        adapters,
        store,
        clock=lambda: NOW,
    )
    return service, controller, repository, store


def request(kind: LifecycleJobKind, key: str = "request-1") -> CreateLifecycleJobRequest:
    return CreateLifecycleJobRequest(
        kind=kind,
        scope=LifecycleScope(kind=LifecycleScopeKind.USER, subjectId="user-1"),
        idempotencyKey=key,
    )


@pytest.mark.asyncio
async def test_legal_hold_blocks_delete_and_tenant_boundaries() -> None:
    service, _, repository, _ = build(RecordingAdapter("postgresql"))
    await service.create_hold(
        tenant_id="tenant-a",
        user_id="admin",
        request=CreateLegalHoldRequest(
            scope=LifecycleScope(kind=LifecycleScopeKind.USER, subjectId="user-1"),
            reason="investigation",
        ),
    )

    with pytest.raises(ConflictError, match="legal_hold_active"):
        await service.create_job(
            tenant_id="tenant-a",
            user_id="user-1",
            request=request(LifecycleJobKind.DELETE),
        )
    with pytest.raises(NotFoundError):
        await repository.get_hold("tenant-b", "hold-1")


@pytest.mark.asyncio
async def test_destructive_partial_failure_preserves_later_adapter_for_retry() -> None:
    first = RecordingAdapter("object-store")
    flaky = RecordingAdapter("langfuse", fail_deletes=1)
    database = RecordingAdapter("postgresql")
    service, controller, _, _ = build(first, flaky, database)
    job = await service.create_job(
        tenant_id="tenant-a",
        user_id="admin",
        request=request(LifecycleJobKind.DELETE),
    )

    failed = await controller.process_once()
    assert failed is not None
    assert failed.status is LifecycleJobStatus.PARTIAL_FAILED
    assert [item.status for item in failed.adapters] == [
        LifecycleAdapterStatus.SUCCEEDED,
        LifecycleAdapterStatus.FAILED,
        LifecycleAdapterStatus.PENDING,
    ]
    assert database.delete_calls == 0

    await service.retry_job(tenant_id="tenant-a", user_id="admin", job_id=job.job_id)
    succeeded = await controller.process_once()
    assert succeeded is not None
    assert succeeded.status is LifecycleJobStatus.SUCCEEDED
    assert first.delete_calls == 1
    assert flaky.delete_calls == 2
    assert database.delete_calls == 1


@pytest.mark.asyncio
async def test_execution_rechecks_hold_added_after_session_job_was_queued() -> None:
    adapter = RecordingAdapter("postgresql")
    repository = InMemoryDataLifecycleRepository()
    store = InMemoryArtifactStore()

    async def related_scopes(
        _tenant_id: str, scope: LifecycleScope
    ) -> tuple[LifecycleScope, ...]:
        return (
            scope,
            LifecycleScope(kind=LifecycleScopeKind.USER, subjectId="user-1"),
        )

    service = DataLifecycleService(
        repository,
        (adapter,),
        export_store=store,
        scope_resolver=related_scopes,
        clock=lambda: NOW,
        id_generator=lambda prefix: f"{prefix}-late-hold",
    )
    controller = DataLifecycleController(
        repository,
        (adapter,),
        store,
        scope_resolver=related_scopes,
        clock=lambda: NOW,
    )
    job = await service.create_job(
        tenant_id="tenant-a",
        user_id="user-1",
        request=CreateLifecycleJobRequest(
            kind=LifecycleJobKind.DELETE,
            scope=LifecycleScope(
                kind=LifecycleScopeKind.SESSION, subjectId="session-1"
            ),
            idempotencyKey="session-delete",
        ),
    )
    await service.create_hold(
        tenant_id="tenant-a",
        user_id="admin",
        request=CreateLegalHoldRequest(
            scope=LifecycleScope(kind=LifecycleScopeKind.USER, subjectId="user-1"),
            reason="hold added after enqueue",
        ),
    )

    blocked = await controller.process_once()
    assert blocked is not None
    assert blocked.job_id == job.job_id
    assert blocked.status is LifecycleJobStatus.FAILED
    assert blocked.adapters[0].error_code == "LegalHoldActive"
    assert adapter.delete_calls == 0


@pytest.mark.asyncio
async def test_export_is_redacted_tenant_scoped_and_downloadable() -> None:
    adapter = RecordingAdapter(
        "postgresql",
        fragment={
            "tenantId": "tenant-a",
            "authorization": "Bearer do-not-export",
            "nested": {"message": "api_key=sk-secret-value"},
        },
    )
    service, controller, _, _ = build(adapter)
    job = await service.create_job(
        tenant_id="tenant-a",
        user_id="user-1",
        request=request(LifecycleJobKind.EXPORT),
    )
    completed = await controller.process_once()
    assert completed is not None
    assert completed.status is LifecycleJobStatus.SUCCEEDED

    downloaded, content = await service.download_export("tenant-a", job.job_id)
    assert downloaded.export_filename == "data-export-user-user-1.zip"
    with ZipFile(BytesIO(content)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "data/postgresql.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        payload = json.loads(archive.read("data/postgresql.json"))
    assert manifest["tenantId"] == "tenant-a"
    assert payload["authorization"] == "[REDACTED]"
    assert "sk-secret-value" not in json.dumps(payload)
    with pytest.raises(NotFoundError):
        await service.download_export("tenant-b", job.job_id)


@pytest.mark.asyncio
async def test_daily_retention_is_idempotent_and_hold_safe() -> None:
    service, _, _, _ = build(RecordingAdapter("postgresql"))
    await service.replace_policy(
        tenant_id="tenant-a",
        user_id="admin",
        request=ReplaceRetentionPolicyRequest(
            expectedRevision=0,
            sessionDays=30,
            artifactDays=30,
            traceDays=14,
            evalDays=90,
        ),
    )
    first = await service.enqueue_due_retention_jobs()
    second = await service.enqueue_due_retention_jobs()
    assert len(first) == len(second) == 1
    assert first[0].job_id == second[0].job_id

    held, _, _, _ = build(RecordingAdapter("postgresql"))
    await held.replace_policy(
        tenant_id="tenant-a",
        user_id="admin",
        request=ReplaceRetentionPolicyRequest(
            expectedRevision=0,
            sessionDays=30,
            artifactDays=30,
            traceDays=14,
            evalDays=90,
        ),
    )
    await held.create_hold(
        tenant_id="tenant-a",
        user_id="admin",
        request=CreateLegalHoldRequest(
            scope=LifecycleScope(kind=LifecycleScopeKind.TENANT, subjectId="tenant-a"),
            reason="regulatory hold",
        ),
    )
    assert await held.enqueue_due_retention_jobs() == ()
