from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast
from zipfile import ZIP_DEFLATED, ZipFile

from harness.core.errors import ConflictError
from harness.core.ports import ArtifactStore
from harness.lifecycle.adapters import LifecycleAdapter
from harness.lifecycle.models import (
    DataLifecycleJob,
    LifecycleAdapterResult,
    LifecycleAdapterStatus,
    LifecycleJobKind,
    LifecycleJobStatus,
    LifecycleScope,
    LifecycleScopeKind,
)
from harness.lifecycle.repositories import DataLifecycleRepository
from harness.runtime.audit_redaction import redact_text

_SECRET_KEYS = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)


def _sanitize_export(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        mapping = cast(dict[object, Any], value)
        return {
            str(child_key): _sanitize_export(child, key=str(child_key))
            for child_key, child in mapping.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_export(child) for child in cast(list[Any] | tuple[Any, ...], value)]
    if isinstance(value, str):
        return redact_text(value, limit=1_000_000)
    return value


class DataLifecycleController:
    def __init__(
        self,
        repository: DataLifecycleRepository,
        adapters: tuple[LifecycleAdapter, ...],
        export_store: ArtifactStore,
        *,
        scope_resolver: Callable[
            [str, LifecycleScope], Awaitable[Sequence[LifecycleScope]]
        ]
        | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._adapters = {adapter.name: adapter for adapter in adapters}
        self._export_store = export_store
        self._scope_resolver = scope_resolver or self._same_scope
        self._clock = clock or (lambda: datetime.now(UTC))

    async def process_once(self) -> DataLifecycleJob | None:
        runnable = await self._repository.list_runnable(limit=1)
        if not runnable:
            return None
        queued = runnable[0]
        running = queued.model_copy(
            update={
                "status": LifecycleJobStatus.RUNNING,
                "updated_at": self._clock(),
                "fencing_token": queued.fencing_token + 1,
            }
        )
        if not await self._repository.compare_and_set(LifecycleJobStatus.QUEUED, running):
            return None
        hold_id = (
            await self._blocking_hold(running)
            if running.kind is not LifecycleJobKind.EXPORT
            else None
        )
        if hold_id is not None:
            running = await self._mark_hold_failure(running, hold_id)
        fragments: dict[str, object] = {}
        for item in running.adapters:
            if hold_id is not None:
                break
            if item.status is LifecycleAdapterStatus.SUCCEEDED:
                continue
            adapter = self._adapters[item.adapter]
            started = item.model_copy(
                update={
                    "status": LifecycleAdapterStatus.RUNNING,
                    "attempts": item.attempts + 1,
                    "updated_at": self._clock(),
                }
            )
            running = await self._replace_adapter(running, started)
            try:
                if running.kind is LifecycleJobKind.EXPORT:
                    fragment, count = await adapter.export(running)
                    fragments[adapter.name] = _sanitize_export(fragment)
                else:
                    count = await adapter.delete(running)
            except Exception as error:  # noqa: BLE001 - durable failure evidence
                failed = started.model_copy(
                    update={
                        "status": LifecycleAdapterStatus.FAILED,
                        "error_code": type(error).__name__,
                        "error_message": "Adapter operation failed; retry is available.",
                        "updated_at": self._clock(),
                    }
                )
                running = await self._replace_adapter(running, failed)
                # Destructive adapters are deliberately ordered from external object
                # stores to PostgreSQL. Stop at the first failure so later metadata
                # remains available to identify and retry the external deletion.
                if running.kind is not LifecycleJobKind.EXPORT:
                    break
            else:
                succeeded = started.model_copy(
                    update={
                        "status": LifecycleAdapterStatus.SUCCEEDED,
                        "processed_items": count,
                        "error_code": None,
                        "error_message": None,
                        "updated_at": self._clock(),
                    }
                )
                running = await self._replace_adapter(running, succeeded)

        if running.kind is LifecycleJobKind.EXPORT:
            try:
                running = await self._store_export(running, fragments)
            except Exception as error:  # noqa: BLE001 - durable failure evidence
                running = running.model_copy(
                    update={
                        "adapters": (
                            *running.adapters,
                            LifecycleAdapterResult(
                                adapter="export-artifact",
                                status=LifecycleAdapterStatus.FAILED,
                                attempts=1,
                                errorCode=type(error).__name__,
                                errorMessage=(
                                    "Export artifact could not be stored; retry is available."
                                ),
                                updatedAt=self._clock(),
                            ),
                        ),
                    }
                )
        failed_count = sum(
            item.status is LifecycleAdapterStatus.FAILED for item in running.adapters
        )
        succeeded_count = sum(
            item.status is LifecycleAdapterStatus.SUCCEEDED for item in running.adapters
        )
        status = (
            LifecycleJobStatus.SUCCEEDED
            if failed_count == 0
            else LifecycleJobStatus.PARTIAL_FAILED
            if succeeded_count
            else LifecycleJobStatus.FAILED
        )
        terminal = running.model_copy(
            update={
                "status": status,
                "updated_at": self._clock(),
                "completed_at": self._clock(),
                "fencing_token": running.fencing_token + 1,
            }
        )
        if not await self._repository.compare_and_set(LifecycleJobStatus.RUNNING, terminal):
            raise ConflictError("data lifecycle job changed before completion")
        return terminal

    async def _blocking_hold(self, job: DataLifecycleJob) -> str | None:
        related_scopes = await self._scope_resolver(job.tenant_id, job.scope)
        for hold in await self._repository.list_holds(job.tenant_id):
            if not hold.active:
                continue
            for scope in related_scopes:
                same_scope = (
                    hold.scope.kind is scope.kind
                    and hold.scope.subject_id == scope.subject_id
                )
                if (
                    hold.scope.kind is LifecycleScopeKind.TENANT
                    or scope.kind is LifecycleScopeKind.TENANT
                    or same_scope
                ):
                    return hold.hold_id
        return None

    async def _mark_hold_failure(
        self, job: DataLifecycleJob, hold_id: str
    ) -> DataLifecycleJob:
        target = next(
            item
            for item in job.adapters
            if item.status is not LifecycleAdapterStatus.SUCCEEDED
        )
        return await self._replace_adapter(
            job,
            target.model_copy(
                update={
                    "status": LifecycleAdapterStatus.FAILED,
                    "error_code": "LegalHoldActive",
                    "error_message": f"Deletion is blocked by legal hold {hold_id}.",
                    "updated_at": self._clock(),
                }
            ),
        )

    @staticmethod
    async def _same_scope(
        _tenant_id: str, scope: LifecycleScope
    ) -> Sequence[LifecycleScope]:
        return (scope,)

    async def _replace_adapter(
        self, job: DataLifecycleJob, replacement: LifecycleAdapterResult
    ) -> DataLifecycleJob:
        updated = job.model_copy(
            update={
                "adapters": tuple(
                    replacement if item.adapter == replacement.adapter else item
                    for item in job.adapters
                ),
                "updated_at": self._clock(),
                "fencing_token": job.fencing_token + 1,
            }
        )
        if not await self._repository.compare_and_set(LifecycleJobStatus.RUNNING, updated):
            raise ConflictError("data lifecycle job fencing conflict")
        return updated

    async def _store_export(
        self, job: DataLifecycleJob, fragments: dict[str, object]
    ) -> DataLifecycleJob:
        object_id = f"lifecycle_export_{job.job_id}"
        filename = f"data-export-{job.scope.kind.value}-{job.scope.subject_id}.zip"
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            manifest = {
                "schemaVersion": "harness.data-export/v1",
                "tenantId": job.tenant_id,
                "jobId": job.job_id,
                "scope": job.scope.model_dump(mode="json", by_alias=True),
                "createdAt": self._clock().isoformat(),
                "adapters": [item.model_dump(mode="json", by_alias=True) for item in job.adapters],
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            for name, fragment in sorted(fragments.items()):
                archive.writestr(
                    f"data/{name}.json",
                    json.dumps(fragment, ensure_ascii=False, indent=2),
                )
        await self._export_store.put(job.tenant_id, object_id, buffer.getvalue())
        return job.model_copy(
            update={
                "export_object_id": object_id,
                "export_filename": filename,
                "adapters": (
                    *job.adapters,
                    LifecycleAdapterResult(
                        adapter="export-artifact",
                        status=LifecycleAdapterStatus.SUCCEEDED,
                        attempts=1,
                        processedItems=1,
                        updatedAt=self._clock(),
                    ),
                ),
            }
        )
