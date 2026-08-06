"""Wait for the phase-one local persistence services to become ready."""

import asyncio
import time
from collections.abc import Awaitable, Callable

import asyncpg
from minio import Minio
from redis.asyncio import Redis


async def retry[T](name: str, check: Callable[[], Awaitable[T]], timeout: float = 90) -> T:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return await check()
        except Exception as error:  # noqa: BLE001 - readiness boundary
            last_error = error
            await asyncio.sleep(1)
    raise RuntimeError(f"{name} did not become ready: {last_error}")


async def postgres_ready() -> None:
    connection = await asyncpg.connect("postgresql://harness:harness@localhost:5432/harness")
    await connection.close()


async def redis_ready() -> None:
    client: Redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        "redis://localhost:6379/0"
    )
    try:
        await client.ping()  # pyright: ignore[reportUnknownMemberType]
    finally:
        await client.aclose()


async def minio_ready() -> None:
    client = Minio(
        "localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False,
    )
    exists = await asyncio.to_thread(client.bucket_exists, "harness-artifacts")
    if not exists:
        raise RuntimeError("harness-artifacts bucket is missing")


async def main() -> None:
    await asyncio.gather(
        retry("PostgreSQL", postgres_ready),
        retry("Redis", redis_ready),
        retry("MinIO", minio_ready),
    )
    print("PostgreSQL, Redis and MinIO are ready")


if __name__ == "__main__":
    asyncio.run(main())
