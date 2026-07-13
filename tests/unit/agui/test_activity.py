from datetime import UTC, datetime

from harness.agui.activity import activity_projection
from harness.core.events import RunEvent

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def event(
    event_type: str,
    payload: dict[str, object] | None = None,
    sequence: int = 1,
) -> RunEvent:
    return RunEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        sequence=sequence,
        type=event_type,
        timestamp=NOW,
        payload=payload or {},
    )


def test_run_queued_creates_one_stable_activity_snapshot() -> None:
    projected = activity_projection(event("run.queued"))

    assert len(projected) == 1
    dumped = projected[0].model_dump(by_alias=True)
    assert dumped["type"] == "ACTIVITY_SNAPSHOT"
    assert dumped["messageId"] == "activity-run-1"
    assert dumped["activityType"] == "harness.run.v1"
    assert dumped["content"] == {
        "run_id": "run-1",
        "status": "queued",
        "started_at": "2026-07-13T00:00:00Z",
        "items": [
            {
                "id": "event-1",
                "event_type": "run.queued",
                "kind": "run",
                "status": "queued",
                "title": "任务已加入队列",
                "summary": None,
                "timestamp": "2026-07-13T00:00:00Z",
                "sequence": 1,
                "metadata": {},
            }
        ],
        "metrics": {},
    }


def test_model_and_result_append_safe_activity_deltas() -> None:
    model = activity_projection(
        event(
            "model.route.selected",
            {
                "provider": "new-api",
                "model": "shdata-glm",
                "used_fallback": False,
                "credential": "never-show",
            },
            2,
        )
    )[0].model_dump(by_alias=True)
    result = activity_projection(
        event(
            "runtime.result",
            {
                "num_turns": 2,
                "total_cost_usd": 0.02,
                "stop_reason": "end_turn",
                "session_id": "private-session",
            },
            3,
        )
    )[0].model_dump(by_alias=True)

    assert model["type"] == "ACTIVITY_DELTA"
    assert model["messageId"] == "activity-run-1"
    assert model["patch"][0]["path"] == "/items/-"
    assert model["patch"][0]["value"]["metadata"] == {
        "provider": "new-api",
        "model": "shdata-glm",
        "used_fallback": False,
    }
    assert result["patch"][1] == {
        "op": "replace",
        "path": "/status",
        "value": "succeeded",
    }
    metric_values = {item["path"]: item["value"] for item in result["patch"][2:]}
    assert metric_values == {
        "/metrics/turns": 2,
        "/metrics/cost_usd": 0.02,
        "/metrics/stop_reason": "end_turn",
    }
    assert "never-show" not in repr(model)
    assert "private-session" not in repr(result)


def test_suppresses_token_and_thinking_noise() -> None:
    assert activity_projection(event("message.delta", {"text": "token"})) == []
    assert (
        activity_projection(
            event("runtime.system", {"subtype": "thinking_tokens"})
        )
        == []
    )


def test_subagent_activity_keeps_parent_and_summary() -> None:
    projected = activity_projection(
        event(
            "subagent.completed",
            {
                "task_id": "task-1",
                "parent_tool_use_id": "tool-1",
                "summary": "Found two issues",
                "status": "completed",
                "secret": "never-show",
            },
            4,
        )
    )[0].model_dump(by_alias=True)

    item = projected["patch"][0]["value"]
    assert item["kind"] == "subagent"
    assert item["summary"] == "Found two issues"
    assert item["metadata"] == {
        "task_id": "task-1",
        "parent_tool_use_id": "tool-1",
    }
    assert "never-show" not in repr(projected)
