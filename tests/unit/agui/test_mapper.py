from datetime import UTC, datetime

from harness.agui.mapper import map_harness_event
from harness.core.events import RunEvent


def event(event_type: str, payload: dict[str, object] | None = None, sequence: int = 1) -> RunEvent:
    return RunEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        sequence=sequence,
        type=event_type,
        timestamp=datetime.now(UTC),
        payload=payload or {},
    )


def test_maps_run_and_text_lifecycle_to_standard_events() -> None:
    started = map_harness_event(event("run.queued"))
    text = map_harness_event(event("message.delta", {"text": "hello"}, 2))
    finished = map_harness_event(event("run.succeeded", sequence=3))

    assert started[0].model_dump(by_alias=True)["type"] == "RUN_STARTED"
    assert text[0].model_dump(by_alias=True) == {
        "type": "TEXT_MESSAGE_CONTENT",
        "timestamp": None,
        "rawEvent": None,
        "messageId": "assistant-run-1",
        "delta": "hello",
    }
    assert finished[0].model_dump(by_alias=True)["type"] == "RUN_FINISHED"


def test_maps_tool_and_versioned_custom_events() -> None:
    tool = map_harness_event(
        event(
            "tool.request",
            {"tool_call_id": "tool-1", "name": "Read", "arguments": {"path": "a"}},
        )
    )
    approval = map_harness_event(event("approval.requested", {"approval_id": "approval-1"}))
    artifact = map_harness_event(event("artifact.ready", {"artifact_id": "artifact-1"}))

    assert [item.model_dump(by_alias=True)["type"] for item in tool] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
    ]
    assert approval[0].model_dump(by_alias=True)["name"] == "harness.approval.v1"
    assert artifact[0].model_dump(by_alias=True)["name"] == "harness.artifact.v1"
