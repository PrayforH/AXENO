"""AG-UI event stream backed entirely by durable Harness repositories."""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

from harness.agui.mapper import map_harness_event
from harness.api.dependencies import ApiContainer, Identity, get_container, require_identity

router = APIRouter(prefix="/agui", tags=["ag-ui"])


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
                data = json.dumps(
                    item.model_dump(mode="json", by_alias=True), separators=(",", ":")
                )
                yield f"id: {event_id}\ndata: {data}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
