"""Redis transient queue and event fan-out adapters."""

import json
from collections.abc import Awaitable
from typing import Protocol
from uuid import uuid4

from harness.core.events import RunEvent
from harness.core.ports import RunTask


class AsyncRedisClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Awaitable[object]: ...

    def zadd(self, name: str, mapping: dict[str, int]) -> Awaitable[object]: ...

    def zrangebyscore(
        self, name: str, minimum: str, maximum: str
    ) -> Awaitable[list[bytes | str]]: ...

    def zcard(self, name: str) -> Awaitable[int]: ...


_ENQUEUE = """
local current = redis.call('TIME')
local now = tonumber(current[1]) + tonumber(current[2]) / 1000000
if redis.call('SADD', KEYS[1], ARGV[1]) == 1 then
  redis.call('ZADD', KEYS[2], now, ARGV[1])
  return 1
end
return 0
"""

_DEQUEUE = """
local current = redis.call('TIME')
local now = tonumber(current[1]) + tonumber(current[2]) / 1000000
local expired = redis.call('ZRANGEBYSCORE', KEYS[3], '-inf', now)
for _, item in ipairs(expired) do
  redis.call('ZREM', KEYS[3], item)
  redis.call('HDEL', KEYS[4], item)
  redis.call('ZADD', KEYS[2], now, item)
end
local items = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now, 'LIMIT', 0, 1)
local item = items[1]
if item then
  redis.call('ZREM', KEYS[2], item)
  redis.call('ZADD', KEYS[3], now + tonumber(ARGV[1]), item)
  redis.call('HSET', KEYS[4], item, ARGV[2])
end
return item
"""

_ACKNOWLEDGE = """
if redis.call('HGET', KEYS[3], ARGV[1]) == ARGV[2] then
  redis.call('ZREM', KEYS[2], ARGV[1])
  redis.call('HDEL', KEYS[3], ARGV[1])
  return redis.call('SREM', KEYS[1], ARGV[1])
end
return 0
"""

_RETRY = """
local current = redis.call('TIME')
local now = tonumber(current[1]) + tonumber(current[2]) / 1000000
if redis.call('HGET', KEYS[3], ARGV[1]) == ARGV[3]
  and redis.call('ZREM', KEYS[2], ARGV[1]) == 1 then
  redis.call('HDEL', KEYS[3], ARGV[1])
  redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
  return 1
end
return 0
"""

_EXTEND_LEASE = """
local current = redis.call('TIME')
local now = tonumber(current[1]) + tonumber(current[2]) / 1000000
if redis.call('HGET', KEYS[2], ARGV[1]) == ARGV[3]
  and redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
  return 1
end
return 0
"""


class RedisTaskQueue:
    def __init__(
        self,
        client: AsyncRedisClient,
        *,
        namespace: str = "harness",
        visibility_timeout_seconds: float = 60,
        retry_delay_seconds: float = 1,
    ) -> None:
        if visibility_timeout_seconds <= 0 or retry_delay_seconds < 0:
            raise ValueError("queue visibility must be positive and retry delay non-negative")
        self._client = client
        self._pending = f"{namespace}:queue:pending"
        self._ready = f"{namespace}:queue:ready"
        self._processing = f"{namespace}:queue:processing"
        self._receipt_key = f"{namespace}:queue:receipts"
        self._receipts: dict[str, str] = {}
        self._visibility_timeout_seconds = visibility_timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds

    async def enqueue(self, task: RunTask) -> None:
        payload = task.model_dump_json()
        await self._client.eval(
            _ENQUEUE,
            2,
            self._pending,
            self._ready,
            payload,
        )

    async def dequeue(self) -> RunTask | None:
        receipt = uuid4().hex
        value = await self._client.eval(
            _DEQUEUE,
            4,
            self._pending,
            self._ready,
            self._processing,
            self._receipt_key,
            str(self._visibility_timeout_seconds),
            receipt,
        )
        if value is None:
            return None
        payload = value.decode() if isinstance(value, bytes) else str(value)
        self._receipts[payload] = receipt
        return RunTask.model_validate_json(payload)

    async def acknowledge(self, task: RunTask) -> None:
        payload = task.model_dump_json()
        receipt = self._receipts.pop(payload, "")
        await self._client.eval(
            _ACKNOWLEDGE,
            3,
            self._pending,
            self._processing,
            self._receipt_key,
            payload,
            receipt,
        )

    async def retry(self, task: RunTask) -> None:
        payload = task.model_dump_json()
        receipt = self._receipts.pop(payload, "")
        await self._client.eval(
            _RETRY,
            3,
            self._ready,
            self._processing,
            self._receipt_key,
            payload,
            str(self._retry_delay_seconds),
            receipt,
        )

    async def extend_lease(self, task: RunTask) -> None:
        payload = task.model_dump_json()
        receipt = self._receipts.get(payload, "")
        await self._client.eval(
            _EXTEND_LEASE,
            2,
            self._processing,
            self._receipt_key,
            payload,
            str(self._visibility_timeout_seconds),
            receipt,
        )

    async def stats(self) -> dict[str, int]:
        ready = await self._client.zcard(self._ready)
        processing = await self._client.zcard(self._processing)
        return {"ready": int(ready), "processing": int(processing)}


class RedisEventBus:
    def __init__(self, client: AsyncRedisClient, *, namespace: str = "harness") -> None:
        self._client = client
        self._namespace = namespace

    def _key(self, tenant_id: str, run_id: str) -> str:
        return f"{self._namespace}:events:{tenant_id}:{run_id}"

    async def publish(self, event: RunEvent) -> None:
        await self._client.zadd(
            self._key(event.tenant_id, event.run_id),
            {json.dumps(event.model_dump(mode="json")): event.sequence},
        )

    async def read(self, tenant_id: str, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        values = await self._client.zrangebyscore(
            self._key(tenant_id, run_id), f"({after_sequence}", "+inf"
        )
        return [RunEvent.model_validate_json(value) for value in values]
