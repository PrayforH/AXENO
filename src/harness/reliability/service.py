from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from harness.reliability.metrics import ReliabilityMetrics
from harness.reliability.models import (
    CapacitySnapshot,
    IncidentStatus,
    ReliabilityIncident,
    ReliabilityOverview,
    SloHealth,
    SloObjective,
)
from harness.reliability.probes import CapacityProbe
from harness.reliability.repositories import ReliabilityRepository


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ReliabilityService:
    def __init__(
        self,
        repository: ReliabilityRepository,
        metrics: ReliabilityMetrics,
        capacity: CapacityProbe,
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
    ) -> None:
        self.repository = repository
        self.metrics = metrics
        self._capacity = capacity
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or _id

    async def overview(self, tenant_id: str) -> ReliabilityOverview:
        stuck_counts = {
            status: int(self.metrics.count("harness_stuck_runs", labels={"status": status}))
            for status in (
                "queued",
                "provisioning",
                "running",
                "waiting_approval",
                "cancelling",
            )
        }
        capacity = await self._capacity.capture(
            tenant_id,
            snapshot_id=self._ids("capacity"),
            captured_at=self._clock(),
            stuck_counts=stuck_counts,
        )
        await self.repository.save_capacity(capacity)
        self._publish_capacity(capacity)
        objectives = self.objectives()
        await self._reconcile_alerts(tenant_id, objectives, capacity)
        return ReliabilityOverview(
            generatedAt=self._clock(),
            objectives=objectives,
            capacity=capacity,
            incidents=tuple(
                await self.repository.list_incidents(
                    tenant_id, status=None, limit=100
                )
            ),
            recentReaperActions=tuple(
                await self.repository.list_reaper_actions(tenant_id, limit=100)
            ),
        )

    def objectives(self) -> tuple[SloObjective, ...]:
        api_create, api_create_count = self.metrics.quantile(
            "harness_api_request_duration_seconds",
            0.95,
            labels={"operation": "run.create"},
        )
        event_delay, event_count = self.metrics.quantile(
            "harness_event_visibility_delay_seconds", 0.95
        )
        queue_wait, queue_wait_count = self.metrics.quantile(
            "harness_run_stage_duration_seconds",
            0.95,
            labels={"stage": "queue_wait"},
        )
        runtime_first_event, runtime_first_event_count = self.metrics.quantile(
            "harness_run_stage_duration_seconds",
            0.95,
            labels={"stage": "runtime_first_event"},
        )
        runtime_first_text, runtime_first_text_count = self.metrics.quantile(
            "harness_run_stage_duration_seconds",
            0.95,
            labels={"stage": "runtime_first_text"},
        )
        cancel, cancel_count = self.metrics.quantile(
            "harness_workflow_convergence_seconds",
            0.95,
            labels={"workflow": "run.cancel"},
        )
        approval, approval_count = self.metrics.quantile(
            "harness_workflow_convergence_seconds",
            0.95,
            labels={"workflow": "approval.decide"},
        )
        downloads_ok = self.metrics.count(
            "harness_artifact_download_total", labels={"outcome": "success"}
        )
        downloads_failed = self.metrics.count(
            "harness_artifact_download_total", labels={"outcome": "failure"}
        )
        download_total = int(downloads_ok + downloads_failed)
        download_ratio = downloads_ok / download_total if download_total else None
        traces_ok = self.metrics.count(
            "harness_trace_terminal_total", labels={"completeness": "complete"}
        )
        traces_missing = self.metrics.count(
            "harness_trace_terminal_total", labels={"completeness": "missing"}
        )
        trace_total = int(traces_ok + traces_missing)
        trace_ratio = traces_ok / trace_total if trace_total else None
        return (
            self._latency(
                "run_create_p95",
                "Run 创建 P95",
                api_create,
                api_create_count,
                0.5,
                "api middleware",
            ),
            self._latency(
                "queue_wait_p95",
                "Queue Wait P95",
                queue_wait,
                queue_wait_count,
                1,
                "durable run lifecycle",
            ),
            self._latency(
                "runtime_first_event_p95",
                "首 Runtime Event P95",
                runtime_first_event,
                runtime_first_event_count,
                1.5,
                "worker runtime stream",
            ),
            self._latency(
                "runtime_first_text_p95",
                "首正文 P95",
                runtime_first_text,
                runtime_first_text_count,
                3,
                "worker runtime stream",
            ),
            self._latency(
                "event_visibility_p95",
                "Event 可见延迟 P95",
                event_delay,
                event_count,
                2,
                "durable event read",
            ),
            self._latency(
                "cancel_convergence_p95",
                "取消收敛 P95",
                cancel,
                cancel_count,
                3,
                "durable run lifecycle",
            ),
            self._latency(
                "approval_convergence_p95",
                "审批恢复 P95",
                approval,
                approval_count,
                10,
                "durable approval lifecycle",
            ),
            self._ratio(
                "artifact_download_success",
                "Artifact 下载成功率",
                download_ratio,
                download_total,
                0.999,
                "artifact API",
            ),
            self._ratio(
                "trace_completeness",
                "Trace 完整率",
                trace_ratio,
                trace_total,
                0.99,
                "terminal quality hook",
            ),
        )

    @staticmethod
    def _latency(
        metric: str,
        label: str,
        observed: float | None,
        count: int,
        target: float,
        source: str,
    ) -> SloObjective:
        health = (
            SloHealth.NO_DATA
            if observed is None
            else SloHealth.BREACHED
            if observed > target
            else SloHealth.AT_RISK
            if observed > target * 0.8
            else SloHealth.HEALTHY
        )
        return SloObjective(
            metric=metric,
            label=label,
            objective=f"< {target:g}s",
            target=target,
            unit="seconds",
            observed=observed,
            sampleCount=count,
            health=health,
            source=source,
        )

    @staticmethod
    def _ratio(
        metric: str,
        label: str,
        observed: float | None,
        count: int,
        target: float,
        source: str,
    ) -> SloObjective:
        health = (
            SloHealth.NO_DATA
            if observed is None
            else SloHealth.BREACHED
            if observed < target
            else SloHealth.AT_RISK
            if observed < target + (1 - target) * 0.2
            else SloHealth.HEALTHY
        )
        return SloObjective(
            metric=metric,
            label=label,
            objective=f"> {target * 100:g}%",
            target=target,
            unit="ratio",
            observed=observed,
            sampleCount=count,
            health=health,
            source=source,
        )

    async def _reconcile_alerts(
        self,
        tenant_id: str,
        objectives: tuple[SloObjective, ...],
        capacity: CapacitySnapshot,
    ) -> None:
        active: dict[str, tuple[str, str, str, float | int | None]] = {}
        for objective in objectives:
            if objective.health is SloHealth.BREACHED:
                active[f"slo:{objective.metric}"] = (
                    "slo_breach",
                    "warning",
                    f"{objective.label} 未达到 {objective.objective}",
                    objective.observed,
                )
        for status, count in capacity.stuck_runs_by_status.items():
            if count:
                active[f"stuck:{status}"] = (
                    "stuck_run",
                    "critical" if status in {"running", "cancelling"} else "warning",
                    f"{count} 个 {status} Run 超过状态阈值",
                    count,
                )
        if capacity.queue_ready >= 1000:
            active["capacity:queue"] = (
                "capacity_pressure",
                "critical",
                "Run ready queue 达到容量告警阈值",
                capacity.queue_ready,
            )
        existing = await self.repository.list_incidents(
            tenant_id, status=IncidentStatus.OPEN, limit=500
        )
        managed_kinds = {"slo_breach", "stuck_run", "capacity_pressure"}
        for fingerprint, (kind, severity, summary, observed) in active.items():
            current = next((item for item in existing if item.fingerprint == fingerprint), None)
            now = self._clock()
            await self.repository.upsert_incident(
                ReliabilityIncident(
                    tenantId=tenant_id,
                    incidentId=current.incident_id if current else self._ids("incident"),
                    fingerprint=fingerprint,
                    kind=kind,
                    severity=severity,
                    status=IncidentStatus.OPEN,
                    resourceType="platform",
                    resourceId=None,
                    summary=summary,
                    details={"observed": observed},
                    openedAt=current.opened_at if current else now,
                    updatedAt=now,
                )
            )
        for current in existing:
            if current.kind in managed_kinds and current.fingerprint not in active:
                now = self._clock()
                await self.repository.upsert_incident(
                    current.model_copy(
                        update={
                            "status": IncidentStatus.RESOLVED,
                            "updated_at": now,
                            "resolved_at": now,
                        }
                    )
                )

    def _publish_capacity(self, value: CapacitySnapshot) -> None:
        for status, count in value.stuck_runs_by_status.items():
            self.metrics.gauge(
                "harness_stuck_runs", count, labels={"status": status}
            )
        self.metrics.gauge(
            "harness_queue_tasks", value.queue_ready, labels={"state": "ready"}
        )
        self.metrics.gauge(
            "harness_queue_tasks",
            value.queue_processing,
            labels={"state": "processing"},
        )
        facts = {
            "active_previews": value.active_previews,
            "pending_approvals": value.pending_approvals,
            "artifact_bytes": value.artifact_bytes,
            "snapshot_bytes": value.snapshot_bytes,
            "lifecycle_backlog": value.lifecycle_backlog,
            "credential_leases": value.credential_leases,
        }
        if value.active_sandboxes is not None:
            facts["active_sandboxes"] = value.active_sandboxes
        if value.database_pool_checked_out is not None:
            facts["database_pool_checked_out"] = value.database_pool_checked_out
        for resource, count in facts.items():
            self.metrics.gauge(
                "harness_capacity_resource",
                count,
                labels={"resource": resource},
            )
