import asyncio
import os
from typing import cast

import pytest
from redis.asyncio import Redis

from harness.core.models import Run
from harness.core.ports import RunTask, TaskQueue
from harness.deployments.queue import DeploymentTask, DeploymentTaskQueue
from harness.evals.queue import EvalTask, EvalTaskQueue
from harness.quality.queue import QualityTask, QualityTaskQueue
from harness.reliability.metrics import ReliabilityMetrics
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue
from harness.studio.preview_queue import PreviewTask, PreviewTaskQueue
from harness.worker.main import worker_loop


def redis_url(database: int) -> str:
    return f"{os.getenv('HARNESS_TEST_REDIS_BASE_URL', 'redis://localhost:6379')}/{database}"


class FaultInjectingQueue:
    def __init__(self, queue: RedisTaskQueue, operation: str) -> None:
        self._queue = queue
        self._operation = operation
        self._failed = False

    def _fail_once(self, operation: str) -> None:
        if operation == self._operation and not self._failed:
            self._failed = True
            raise RuntimeError("injected redis outage")

    async def enqueue(self, task: RunTask) -> None:
        await self._queue.enqueue(task)

    async def dequeue(self) -> RunTask | None:
        self._fail_once("dequeue")
        return await self._queue.dequeue()

    async def acknowledge(self, task: RunTask) -> None:
        self._fail_once("acknowledge")
        await self._queue.acknowledge(task)

    async def retry(self, task: RunTask) -> None:
        self._fail_once("retry")
        await self._queue.retry(task)

    async def extend_lease(self, task: RunTask) -> None:
        await self._queue.extend_lease(task)

    async def stats(self) -> dict[str, int]:
        return await self._queue.stats()


class RecoveringExecutor:
    def __init__(self, stop: asyncio.Event, operation: str) -> None:
        self._stop = stop
        self._operation = operation
        self.calls = 0
        self.business_completions = 0
        self._terminal = False

    async def execute(self, tenant_id: str, run_id: str) -> Run:
        del tenant_id, run_id
        self.calls += 1
        if self._operation == "retry" and self.calls == 1:
            raise RuntimeError("injected executor failure")
        if not self._terminal:
            self.business_completions += 1
            self._terminal = True
        if self._operation != "acknowledge" or self.calls >= 2:
            self._stop.set()
        return Run.model_construct()


