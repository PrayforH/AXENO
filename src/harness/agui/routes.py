"""AG-UI agent endpoint and replay stream backed by Harness repositories."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from ag_ui.core import RunAgentInput, RunFinishedEvent, RunStartedEvent
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from harness.agui.mapper import map_harness_event
from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity

router = APIRouter(prefix="/agui", tags=["ag-ui"])


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
        while True:
            events = await container.events.list_after(
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
            latest = await container.runs.get(identity.tenant_id, run.run_id)
            if latest.status.is_terminal and not await container.events.list_after(
                identity.tenant_id, run.run_id, sequence
            ):
                break
            await asyncio.sleep(0.02)
        if worker_task is not None:
            await worker_task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/events")
async def stream_agui_events(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await container.runs.get(identity.tenant_id, run_id)
    raw_id = (last_event_id or "0").split(":", 1)[0]
    events = await container.events.list_after(identity.tenant_id, run_id, int(raw_id))

    async def stream() -> AsyncIterator[str]:
        for event in events:
            projected = map_harness_event(event)
            for index, item in enumerate(projected):
                event_id = (
                    str(event.sequence) if len(projected) == 1 else f"{event.sequence}:{index + 1}"
                )
                yield _encode_event(event_id, item)

    return StreamingResponse(stream(), media_type="text/event-stream")
