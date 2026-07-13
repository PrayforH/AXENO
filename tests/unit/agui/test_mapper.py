import json
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

    assert [item.model_dump(by_alias=True)["type"] for item in started] == [
        "RUN_STARTED",
        "ACTIVITY_SNAPSHOT",
    ]
    assert text[0].model_dump(by_alias=True) == {
        "type": "TEXT_MESSAGE_CONTENT",
        "timestamp": None,
        "rawEvent": None,
        "messageId": "assistant-run-1",
        "delta": "hello",
    }
    assert [item.model_dump(by_alias=True)["type"] for item in finished] == [
        "ACTIVITY_DELTA",
        "RUN_FINISHED",
    ]


def test_maps_tool_and_domain_events_to_tool_calls() -> None:
    tool = map_harness_event(
        event(
            "tool.request",
            {"tool_call_id": "tool-1", "name": "Read", "arguments": {"path": "a"}},
        )
    )
    approval = map_harness_event(
        event(
            "approval.requested",
            {
                "approval_id": "approval-1",
                "tool_call_id": "tool-1",
                "reason": "Write requires approval",
                "message_id": "assistant-approval-segment",
            },
        )
    )
    artifact = map_harness_event(
        event(
            "artifact.ready",
            {
                "artifact_id": "artifact-1",
                "name": "result.txt",
                "media_type": "text/plain",
                "size_bytes": 21,
            },
        )
    )

    assert [item.model_dump(by_alias=True)["type"] for item in tool] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "ACTIVITY_DELTA",
    ]
    assert [item.model_dump(by_alias=True)["type"] for item in approval] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "ACTIVITY_DELTA",
    ]
    assert approval[0].model_dump(by_alias=True)["toolCallName"] == (
        "harness_request_approval"
    )
    assert approval[0].model_dump(by_alias=True)["parentMessageId"] == (
        "assistant-approval-segment"
    )
    assert json.loads(approval[1].model_dump(by_alias=True)["delta"]) == {
        "approval_id": "approval-1",
        "run_id": "run-1",
        "tool_call_id": "tool-1",
        "reason": "Write requires approval",
    }
    assert artifact[0].model_dump(by_alias=True)["toolCallName"] == (
        "harness_present_artifact"
    )
    assert json.loads(artifact[1].model_dump(by_alias=True)["delta"]) == {
        "artifact_id": "artifact-1",
        "run_id": "run-1",
        "name": "result.txt",
        "media_type": "text/plain",
        "size_bytes": 21,
    }


def test_keeps_subagent_events_as_versioned_activity() -> None:
    activity = map_harness_event(event("subagent.started", {"name": "researcher"}))

    assert activity[0].model_dump(by_alias=True)["name"] == "harness.subagent.v1"
    assert activity[1].model_dump(by_alias=True)["type"] == "ACTIVITY_DELTA"


def test_maps_approval_decision_to_matching_tool_result() -> None:
    requested = map_harness_event(
        event("approval.requested", {"approval_id": "approval-1"}, sequence=2)
    )
    approved = map_harness_event(
        event("approval.approved", {"approval_id": "approval-1"}, sequence=3)
    )

    assert requested[0].model_dump(by_alias=True)["toolCallId"] == (
        "harness-approval-approval-1"
    )
    assert approved[0].model_dump(by_alias=True)["type"] == "TOOL_CALL_RESULT"
    assert approved[0].model_dump(by_alias=True)["toolCallId"] == (
        "harness-approval-approval-1"
    )
    assert approved[1].model_dump(by_alias=True)["type"] == "ACTIVITY_DELTA"


def test_artifact_projection_completes_its_tool_call() -> None:
    projected = map_harness_event(
        event("artifact.ready", {"artifact_id": "artifact-1", "name": "result.txt"})
    )

    assert [item.model_dump(by_alias=True)["type"] for item in projected] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "ACTIVITY_DELTA",
    ]
    assert projected[-2].model_dump(by_alias=True)["toolCallId"] == (
        "harness-artifact-artifact-1"
    )
