from datetime import UTC, datetime

from harness.core.events import RunEvent
from harness.core.models import Run, RunStatus
from harness.studio.try_run import build_codex_loop

NOW = datetime.now(UTC)


def event(sequence: int, event_type: str, payload: dict[str, object]) -> RunEvent:
    return RunEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-1",
        sequence=sequence,
        type=event_type,
        timestamp=NOW,
        payload=payload,
    )


def test_codex_loop_marks_observed_failure_and_recovery_as_correction() -> None:
    run = Run(
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-1",
        status=RunStatus.SUCCEEDED,
        idempotency_key="key-1",
        created_at=NOW,
        updated_at=NOW,
        input={"prompt": "读取输入，失败后换一条安全路径并验证结果"},
    )
    loop = build_codex_loop(
        run,
        [
            event(1, "run.running", {}),
            event(2, "tool.request", {"name": "Read"}),
            event(3, "tool.result", {"name": "Read", "success": False, "error": "missing"}),
            event(4, "tool.request", {"name": "Glob"}),
            event(5, "tool.result", {"name": "Glob", "success": True}),
            event(6, "message.completed", {}),
            event(7, "run.succeeded", {}),
        ],
    )

    assert [stage.id for stage in loop] == [
        "plan",
        "tools",
        "correction",
        "verification",
        "result",
    ]
    assert loop[2].status == "completed"
    assert {item.event_type for item in loop[2].evidence} >= {
        "tool.result",
        "message.completed",
        "run.succeeded",
    }
    assert loop[3].status == "completed"
    assert loop[4].status == "completed"


def test_codex_loop_does_not_invent_correction_for_first_pass_success() -> None:
    run = Run(
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-1",
        status=RunStatus.SUCCEEDED,
        idempotency_key="key-1",
        created_at=NOW,
        updated_at=NOW,
        input={"prompt": "直接回答"},
    )
    loop = build_codex_loop(
        run,
        [event(1, "message.completed", {}), event(2, "run.succeeded", {})],
    )

    assert loop[1].status == "skipped"
    assert loop[2].status == "skipped"
    assert loop[2].evidence == ()
