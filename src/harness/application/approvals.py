"""Approval request and decision use cases."""

import asyncio
from datetime import timedelta

from harness.application.events import EventService
from harness.application.types import Clock, IdGenerator
from harness.core.errors import ConflictError
from harness.core.models import ApprovalRequest, ApprovalStatus, Run, RunStatus
from harness.core.ports import ApprovalRepository, RunRepository
from harness.core.state_machine import transition


class ApprovalService:
    def __init__(
        self,
        *,
        runs: RunRepository,
        approvals: ApprovalRepository,
        events: EventService,
        clock: Clock,
        id_generator: IdGenerator,
        ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._runs = runs
        self._approvals = approvals
        self._events = events
        self._clock = clock
        self._id_generator = id_generator
        self._ttl = ttl
        self._inline_waiters: dict[str, asyncio.Future[ApprovalStatus]] = {}

    def has_inline_waiter(self, approval_id: str) -> bool:
        return approval_id in self._inline_waiters

    def _register_inline_waiter(self, approval_id: str) -> None:
        if approval_id not in self._inline_waiters:
            self._inline_waiters[approval_id] = (
                asyncio.get_running_loop().create_future()
            )

    async def wait_for_decision(self, approval_id: str) -> ApprovalStatus:
        future = self._inline_waiters.get(approval_id)
        if future is None:
            raise ConflictError(f"inline approval waiter is not registered: {approval_id}")
        try:
            return await future
        finally:
            self._inline_waiters.pop(approval_id, None)

    async def _move(self, run: Run, status: RunStatus) -> Run:
        updated = run.model_copy(
            update={"status": transition(run.status, status), "updated_at": self._clock()}
        )
        if not await self._runs.compare_and_set(run.status, updated):
            raise ConflictError(f"run changed during approval: {run.run_id}")
        await self._events.append(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            session_id=run.session_id,
            event_type=f"run.{status.value}",
        )
        return updated

    async def request(
        self,
        *,
        tenant_id: str,
        run_id: str,
        tool_call_id: str,
        reason: str,
        message_id: str | None = None,
        inline: bool = False,
    ) -> ApprovalRequest:
        existing = await self._approvals.find_by_tool_call(tenant_id, run_id, tool_call_id)
        if existing is not None:
            if inline and existing.status is ApprovalStatus.PENDING:
                self._register_inline_waiter(existing.approval_id)
            return existing
        run = await self._runs.get(tenant_id, run_id)
        if run.status is not RunStatus.RUNNING:
            raise ConflictError("approval can only pause a running Run")
        now = self._clock()
        approval = ApprovalRequest(
            approval_id=self._id_generator("approval"),
            run_id=run_id,
            tenant_id=tenant_id,
            tool_call_id=tool_call_id,
            status=ApprovalStatus.PENDING,
            reason=reason,
            expires_at=now + self._ttl,
            created_at=now,
        )
        if inline:
            self._register_inline_waiter(approval.approval_id)
        await self._approvals.add(approval)
        payload = approval.model_dump(mode="json")
        if message_id is not None:
            payload["message_id"] = message_id
        await self._events.append(
            tenant_id=tenant_id,
            run_id=run_id,
            session_id=run.session_id,
            event_type="approval.requested",
            payload=payload,
        )
        await self._move(run, RunStatus.WAITING_APPROVAL)
        return approval

    async def decide(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        decision: ApprovalStatus,
    ) -> ApprovalRequest:
        if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise ConflictError("approval decision must be approved or rejected")
        current = await self._approvals.get(tenant_id, approval_id)
        if current.status is decision:
            return current
        if current.status is not ApprovalStatus.PENDING:
            raise ConflictError(f"approval is already {current.status.value}")
        if self._clock() >= current.expires_at:
            expired = current.model_copy(update={"status": ApprovalStatus.EXPIRED})
            await self._approvals.compare_and_set(ApprovalStatus.PENDING, expired)
            raise ConflictError("approval has expired")
        updated = current.model_copy(update={"status": decision})
        if not await self._approvals.compare_and_set(ApprovalStatus.PENDING, updated):
            raise ConflictError("approval changed while decision was applied")
        run = await self._runs.get(tenant_id, current.run_id)
        await self._events.append(
            tenant_id=tenant_id,
            run_id=run.run_id,
            session_id=run.session_id,
            event_type=f"approval.{decision.value}",
            payload={"approval_id": approval_id},
        )
        if decision is ApprovalStatus.APPROVED:
            await self._move(run, RunStatus.RUNNING)
        else:
            await self._events.append(
                tenant_id=tenant_id,
                run_id=run.run_id,
                session_id=run.session_id,
                event_type="tool.result",
                payload={
                    "tool_call_id": current.tool_call_id,
                    "is_error": True,
                    "error": {
                        "code": "approval_rejected",
                        "message": "tool use rejected",
                    },
                },
            )
            await self._move(run, RunStatus.REJECTED)
        waiter = self._inline_waiters.get(approval_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(decision)
        return updated
