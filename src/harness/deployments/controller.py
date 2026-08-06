"""Deployment reconcile with fail-closed environment CAS."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from harness.deployments.models import (
    Deployment,
    DeploymentRoute,
    DeploymentSnapshot,
    DeploymentStatus,
)
from harness.deployments.queue import DeploymentTaskQueue
from harness.deployments.repositories import DeploymentRepository, EnvironmentRepository

DeployHook = Callable[[DeploymentSnapshot], Awaitable[None]]


async def _noop(_snapshot: DeploymentSnapshot) -> None:
    return None


class DeploymentController:
    def __init__(
        self,
        *,
        environments: EnvironmentRepository,
        deployments: DeploymentRepository,
        queue: DeploymentTaskQueue,
        deploy: DeployHook | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._environments = environments
        self._deployments = deployments
        self._queue = queue
        self._deploy = deploy or _noop
        self._clock = clock or (lambda: datetime.now(UTC))

    async def process_once(self) -> Deployment | None:
        task = await self._queue.dequeue()
        if task is None:
            return None
        try:
            result = await self.reconcile(task.tenant_id, task.deployment_id)
        except Exception:
            await self._queue.retry(task)
            raise
        if result.status.is_terminal:
            await self._queue.acknowledge(task)
        else:
            await self._queue.retry(task)
        return result

    async def drain_locally(
        self, tenant_id: str, deployment_id: str, *, max_steps: int = 8
    ) -> Deployment:
        """Converge one Deployment in explicit in-memory auto-execute mode."""

        for _step in range(max_steps):
            await self.process_once()
            current = await self._deployments.get(tenant_id, deployment_id)
            if current.status.is_terminal:
                return current
        raise TimeoutError("local Deployment auto-execution did not converge")

    async def reconcile(self, tenant_id: str, deployment_id: str) -> Deployment:
        current = await self._deployments.get(tenant_id, deployment_id)
        if current.status.is_terminal:
            return current
        if current.status is DeploymentStatus.QUEUED:
            return await self._move(current, DeploymentStatus.RECONCILING)
        snapshot = await self._deployments.get_snapshot(tenant_id, current.target_snapshot_id)
        try:
            environment = await self._environments.get(
                tenant_id,
                current.requested_by,
                current.agent_name,
                current.environment,
            )
            if environment.revision != current.expected_environment_revision:
                return await self._move(
                    current, DeploymentStatus.FAILED, error_code="environment_revision_conflict"
                )
            await self._deploy(snapshot)
            if current.canary_percent < 100:
                if environment.healthy_snapshot_id is None:
                    return await self._move(
                        current,
                        DeploymentStatus.FAILED,
                        error_code="canary_requires_healthy_version",
                    )
                if environment.healthy_snapshot_id == snapshot.snapshot_id:
                    routes = (DeploymentRoute(snapshotId=snapshot.snapshot_id, weight=100),)
                else:
                    routes = (
                        DeploymentRoute(
                            snapshotId=environment.healthy_snapshot_id,
                            weight=100 - current.canary_percent,
                        ),
                        DeploymentRoute(
                            snapshotId=snapshot.snapshot_id,
                            weight=current.canary_percent,
                        ),
                    )
                healthy = environment.healthy_snapshot_id
            else:
                routes = (DeploymentRoute(snapshotId=snapshot.snapshot_id, weight=100),)
                healthy = snapshot.snapshot_id
            updated_environment = environment.model_copy(
                update={
                    "revision": environment.revision + 1,
                    "routes": routes,
                    "healthy_snapshot_id": healthy,
                    "updated_at": self._clock(),
                }
            )
            if not await self._environments.compare_and_set(
                environment.revision, updated_environment
            ):
                return await self._move(
                    current, DeploymentStatus.FAILED, error_code="environment_revision_conflict"
                )
            return await self._move(current, DeploymentStatus.SUCCEEDED)
        except Exception:
            return await self._move(
                current, DeploymentStatus.FAILED, error_code="deployment_reconcile_failed"
            )

    async def _move(
        self, current: Deployment, status: DeploymentStatus, *, error_code: str | None = None
    ) -> Deployment:
        updated = current.model_copy(
            update={
                "status": status,
                "fencing_token": current.fencing_token + 1,
                "updated_at": self._clock(),
                "completed_at": self._clock() if status.is_terminal else None,
                "error_code": error_code,
            }
        )
        if not await self._deployments.compare_and_set(current.status, updated):
            return await self._deployments.get(current.tenant_id, current.deployment_id)
        return updated
