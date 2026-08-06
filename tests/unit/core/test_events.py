from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from harness.core.events import RunEvent


def test_run_event_is_versioned_and_immutable() -> None:
    event = RunEvent(
        event_id="evt-1",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-1",
        sequence=1,
        type="run.started",
        timestamp=datetime.now(UTC),
        payload={"worker": "worker-1"},
    )

    assert event.schema_version == 1
    with pytest.raises(ValidationError):
        event.sequence = 2  # type: ignore[misc]


def test_run_event_sequence_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        RunEvent(
            event_id="evt-1",
            run_id="run-1",
            session_id="session-1",
            tenant_id="tenant-1",
            sequence=0,
            type="run.started",
            timestamp=datetime.now(UTC),
        )

