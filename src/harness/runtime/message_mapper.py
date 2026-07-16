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

_RESULT_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

_PROVIDER_ERROR_PREFIXES = (
    "failed to authenticate. api error:",
    "failed to connect to api:",
)
_SAFE_PROVIDER_ERROR_TEXT = (
    "The model provider rejected the request. Open run details for the status code."
)


def _safe_model_text(text: str) -> str:
    """Suppress SDK-generated provider diagnostics that can contain quota or request IDs."""
    if text.strip().lower().startswith(_PROVIDER_ERROR_PREFIXES):
        return _SAFE_PROVIDER_ERROR_TEXT
    return text


def result_subtype(message: ResultMessage) -> str:
    """Normalize gateways that report an error result with the SDK success subtype."""
    if not message.is_error:
        return message.subtype
    if message.api_error_status is not None and message.subtype in {"", "success"}:
        return f"api_error_{message.api_error_status}"
    return message.subtype or "provider_error"


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
                    "text": _safe_model_text(block.text),
                },
            )
            for block in message.content
            if isinstance(block, TextBlock)
        ]
    events: list[RuntimeEvent] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            events.append(
                RuntimeEvent(
                    type="message.delta", payload={"text": _safe_model_text(block.text)}
                )
            )
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
                            "text": _safe_model_text(str(typed_delta.get("text", ""))),
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
                    payload={
                        "text": _safe_model_text(str(typed_delta.get("text", "")))
                    },
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


def result_usage(message: ResultMessage) -> dict[str, int]:
    """Return only aggregate numeric usage fields safe for events and traces."""
    if not isinstance(message.usage, dict):
        return {}
    return {
        key: value
        for key in _RESULT_USAGE_KEYS
        if isinstance((value := message.usage.get(key)), int)
        and not isinstance(value, bool)
        and value >= 0
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
            type="subagent.updated",
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
                else "subagent.updated"
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
                    "subtype": result_subtype(message),
                    "is_error": message.is_error,
                    "num_turns": message.num_turns,
                    "session_id": message.session_id,
                    "total_cost_usd": message.total_cost_usd,
                    "stop_reason": message.stop_reason,
                    "duration_ms": message.duration_ms,
                    "duration_api_ms": message.duration_api_ms,
                    "usage": result_usage(message),
                },
            )
        ]
    if isinstance(message, SystemMessage):
        task_event = _map_task_message(message)
        if task_event is not None:
            return [task_event]
        if message.subtype not in {"init", "status"}:
            return []
        safe: dict[str, Any] = {"subtype": message.subtype}
        for key in ("session_id", "status"):
            if key in message.data and isinstance(message.data[key], (str, int, float, bool)):
                safe[key] = message.data[key]
        if message.subtype == "init":
            tools = message.data.get("tools")
            if isinstance(tools, list):
                safe["tools"] = [
                    tool for tool in cast(list[object], tools) if isinstance(tool, str)
                ]
            servers = message.data.get("mcp_servers")
            if isinstance(servers, list):
                safe_servers: list[dict[str, str]] = []
                for raw_server in cast(list[object], servers):
                    if not isinstance(raw_server, dict):
                        continue
                    server = cast(dict[object, object], raw_server)
                    safe_server = {
                        key: value
                        for key in ("name", "status")
                        if isinstance((value := server.get(key)), str)
                    }
                    safe_servers.append(safe_server)
                safe["mcp_servers"] = safe_servers
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
