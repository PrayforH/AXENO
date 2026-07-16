"""Durable, short-lived Studio Preview Deployment facts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from harness.studio.models import StudioModel


class PreviewStatus(StrEnum):
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    READY = "ready"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in {
            PreviewStatus.CANCELLED,
            PreviewStatus.FAILED,
            PreviewStatus.EXPIRED,
        }


class PreviewDeployment(StudioModel):
    preview_id: str = Field(alias="previewId", min_length=1)
    tenant_id: str = Field(alias="tenantId", min_length=1)
    draft_id: str = Field(alias="draftId", min_length=1)
    draft_revision: int = Field(alias="draftRevision", ge=1)
    content_hash: str = Field(alias="contentHash", pattern=r"^[a-f0-9]{64}$")
    package_hash: str = Field(alias="packageHash", pattern=r"^[a-f0-9]{64}$")
    requested_by: str = Field(alias="requestedBy", min_length=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=256)
    status: PreviewStatus
    identity_kind: Literal["test"] = Field(default="test", alias="identityKind")
    environment: Literal["preview"] = "preview"
    fencing_token: int = Field(default=0, alias="fencingToken", ge=0)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    expires_at: datetime = Field(alias="expiresAt")
    error_code: str | None = Field(default=None, alias="errorCode")
    stale: bool = False
    stale_reason: str | None = Field(default=None, alias="staleReason")


class CreatePreviewRequest(StudioModel):
    draft_id: str = Field(alias="draftId", min_length=1)
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=256)
    ttl_seconds: int = Field(default=3600, alias="ttlSeconds", ge=60, le=3600)


_ALLOWED_TRANSITIONS: dict[PreviewStatus, frozenset[PreviewStatus]] = {
    PreviewStatus.QUEUED: frozenset(
        {PreviewStatus.PROVISIONING, PreviewStatus.CANCELLING, PreviewStatus.EXPIRED}
    ),
    PreviewStatus.PROVISIONING: frozenset(
        {
            PreviewStatus.READY,
            PreviewStatus.CANCELLING,
            PreviewStatus.FAILED,
            PreviewStatus.EXPIRED,
        }
    ),
    PreviewStatus.READY: frozenset(
        {PreviewStatus.CANCELLING, PreviewStatus.FAILED, PreviewStatus.EXPIRED}
    ),
    PreviewStatus.CANCELLING: frozenset(
        {PreviewStatus.CANCELLED, PreviewStatus.FAILED, PreviewStatus.EXPIRED}
    ),
}


def transition_preview(current: PreviewStatus, target: PreviewStatus) -> PreviewStatus:
    if current.is_terminal or target not in _ALLOWED_TRANSITIONS.get(
        current, frozenset()
    ):
        raise ValueError(
            f"invalid Preview transition: {current.value} -> {target.value}"
        )
    return target
