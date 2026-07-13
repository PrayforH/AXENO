import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from harness.adapters.memory import (
    InMemoryApprovalRepository,
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
)
from harness.application.approvals import ApprovalService
from harness.application.events import EventService
from harness.core.errors import ConflictError
from harness.core.models import ApprovalStatus, Run, RunStatus

NOW = datetime(2026, 7, 11, tzinfo=UTC)


def ids() -> Callable[[str], str]:
    counters: dict[str, int] = {}

    def generate(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    return generate


async def arrange(*, clock: Callable[[], datetime] = lambda: NOW):
    runs = InMemoryRunRepository()
    approvals = InMemoryApprovalRepository()
    events = InMemoryEventRepository()
    run = Run(
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        status=RunStatus.RUNNING,
        idempotency_key="idem-1",
        created_at=NOW,
        updated_at=NOW,
    )
    await runs.add(run)
    service = ApprovalService(
        runs=runs,
        approvals=approvals,
        events=EventService(events, InMemoryEventBus(), clock=clock, id_generator=ids()),
        clock=clock,
        id_generator=ids(),
        ttl=timedelta(minutes=5),
    )
    return service, runs, events


@pytest.mark.asyncio
async def test_approval_request_is_idempotent_and_approval_resumes_run() -> None:
    service, runs, events = await arrange()

    first = await service.request(
        tenant_id="tenant-a",
        run_id="run-1",
        tool_call_id="tool-1",
        reason="Write requires review",
    )
    repeated = await service.request(
        tenant_id="tenant-a",
        run_id="run-1",
        tool_call_id="tool-1",
        reason="Write requires review",
    )
    approved = await service.decide(
        tenant_id="tenant-a",
        approval_id=first.approval_id,
        decision=ApprovalStatus.APPROVED,
    )

    assert repeated.approval_id == first.approval_id
    assert approved.status is ApprovalStatus.APPROVED
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.RUNNING
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert [event.type for event in emitted] == [
        "approval.requested",
        "run.waiting_approval",
        "approval.approved",
        "run.running",
    ]


@pytest.mark.asyncio
async def test_rejection_emits_structured_tool_error_and_stops_run() -> None:
    service, runs, events = await arrange()
    approval = await service.request(
        tenant_id="tenant-a",
        run_id="run-1",
        tool_call_id="tool-1",
        reason="review",
    )

    rejected = await service.decide(
        tenant_id="tenant-a",
        approval_id=approval.approval_id,
        decision=ApprovalStatus.REJECTED,
    )

    assert rejected.status is ApprovalStatus.REJECTED
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.REJECTED
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert emitted[-2].type == "tool.result"
    assert emitted[-2].payload == {
        "tool_call_id": "tool-1",
        "is_error": True,
        "error": {"code": "approval_rejected", "message": "tool use rejected"},
    }


@pytest.mark.asyncio
async def test_expired_approval_cannot_execute() -> None:
    current = NOW

    def clock() -> datetime:
        return current

    service, _, _ = await arrange(clock=clock)
    approval = await service.request(
        tenant_id="tenant-a",
        run_id="run-1",
        tool_call_id="tool-1",
        reason="review",
    )
    current = NOW + timedelta(minutes=6)

    with pytest.raises(ConflictError, match="expired"):
        await service.decide(
            tenant_id="tenant-a",
            approval_id=approval.approval_id,
            decision=ApprovalStatus.APPROVED,
        )


@pytest.mark.asyncio
async def test_inline_approval_wakes_the_waiting_sdk_call_and_cleans_up() -> None:
    service, runs, events = await arrange()

    approval = await service.request(
        tenant_id="tenant-a",
        run_id="run-1",
        tool_call_id="tool-inline",
        reason="Bash requires review",
        inline=True,
    )

    assert service.has_inline_waiter(approval.approval_id)
    emitted = await events.list_after("tenant-a", "run-1", 0)
    assert emitted[0].type == "approval.requested"
    waiting = asyncio.create_task(service.wait_for_decision(approval.approval_id))
    await service.decide(
        tenant_id="tenant-a",
        approval_id=approval.approval_id,
        decision=ApprovalStatus.APPROVED,
    )

    assert await waiting is ApprovalStatus.APPROVED
    assert not service.has_inline_waiter(approval.approval_id)
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.RUNNING


@pytest.mark.asyncio
async def test_inline_rejection_wakes_the_sdk_call_with_rejected_status() -> None:
    service, runs, _ = await arrange()
    approval = await service.request(
        tenant_id="tenant-a",
        run_id="run-1",
        tool_call_id="tool-inline",
        reason="review",
        inline=True,
    )
    waiting = asyncio.create_task(service.wait_for_decision(approval.approval_id))

    await service.decide(
        tenant_id="tenant-a",
        approval_id=approval.approval_id,
        decision=ApprovalStatus.REJECTED,
    )

    assert await waiting is ApprovalStatus.REJECTED
    assert (await runs.get("tenant-a", "run-1")).status is RunStatus.REJECTED
