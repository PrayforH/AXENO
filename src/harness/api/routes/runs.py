import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, status
from fastapi.responses import StreamingResponse

from harness.api.dependencies import (
    ApiContainer,
    Identity,
    ensure_permission,
    get_container,
    require_identity,
    require_owned_run,
    require_owned_session,
)
from harness.api.schemas import CreateRunRequest
from harness.core.models import Run

router = APIRouter(tags=["runs"])


@router.post(
    "/sessions/{session_id}/runs",
    response_model=Run,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    session_id: str,
    body: CreateRunRequest,
    background_tasks: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> Run:
    ensure_permission(identity, "tasks:write")
    await require_owned_session(container, identity, session_id)
    run_input: dict[str, object] = {"prompt": body.prompt}
    if body.input_artifact_ids:
        run_input["input_artifact_ids"] = list(body.input_artifact_ids)
    run = await container.runs.create(
        identity.tenant_id,
        session_id,
        idempotency_key,
        input=run_input,
    )
    if container.auto_execute:
        background_tasks.add_task(container.worker.execute, identity.tenant_id, run.run_id)
    return run


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Run:
    ensure_permission(identity, "tasks:read")
    return await require_owned_run(container, identity, run_id)


@router.post("/runs/{run_id}/cancel", response_model=Run)
async def cancel_run(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
) -> Run:
    ensure_permission(identity, "tasks:write")
    await require_owned_run(container, identity, run_id)
    return await container.runs.cancel(identity.tenant_id, run_id)


@router.get("/runs/{run_id}/events")
async def replay_events(
    run_id: str,
    identity: Annotated[Identity, Depends(require_identity)],
    container: Annotated[ApiContainer, Depends(get_container)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    ensure_permission(identity, "tasks:read")
    await require_owned_run(container, identity, run_id)
    after_sequence = int(last_event_id or "0")
    events = await container.observed_events.list_after(
        identity.tenant_id, run_id, after_sequence
    )

    async def stream() -> AsyncIterator[str]:
        for event in events:
            data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
            yield f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
