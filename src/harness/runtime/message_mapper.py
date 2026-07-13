"""Map Claude Agent SDK messages into stable Harness events."""

from typing import Any, cast

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from harness.runtime.base import RuntimeEvent


def _safe_tool_result_content(content: object) -> object:
    """Hide Claude SDK coordination metadata while preserving normal tool output."""
    rendered = repr(content).lower()
    if "tool result is internal metadata" in rendered and (
        "agentid" in rendered or "output_file" in rendered
    ):
        return "[Internal tool metadata omitted]"
    return content


def _map_assistant(message: AssistantMessage) -> list[RuntimeEvent]:
    if message.parent_tool_use_id is not None:
        return [
            RuntimeEvent(
                type="subagent.delta",
                payload={
                    "parent_tool_use_id": message.parent_tool_use_id,
                    "text": block.text,
                },
            )
            for block in message.content
            if isinstance(block, TextBlock)
        ]
    events: list[RuntimeEvent] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            events.append(RuntimeEvent(type="message.delta", payload={"text": block.text}))
        elif isinstance(block, ToolUseBlock):
            events.append(
                RuntimeEvent(
                    type="tool.request",
                    payload={
                        "tool_call_id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                    },
                )
            )
        elif isinstance(block, ToolResultBlock):
            events.append(
                RuntimeEvent(
                    type="tool.result",
                    payload={
                        "tool_call_id": block.tool_use_id,
                        "content": _safe_tool_result_content(block.content),
                        "is_error": bool(block.is_error),
                    },
                )
            )
    return events


def _map_stream(message: StreamEvent) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    event = message.event
    delta = event.get("delta", {})
    if message.parent_tool_use_id is not None:
        if isinstance(delta, dict):
            typed_delta = cast(dict[str, Any], delta)
            if typed_delta.get("type") == "text_delta":
                return [
                    RuntimeEvent(
                        type="subagent.delta",
                        payload={
                            "parent_tool_use_id": message.parent_tool_use_id,
                            "text": str(typed_delta.get("text", "")),
                        },
                    )
                ]
        return []
    event_type = event.get("type")
    if event_type == "message_start":
        events.append(RuntimeEvent(type="message.start"))
    elif event_type == "message_stop":
        events.append(RuntimeEvent(type="message.completed"))
    if isinstance(delta, dict):
        typed_delta = cast(dict[str, Any], delta)
        if typed_delta.get("type") == "text_delta":
            events.append(
                RuntimeEvent(
                    type="message.delta",
                    payload={"text": str(typed_delta.get("text", ""))},
                )
            )
    return events


def _task_usage(usage: object) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    typed = cast(dict[str, Any], usage)
    return {
        key: int(typed[key])
        for key in ("total_tokens", "tool_uses", "duration_ms")
        if isinstance(typed.get(key), int)
    }


def _map_task_message(message: SystemMessage) -> RuntimeEvent | None:
    if isinstance(message, TaskStartedMessage):
        return RuntimeEvent(
            type="subagent.started",
            payload={
                "task_id": message.task_id,
                "description": message.description,
                "status": "running",
                "parent_tool_use_id": message.tool_use_id,
                "task_type": message.task_type,
            },
        )
    if isinstance(message, TaskProgressMessage):
        return RuntimeEvent(
            type="subagent.progress",
            payload={
                "task_id": message.task_id,
                "description": message.description,
                "status": "running",
                "parent_tool_use_id": message.tool_use_id,
                "last_tool_name": message.last_tool_name,
                "usage": _task_usage(message.usage),
            },
        )
    if isinstance(message, TaskNotificationMessage):
        return RuntimeEvent(
            type=(
                "subagent.completed"
                if message.status == "completed"
                else "subagent.failed"
            ),
            payload={
                "task_id": message.task_id,
                "status": message.status,
                "summary": message.summary,
                "parent_tool_use_id": message.tool_use_id,
                "usage": _task_usage(message.usage),
            },
        )
    if isinstance(message, TaskUpdatedMessage):
        status = message.status
        if status is None and isinstance(message.patch.get("status"), str):
            status = message.patch["status"]
        terminal = status in {"completed", "failed", "killed"}
        return RuntimeEvent(
            type=(
                "subagent.completed"
                if status == "completed"
                else "subagent.failed"
                if terminal
                else "subagent.progress"
            ),
            payload={"task_id": message.task_id, "status": status or "running"},
        )
    return None


def map_sdk_message(message: object) -> list[RuntimeEvent]:
    if isinstance(message, AssistantMessage):
        return _map_assistant(message)
    if isinstance(message, StreamEvent):
        return _map_stream(message)
    if isinstance(message, ResultMessage):
        return [
            RuntimeEvent(
                type="runtime.result",
                payload={
                    "subtype": message.subtype,
                    "is_error": message.is_error,
                    "num_turns": message.num_turns,
                    "session_id": message.session_id,
                    "total_cost_usd": message.total_cost_usd,
                    "stop_reason": message.stop_reason,
                },
            )
        ]
    if isinstance(message, SystemMessage):
        task_event = _map_task_message(message)
        if task_event is not None:
            return [task_event]
        safe: dict[str, Any] = {"subtype": message.subtype}
        for key in ("session_id", "status"):
            if key in message.data and isinstance(message.data[key], (str, int, float, bool)):
                safe[key] = message.data[key]
        return [RuntimeEvent(type="runtime.system", payload=safe)]
    if isinstance(message, UserMessage) and isinstance(message.content, list):
        events: list[RuntimeEvent] = []
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                events.append(
                    RuntimeEvent(
                        type="tool.result",
                        payload={
                            "tool_call_id": block.tool_use_id,
                            "content": _safe_tool_result_content(block.content),
                            "is_error": bool(block.is_error),
                        },
                    )
                )
        return events
    return []
