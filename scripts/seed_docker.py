"""Idempotently publish production Agent bundles into a running Docker API."""

import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from harness.agent_package import pack_agent_package


def _publish_bundle(
    *,
    api_url: str,
    tenant_id: str,
    user_id: str,
    api_token: str,
    manifest: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="harness-seed-") as directory:
        archive, _ = pack_agent_package(manifest, output_directory=directory)
        headers = {
            "Content-Type": "application/zip",
            "X-Tenant-ID": tenant_id,
            "X-User-ID": user_id,
        }
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        request = urllib.request.Request(
            f"{api_url}/v1/agents/bundles",
            data=archive.read_bytes(),
            headers=headers,
            method="POST",
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    if response.status == 201:
                        return
            except urllib.error.HTTPError as error:
                if error.code == 409:
                    return
                if error.code < 500:
                    raise
            except urllib.error.URLError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Harness API was not ready for Agent publication")
            time.sleep(1)


def main() -> None:
    api_url = os.getenv("HARNESS_API_URL", "http://api:8000").rstrip("/")
    tenant_id = os.getenv("HARNESS_TENANT_ID", "local")
    user_id = os.getenv("HARNESS_USER_ID", "system")
    api_token = os.getenv("HARNESS_API_BEARER_TOKEN", "")
    raw_manifests = os.getenv(
        "HARNESS_SEED_AGENT_MANIFESTS",
        (
            "/app/agents/helper-agent/agent.yaml,"
            "/app/agents/echo-agent/agent.yaml,"
            "/app/agents/public-opinion-agent/agent.yaml"
        ),
    )
    for value in raw_manifests.split(","):
        value = value.strip()
        if not value:
            continue
        _publish_bundle(
            api_url=api_url,
            tenant_id=tenant_id,
            user_id=user_id,
            api_token=api_token,
            manifest=Path(value),
        )


if __name__ == "__main__":
    main()
