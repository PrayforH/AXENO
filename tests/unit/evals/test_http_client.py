import json

import httpx
import pytest

from harness.evals.runner import HttpHarnessEvalClient


@pytest.mark.asyncio
async def test_http_eval_client_uses_public_session_run_and_event_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/input-artifacts":
            return httpx.Response(201, json={"input_artifact_id": "input-1"})
        if request.url.path == "/v1/sessions":
            return httpx.Response(201, json={"session_id": "session-1"})
        if request.url.path == "/v1/sessions/session-1/runs":
            return httpx.Response(202, json={"run_id": "run-1"})
        if request.url.path == "/v1/runs/run-1":
            return httpx.Response(200, json={"status": "succeeded"})
        if request.url.path == "/v1/runs/run-1/cancel":
            return httpx.Response(200, json={"status": "cancelling"})
        event = {
            "type": "message.completed",
            "payload": {"text": "done"},
        }
        return httpx.Response(
            200,
            text=f"id: 1\nevent: message.completed\ndata: {json.dumps(event)}\n\n",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "eval-user"},
    ) as http_client:
        client = HttpHarnessEvalClient(
            base_url="http://harness.test/v1/",
            tenant_id="ignored-by-injected-client",
            user_id="ignored-by-injected-client",
            api_token="private-service-token",
            client=http_client,
            poll_interval_seconds=0,
        )
        input_id = await client.upload_input(
            "invoice.txt", "text/plain", b"INV-100"
        )
        session_id = await client.create_session("invoice-reviewer", "1.0.0")
        run_id = await client.create_run(
            session_id, "review", "eval-key", (input_id,)
        )
        run = await client.wait_for_run(
            run_id,
            accepted_statuses=("succeeded",),
            timeout_seconds=1,
        )
        await client.cancel_run(run_id)

    assert session_id == "session-1"
    assert run.status == "succeeded"
    assert run.events[0]["type"] == "message.completed"
    run_request = next(
        request for request in requests if request.url.path.endswith("/runs")
    )
    assert run_request.headers["Idempotency-Key"] == "eval-key"
    assert json.loads(run_request.content)["input_artifact_ids"] == ["input-1"]
    assert requests[-1].url.path == "/v1/runs/run-1/cancel"
    assert all(
        request.headers["X-Tenant-ID"] == "ignored-by-injected-client"
        for request in requests
    )
    assert all(
        request.headers["Authorization"] == "Bearer private-service-token"
        for request in requests
    )
    assert "private-service-token" not in repr(requests)


@pytest.mark.asyncio
async def test_http_eval_client_raises_when_server_run_does_not_finish() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "running"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        client = HttpHarnessEvalClient(
            base_url="http://harness.test/v1",
            tenant_id="tenant-a",
            user_id="eval-user",
            client=http_client,
            poll_interval_seconds=0,
        )

        with pytest.raises(TimeoutError, match="did not reach a terminal status"):
            await client.wait_for_run(
                "run-stuck",
                accepted_statuses=("succeeded",),
                timeout_seconds=0,
            )
