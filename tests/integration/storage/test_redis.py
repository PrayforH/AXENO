import asyncio
from typing import cast

import pytest
from redis.asyncio import Redis

from harness.core.ports import RunTask
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue


@pytest.mark.asyncio
async def test_redis_queue_deduplicates_delivery() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        "redis://localhost:6379/15", decode_responses=True
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
