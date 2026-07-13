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
    queue = RedisTaskQueue(cast(AsyncRedisClient, client), namespace="test")
    try:
        task = RunTask(tenant_id="tenant-a", run_id="run-1")
        await queue.enqueue(task)
        await queue.enqueue(task)
        assert await queue.dequeue() == task
        assert await queue.dequeue() is None
    finally:
        await client.aclose()
