from datetime import UTC, datetime
from typing import cast

import pytest

from harness.reliability.metrics import ReliabilityMetrics
from harness.reliability.models import (
    CapacitySnapshot,
    IncidentStatus,
    ReliabilityIncident,
    SloHealth,
)
from harness.reliability.probes import CapacityProbe
from harness.reliability.repositories import InMemoryReliabilityRepository
from harness.reliability.service import ReliabilityService

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


class StaticCapacityProbe:
    async def capture(
        self,
        tenant_id: str,
        *,
        snapshot_id: str,
        captured_at: datetime,
        stuck_counts: dict[str, int],
    ) -> CapacitySnapshot:
        return CapacitySnapshot(
            tenantId=tenant_id,
            snapshotId=snapshot_id,
            capturedAt=captured_at,
            queueReady=0,
            queueProcessing=0,
            runsByStatus={},
            stuckRunsByStatus=stuck_counts,
            activePreviews=0,
            pendingApprovals=0,
            artifactBytes=0,
            snapshotBytes=0,
            lifecycleBacklog=0,
            credentialLeases=0,
        )


@pytest.mark.asyncio
async def test_slo_reconciliation_does_not_resolve_reaper_incidents() -> None:
    repository = InMemoryReliabilityRepository()
    await repository.upsert_incident(
        ReliabilityIncident(
            tenantId="tenant-a",
            incidentId="incident-1",
            fingerprint="reaper-finalize:run-1",
            kind="reaper_finalize_failed",
            severity="critical",
            status=IncidentStatus.OPEN,
            resourceType="run",
            resourceId="run-1",
            summary="repair",
            openedAt=NOW,
            updatedAt=NOW,
        )
    )
    metrics = ReliabilityMetrics()
    metrics.observe(
        "harness_api_request_duration_seconds",
        0.8,
        labels={"operation": "run.create"},
    )
    counters: dict[str, int] = {}

    def ids(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"generated-{prefix}-{counters[prefix]}"

    service = ReliabilityService(
        repository,
        metrics,
        cast(CapacityProbe, StaticCapacityProbe()),
        clock=lambda: NOW,
        id_generator=ids,
    )

    overview = await service.overview("tenant-a")

    objectives = {item.metric: item for item in overview.objectives}
    assert objectives["run_create_p95"].health is SloHealth.BREACHED
    incidents = await repository.list_incidents(
        "tenant-a", status=IncidentStatus.OPEN, limit=10
    )
    assert {item.fingerprint for item in incidents} == {
        "reaper-finalize:run-1",
        "slo:run_create_p95",
    }
    assert (await repository.latest_capacity("tenant-a")) == overview.capacity
    assert await repository.latest_capacity("tenant-b") is None
