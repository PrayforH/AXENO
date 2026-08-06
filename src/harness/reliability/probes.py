from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Protocol

from harness.core.models import ApprovalStatus, Run, RunStatus
from harness.core.ports import ApprovalRepository, RunRepository
from harness.execution.credentials import CredentialLeaseMaintenance
from harness.lifecycle.models import LifecycleJobStatus
from harness.lifecycle.repositories import DataLifecycleRepository
from harness.reliability.models import CapacitySnapshot
from harness.studio.preview_repositories import PreviewRepository


class QueueStats(Protocol):
    async def stats(self) -> dict[str, int]: ...


class ReliabilityRunRepository(RunRepository, Protocol):
    async def list_for_tenant(self, tenant_id: str, *, limit: int) -> list[Run]: ...

    async def list_stale(
        self,
        statuses: frozenset[RunStatus],
        updated_at_or_before: datetime,
        *,
        limit: int,
    ) -> list[Run]: ...


InfrastructureFacts = Callable[
    [str], Awaitable[Mapping[str, int | None]]
]


async def _empty_facts(_tenant_id: str) -> Mapping[str, int | None]:
    return {}


class CapacityProbe:
    def __init__(
        self,
        *,
        runs: ReliabilityRunRepository,
        approvals: ApprovalRepository,
        previews: PreviewRepository,
        queue: QueueStats,
        lifecycle: DataLifecycleRepository,
        credentials: CredentialLeaseMaintenance | None,
        infrastructure_facts: InfrastructureFacts | None = None,
        max_rows: int = 10_000,
    ) -> None:
        self._runs = runs
        self._approvals = approvals
        self._previews = previews
        self._queue = queue
        self._lifecycle = lifecycle
        self._credentials = credentials
        self._infrastructure_facts = infrastructure_facts or _empty_facts
        self._max_rows = max_rows

    async def capture(
        self,
        tenant_id: str,
        *,
        snapshot_id: str,
        captured_at: datetime,
        stuck_counts: Mapping[str, int],
    ) -> CapacitySnapshot:
        runs = await self._runs.list_for_tenant(tenant_id, limit=self._max_rows)
        run_counts = Counter(item.status.value for item in runs)
        approvals = await self._approvals.list_for_runs(
            tenant_id, [item.run_id for item in runs]
        )
        pending_approvals = sum(
            item.status is ApprovalStatus.PENDING for item in approvals
        )
        previews = await self._previews.list_for_tenant(tenant_id)
        active_previews = sum(not item.status.is_terminal for item in previews)
        queue = await self._queue.stats()
        lifecycle = await self._lifecycle.list_jobs(tenant_id, limit=self._max_rows)
        lifecycle_backlog = sum(
            item.status
            in {
                LifecycleJobStatus.QUEUED,
                LifecycleJobStatus.RUNNING,
                LifecycleJobStatus.PARTIAL_FAILED,
                LifecycleJobStatus.FAILED,
            }
            for item in lifecycle
        )
        facts = await self._infrastructure_facts(tenant_id)
        credential_leases = (
            await self._credentials.active_lease_count()
            if self._credentials is not None
            else 0
        )
        return CapacitySnapshot(
            tenantId=tenant_id,
            snapshotId=snapshot_id,
            capturedAt=captured_at,
            queueReady=queue.get("ready", 0),
            queueProcessing=queue.get("processing", 0),
            runsByStatus=dict(run_counts),
            stuckRunsByStatus=dict(stuck_counts),
            activePreviews=active_previews,
            pendingApprovals=pending_approvals,
            activeSandboxes=facts.get("active_sandboxes"),
            databasePoolCheckedOut=facts.get("database_pool_checked_out"),
            artifactBytes=int(facts.get("artifact_bytes") or 0),
            snapshotBytes=int(facts.get("snapshot_bytes") or 0),
            lifecycleBacklog=lifecycle_backlog,
            credentialLeases=credential_leases,
        )
