from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from harness.studio.models import StudioModel


class QuotaResource(StrEnum):
    CONCURRENT_RUNS = "concurrent_runs"
    CONCURRENT_SUBAGENTS = "concurrent_subagents"
    MODEL_TOKENS = "model_tokens"
    MODEL_COST_MICRO_USD = "model_cost_micro_usd"
    MCP_REQUESTS = "mcp_requests"
    ARTIFACT_BYTES = "artifact_bytes"
    SNAPSHOT_BYTES = "snapshot_bytes"
    ACTIVE_PREVIEWS = "active_previews"
    DEPLOYMENT_PROMOTIONS = "deployment_promotions"


class ReservationState(StrEnum):
    ACTIVE = "active"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


class CostState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class QuotaScope(StudioModel):
    agent_name: str | None = Field(default=None, alias="agentName")
    environment: str | None = None

    @property
    def key(self) -> str:
        return f"agent={self.agent_name or '*'}|environment={self.environment or '*'}"


class QuotaPolicy(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    policy_id: str = Field(alias="policyId", min_length=1)
    revision: int = Field(ge=0)
    scope: QuotaScope = QuotaScope()
    limits: dict[QuotaResource, int]
    updated_by: str = Field(alias="updatedBy", min_length=1)
    updated_at: datetime = Field(alias="updatedAt")

    @model_validator(mode="after")
    def positive_limits(self) -> QuotaPolicy:
        if not self.limits or any(value < 1 for value in self.limits.values()):
            raise ValueError("quota limits must be positive")
        return self


class ReplaceQuotaPolicyRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    scope: QuotaScope = QuotaScope()
    limits: dict[QuotaResource, int]

    @model_validator(mode="after")
    def positive_limits(self) -> ReplaceQuotaPolicyRequest:
        if not self.limits or any(value < 1 for value in self.limits.values()):
            raise ValueError("quota limits must be positive")
        return self


class QuotaConstraint(StudioModel):
    scope_key: str = Field(alias="scopeKey", min_length=1)
    limit: int = Field(ge=1)


class ResourceReservation(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    reservation_id: str = Field(alias="reservationId", min_length=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1)
    resource: QuotaResource
    amount: int = Field(ge=1)
    constraints: tuple[QuotaConstraint, ...]
    agent_name: str | None = Field(default=None, alias="agentName")
    environment: str | None = None
    subject_id: str = Field(alias="subjectId", min_length=1)
    state: ReservationState
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")


class UsageLedgerEntry(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    entry_id: str = Field(alias="entryId", min_length=1)
    reservation_id: str | None = Field(default=None, alias="reservationId")
    resource: QuotaResource
    amount: int | None = Field(default=None, ge=0)
    cost_state: CostState = Field(default=CostState.KNOWN, alias="costState")
    agent_name: str | None = Field(default=None, alias="agentName")
    environment: str | None = None
    subject_id: str = Field(alias="subjectId", min_length=1)
    occurred_at: datetime = Field(alias="occurredAt")

    @model_validator(mode="after")
    def unknown_has_no_amount(self) -> UsageLedgerEntry:
        if self.cost_state is CostState.UNKNOWN and self.amount is not None:
            raise ValueError("unknown cost must not contain an amount")
        if self.cost_state is CostState.KNOWN and self.amount is None:
            raise ValueError("known usage requires an amount")
        return self


class QuotaCounter(StudioModel):
    tenant_id: str = Field(alias="tenantId")
    scope_key: str = Field(alias="scopeKey")
    resource: QuotaResource
    window_key: str = Field(alias="windowKey")
    reserved: int = Field(ge=0)
    committed: int = Field(ge=0)
    limit: int | None = Field(default=None, ge=1)


class QuotaUsageView(StudioModel):
    policies: tuple[QuotaPolicy, ...]
    counters: tuple[QuotaCounter, ...]
    active_reservations: tuple[ResourceReservation, ...] = Field(alias="activeReservations")
    unknown_cost_entries: int = Field(alias="unknownCostEntries", ge=0)
