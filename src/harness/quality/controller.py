from __future__ import annotations

from datetime import UTC, datetime

from harness.quality.langfuse import QualityExporter
from harness.quality.models import QualitySyncStatus
from harness.quality.queue import QualityTaskQueue
from harness.quality.repositories import QualityRepository


class QualitySyncController:
    def __init__(
        self,
        *,
        repository: QualityRepository,
        queue: QualityTaskQueue,
        exporter: QualityExporter,
        max_attempts: int = 8,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._exporter = exporter
        self._max_attempts = max_attempts

    async def process_once(self) -> object | None:
        task = await self._queue.dequeue()
        if task is None:
            return None
        job = await self._repository.get_sync(task.tenant_id, task.sync_id)
        syncing = job.model_copy(
            update={
                "status": QualitySyncStatus.SYNCING,
                "attempts": job.attempts + 1,
                "updated_at": datetime.now(UTC),
                "error_code": None,
            }
        )
        await self._repository.update_sync(syncing)
        try:
            if job.kind == "score":
                await self._exporter.export_score(
                    await self._repository.get_score(job.tenant_id, job.resource_id)
                )
            else:
                await self._exporter.export_dataset(
                    await self._repository.get_dataset(job.tenant_id, job.resource_id)
                )
        except Exception:
            terminal = syncing.attempts >= self._max_attempts
            failed = syncing.model_copy(
                update={
                    "status": QualitySyncStatus.FAILED if terminal else QualitySyncStatus.RETRYING,
                    "updated_at": datetime.now(UTC),
                    "error_code": "quality_export_unavailable",
                }
            )
            await self._repository.update_sync(failed)
            if terminal:
                await self._queue.acknowledge(task)
            else:
                await self._queue.retry(task)
            return failed
        succeeded = syncing.model_copy(
            update={"status": QualitySyncStatus.SUCCEEDED, "updated_at": datetime.now(UTC)}
        )
        await self._repository.update_sync(succeeded)
        await self._queue.acknowledge(task)
        return succeeded
