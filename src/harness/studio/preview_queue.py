"""Preview jobs reuse the proven leased Run queue with a separate namespace."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from harness.adapters.memory import InMemoryTaskQueue
from harness.core.ports import RunTask, TaskQueue
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue


class PreviewTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    preview_id: str


class PreviewTaskQueue:
    def __init__(self, queue: TaskQueue) -> None:
        self._queue = queue

    @classmethod
    def memory(cls) -> PreviewTaskQueue:
        return cls(InMemoryTaskQueue())

    @classmethod
    def redis(
        cls,
        client: AsyncRedisClient,
        *,
        visibility_timeout_seconds: float,
        retry_delay_seconds: float,
    ) -> PreviewTaskQueue:
        return cls(
            RedisTaskQueue(
                client,
                namespace="harness:preview",
                visibility_timeout_seconds=visibility_timeout_seconds,
                retry_delay_seconds=retry_delay_seconds,
            )
        )

    @staticmethod
    def _run_task(task: PreviewTask) -> RunTask:
        return RunTask(tenant_id=task.tenant_id, run_id=task.preview_id)

    @staticmethod
    def _preview_task(task: RunTask) -> PreviewTask:
        return PreviewTask(tenant_id=task.tenant_id, preview_id=task.run_id)

    async def enqueue(self, task: PreviewTask) -> None:
        await self._queue.enqueue(self._run_task(task))

    async def dequeue(self) -> PreviewTask | None:
        task = await self._queue.dequeue()
        return None if task is None else self._preview_task(task)

    async def acknowledge(self, task: PreviewTask) -> None:
        await self._queue.acknowledge(self._run_task(task))

    async def retry(self, task: PreviewTask) -> None:
        await self._queue.retry(self._run_task(task))

    async def extend_lease(self, task: PreviewTask) -> None:
        await self._queue.extend_lease(self._run_task(task))
