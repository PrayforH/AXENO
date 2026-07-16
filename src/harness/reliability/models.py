from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from harness.studio.models import StudioModel


class SloHealth(StrEnum):
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    NO_DATA = "no_data"


class IncidentStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReaperOutcome(StrEnum):
    REAPED = "reaped"
    SKIPPED = "skipped"
    FAILED = "failed"


class SloObjective(StudioModel):
    metric: str
    label: str
    objective: str
    target: float
    unit: str
    observed: float | None = None
    sample_count: int = Field(default=0, alias="sampleCount", ge=0)
    health: SloHealth = SloHealth.NO_DATA
    source: str


class CapacitySnapshot(StudioModel):
    tenant_id: str = Field(alias="tenantId")
    snapshot_id: str = Field(alias="snapshotId")
    captured_at: datetime = Field(alias="capturedAt")
    queue_ready: int = Field(alias="queueReady", ge=0)
    queue_processing: int = Field(alias="queueProcessing", ge=0)
    runs_by_status: dict[str, int] = Field(alias="runsByStatus")
    stuck_runs_by_status: dict[str, int] = Field(alias="stuckRunsByStatus")
    active_previews: int = Field(alias="activePreviews", ge=0)
    pending_approvals: int = Field(alias="pendingApprovals", ge=0)
    active_sandboxes: int | None = Field(default=None, alias="activeSandboxes", ge=0)
    database_pool_checked_out: int | None = Field(
        default=None, alias="databasePoolCheckedOut", ge=0
    )
    artifact_bytes: int = Field(alias="artifactBytes", ge=0)
    snapshot_bytes: int = Field(alias="snapshotBytes", ge=0)
    lifecycle_backlog: int = Field(alias="lifecycleBacklog", ge=0)
    credential_leases: int = Field(alias="credentialLeases", ge=0)


class ReliabilityIncident(StudioModel):
    tenant_id: str = Field(alias="tenantId")
    incident_id: str = Field(alias="incidentId")
    fingerprint: str
    kind: str
    severity: str
    status: IncidentStatus
    resource_type: str = Field(alias="resourceType")
    resource_id: str | None = Field(default=None, alias="resourceId")
    summary: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    opened_at: datetime = Field(alias="openedAt")
    updated_at: datetime = Field(alias="updatedAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")
    recovery_owner: str | None = Field(default=None, alias="recoveryOwner")
    recovery_lease_expires_at: datetime | None = Field(
        default=None, alias="recoveryLeaseExpiresAt"
    )
    recovery_attempts: int = Field(default=0, alias="recoveryAttempts", ge=0)


class ReaperAction(StudioModel):
    action_id: str = Field(alias="actionId")
    tenant_id: str = Field(alias="tenantId")
    reaper: str
    resource_type: str = Field(alias="resourceType")
    resource_id: str = Field(alias="resourceId")
    expected_state: str = Field(alias="expectedState")
    observed_state: str = Field(alias="observedState")
    outcome: ReaperOutcome
    error_code: str | None = Field(default=None, alias="errorCode")
    occurred_at: datetime = Field(alias="occurredAt")


class ReliabilityOverview(StudioModel):
    generated_at: datetime = Field(alias="generatedAt")
    objectives: tuple[SloObjective, ...]
    capacity: CapacitySnapshot
    incidents: tuple[ReliabilityIncident, ...]
    recent_reaper_actions: tuple[ReaperAction, ...] = Field(alias="recentReaperActions")
