from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from harness.adapters.memory import (
    InMemoryEventBus,
    InMemoryEventRepository,
    InMemoryRunRepository,
)
from harness.application.events import EventService
from harness.core.models import Run, RunStatus
from harness.quota.service import QuotaService
from harness.reliability.controller import MaintenanceReaper, ReliabilityController
from harness.reliability.metrics import ReliabilityMetrics
from harness.reliability.models import IncidentStatus, ReaperOutcome
from harness.reliability.repositories import InMemoryReliabilityRepository

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
ACTIVE = (
    RunStatus.QUEUED,
    RunStatus.PROVISIONING,
    RunStatus.RUNNING,
    RunStatus.WAITING_APPROVAL,
    RunStatus.CANCELLING,
)


def run(status: RunStatus, *, suffix: str, updated_at: datetime) -> Run:
    return Run(
        run_id=f"run-{suffix}",
        session_id=f"session-{suffix}",
        tenant_id="tenant-a",
        status=status,
        idempotency_key=f"idem-{suffix}",
        created_at=updated_at,
        updated_at=updated_at,
    )


def controller(
    runs: InMemoryRunRepository,
    raw_events: InMemoryEventRepository,
    repository: InMemoryReliabilityRepository,
    *,
    quotas: QuotaService | None = None,
    maintenance: tuple[MaintenanceReaper, ...] = (),
    metrics: ReliabilityMetrics | None = None,
) -> ReliabilityController:
    return ReliabilityController(
        runs=runs,
        events=EventService(
            raw_events,
            InMemoryEventBus(),
            clock=lambda: NOW,
            id_generator=lambda prefix: f"{prefix}-{len(raw_events._items) + 1}",  # pyright: ignore[reportPrivateUsage]
        ),
        repository=repository,
        metrics=metrics or ReliabilityMetrics(),
        thresholds={status: 60 for status in ACTIVE},
        quotas=quotas,
        maintenance=maintenance,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_reaper_converges_all_active_states_without_touching_fresh_runs() -> None:
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    repository = InMemoryReliabilityRepository()
    for status in ACTIVE:
        await runs.add(
            run(status, suffix=status.value, updated_at=NOW - timedelta(seconds=61))
        )
    fresh = run(RunStatus.RUNNING, suffix="fresh", updated_at=NOW - timedelta(seconds=59))
    await runs.add(fresh)
    metrics = ReliabilityMetrics()

    reaped = await controller(runs, events, repository, metrics=metrics).process_once()

    assert reaped == 5
    for status in ACTIVE:
        stored = await runs.get("tenant-a", f"run-{status.value}")
        expected = (
            RunStatus.CANCELLED
            if status is RunStatus.CANCELLING
            else RunStatus.TIMED_OUT
        )
        assert stored.status is expected
        assert stored.fencing_token == 1
        recorded = await events.list_after("tenant-a", stored.run_id, 0)
        assert [item.type for item in recorded] == [f"run.{expected.value}"]
    assert (await runs.get("tenant-a", fresh.run_id)).status is RunStatus.RUNNING
    actions = await repository.list_reaper_actions("tenant-a", limit=20)
    assert len(actions) == 5
    assert all(item.outcome is ReaperOutcome.REAPED for item in actions)
    convergence, count = metrics.quantile(
        "harness_workflow_convergence_seconds",
        0.95,
        labels={"workflow": "run.cancel"},
    )
    assert convergence == 61
    assert count == 1


class FlakyQuotaRelease:
    def __init__(self) -> None:
        self.calls = 0

    async def release_subject(self, tenant_id: str, subject_id: str) -> int:
        del tenant_id, subject_id
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("injected quota outage")
        return 1


@pytest.mark.asyncio
async def test_terminal_side_effect_failure_is_leased_and_repaired_idempotently() -> None:
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    repository = InMemoryReliabilityRepository()
    await runs.add(
        run(RunStatus.RUNNING, suffix="repair", updated_at=NOW - timedelta(seconds=61))
    )
    quota = FlakyQuotaRelease()
    subject = controller(
        runs,
        events,
        repository,
        quotas=cast(QuotaService, quota),
    )

    assert await subject.process_once() == 0
    terminal = await runs.get("tenant-a", "run-repair")
    assert terminal.status is RunStatus.TIMED_OUT
    incident = await repository.get_incident_by_fingerprint(
        "tenant-a", "reaper-finalize:run-repair"
    )
    assert incident is not None and incident.status is IncidentStatus.OPEN

    assert await subject.process_once() == 1
    incident = await repository.get_incident_by_fingerprint(
        "tenant-a", "reaper-finalize:run-repair"
    )
    assert incident is not None and incident.status is IncidentStatus.RESOLVED
    assert incident.recovery_attempts == 1
    recorded = await events.list_after("tenant-a", "run-repair", 0)
    assert [item.type for item in recorded] == ["run.timed_out"]
    assert quota.calls == 2
    assert await subject.process_once() == 0


@pytest.mark.asyncio
async def test_recovery_claim_has_a_lease_fence() -> None:
    repository = InMemoryReliabilityRepository()
    from harness.reliability.models import ReliabilityIncident

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

    first = await repository.try_claim_incident(
        "tenant-a",
        "reaper-finalize:run-1",
        owner="worker-a",
        claimed_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    second = await repository.try_claim_incident(
        "tenant-a",
        "reaper-finalize:run-1",
        owner="worker-b",
        claimed_at=NOW + timedelta(seconds=1),
        lease_expires_at=NOW + timedelta(seconds=31),
    )

    assert first is not None and first.recovery_owner == "worker-a"
    assert second is None


@pytest.mark.asyncio
async def test_maintenance_failures_are_isolated_and_durable() -> None:
    runs = InMemoryRunRepository()
    events = InMemoryEventRepository()
    repository = InMemoryReliabilityRepository()

    async def broken() -> int:
        raise RuntimeError("injected")

    async def healthy() -> int:
        return 2

    subject = controller(
        runs,
        events,
        repository,
        maintenance=(
            MaintenanceReaper("broken", "sandbox", broken),
            MaintenanceReaper("healthy", "preview", healthy),
        ),
    )

    assert await subject.process_once() == 2
    actions = await repository.list_reaper_actions("tenant-a", limit=10)
    assert {item.reaper: item.outcome for item in actions} == {
        "broken": ReaperOutcome.FAILED,
        "healthy": ReaperOutcome.REAPED,
    }
    incidents = await repository.list_incidents(
        "platform", status=IncidentStatus.OPEN, limit=10
    )
    assert [item.fingerprint for item in incidents] == ["maintenance:broken"]
