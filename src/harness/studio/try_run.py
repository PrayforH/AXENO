"""Studio inline Try Run request and aggregated result contracts."""

from __future__ import annotations

from pydantic import Field

from harness.core.events import RunEvent
from harness.core.models import ApprovalRequest, Artifact, Run
from harness.studio.models import StudioModel


class CreateStudioTryRunRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    prompt: str = Field(min_length=1, max_length=100_000)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=200)


class StudioTryRunView(StudioModel):
    draft_id: str = Field(alias="draftId")
    draft_revision: int = Field(alias="draftRevision", ge=1)
    run: Run
    events: tuple[RunEvent, ...] = ()
    approvals: tuple[ApprovalRequest, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    final_text: str = Field(default="", alias="finalText")


def final_text(events: list[RunEvent]) -> str:
    return "".join(
        str(event.payload.get("text", ""))
        for event in events
        if event.type == "message.delta"
    )
