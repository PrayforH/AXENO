"""Idempotently publish the default Agent used by the local Web console."""

import asyncio
import os
from pathlib import Path
from typing import TypedDict

from httpx import AsyncClient

DEFAULT_MANIFEST = Path("agents/echo-agent/agent.yaml")
DEFAULT_MANIFESTS = (
    Path("agents/helper-agent/agent.yaml"),
    DEFAULT_MANIFEST,
)
HEADERS = {"X-Tenant-ID": "local", "X-User-ID": "developer"}


class LocalClientOptions(TypedDict):
    base_url: str
    timeout: int
    trust_env: bool


def local_client_options(api_url: str) -> LocalClientOptions:
    return {"base_url": api_url, "timeout": 10, "trust_env": False}


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


async def bootstrap_local_agents(client: AsyncClient) -> None:
    for manifest_path in DEFAULT_MANIFESTS:
        await bootstrap_local_agent(client, manifest_path)


async def main() -> None:
    api_url = os.getenv("HARNESS_API_URL", "http://127.0.0.1:8000")
    async with AsyncClient(**local_client_options(api_url)) as client:
        await bootstrap_local_agents(client)
    print("Local Agents: helper-agent@1.0.0, echo-agent@0.3.0 ready")


if __name__ == "__main__":
    asyncio.run(main())
