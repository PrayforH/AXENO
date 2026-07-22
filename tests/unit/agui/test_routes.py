from datetime import UTC, datetime

from harness.agui.routes import _final_response_text
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

    assert _final_response_text(events) == "第一段第二段"


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

    assert _final_response_text(events) == "检查完成：工作区正常。"
