from pydantic import BaseModel, ConfigDict

from harness.adapters.memory import InMemoryTaskQueue
from harness.core.ports import RunTask, TaskQueue
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue


class QualityTask(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: str
    sync_id: str


class QualityTaskQueue:
    def __init__(self, queue: TaskQueue) -> None:
        self._queue = queue

    @classmethod
    def memory(cls) -> "QualityTaskQueue":
        return cls(InMemoryTaskQueue())

    @classmethod
    def redis(
        cls,
        client: AsyncRedisClient,
        *,
        visibility_timeout_seconds: float,
        retry_delay_seconds: float,
    ) -> "QualityTaskQueue":
        return cls(
            RedisTaskQueue(
                client,
                namespace="harness:quality",
                visibility_timeout_seconds=visibility_timeout_seconds,
                retry_delay_seconds=retry_delay_seconds,
            )
        )

    @staticmethod
    def _raw(task: QualityTask) -> RunTask:
        return RunTask(tenant_id=task.tenant_id, run_id=task.sync_id)

    async def enqueue(self, task: QualityTask) -> None:
        await self._queue.enqueue(self._raw(task))

    async def dequeue(self) -> QualityTask | None:
        task = await self._queue.dequeue()
        return None if task is None else QualityTask(tenant_id=task.tenant_id, sync_id=task.run_id)

    async def acknowledge(self, task: QualityTask) -> None:
        await self._queue.acknowledge(self._raw(task))

    async def retry(self, task: QualityTask) -> None:
        await self._queue.retry(self._raw(task))
