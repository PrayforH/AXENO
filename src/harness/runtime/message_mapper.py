"""Map Claude Agent SDK messages into stable Harness events."""

from typing import Any, cast

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from harness.runtime.base import RuntimeEvent


def _map_assistant(message: AssistantMessage) -> list[RuntimeEvent]:
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
                        "content": block.content,
                        "is_error": bool(block.is_error),
                    },
                )
            )
    return events


def _map_stream(message: StreamEvent) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    if message.parent_tool_use_id is not None:
        events.append(
            RuntimeEvent(
                type="subagent.delta",
                payload={"parent_tool_use_id": message.parent_tool_use_id},
            )
        )
    event = message.event
    delta = event.get("delta", {})
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
        safe: dict[str, Any] = {"subtype": message.subtype}
        if "session_id" in message.data:
            safe["session_id"] = str(message.data["session_id"])
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
                            "content": block.content,
                            "is_error": bool(block.is_error),
                        },
                    )
                )
        return events
    return []
