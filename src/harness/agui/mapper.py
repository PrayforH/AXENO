"""Project durable Harness events into standard AG-UI events."""

import json
from collections.abc import Sequence

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from harness.core.events import RunEvent


def _custom(event: RunEvent, name: str) -> Sequence[BaseEvent]:
    return [CustomEvent(name=name, value=event.payload)]


def map_harness_event(event: RunEvent) -> Sequence[BaseEvent]:
    message_id = str(event.payload.get("message_id", f"assistant-{event.run_id}"))
    if event.type == "run.queued":
        return [RunStartedEvent(thread_id=event.session_id, run_id=event.run_id)]
    if event.type == "run.succeeded":
        return [RunFinishedEvent(thread_id=event.session_id, run_id=event.run_id)]
    if event.type in {"run.failed", "run.rejected", "run.timed_out"}:
        return [
            RunErrorEvent(
                message=str(event.payload.get("message", event.type)),
                code=str(event.payload.get("error_code", event.type.removeprefix("run."))),
            )
        ]
    if event.type == "message.start":
        return [TextMessageStartEvent(message_id=message_id, role="assistant")]
    if event.type == "message.delta":
        text = str(event.payload.get("text", ""))
        return [] if not text else [TextMessageContentEvent(message_id=message_id, delta=text)]
    if event.type == "message.completed":
        return [TextMessageEndEvent(message_id=message_id)]
    if event.type == "tool.request":
        tool_call_id = str(event.payload.get("tool_call_id", ""))
        return [
            ToolCallStartEvent(
                tool_call_id=tool_call_id,
                tool_call_name=str(event.payload.get("name", "")),
                parent_message_id=message_id,
            ),
            ToolCallArgsEvent(
                tool_call_id=tool_call_id,
                delta=json.dumps(event.payload.get("arguments", {}), separators=(",", ":")),
            ),
            ToolCallEndEvent(tool_call_id=tool_call_id),
        ]
    if event.type == "tool.result":
        return [
            ToolCallResultEvent(
                message_id=f"tool-result-{event.sequence}",
                tool_call_id=str(event.payload.get("tool_call_id", "")),
                content=json.dumps(event.payload, separators=(",", ":")),
                role="tool",
            )
        ]
    if event.type == "approval.requested":
        return _custom(event, "harness.approval.v1")
    if event.type.startswith("subagent."):
        return _custom(event, "harness.subagent.v1")
    if event.type.startswith("artifact.") or event.type == "workspace.archived":
        return _custom(event, "harness.artifact.v1")
    if event.type in {"runtime.result", "model.route.selected"}:
        return _custom(event, "harness.runtime.v1")
    if event.type.startswith("run."):
        return [
            StateSnapshotEvent(
                snapshot={
                    "runId": event.run_id,
                    "threadId": event.session_id,
                    "status": event.type.removeprefix("run."),
                    "sequence": event.sequence,
                }
            )
        ]
    return []
