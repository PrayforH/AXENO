"""Redis transient queue and event fan-out adapters."""

import json
from collections.abc import Awaitable
from typing import Protocol

from harness.core.events import RunEvent
from harness.core.ports import RunTask


class AsyncRedisClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Awaitable[object]: ...

    def zadd(self, name: str, mapping: dict[str, int]) -> Awaitable[object]: ...

    def zrangebyscore(
        self, name: str, minimum: str, maximum: str
    ) -> Awaitable[list[bytes | str]]: ...


_ENQUEUE = """
if redis.call('SADD', KEYS[1], ARGV[1]) == 1 then
  redis.call('RPUSH', KEYS[2], ARGV[1])
  return 1
end
return 0
"""

_DEQUEUE = """
local item = redis.call('LPOP', KEYS[2])
if item then redis.call('SREM', KEYS[1], item) end
return item
"""


class RedisTaskQueue:
    def __init__(self, client: AsyncRedisClient, *, namespace: str = "harness") -> None:
        self._client = client
        self._pending = f"{namespace}:queue:pending"
        self._queue = f"{namespace}:queue:runs"

    async def enqueue(self, task: RunTask) -> None:
        payload = task.model_dump_json()
        await self._client.eval(_ENQUEUE, 2, self._pending, self._queue, payload)

    async def dequeue(self) -> RunTask | None:
        value = await self._client.eval(_DEQUEUE, 2, self._pending, self._queue)
        if value is None:
            return None
        return RunTask.model_validate_json(
            value.decode() if isinstance(value, bytes) else str(value)
        )


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
