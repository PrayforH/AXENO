from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from harness.studio.models import StudioModel


class LifecycleScopeKind(StrEnum):
    TENANT = "tenant"
    USER = "user"
    SESSION = "session"
    AGENT = "agent"


class LifecycleJobKind(StrEnum):
    EXPORT = "export"
    DELETE = "delete"
    RETENTION = "retention"


class LifecycleJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            LifecycleJobStatus.SUCCEEDED,
            LifecycleJobStatus.PARTIAL_FAILED,
            LifecycleJobStatus.FAILED,
        }


class LifecycleAdapterStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class LifecycleScope(StudioModel):
    kind: LifecycleScopeKind
    subject_id: str = Field(alias="subjectId", min_length=1)


class RetentionPolicy(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    policy_id: str = Field(alias="policyId", min_length=1)
    revision: int = Field(ge=0)
    session_days: int = Field(alias="sessionDays", ge=1)
    artifact_days: int = Field(alias="artifactDays", ge=1)
    trace_days: int = Field(alias="traceDays", ge=1)
    eval_days: int = Field(alias="evalDays", ge=1)
    updated_by: str = Field(alias="updatedBy", min_length=1)
    updated_at: datetime = Field(alias="updatedAt")


class ReplaceRetentionPolicyRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    session_days: int = Field(alias="sessionDays", ge=1)
    artifact_days: int = Field(alias="artifactDays", ge=1)
    trace_days: int = Field(alias="traceDays", ge=1)
    eval_days: int = Field(alias="evalDays", ge=1)


class LegalHold(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    hold_id: str = Field(alias="holdId", min_length=1)
    scope: LifecycleScope
    reason: str = Field(min_length=1, max_length=1000)
    active: bool = True
    created_by: str = Field(alias="createdBy", min_length=1)
    created_at: datetime = Field(alias="createdAt")
    released_by: str | None = Field(default=None, alias="releasedBy")
    released_at: datetime | None = Field(default=None, alias="releasedAt")


class CreateLegalHoldRequest(StudioModel):
    scope: LifecycleScope
    reason: str = Field(min_length=1, max_length=1000)


class LifecycleAdapterResult(StudioModel):
    adapter: str = Field(min_length=1)
    status: LifecycleAdapterStatus
    attempts: int = Field(ge=0)
    processed_items: int = Field(default=0, alias="processedItems", ge=0)
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    updated_at: datetime = Field(alias="updatedAt")


class DataLifecycleJob(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    job_id: str = Field(alias="jobId", min_length=1)
    kind: LifecycleJobKind
    scope: LifecycleScope
    requested_by: str = Field(alias="requestedBy", min_length=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1)
    status: LifecycleJobStatus
    fencing_token: int = Field(default=0, alias="fencingToken", ge=0)
    adapters: tuple[LifecycleAdapterResult, ...]
    retention_cutoffs: dict[str, datetime] = Field(default_factory=dict, alias="retentionCutoffs")
    export_object_id: str | None = Field(default=None, alias="exportObjectId")
    export_filename: str | None = Field(default=None, alias="exportFilename")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")


class CreateLifecycleJobRequest(StudioModel):
    kind: LifecycleJobKind
    scope: LifecycleScope
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1)

    @model_validator(mode="after")
    def retention_is_tenant_scoped(self) -> CreateLifecycleJobRequest:
        if (
            self.kind is LifecycleJobKind.RETENTION
            and self.scope.kind is not LifecycleScopeKind.TENANT
        ):
            raise ValueError("retention jobs must use tenant scope")
        return self


class LifecycleOverview(StudioModel):
    policy: RetentionPolicy
    holds: tuple[LegalHold, ...]
    jobs: tuple[DataLifecycleJob, ...]
