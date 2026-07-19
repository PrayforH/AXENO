import asyncio
import os
from typing import cast

import pytest
from redis.asyncio import Redis

from harness.core.ports import RunTask
from harness.deployments.queue import DeploymentTask, DeploymentTaskQueue
from harness.evals.queue import EvalTask, EvalTaskQueue
from harness.quality.queue import QualityTask, QualityTaskQueue
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue
from harness.studio.preview_queue import PreviewTask, PreviewTaskQueue


def redis_url(database: int) -> str:
    return f"{os.getenv('HARNESS_TEST_REDIS_BASE_URL', 'redis://localhost:6379')}/{database}"


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
