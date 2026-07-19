"""A2A 1.0 HTTP+JSON adapter over durable Harness Runs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from harness.core.models import ArtifactStatus, Run, RunStatus
from harness.triggers.api import (
    authentication_error,
    bearer_secret,
    get_trigger_service,
)
from harness.triggers.service import AgentTriggerService, TriggerAuthenticationError

router = APIRouter(
    prefix="/a2a/agent-triggers/{trigger_id}",
    tags=["a2a"],
)

_TERMINAL_EVENTS = {
    "run.cancelled",
    "run.failed",
    "run.rejected",
    "run.succeeded",
    "run.timed_out",
}


def _version(value: str | None) -> None:
    if value != "1.0":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "a2a_version_not_supported",
                "message": "A2A-Version 1.0 is required",
                "supportedVersions": ["1.0"],
            },
        )


def _prompt(body: dict[str, object]) -> tuple[str, str]:
    message_value = body.get("message")
    message = (
        cast(dict[str, object], message_value)
        if isinstance(message_value, dict)
        else None
    )
    if not isinstance(message, dict):
        raise HTTPException(status_code=422, detail={"code": "a2a_message_required"})
    message_id = message.get("messageId")
    parts_value = message.get("parts")
    if not isinstance(message_id, str) or not message_id:
        raise HTTPException(status_code=422, detail={"code": "a2a_message_id_required"})
    if not isinstance(parts_value, list):
        raise HTTPException(status_code=422, detail={"code": "a2a_parts_required"})
    parts = cast(list[object], parts_value)
    text: list[str] = []
    for part in parts:
        part_value = cast(dict[str, object], part) if isinstance(part, dict) else None
        text_value = part_value.get("text") if part_value is not None else None
        if not isinstance(text_value, str):
            raise HTTPException(
                status_code=415,
                detail={"code": "a2a_content_type_not_supported"},
            )
        text.append(text_value)
    prompt = "\n".join(text).strip()
    if not prompt:
        raise HTTPException(status_code=422, detail={"code": "a2a_text_required"})
    return message_id, prompt


def _state(status_value: RunStatus) -> str:
    return {
        RunStatus.WAITING_APPROVAL: "TASK_STATE_AUTH_REQUIRED",
        RunStatus.SUCCEEDED: "TASK_STATE_COMPLETED",
        RunStatus.FAILED: "TASK_STATE_FAILED",
        RunStatus.TIMED_OUT: "TASK_STATE_FAILED",
        RunStatus.CANCELLED: "TASK_STATE_CANCELED",
        RunStatus.REJECTED: "TASK_STATE_REJECTED",
    }.get(status_value, "TASK_STATE_WORKING")


async def _task(request: Request, run: Run) -> dict[str, object]:
    artifacts = await request.app.state.container.artifacts.list_for_run(
        run.tenant_id, run.run_id
    )
    value: dict[str, object] = {
        "id": run.run_id,
        "contextId": run.session_id,
        "status": {
            "state": _state(run.status),
            "timestamp": run.updated_at.isoformat(),
        },
        "createdAt": run.created_at.isoformat(),
        "lastModified": run.updated_at.isoformat(),
    }
    ready = [item for item in artifacts if item.status is ArtifactStatus.READY]
    if ready:
        value["artifacts"] = [
            {
                "artifactId": item.artifact_id,
                "name": item.name,
                "parts": [
                    {
                        "url": f"/v1/artifacts/{item.artifact_id}/content",
                        "mediaType": item.media_type,
                    }
                ],
            }
            for item in ready
        ]
    return {"task": value}


async def _authorized_run(
    service: AgentTriggerService,
    *,
    trigger_id: str,
    authorization: str,
    run_id: str,
) -> Run:
    try:
        return await service.run(
            trigger_id=trigger_id,
            secret=bearer_secret(authorization),
            run_id=run_id,
        )
    except TriggerAuthenticationError as error:
        raise authentication_error() from error


@router.get("/agent-card.json")
async def agent_card(trigger_id: str, request: Request) -> JSONResponse:
    service = get_trigger_service(request)
    trigger = await service.public_card(trigger_id)
    base = str(request.base_url).rstrip("/")
    endpoint = f"{base}/a2a/agent-triggers/{trigger_id}"
    return JSONResponse(
        {
            "name": trigger.name,
            "description": (
                f"Agent Studio deployment {trigger.agent_name} "
                f"in {trigger.environment.value}"
            ),
            "supportedInterfaces": [
                {
                    "url": endpoint,
                    "protocolBinding": "HTTP+JSON",
                    "protocolVersion": "1.0",
                }
            ],
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
                "extendedAgentCard": False,
            },
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer"}
            },
            "security": [{"bearer": []}],
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": [
                {
                    "id": trigger.agent_name,
                    "name": trigger.agent_name,
                    "description": "Execute the published Agent Studio deployment.",
                    "tags": ["agent-studio", trigger.environment.value],
                    "inputModes": ["text/plain"],
                    "outputModes": ["text/plain", "application/json"],
                }
            ],
        },
        media_type="application/a2a+json",
    )


@router.post("/message:send")
async def send_message(
    trigger_id: str,
    body: dict[str, object],
    background_tasks: BackgroundTasks,
    request: Request,
    authorization: Annotated[str, Header(alias="Authorization")],
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> JSONResponse:
    _version(a2a_version)
    message_id, prompt = _prompt(body)
    service = get_trigger_service(request)
    try:
        _invocation, run = await service.invoke(
            trigger_id=trigger_id,
            secret=bearer_secret(authorization),
            idempotency_key=f"a2a:{message_id}",
            prompt=prompt,
        )
    except TriggerAuthenticationError as error:
        raise authentication_error() from error
    container = request.app.state.container
    if container.auto_execute:
        background_tasks.add_task(container.worker.execute, run.tenant_id, run.run_id)
    return JSONResponse(await _task(request, run), media_type="application/a2a+json")


async def _stream_events(
    request: Request,
    run: Run,
    *,
    sequence: int = 0,
) -> AsyncIterator[str]:
    yield f"data: {json.dumps(await _task(request, run), separators=(',', ':'))}\n\n"
    terminal = run.status.is_terminal
    while not terminal:
        events = await request.app.state.container.observed_events.list_after(
            run.tenant_id, run.run_id, sequence
        )
        for event in events:
            sequence = event.sequence
            current = await request.app.state.container.runs.get(
                run.tenant_id, run.run_id
            )
            if event.type == "artifact.ready":
                payload = {
                    "artifactUpdate": {
                        "taskId": run.run_id,
                        "contextId": run.session_id,
                        "artifact": {
                            "artifactId": event.payload.get("artifact_id"),
                            "name": event.payload.get("name"),
                            "parts": [
                                {
                                    "url": (
                                        "/v1/artifacts/"
                                        f"{event.payload.get('artifact_id')}/content"
                                    ),
                                    "mediaType": event.payload.get("media_type"),
                                }
                            ],
                        },
                    }
                }
            else:
                payload = {
                    "statusUpdate": {
                        "taskId": run.run_id,
                        "contextId": run.session_id,
                        "status": {
                            "state": _state(current.status),
                            "timestamp": event.timestamp.isoformat(),
                        },
                    }
                }
            yield (
                f"id: {sequence}\n"
                f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            )
            if event.type in _TERMINAL_EVENTS:
                terminal = True
        if not terminal:
            await asyncio.sleep(0.05)


@router.post("/message:stream")
async def stream_message(
    trigger_id: str,
    body: dict[str, object],
    request: Request,
    authorization: Annotated[str, Header(alias="Authorization")],
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> StreamingResponse:
    _version(a2a_version)
    message_id, prompt = _prompt(body)
    service = get_trigger_service(request)
    try:
        _invocation, run = await service.invoke(
            trigger_id=trigger_id,
            secret=bearer_secret(authorization),
            idempotency_key=f"a2a:{message_id}",
            prompt=prompt,
        )
    except TriggerAuthenticationError as error:
        raise authentication_error() from error
    if request.app.state.container.auto_execute:
        asyncio.create_task(
            request.app.state.container.worker.execute(run.tenant_id, run.run_id)
        )
    return StreamingResponse(
        _stream_events(request, run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks/{run_id}")
async def get_task(
    trigger_id: str,
    run_id: str,
    request: Request,
    authorization: Annotated[str, Header(alias="Authorization")],
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> JSONResponse:
    _version(a2a_version)
    run = await _authorized_run(
        get_trigger_service(request),
        trigger_id=trigger_id,
        authorization=authorization,
        run_id=run_id,
    )
    return JSONResponse(await _task(request, run), media_type="application/a2a+json")


@router.post("/tasks/{run_id}:cancel")
async def cancel_task(
    trigger_id: str,
    run_id: str,
    request: Request,
    authorization: Annotated[str, Header(alias="Authorization")],
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> JSONResponse:
    _version(a2a_version)
    run = await _authorized_run(
        get_trigger_service(request),
        trigger_id=trigger_id,
        authorization=authorization,
        run_id=run_id,
    )
    cancelled = await request.app.state.container.runs.cancel(
        run.tenant_id, run.run_id
    )
    return JSONResponse(
        await _task(request, cancelled),
        media_type="application/a2a+json",
    )


@router.post("/tasks/{run_id}:subscribe")
async def subscribe_task(
    trigger_id: str,
    run_id: str,
    request: Request,
    authorization: Annotated[str, Header(alias="Authorization")],
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    _version(a2a_version)
    run = await _authorized_run(
        get_trigger_service(request),
        trigger_id=trigger_id,
        authorization=authorization,
        run_id=run_id,
    )
    if run.status.is_terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "a2a_task_not_subscribable"},
        )
    sequence = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        _stream_events(request, run, sequence=sequence),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
