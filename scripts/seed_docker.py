"""Idempotently publish the default Agent package into a running Docker API."""

import json
import os
import time
import urllib.error
import urllib.request


def main() -> None:
    api_url = os.getenv("HARNESS_API_URL", "http://api:8000").rstrip("/")
    tenant_id = os.getenv("HARNESS_TENANT_ID", "local")
    user_id = os.getenv("HARNESS_USER_ID", "system")
    manifest = os.getenv(
        "HARNESS_SEED_AGENT_MANIFEST", "/app/agents/echo-agent/agent.yaml"
    )
    request = urllib.request.Request(
        f"{api_url}/v1/agents",
        data=json.dumps({"path": manifest}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Tenant-ID": tenant_id,
            "X-User-ID": user_id,
        },
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


if __name__ == "__main__":
    main()
