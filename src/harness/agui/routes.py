"""AG-UI agent endpoint and replay stream backed by Harness repositories."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from ag_ui.core import RunAgentInput, RunFinishedEvent, RunStartedEvent
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from harness.agui.activity import build_run_activity
from harness.agui.mapper import map_harness_event
from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
    require_owned_run,
)
from harness.core.models import ApprovalRequest, ApprovalStatus, Run

router = APIRouter(prefix="/agui", tags=["ag-ui"])

_TERMINAL_EVENT_TYPES = {
    "run.cancelled",
    "run.failed",
    "run.rejected",
    "run.succeeded",
    "run.timed_out",
}


class AguiThreadSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    session_id: str
    title: str
    agent_name: str
    agent_version: str
    status: str
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    pending_approval: ApprovalRequest | None = None


class AguiHistoryFunction(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    arguments: str


class AguiHistoryToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    type: Literal["function"] = "function"
    function: AguiHistoryFunction


class AguiHistoryMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    role: str
    content: str
    tool_calls: list[AguiHistoryToolCall] | None = Field(
        default=None, serialization_alias="toolCalls"
    )
    tool_call_id: str | None = Field(
        default=None, serialization_alias="toolCallId"
    )


class AguiThreadHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    messages: list[AguiHistoryMessage]


def _encode_event(event_id: str, event: object) -> str:
    data = json.dumps(
        event.model_dump(mode="json", by_alias=True, exclude_none=True),  # type: ignore[attr-defined]
        separators=(",", ":"),
    )
    return f"id: {event_id}\ndata: {data}\n\n"


@router.post("")
async def run_agui_agent(
    body: RunAgentInput,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    agent_name: Annotated[str, Query()],
    agent_version: Annotated[str, Query()],
) -> StreamingResponse:
    ensure_permission(identity, "tasks:write")
    run = await container.agui.create_run(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        agent_name=agent_name,
        agent_version=agent_version,
        request=body,
    )
    worker_task = (
        asyncio.create_task(container.worker.execute(identity.tenant_id, run.run_id))
        if container.auto_execute
        else None
    )

    async def stream() -> AsyncIterator[str]:
        sequence = 0
        terminal_event_seen = False
        while True:
            events = await container.observed_events.list_after(
                identity.tenant_id, run.run_id, sequence
            )
            for event in events:
                projected = map_harness_event(event)
                for index, item in enumerate(projected):
                    if isinstance(item, (RunStartedEvent, RunFinishedEvent)):
                        item = item.model_copy(
                            update={"thread_id": body.thread_id, "run_id": body.run_id}
                        )
                    event_id = (
                        str(event.sequence)
                        if len(projected) == 1
                        else f"{event.sequence}:{index + 1}"
                    )
                    yield _encode_event(event_id, item)
                sequence = event.sequence
                if event.type in _TERMINAL_EVENT_TYPES:
                    terminal_event_seen = True
            if terminal_event_seen:
                break
            await asyncio.sleep(0.02)
        if worker_task is not None:
            await worker_task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/threads", response_model=list[AguiThreadSummary])
async def list_agui_threads(
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AguiThreadSummary]:
    ensure_permission(identity, "tasks:read")
    bindings = await container.agui.list_bindings(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        limit=limit,
    )
    sessions = {
        binding.session_id: await container.sessions.get(
            identity.tenant_id, binding.session_id
        )
        for binding in bindings
    }
    runs = await container.runs.list_for_sessions(
        identity.tenant_id,
        [binding.session_id for binding in bindings],
        limit=max(limit * 20, 200),
    )
    runs_by_session: dict[str, list[Run]] = {}
    for run in runs:
        runs_by_session.setdefault(run.session_id, []).append(run)
    approvals = await container.approvals.list_for_runs(
        identity.tenant_id, [run.run_id for run in runs]
    )
    now = datetime.now(UTC)
    pending_by_run = {
        approval.run_id: approval
        for approval in approvals
        if approval.status is ApprovalStatus.PENDING and approval.expires_at > now
    }

    summaries: list[AguiThreadSummary] = []
    for binding in bindings:
        thread_runs = runs_by_session.get(binding.session_id, [])
        visible_runs = _visible_thread_runs(thread_runs)
        latest = max(
            visible_runs,
            key=lambda item: (item.updated_at, item.run_id),
            default=None,
        )
        pending = next(
            (
                pending_by_run[item.run_id]
                for item in sorted(
                    visible_runs,
                    key=lambda value: (value.updated_at, value.run_id),
                    reverse=True,
                )
                if item.run_id in pending_by_run
            ),
            None,
        )
        session = sessions[binding.session_id]
        prompts = _conversation_prompts(visible_runs)
        summaries.append(
            AguiThreadSummary(
                thread_id=binding.thread_id,
                session_id=binding.session_id,
                title=await container.agui.resolve_title(binding, prompts),
                agent_name=session.agent_name,
                agent_version=session.agent_version,
                status=(
                    "waiting_approval"
                    if pending is not None
                    else latest.status.value
                    if latest
                    else "idle"
                ),
                run_id=pending.run_id if pending is not None else latest.run_id if latest else None,
                created_at=binding.created_at,
                updated_at=latest.updated_at if latest is not None else binding.updated_at,
                pending_approval=pending,
            )
        )
    return sorted(
        summaries,
        key=lambda item: (
            item.pending_approval is not None,
            item.updated_at,
            item.thread_id,
        ),
        reverse=True,
    )[:limit]


@router.get(
    "/threads/{thread_id}/history",
    response_model=AguiThreadHistory,
    response_model_by_alias=True,
    response_model_exclude_none=True,
)
async def get_agui_thread_history(
    thread_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AguiThreadHistory:
    ensure_permission(identity, "tasks:read")
    binding = await container.agui.get_binding(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        thread_id=thread_id,
    )
    runs = await container.runs.list_for_sessions(
        identity.tenant_id, [binding.session_id], limit=200
    )
    runs = _visible_thread_runs(runs)
    messages: list[AguiHistoryMessage] = []
    for run in sorted(runs, key=lambda item: (item.created_at, item.run_id)):
        prompt = run.input.get("prompt")
        if isinstance(prompt, str) and prompt:
            messages.append(
                AguiHistoryMessage(
                    id=f"user-{run.run_id}", role="user", content=prompt
                )
            )
        events = await container.observed_events.list_after(
            identity.tenant_id, run.run_id, 0
        )
        response = "".join(
            str(event.payload.get("text", ""))
            for event in events
            if event.type == "message.delta"
        )
        artifacts = await container.artifacts.list_for_run(
            identity.tenant_id, run.run_id
        )
        activity = build_run_activity(events)
        activity_tool_call = (
            AguiHistoryToolCall(
                id=f"harness-activity-{run.run_id}",
                function=AguiHistoryFunction(
                    name="harness_run_activity",
                    arguments=json.dumps(
                        {"activity": activity}, separators=(",", ":")
                    ),
                ),
            )
            if activity is not None
            else None
        )
        artifact_tool_calls = [
            AguiHistoryToolCall(
                id=f"harness-artifact-{artifact.artifact_id}",
                function=AguiHistoryFunction(
                    name="harness_present_artifact",
                    arguments=json.dumps(
                        {
                            "artifact_id": artifact.artifact_id,
                            "run_id": artifact.run_id,
                            "name": artifact.name,
                            "media_type": artifact.media_type,
                            "size_bytes": artifact.size_bytes,
                            "sha256": artifact.sha256,
                            "status": artifact.status.value,
                        },
                        separators=(",", ":"),
                    ),
                ),
            )
            for artifact in artifacts
        ]
        tool_calls = [
            *([activity_tool_call] if activity_tool_call is not None else []),
            *artifact_tool_calls,
        ]
        if response or tool_calls:
            messages.append(
                AguiHistoryMessage(
                    id=f"assistant-{run.run_id}",
                    role="assistant",
                    content=response,
                    tool_calls=tool_calls or None,
                )
            )
        if activity_tool_call is not None:
            messages.append(
                AguiHistoryMessage(
                    id=f"tool-activity-{run.run_id}",
                    role="tool",
                    content=json.dumps(
                        {"status": "ready"}, separators=(",", ":")
                    ),
                    tool_call_id=activity_tool_call.id,
                )
            )
        messages.extend(
            AguiHistoryMessage(
                id=f"tool-artifact-{artifact.artifact_id}",
                role="tool",
                content=json.dumps({"status": "ready"}, separators=(",", ":")),
                tool_call_id=f"harness-artifact-{artifact.artifact_id}",
            )
            for artifact in artifacts
        )
    return AguiThreadHistory(thread_id=thread_id, messages=messages)


def _conversation_prompts(runs: list[Run]) -> list[str]:
    if not runs:
        return []
    latest = max(runs, key=lambda item: (item.created_at, item.run_id))
    stored = latest.input.get("conversation_prompts")
    stored_items = cast(list[object], stored) if isinstance(stored, list) else []
    if stored_items and all(isinstance(item, str) for item in stored_items):
        return [item for item in cast(list[str], stored_items) if item.strip()]
    return [
        prompt
        for item in sorted(runs, key=lambda value: (value.created_at, value.run_id))
        if isinstance((prompt := item.input.get("prompt")), str) and prompt.strip()
    ]


def _visible_thread_runs(runs: list[Run]) -> list[Run]:
    ordered = sorted(runs, key=lambda item: (item.created_at, item.run_id))
    if not ordered:
        return []
    latest = ordered[-1]
    stored = latest.input.get("conversation_prompts")
    stored_items = cast(list[object], stored) if isinstance(stored, list) else []
    if not (
        stored_items
        and all(isinstance(item, str) for item in stored_items)
        and latest.input.get("prompt") == stored_items[-1]
    ):
        return ordered

    prompts = [item for item in cast(list[str], stored_items) if item.strip()]
    selected: list[Run] = []
    cursor = 0
    for prompt in prompts[:-1]:
        match_index = next(
            (
                index
                for index in range(cursor, len(ordered) - 1)
                if ordered[index].input.get("prompt") == prompt
            ),
            None,
        )
        if match_index is None:
            return ordered
        selected.append(ordered[match_index])
        cursor = match_index + 1
    selected.append(latest)
    return selected


@router.post(
    "/threads/{thread_id}/runs/{client_run_id}/cancel",
    response_model=Run,
)
async def cancel_agui_run(
    thread_id: str,
    client_run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Run:
    ensure_permission(identity, "tasks:write")
    return await container.agui.cancel_run(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        thread_id=thread_id,
        client_run_id=client_run_id,
    )


@router.get("/runs/{run_id}/events")
async def stream_agui_events(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    ensure_permission(identity, "tasks:read")
    await require_owned_run(container, identity, run_id)
    raw_id = (last_event_id or "0").split(":", 1)[0]
    events = await container.observed_events.list_after(
        identity.tenant_id, run_id, int(raw_id)
    )

    async def stream() -> AsyncIterator[str]:
        for event in events:
            projected = map_harness_event(event)
            for index, item in enumerate(projected):
                event_id = (
                    str(event.sequence) if len(projected) == 1 else f"{event.sequence}:{index + 1}"
                )
                yield _encode_event(event_id, item)

    return StreamingResponse(stream(), media_type="text/event-stream")
