"""Idempotently publish the default Agent used by the local Web console."""

import asyncio
import os
from pathlib import Path

from httpx import AsyncClient

DEFAULT_MANIFEST = Path("tests/fixtures/agents/echo-agent/agent.yaml")
HEADERS = {"X-Tenant-ID": "local", "X-User-ID": "developer"}


async def bootstrap_local_agent(
    client: AsyncClient,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> None:
    response = await client.post(
        "/v1/agents",
        json={"path": str(manifest_path)},
        headers=HEADERS,
    )
    if response.status_code not in {201, 409}:
        response.raise_for_status()


async def main() -> None:
    api_url = os.getenv("HARNESS_API_URL", "http://127.0.0.1:8000")
    async with AsyncClient(base_url=api_url, timeout=10) as client:
        await bootstrap_local_agent(client)
    print("Local Agent: echo-agent@0.1.0 ready")


if __name__ == "__main__":
    asyncio.run(main())
