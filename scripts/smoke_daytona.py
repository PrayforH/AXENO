"""Provision a disposable Daytona sandbox and probe the configured model gateway."""

from __future__ import annotations

import asyncio
import os
import shlex
from urllib.parse import urlsplit, urlunsplit

from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams, DaytonaConfig

from harness.sandbox.daytona import configure_default_ca_bundle


def gateway_origin(value: str) -> str:
    """Return a credential-free HTTP origin suitable for a connectivity probe."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("HARNESS_NEW_API_BASE_URL must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("HARNESS_NEW_API_BASE_URL must not contain credentials")
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


async def main() -> int:
    api_key = os.getenv("HARNESS_DAYTONA_API_KEY", "").strip()
    gateway_url = os.getenv("HARNESS_NEW_API_BASE_URL", "").strip()
    if not api_key or not gateway_url:
        print(
            "FAIL: HARNESS_DAYTONA_API_KEY and HARNESS_NEW_API_BASE_URL are required"
        )
        return 2

    try:
        origin = gateway_origin(gateway_url)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2

    configure_default_ca_bundle()
    client = AsyncDaytona(
        DaytonaConfig(
            api_key=api_key,
            api_url=os.getenv("HARNESS_DAYTONA_API_URL") or None,
            target=os.getenv("HARNESS_DAYTONA_TARGET") or None,
        )
    )
    sandbox = None
    try:
        sandbox = await client.create(
            CreateSandboxFromSnapshotParams.model_validate(
                {
                    "snapshot": os.getenv("HARNESS_DAYTONA_SNAPSHOT") or None,
                    "name": "harness-network-preflight",
                    "labels": {"harness.purpose": "network-preflight"},
                    "auto_stop_interval": 15,
                    "auto_delete_interval": 60,
                }
            )
        )
        print("PASS: Daytona API created a disposable sandbox")
        command = (
            "curl -sS -o /dev/null -w '%{http_code}' 2>/dev/null "
            "--connect-timeout 5 --max-time 10 "
            f"{shlex.quote(origin)}"
        )
        result = await sandbox.process.exec(command, timeout=20)
        status = result.result.strip()
        if result.exit_code != 0 or status == "000":
            print("FAIL: Daytona sandbox cannot reach the configured model gateway")
            return 1
        print(
            "PASS: Daytona sandbox reached the configured model gateway "
            f"(HTTP {status})"
        )
        return 0
    except Exception as exc:
        print(f"FAIL: Daytona preflight failed during {type(exc).__name__}")
        return 1
    finally:
        try:
            if sandbox is not None:
                try:
                    await client.stop(sandbox)
                finally:
                    await client.delete(sandbox)
        finally:
            await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
