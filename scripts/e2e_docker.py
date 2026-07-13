"""Black-box Docker E2E for upload, processing, memory, artifact and restart durability."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx

ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / "deploy/docker-compose/compose.yaml"
DEFAULT_ENV = ROOT / "deploy/docker-compose/.env.docker"


def _events(body: str) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], json.loads(line.removeprefix("data: ")))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _wait_for_health(client: httpx.Client, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError("Harness API did not become healthy")


def _agui_request(
    client: httpx.Client,
    *,
    thread_id: str,
    run_id: str,
    content: str | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    response = client.post(
        "/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
        json={
            "threadId": thread_id,
            "runId": run_id,
            "state": {},
            "messages": [
                {"id": f"message-{run_id}", "role": "user", "content": content}
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        },
        timeout=900,
    )
    response.raise_for_status()
    events = _events(response.text)
    errors = [event for event in events if event.get("type") == "RUN_ERROR"]
    if errors:
        raise AssertionError(f"Docker model run failed: {errors[-1]}")
    if not any(event.get("type") == "RUN_FINISHED" for event in events):
        raise AssertionError("Docker model run did not finish")
    return events


def _artifact_id(events: list[dict[str, Any]]) -> str:
    tool_ids = {
        str(event["toolCallId"])
        for event in events
        if event.get("type") == "TOOL_CALL_START"
        and event.get("toolCallName") == "harness_present_artifact"
    }
    for event in events:
        if event.get("type") != "TOOL_CALL_ARGS":
            continue
        if str(event.get("toolCallId")) not in tool_ids:
            continue
        arguments = cast(dict[str, Any], json.loads(str(event["delta"])))
        artifact_id = arguments.get("artifact_id")
        if isinstance(artifact_id, str):
            return artifact_id
    raise AssertionError("publish_artifact did not produce an artifact")


def _session_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "STATE_SNAPSHOT":
            continue
        snapshot = event.get("snapshot")
        if isinstance(snapshot, dict):
            session_id = cast(dict[str, Any], snapshot).get("threadId")
            if isinstance(session_id, str) and session_id.startswith("session_"):
                return session_id
    raise AssertionError("Harness session ID was not projected in AG-UI state")


def _assistant_text(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(event.get("delta", ""))
        for event in events
        if event.get("type") == "TEXT_MESSAGE_CONTENT"
    )


def _restart(compose_env: Path) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(compose_env),
            "-f",
            str(COMPOSE),
            "restart",
            "api",
            "worker",
        ],
        cwd=ROOT,
        check=True,
    )


def run(*, api_url: str, compose_env: Path, restart: bool) -> dict[str, Any]:
    unique = uuid4().hex[:12]
    marker = f"docker-e2e-{unique}"
    memory_marker = f"docker-memory-{unique}"
    headers = {
        "X-Tenant-ID": "docker-e2e",
        "X-User-ID": "docker-e2e-user",
    }
    with httpx.Client(
        base_url=api_url,
        headers=headers,
        trust_env=False,
    ) as client:
        _wait_for_health(client)
        published = client.post(
            "/v1/agents",
            json={"path": "/app/agents/echo-agent/agent.yaml"},
        )
        if published.status_code not in {201, 409}:
            published.raise_for_status()
        uploaded = client.post(
            "/v1/input-artifacts",
            files={"file": ("docker-e2e.txt", marker.encode(), "text/plain")},
        )
        uploaded.raise_for_status()
        input_artifact_id = str(uploaded.json()["input_artifact_id"])

        first = _agui_request(
            client,
            thread_id=f"docker-thread-{unique}",
            run_id=f"docker-run-{unique}",
            content=[
                {
                    "type": "text",
                    "text": (
                        f"Read the attached file. Call update_user_memory with exactly "
                        f"'{memory_marker}'. Then call publish_artifact for that attached "
                        "workspace file. Finish by repeating the file marker exactly."
                    ),
                },
                {
                    "type": "binary",
                    "mimeType": "text/plain",
                    "id": input_artifact_id,
                    "filename": "docker-e2e.txt",
                },
            ],
        )
        if marker not in _assistant_text(first):
            raise AssertionError("model did not read the uploaded marker")
        artifact_id = _artifact_id(first)
        session_id = _session_id(first)
        files = client.get(f"/v1/threads/{session_id}/files")
        files.raise_for_status()
        catalog = cast(list[dict[str, Any]], files.json())
        if not any(item.get("input_artifact_id") == input_artifact_id for item in catalog):
            raise AssertionError("original upload is missing from the thread file catalog")
        if not any(item.get("parent_file_id") for item in catalog):
            raise AssertionError("processed file lineage is missing from the catalog")

        second = _agui_request(
            client,
            thread_id=f"docker-memory-thread-{unique}",
            run_id=f"docker-memory-run-{unique}",
            content="Return the exact durable user memory marker and nothing else.",
        )
        if memory_marker not in _assistant_text(second):
            raise AssertionError("cross-session durable memory was not recalled")

        if restart:
            _restart(compose_env)
            _wait_for_health(client)
        input_download = client.get(
            f"/v1/input-artifacts/{input_artifact_id}/content"
        )
        input_download.raise_for_status()
        artifact_download = client.get(f"/v1/artifacts/{artifact_id}/content")
        artifact_download.raise_for_status()
        if marker.encode() not in input_download.content:
            raise AssertionError("input artifact did not survive restart")
        if marker.encode() not in artifact_download.content:
            raise AssertionError("published artifact did not survive restart")

    return {
        "marker": marker,
        "input_artifact_id": input_artifact_id,
        "artifact_id": artifact_id,
        "session_id": session_id,
        "restart_verified": restart,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--compose-env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--skip-restart", action="store_true")
    arguments = parser.parse_args()
    print(
        run(
            api_url=arguments.api_url,
            compose_env=arguments.compose_env,
            restart=not arguments.skip_restart,
        )
    )


if __name__ == "__main__":
    main()
