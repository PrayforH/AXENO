"""Leased queue namespace for durable Eval Runs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from harness.adapters.memory import InMemoryTaskQueue
from harness.core.ports import RunTask, TaskQueue
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue


class EvalTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    eval_run_id: str


class EvalTaskQueue:
    def __init__(self, queue: TaskQueue) -> None:
        self._queue = queue

    @classmethod
    def memory(cls) -> EvalTaskQueue:
        return cls(InMemoryTaskQueue())

    @classmethod
    def redis(
        cls,
        client: AsyncRedisClient,
        *,
        visibility_timeout_seconds: float,
        retry_delay_seconds: float,
    ) -> EvalTaskQueue:
        return cls(
            RedisTaskQueue(
                client,
                namespace="harness:eval",
                visibility_timeout_seconds=visibility_timeout_seconds,
                retry_delay_seconds=retry_delay_seconds,
            )
        )

    @staticmethod
    def _run_task(task: EvalTask) -> RunTask:
        return RunTask(tenant_id=task.tenant_id, run_id=task.eval_run_id)

    @staticmethod
    def _eval_task(task: RunTask) -> EvalTask:
        return EvalTask(tenant_id=task.tenant_id, eval_run_id=task.run_id)

    async def enqueue(self, task: EvalTask) -> None:
        await self._queue.enqueue(self._run_task(task))

    async def dequeue(self) -> EvalTask | None:
        task = await self._queue.dequeue()
        return None if task is None else self._eval_task(task)

    async def acknowledge(self, task: EvalTask) -> None:
        await self._queue.acknowledge(self._run_task(task))

    async def retry(self, task: EvalTask) -> None:
        await self._queue.retry(self._run_task(task))

    async def extend_lease(self, task: EvalTask) -> None:
        await self._queue.extend_lease(self._run_task(task))
