from datetime import UTC, datetime

from harness.agui.routes import final_response_text, project_stream_event
from harness.core.events import RunEvent


def _event(event_type: str, sequence: int, **payload: object) -> RunEvent:
    return RunEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        sequence=sequence,
        type=event_type,
        timestamp=datetime(2026, 7, 21, tzinfo=UTC),
        payload=payload,
    )


def test_final_response_keeps_all_text_when_no_actions_run() -> None:
    events = [
        _event("message.delta", 1, text="第一段"),
        _event("message.delta", 2, text="第二段"),
        _event("run.succeeded", 3),
    ]

    assert final_response_text(events) == "第一段第二段"


def test_final_response_excludes_progress_commentary_before_last_action() -> None:
    events = [
        _event("message.delta", 1, text="我先检查工作区。"),
        _event("tool.request", 2, tool_name="Bash"),
        _event("tool.allowed", 3, tool_name="Bash"),
        _event("tool.result", 4, tool_name="Bash"),
        _event("message.delta", 5, text="检查完成："),
        _event("message.delta", 6, text="工作区正常。"),
        _event("workspace.archived", 7),
    ]

    assert final_response_text(events) == "检查完成：工作区正常。"


def test_live_projection_emits_only_final_response_then_artifact() -> None:
    events = [
        _event("run.queued", 1),
        _event("message.start", 2, message_id="progress"),
        _event("message.delta", 3, message_id="progress", text="我先生成文件。"),
        _event("message.completed", 4, message_id="progress"),
        _event("tool.request", 5, tool_call_id="publish-1", name="publish_artifact"),
        _event("tool.result", 6, tool_call_id="publish-1"),
        _event("message.start", 7, message_id="final"),
        _event("message.delta", 8, message_id="final", text="文件已经生成。"),
        _event("message.completed", 9, message_id="final"),
        _event(
            "artifact.ready",
            10,
            artifact_id="artifact-1",
            name="报告.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _event("run.succeeded", 11),
    ]

    queued = [
        item.model_dump(by_alias=True)
        for item in project_stream_event(events[0], events[:1])
    ]
    assert [item["type"] for item in queued] == [
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "ACTIVITY_SNAPSHOT",
    ]
    assert queued[1]["messageId"] == "assistant-run-1"

    progress_types = [
        item.model_dump(by_alias=True)["type"]
        for event in events[1:-1]
        for item in project_stream_event(event, events[: event.sequence])
    ]
    terminal = [
        item.model_dump(by_alias=True)
        for item in project_stream_event(events[-1], events)
    ]

    assert "TEXT_MESSAGE_CONTENT" not in progress_types
    assert "TOOL_CALL_START" not in [
        item.model_dump(by_alias=True)["type"]
        for item in project_stream_event(events[-2], events[:-1])
    ]
    terminal_types = [item["type"] for item in terminal]
    assert terminal_types == [
        "ACTIVITY_DELTA",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "RUN_FINISHED",
    ]
    assert terminal[1]["delta"] == "文件已经生成。"
    assert terminal[3]["parentMessageId"] == "assistant-run-1"


def test_live_projection_closes_started_message_before_run_error() -> None:
    queued = _event("run.queued", 1)
    failed = _event("run.failed", 2, message="模型调用失败")

    terminal = [
        item.model_dump(by_alias=True)
        for item in project_stream_event(failed, [queued, failed])
    ]

    assert [item["type"] for item in terminal] == [
        "ACTIVITY_DELTA",
        "TEXT_MESSAGE_END",
        "RUN_ERROR",
    ]
    assert terminal[1]["messageId"] == "assistant-run-1"
