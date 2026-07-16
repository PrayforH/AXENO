from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.core.models import Run, RunStatus, Session
from harness.runtime.base import RuntimeContext
from harness.runtime.fake import FakeRuntime

NOW = datetime(2026, 7, 13, tzinfo=UTC)


@pytest.mark.asyncio
async def test_slow_marker_uses_injected_delay_for_local_cancel_validation(
    tmp_path: Path,
) -> None:
    delays: list[float] = []

    async def delay(seconds: float) -> None:
        delays.append(seconds)

    runtime = FakeRuntime(delay=delay)
    context = RuntimeContext(
        run=Run(
            run_id="run-1",
            session_id="session-1",
            tenant_id="local",
            status=RunStatus.RUNNING,
            idempotency_key="slow-runtime",
            created_at=NOW,
            updated_at=NOW,
            input={"prompt": "[slow] verify cancel"},
        ),
        session=Session(
            session_id="session-1",
            tenant_id="local",
            user_id="developer",
            agent_name="echo-agent",
            agent_version="0.1.0",
            created_at=NOW,
        ),
        workspace=tmp_path,
    )

    events = [event async for event in runtime.execute(context)]

    assert delays == [3.0]
    assert [event.type for event in events] == [
        "message.start",
        "message.delta",
        "message.completed",
    ]
