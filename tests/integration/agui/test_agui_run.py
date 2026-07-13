import asyncio
import json
from pathlib import Path

import pytest
from ag_ui.core import RunAgentInput
from httpx import ASGITransport, AsyncClient

from harness.api.app import create_memory_app
from harness.core.errors import NotFoundError

FIXTURE_MANIFEST = Path("tests/fixtures/agents/echo-agent/agent.yaml")
HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-1"}


def _request(*, thread_id: str, run_id: str, prompt: str) -> dict[str, object]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": {},
        "messages": [{"id": f"message-{run_id}", "role": "user", "content": prompt}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def _events(body: str) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_post_agui_runs_agent_and_streams_standard_events() -> None:
    app = create_memory_app(auto_execute=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        published = await client.post(
            "/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS
        )
        assert published.status_code == 201

        response = await client.post(
            "/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
            json=_request(thread_id="thread-a", run_id="client-run-1", prompt="hello"),
            headers=HEADERS,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert events[0] == {
        "type": "RUN_STARTED",
        "threadId": "thread-a",
        "runId": "client-run-1",
    }
    assert any(
        event.get("type") == "TEXT_MESSAGE_CONTENT"
        and event.get("delta") == "Echo: hello"
        for event in events
    )
    assert sum(event.get("type") == "ACTIVITY_SNAPSHOT" for event in events) == 1
    assert any(event.get("type") == "ACTIVITY_DELTA" for event in events)
    assert events[-1] == {
        "type": "RUN_FINISHED",
        "threadId": "thread-a",
        "runId": "client-run-1",
    }


@pytest.mark.asyncio
async def test_post_agui_waits_for_terminal_event_after_run_status_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_memory_app(auto_execute=True)
    worker = app.state.container.worker
    event_service = worker._events
    original_append = event_service.append

    async def delayed_append(**values: object):
        if values.get("event_type") == "run.succeeded":
            await asyncio.sleep(0.1)
        return await original_append(**values)

    monkeypatch.setattr(event_service, "append", delayed_append)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS
        )
        response = await client.post(
            "/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
            json=_request(thread_id="thread-race", run_id="client-race", prompt="hello"),
            headers=HEADERS,
        )

    assert any(event.get("type") == "RUN_FINISHED" for event in _events(response.text))


@pytest.mark.asyncio
async def test_post_agui_reuses_harness_session_for_same_thread() -> None:
    app = create_memory_app(auto_execute=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        for run_id in ("client-run-1", "client-run-2"):
            response = await client.post(
                "/v1/agui?agent_name=echo-agent&agent_version=0.1.0",
                json=_request(thread_id="thread-a", run_id=run_id, prompt=run_id),
                headers=HEADERS,
            )
            assert response.status_code == 200

    first = await app.state.container.agui.get_binding(
        tenant_id="tenant-a", user_id="user-1", thread_id="thread-a"
    )
    second = await app.state.container.agui.get_binding(
        tenant_id="tenant-a", user_id="user-1", thread_id="thread-a"
    )
    assert first.session_id == second.session_id
    assert first.agent_name == "echo-agent"
    assert first.agent_version == "0.1.0"


@pytest.mark.asyncio
async def test_cancel_agui_run_resolves_protocol_ids_to_harness_run() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        request = RunAgentInput.model_validate(
            _request(thread_id="thread-cancel", run_id="client-run-cancel", prompt="wait")
        )
        run = await app.state.container.agui.create_run(
            tenant_id="tenant-a",
            user_id="user-1",
            agent_name="echo-agent",
            agent_version="0.1.0",
            request=request,
        )

        response = await client.post(
            "/v1/agui/threads/thread-cancel/runs/client-run-cancel/cancel",
            headers=HEADERS,
        )

    assert response.status_code == 200
    assert response.json()["run_id"] == run.run_id
    assert response.json()["status"] == "cancelling"


@pytest.mark.asyncio
async def test_agui_run_resolves_uploaded_binary_input_for_owner() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        uploaded = await client.post(
            "/v1/input-artifacts",
            files={"file": ("facts.txt", b"The code is amber-731.", "text/plain")},
            headers=HEADERS,
        )
        input_artifact_id = uploaded.json()["input_artifact_id"]

    body = _request(thread_id="thread-file", run_id="client-file", prompt="Read it")
    body["messages"] = [
        {
            "id": "message-file",
            "role": "user",
            "content": [
                {"type": "text", "text": "Read it"},
                {
                    "type": "binary",
                    "mimeType": "text/plain",
                    "id": input_artifact_id,
                    "filename": "facts.txt",
                },
                {
                    "type": "binary",
                    "mimeType": "text/plain",
                    "id": input_artifact_id,
                    "filename": "duplicate.txt",
                },
            ],
        }
    ]
    run = await app.state.container.agui.create_run(
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="0.1.0",
        request=RunAgentInput.model_validate(body),
    )

    assert run.input == {
        "prompt": "Read it",
        "input_artifact_ids": [input_artifact_id],
    }


@pytest.mark.asyncio
async def test_agui_run_does_not_trust_inline_data_urls_or_cross_user_ids() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        uploaded = await client.post(
            "/v1/input-artifacts",
            files={"file": ("private.txt", b"private", "text/plain")},
            headers=HEADERS,
        )
        input_artifact_id = uploaded.json()["input_artifact_id"]

    untrusted = _request(thread_id="thread-untrusted", run_id="untrusted", prompt="Read")
    untrusted["messages"] = [
        {
            "id": "message-untrusted",
            "role": "user",
            "content": [
                {"type": "text", "text": "Read"},
                {
                    "type": "binary",
                    "mimeType": "text/plain",
                    "url": "file:///Users/example/private.txt",
                    "data": "c2VjcmV0",
                    "filename": "private.txt",
                },
            ],
        }
    ]
    run = await app.state.container.agui.create_run(
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="0.1.0",
        request=RunAgentInput.model_validate(untrusted),
    )
    assert run.input["input_artifact_ids"] == []

    forged = _request(thread_id="thread-forged", run_id="forged", prompt="Read")
    forged["messages"] = [
        {
            "id": "message-forged",
            "role": "user",
            "content": [
                {"type": "text", "text": "Read"},
                {
                    "type": "binary",
                    "mimeType": "text/plain",
                    "id": input_artifact_id,
                },
            ],
        }
    ]
    with pytest.raises(NotFoundError, match="input artifact not found"):
        await app.state.container.agui.create_run(
            tenant_id="tenant-a",
            user_id="user-2",
            agent_name="echo-agent",
            agent_version="0.1.0",
            request=RunAgentInput.model_validate(forged),
        )


@pytest.mark.asyncio
async def test_agui_run_accepts_assistant_ui_document_transport_envelope() -> None:
    app = create_memory_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/agents", json={"path": str(FIXTURE_MANIFEST)}, headers=HEADERS)
        uploaded = await client.post(
            "/v1/input-artifacts",
            files={"file": ("report.pdf", b"fake pdf", "application/pdf")},
            headers=HEADERS,
        )
        input_artifact_id = uploaded.json()["input_artifact_id"]

    body = _request(thread_id="thread-document", run_id="document", prompt="Read")
    body["messages"] = [
        {
            "id": "message-document",
            "role": "user",
            "content": [
                {"type": "text", "text": "Read"},
                {
                    "type": "document",
                    "source": {
                        "type": "data",
                        "value": input_artifact_id,
                        "mimeType": "application/pdf",
                    },
                    "metadata": {"filename": "report.pdf"},
                },
            ],
        }
    ]

    run = await app.state.container.agui.create_run(
        tenant_id="tenant-a",
        user_id="user-1",
        agent_name="echo-agent",
        agent_version="0.1.0",
        request=RunAgentInput.model_validate(body),
    )

    assert run.input["input_artifact_ids"] == [input_artifact_id]
