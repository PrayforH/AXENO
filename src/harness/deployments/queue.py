"""Leased deployment reconcile queue."""

from pydantic import BaseModel, ConfigDict

from harness.adapters.memory import InMemoryTaskQueue
from harness.core.ports import RunTask, TaskQueue
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue


class DeploymentTask(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: str
    deployment_id: str


class DeploymentTaskQueue:
    def __init__(self, queue: TaskQueue) -> None:
        self._queue = queue

    @classmethod
    def memory(cls) -> "DeploymentTaskQueue":
        return cls(InMemoryTaskQueue())

    @classmethod
    def redis(
        cls,
        client: AsyncRedisClient,
        *,
        visibility_timeout_seconds: float,
        retry_delay_seconds: float,
    ) -> "DeploymentTaskQueue":
        return cls(
            RedisTaskQueue(
                client,
                namespace="harness:deployment",
                visibility_timeout_seconds=visibility_timeout_seconds,
                retry_delay_seconds=retry_delay_seconds,
            )
        )

    @staticmethod
    def _raw(task: DeploymentTask) -> RunTask:
        return RunTask(tenant_id=task.tenant_id, run_id=task.deployment_id)

    async def enqueue(self, task: DeploymentTask) -> None:
        await self._queue.enqueue(self._raw(task))

    async def dequeue(self) -> DeploymentTask | None:
        task = await self._queue.dequeue()
        return (
            None
            if task is None
            else DeploymentTask(tenant_id=task.tenant_id, deployment_id=task.run_id)
        )

    async def acknowledge(self, task: DeploymentTask) -> None:
        await self._queue.acknowledge(self._raw(task))

    async def retry(self, task: DeploymentTask) -> None:
        await self._queue.retry(self._raw(task))
