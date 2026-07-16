from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from harness.application.events import EventService
from harness.core.models import Run, RunStatus
from harness.core.state_machine import transition
from harness.execution.credentials import CredentialBroker
from harness.quota.service import QuotaService
from harness.reliability.metrics import ReliabilityMetrics
from harness.reliability.models import (
    IncidentStatus,
    ReaperAction,
    ReaperOutcome,
    ReliabilityIncident,
)
from harness.reliability.probes import ReliabilityRunRepository
from harness.reliability.repositories import ReliabilityRepository


@dataclass(frozen=True)
class MaintenanceReaper:
    name: str
    resource_type: str
    callback: Callable[[], Awaitable[int]]


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ReliabilityController:
    def __init__(
        self,
        *,
        runs: ReliabilityRunRepository,
        events: EventService,
        repository: ReliabilityRepository,
        metrics: ReliabilityMetrics,
        thresholds: Mapping[RunStatus, int],
        maintenance: Sequence[MaintenanceReaper] = (),
        quotas: QuotaService | None = None,
        credentials: CredentialBroker | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
    ) -> None:
        required = {
            RunStatus.QUEUED,
            RunStatus.PROVISIONING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }
        if set(thresholds) != required or any(value < 1 for value in thresholds.values()):
            raise ValueError("stuck run thresholds must define every active state")
        self._runs = runs
        self._events = events
        self._repository = repository
        self._metrics = metrics
        self._thresholds = dict(thresholds)
        self._maintenance = tuple(maintenance)
        self._quotas = quotas
        self._credentials = credentials
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or _id
        self._worker_id = self._ids("reaper_worker")

    async def process_once(self, *, limit_per_status: int = 100) -> int:
        reaped = await self._repair_finalize_failures(limit=limit_per_status)
        reaped += await self.reap_stuck_runs(limit_per_status=limit_per_status)
        for maintenance in self._maintenance:
            reaped += await self._run_maintenance(maintenance)
        return reaped

    async def reap_stuck_runs(self, *, limit_per_status: int = 100) -> int:
        now = self._clock()
        total = 0
        for status, seconds in self._thresholds.items():
            cutoff = now - timedelta(seconds=seconds)
            candidates = await self._runs.list_stale(
                frozenset({status}), cutoff, limit=limit_per_status
            )
            unresolved = 0
            for candidate in candidates:
                outcome = await self._reap_run(candidate, cutoff)
                if outcome is ReaperOutcome.REAPED:
                    total += 1
                elif outcome is ReaperOutcome.FAILED:
                    unresolved += 1
            self._metrics.gauge(
                "harness_stuck_runs",
                unresolved,
                labels={"status": status.value},
            )
        return total

    async def _reap_run(self, candidate: Run, cutoff: datetime) -> ReaperOutcome:
        current = await self._runs.get(candidate.tenant_id, candidate.run_id)
        if current.status is not candidate.status or current.updated_at > cutoff:
            await self._record_action(
                candidate,
                expected=candidate.status.value,
                observed=current.status.value,
                outcome=ReaperOutcome.SKIPPED,
            )
            return ReaperOutcome.SKIPPED
        target = (
            RunStatus.CANCELLED
            if current.status is RunStatus.CANCELLING
            else RunStatus.TIMED_OUT
        )
        updated = current.model_copy(
            update={
                "status": transition(current.status, target),
                "updated_at": self._clock(),
                "fencing_token": current.fencing_token + 1,
                "error_code": f"stuck_{current.status.value}_reaped",
            }
        )
        if not await self._runs.compare_and_set(current.status, updated):
            latest = await self._runs.get(current.tenant_id, current.run_id)
            await self._record_action(
                current,
                expected=current.status.value,
                observed=latest.status.value,
                outcome=ReaperOutcome.SKIPPED,
            )
            return ReaperOutcome.SKIPPED
        try:
            await self._finalize_run(updated)
        except Exception as error:  # noqa: BLE001 - durable recovery evidence
            await self._record_action(
                current,
                expected=current.status.value,
                observed=updated.status.value,
                outcome=ReaperOutcome.FAILED,
                error_code=type(error).__name__,
            )
            await self._open_incident(
                tenant_id=updated.tenant_id,
                fingerprint=f"reaper-finalize:{updated.run_id}",
                kind="reaper_finalize_failed",
                severity="critical",
                resource_type="run",
                resource_id=updated.run_id,
                summary="Run 已收敛终态，但清理副作用需要重试",
                details={"errorCode": type(error).__name__},
            )
            return ReaperOutcome.FAILED
        await self._record_action(
            current,
            expected=current.status.value,
            observed=updated.status.value,
            outcome=ReaperOutcome.REAPED,
        )
        return ReaperOutcome.REAPED

    async def _repair_finalize_failures(self, *, limit: int) -> int:
        incidents = await self._repository.list_recovery_incidents(
            kind="reaper_finalize_failed", limit=limit
        )
        repaired = 0
        for incident in incidents:
            claimed_at = self._clock()
            claimed = await self._repository.try_claim_incident(
                incident.tenant_id,
                incident.fingerprint,
                owner=self._worker_id,
                claimed_at=claimed_at,
                lease_expires_at=claimed_at + timedelta(seconds=30),
            )
            if claimed is None or claimed.resource_id is None:
                continue
            run = await self._runs.get(claimed.tenant_id, claimed.resource_id)
            if not run.status.is_terminal:
                await self._resolve_incident(claimed.tenant_id, claimed.fingerprint)
                continue
            try:
                await self._finalize_run(run)
            except Exception as error:  # noqa: BLE001 - durable retry evidence
                failed_at = self._clock()
                await self._repository.upsert_incident(
                    claimed.model_copy(
                        update={
                            "details": {
                                **claimed.details,
                                "lastErrorCode": type(error).__name__,
                            },
                            "updated_at": failed_at,
                            "recovery_owner": None,
                            "recovery_lease_expires_at": failed_at,
                        }
                    )
                )
                await self._record_action(
                    run,
                    expected=run.status.value,
                    observed="finalize_failed",
                    outcome=ReaperOutcome.FAILED,
                    error_code=type(error).__name__,
                )
                continue
            await self._record_action(
                run,
                expected=run.status.value,
                observed="finalized",
                outcome=ReaperOutcome.REAPED,
            )
            await self._resolve_incident(claimed.tenant_id, claimed.fingerprint)
            repaired += 1
        return repaired

    async def _finalize_run(self, run: Run) -> None:
        existing = await self._events.list_after(run.tenant_id, run.run_id, 0)
        event_type = f"run.{run.status.value}"
        has_reaper_terminal_event = any(
            event.type == event_type and event.payload.get("reaper") == "stuck-run"
            for event in existing
        )
        if not has_reaper_terminal_event:
            await self._events.append(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                session_id=run.session_id,
                event_type=event_type,
                payload={
                    "error_code": run.error_code,
                    "reaper": "stuck-run",
                },
            )
        if self._quotas is not None:
            await self._quotas.release_subject(run.tenant_id, run.run_id)
        if self._credentials is not None:
            await self._credentials.revoke_run(run.tenant_id, run.run_id)

    async def _run_maintenance(self, item: MaintenanceReaper) -> int:
        try:
            count = await item.callback()
        except Exception as error:  # noqa: BLE001 - maintenance remains isolated
            now = self._clock()
            await self._repository.add_reaper_action(
                ReaperAction(
                    actionId=self._ids("reaper_action"),
                    tenantId="platform",
                    reaper=item.name,
                    resourceType=item.resource_type,
                    resourceId="batch",
                    expectedState="eligible",
                    observedState="error",
                    outcome=ReaperOutcome.FAILED,
                    errorCode=type(error).__name__,
                    occurredAt=now,
                )
            )
            self._metrics.increment(
                "harness_reaper_actions_total",
                labels={"reaper": item.name, "outcome": "failed"},
            )
            await self._open_incident(
                tenant_id="platform",
                fingerprint=f"maintenance:{item.name}",
                kind="maintenance_failed",
                severity="critical",
                resource_type=item.resource_type,
                resource_id=None,
                summary=f"{item.name} Reaper 执行失败",
                details={"errorCode": type(error).__name__},
            )
            return 0
        if count:
            await self._repository.add_reaper_action(
                ReaperAction(
                    actionId=self._ids("reaper_action"),
                    tenantId="platform",
                    reaper=item.name,
                    resourceType=item.resource_type,
                    resourceId="batch",
                    expectedState="eligible",
                    observedState="terminal",
                    outcome=ReaperOutcome.REAPED,
                    occurredAt=self._clock(),
                )
            )
            self._metrics.increment(
                "harness_reaper_actions_total",
                amount=count,
                labels={"reaper": item.name, "outcome": "reaped"},
            )
        await self._resolve_incident("platform", f"maintenance:{item.name}")
        return count

    async def _record_action(
        self,
        run: Run,
        *,
        expected: str,
        observed: str,
        outcome: ReaperOutcome,
        error_code: str | None = None,
    ) -> None:
        await self._repository.add_reaper_action(
            ReaperAction(
                actionId=self._ids("reaper_action"),
                tenantId=run.tenant_id,
                reaper="stuck-run",
                resourceType="run",
                resourceId=run.run_id,
                expectedState=expected,
                observedState=observed,
                outcome=outcome,
                errorCode=error_code,
                occurredAt=self._clock(),
            )
        )
        self._metrics.increment(
            "harness_reaper_actions_total",
            labels={"reaper": "stuck-run", "outcome": outcome.value},
        )

    async def _open_incident(
        self,
        *,
        tenant_id: str,
        fingerprint: str,
        kind: str,
        severity: str,
        resource_type: str,
        resource_id: str | None,
        summary: str,
        details: dict[str, str | int | float | bool | None],
    ) -> None:
        current = await self._repository.get_incident_by_fingerprint(
            tenant_id, fingerprint
        )
        now = self._clock()
        await self._repository.upsert_incident(
            ReliabilityIncident(
                tenantId=tenant_id,
                incidentId=current.incident_id if current else self._ids("incident"),
                fingerprint=fingerprint,
                kind=kind,
                severity=severity,
                status=IncidentStatus.OPEN,
                resourceType=resource_type,
                resourceId=resource_id,
                summary=summary,
                details=details,
                openedAt=current.opened_at if current else now,
                updatedAt=now,
            )
        )

    async def _resolve_incident(self, tenant_id: str, fingerprint: str) -> None:
        current = await self._repository.get_incident_by_fingerprint(
            tenant_id, fingerprint
        )
        if current is None or current.status is IncidentStatus.RESOLVED:
            return
        now = self._clock()
        await self._repository.upsert_incident(
            current.model_copy(
                update={
                    "status": IncidentStatus.RESOLVED,
                    "updated_at": now,
                    "resolved_at": now,
                    "recovery_owner": None,
                    "recovery_lease_expires_at": None,
                }
            )
        )
