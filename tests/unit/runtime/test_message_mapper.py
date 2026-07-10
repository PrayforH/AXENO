from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
)

from harness.runtime.message_mapper import map_sdk_message


def test_maps_assistant_text_and_tool_use() -> None:
    message = AssistantMessage(
        content=[
            TextBlock(text="hello"),
            ToolUseBlock(id="tool-1", name="Read", input={"file_path": "a.txt"}),
        ],
        model="claude-sonnet-4-6",
    )

    events = map_sdk_message(message)

    assert [event.type for event in events] == ["message.delta", "tool.request"]
    assert events[0].payload == {"text": "hello"}
    assert events[1].payload == {
        "tool_call_id": "tool-1",
        "name": "Read",
        "arguments": {"file_path": "a.txt"},
    }


def test_maps_partial_text_and_subagent_lifecycle() -> None:
    partial = StreamEvent(
        uuid="event-1",
        session_id="session-1",
        parent_tool_use_id="agent-tool-1",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x"}},
    )

    events = map_sdk_message(partial)

    assert [event.type for event in events] == ["subagent.delta", "message.delta"]
    assert events[0].payload["parent_tool_use_id"] == "agent-tool-1"


def test_result_event_contains_cost_but_not_prompt_or_secret() -> None:
    result = ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=False,
        num_turns=1,
        session_id="claude-session",
        total_cost_usd=0.01,
    )

    events = map_sdk_message(result)

    assert events[0].type == "runtime.result"
    assert events[0].payload == {
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "session_id": "claude-session",
        "total_cost_usd": 0.01,
        "stop_reason": None,
    }
