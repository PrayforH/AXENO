"""Recoverable Preview Deployment controller and TTL reaper."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from harness.core.errors import ConflictError, NotFoundError
from harness.quota.service import QuotaService
from harness.studio.preview_models import (
    PreviewDeployment,
    PreviewStatus,
    transition_preview,
)
from harness.studio.preview_queue import PreviewTask, PreviewTaskQueue
from harness.studio.preview_repositories import PreviewRepository

PreviewProvisioner = Callable[[PreviewDeployment], Awaitable[None]]


class PreviewProvisioningError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


async def _no_op_provisioner(_preview: PreviewDeployment) -> None:
    """G07 lifecycle hook; G08 replaces this with real isolated Preflight."""


class PreviewController:
    def __init__(
        self,
        *,
        repository: PreviewRepository,
        queue: PreviewTaskQueue,
        provisioner: PreviewProvisioner | None = None,
        heartbeat_seconds: float = 20,
        clock: Callable[[], datetime] | None = None,
        quotas: QuotaService | None = None,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("Preview heartbeat interval must be positive")
        self._repository = repository
        self._queue = queue
        self._provisioner = provisioner or _no_op_provisioner
        self._heartbeat_seconds = heartbeat_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._quotas = quotas

    async def process_once(self) -> PreviewDeployment | None:
        task = await self._queue.dequeue()
        if task is None:
            return None
        try:
            result = await self.reconcile(task.tenant_id, task.preview_id)
        except NotFoundError:
            # Redis can outlive a restored PostgreSQL snapshot. A task whose
            # authoritative Preview row no longer exists is stale, not retryable.
            await self._queue.acknowledge(task)
            return None
        except PreviewProvisioningError as error:
            try:
                result = await self._fail(task, error.error_code)
            except Exception:
                await self._queue.retry(task)
                raise
        except Exception:
            try:
                result = await self._fail(task, "preview_controller_failed")
            except Exception:
                await self._queue.retry(task)
                raise
        await self._queue.acknowledge(task)
        return result

    async def reconcile(self, tenant_id: str, preview_id: str) -> PreviewDeployment:
        current = await self._repository.get(tenant_id, preview_id)
        if current.status.is_terminal:
            return current
        if current.expires_at <= self._clock():
            return await self._move(current, PreviewStatus.EXPIRED)
        if current.status is PreviewStatus.CANCELLING:
            return await self._move(current, PreviewStatus.CANCELLED)
        if current.status is PreviewStatus.QUEUED:
            current = await self._move(current, PreviewStatus.PROVISIONING)
        if current.status is PreviewStatus.PROVISIONING:
            try:
                await self._provision_with_heartbeat(current)
            except PreviewProvisioningError as error:
                latest = await self._repository.get(tenant_id, preview_id)
                if latest.status.is_terminal:
                    return latest
                return await self._move(latest, PreviewStatus.FAILED, error_code=error.error_code)
            latest = await self._repository.get(tenant_id, preview_id)
            if latest.expires_at <= self._clock():
                return await self._move(latest, PreviewStatus.EXPIRED)
            if latest.status is PreviewStatus.CANCELLING:
                return await self._move(latest, PreviewStatus.CANCELLED)
            if latest.status is PreviewStatus.PROVISIONING:
                return await self._move(latest, PreviewStatus.READY)
            return latest
        return current

    async def _provision_with_heartbeat(self, current: PreviewDeployment) -> None:
        task = PreviewTask(tenant_id=current.tenant_id, preview_id=current.preview_id)
        stopped = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=self._heartbeat_seconds)
                    return
                except TimeoutError:
                    await self._queue.extend_lease(task)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            await self._provisioner(current)
        finally:
            stopped.set()
            await heartbeat_task

    async def reap_expired(self, *, limit: int = 100) -> int:
        due = await self._repository.list_expired_active(self._clock(), limit=limit)
        count = 0
        for preview in due:
            current = await self._repository.get(preview.tenant_id, preview.preview_id)
            if current.status.is_terminal or current.expires_at > self._clock():
                continue
            try:
                result = await self._move(current, PreviewStatus.EXPIRED)
            except ConflictError:
                continue
            if result.status is PreviewStatus.EXPIRED:
                count += 1
        return count

    async def _fail(self, task: PreviewTask, error_code: str) -> PreviewDeployment:
        current = await self._repository.get(task.tenant_id, task.preview_id)
        if current.status.is_terminal:
            return current
        return await self._move(current, PreviewStatus.FAILED, error_code=error_code)

    async def _move(
        self,
        current: PreviewDeployment,
        target: PreviewStatus,
        *,
        error_code: str | None = None,
    ) -> PreviewDeployment:
        updated = current.model_copy(
            update={
                "status": transition_preview(current.status, target),
                "updated_at": self._clock(),
                "fencing_token": current.fencing_token + 1,
                "error_code": error_code,
            }
        )
        if not await self._repository.compare_and_set(current.status, updated):
            raise ConflictError(f"Preview changed during transition: {current.preview_id}")
        if updated.status.is_terminal and self._quotas is not None:
            await self._quotas.release_subject(
                updated.tenant_id,
                f"preview:{updated.requested_by}:{updated.idempotency_key}",
            )
        return updated
