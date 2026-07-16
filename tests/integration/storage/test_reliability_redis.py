import os
from typing import cast

import pytest
from redis.asyncio import Redis

from harness.core.ports import RunTask
from harness.storage.redis import AsyncRedisClient, RedisTaskQueue


@pytest.mark.asyncio
async def test_queue_capacity_stats_follow_ready_and_processing_leases() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        os.getenv("HARNESS_TEST_REDIS_URL", "redis://localhost:6379/10"),
        decode_responses=True,
    )
    await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    queue = RedisTaskQueue(cast(AsyncRedisClient, client), namespace="reliability-test")
    try:
        first = RunTask(tenant_id="tenant-a", run_id="run-1")
        second = RunTask(tenant_id="tenant-a", run_id="run-2")
        await queue.enqueue(first)
        await queue.enqueue(second)
        assert await queue.stats() == {"ready": 2, "processing": 0}

        assert await queue.dequeue() == first
        assert await queue.stats() == {"ready": 1, "processing": 1}

        await queue.acknowledge(first)
        assert await queue.stats() == {"ready": 1, "processing": 0}
    finally:
        await client.aclose()