@pytest.mark.parametrize("operation", ["dequeue", "retry", "acknowledge"])
@pytest.mark.asyncio
async def test_worker_recovers_from_real_redis_queue_operation_failure(
    operation: str,
) -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        redis_url(10), decode_responses=True
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    redis_queue = RedisTaskQueue(
        cast(AsyncRedisClient, client),
        namespace=f"worker-fault-{operation}",
        visibility_timeout_seconds=0.03,
        retry_delay_seconds=0,
    )
    queue = FaultInjectingQueue(redis_queue, operation)
    task = RunTask(tenant_id="tenant-a", run_id=f"run-{operation}")
    await queue.enqueue(task)
    stop = asyncio.Event()
    executor = RecoveringExecutor(stop, operation)
    metrics = ReliabilityMetrics()
    try:
        await asyncio.wait_for(
            worker_loop(
                cast(TaskQueue, queue),
                executor,
                stop=stop,
                poll_interval=0.005,
                lease_heartbeat_interval=1,
                metrics=metrics,
            ),
            timeout=1,
        )

        assert executor.business_completions == 1
        assert executor.calls == (2 if operation in {"retry", "acknowledge"} else 1)
        assert metrics.count(
            "harness_worker_queue_failures_total",
            labels={"operation": operation},
        ) == 1
        assert await redis_queue.stats() == {"ready": 0, "processing": 0}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_queue_deduplicates_delivery() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        redis_url(15), decode_responses=True
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    queue = RedisTaskQueue(
        cast(AsyncRedisClient, client),
        namespace="test",
        visibility_timeout_seconds=0.05,
        retry_delay_seconds=0,
    )
    try:
        task = RunTask(tenant_id="tenant-a", run_id="run-1")
        await queue.enqueue(task)
        await queue.enqueue(task)
        assert await queue.dequeue() == task
        assert await queue.dequeue() is None
        await queue.retry(task)
        assert await queue.dequeue() == task
        await asyncio.sleep(0.06)
        second_owner = RedisTaskQueue(
            cast(AsyncRedisClient, client),
            namespace="test",
            visibility_timeout_seconds=0.05,
            retry_delay_seconds=0,
        )
        assert await second_owner.dequeue() == task
        await queue.acknowledge(task)
        await second_owner.retry(task)
        assert await second_owner.dequeue() == task
        await second_owner.acknowledge(task)
        await queue.enqueue(task)
        assert await queue.dequeue() == task
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_preview_queue_recovers_a_crashed_worker_lease() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        redis_url(14), decode_responses=True
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    queue = PreviewTaskQueue.redis(
        cast(AsyncRedisClient, client),
        visibility_timeout_seconds=0.05,
        retry_delay_seconds=0,
    )
    try:
        task = PreviewTask(tenant_id="tenant-a", preview_id="preview-1")
        await queue.enqueue(task)
        await queue.enqueue(task)
        assert await queue.dequeue() == task
        assert await queue.dequeue() is None

        # The first owner disappears without ACK; a new Controller instance can
        # acquire the same durable job after its visibility lease expires.
        await asyncio.sleep(0.06)
        recovered_queue = PreviewTaskQueue.redis(
            cast(AsyncRedisClient, client),
            visibility_timeout_seconds=0.05,
            retry_delay_seconds=0,
        )
        recovered = None
        for _attempt in range(20):
            recovered = await recovered_queue.dequeue()
            if recovered is not None:
                break
            await asyncio.sleep(0.02)
        assert recovered == task
        await recovered_queue.acknowledge(task)
        assert await recovered_queue.dequeue() is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_eval_queue_recovers_a_crashed_controller_lease() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        redis_url(13), decode_responses=True
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    queue = EvalTaskQueue.redis(
        cast(AsyncRedisClient, client),
        visibility_timeout_seconds=0.05,
        retry_delay_seconds=0,
    )
    try:
        task = EvalTask(tenant_id="tenant-a", eval_run_id="eval-run-one")
        await queue.enqueue(task)
        await queue.enqueue(task)
        assert await queue.dequeue() == task
        assert await queue.dequeue() is None
        await asyncio.sleep(0.06)
        recovered = EvalTaskQueue.redis(
            cast(AsyncRedisClient, client),
            visibility_timeout_seconds=0.05,
            retry_delay_seconds=0,
        )
        item = None
        for _attempt in range(20):
            item = await recovered.dequeue()
            if item is not None:
                break
            await asyncio.sleep(0.02)
        assert item == task
        await recovered.acknowledge(task)
        assert await recovered.dequeue() is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_deployment_queue_recovers_a_crashed_controller_lease() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        redis_url(12), decode_responses=True
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    queue = DeploymentTaskQueue.redis(
        cast(AsyncRedisClient, client),
        visibility_timeout_seconds=0.05,
        retry_delay_seconds=0,
    )
    try:
        task = DeploymentTask(tenant_id="tenant-a", deployment_id="deployment-one")
        await queue.enqueue(task)
        await queue.enqueue(task)
        assert await queue.dequeue() == task
        assert await queue.dequeue() is None
        await asyncio.sleep(0.06)
        recovered = DeploymentTaskQueue.redis(
            cast(AsyncRedisClient, client),
            visibility_timeout_seconds=0.05,
            retry_delay_seconds=0,
        )
        item = None
        for _attempt in range(20):
            item = await recovered.dequeue()
            if item is not None:
                break
            await asyncio.sleep(0.02)
        assert item == task
        await recovered.acknowledge(task)
        assert await recovered.dequeue() is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_quality_queue_recovers_a_crashed_sync_worker_lease() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        redis_url(11), decode_responses=True
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    queue = QualityTaskQueue.redis(
        cast(AsyncRedisClient, client),
        visibility_timeout_seconds=0.05,
        retry_delay_seconds=0,
    )
    try:
        task = QualityTask(tenant_id="tenant-a", sync_id="quality-sync-one")
        await queue.enqueue(task)
        assert await queue.dequeue() == task
        await asyncio.sleep(0.06)
        recovered = QualityTaskQueue.redis(
            cast(AsyncRedisClient, client),
            visibility_timeout_seconds=0.05,
            retry_delay_seconds=0,
        )
        item = None
        for _attempt in range(20):
            item = await recovered.dequeue()
            if item is not None:
                break
            await asyncio.sleep(0.02)
        assert item == task
        await recovered.acknowledge(task)
    finally:
        await client.aclose()
