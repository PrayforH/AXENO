"""Immutable deployment snapshots and mutable environment pointers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from harness.studio.models import StudioModel


class EnvironmentName(StrEnum):
    TEST = "test"
    CANARY = "canary"
    PRODUCTION = "production"


class DeploymentStatus(StrEnum):
    QUEUED = "queued"
    RECONCILING = "reconciling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {DeploymentStatus.SUCCEEDED, DeploymentStatus.FAILED}


class DeploymentRoute(StudioModel):
    snapshot_id: str = Field(alias="snapshotId", min_length=1)
    weight: int = Field(ge=1, le=100)


class Environment(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    agent_name: str = Field(alias="agentName", pattern=r"^[a-z][a-z0-9-]*$")
    name: EnvironmentName
    revision: int = Field(ge=0)
    routes: tuple[DeploymentRoute, ...] = ()
    healthy_snapshot_id: str | None = Field(default=None, alias="healthySnapshotId")
    updated_at: datetime = Field(alias="updatedAt")

    @model_validator(mode="after")
    def valid_routes(self) -> Environment:
        if self.routes and sum(item.weight for item in self.routes) != 100:
            raise ValueError("deployment route weights must total 100")
        if len({item.snapshot_id for item in self.routes}) != len(self.routes):
            raise ValueError("deployment route snapshots must be unique")
        return self


class DeploymentSnapshot(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    snapshot_id: str = Field(alias="snapshotId", min_length=1)
    agent_name: str = Field(alias="agentName", pattern=r"^[a-z][a-z0-9-]*$")
    agent_version: str = Field(alias="agentVersion", min_length=1)
    environment: EnvironmentName
    manifest_hash: str = Field(alias="manifestHash", pattern=r"^[a-f0-9]{64}$")
    package_hash: str = Field(alias="packageHash", pattern=r"^[a-f0-9]{64}$")
    image_digest: str = Field(alias="imageDigest", pattern=r"^sha256:[a-f0-9]{64}$")
    execution_profile: str = Field(alias="executionProfile", min_length=1)
    execution_profile_version: int = Field(
        default=1, alias="executionProfileVersion", ge=1
    )
    execution_profile_hash: str = Field(
        default="0" * 64,
        alias="executionProfileHash",
        pattern=r"^[a-f0-9]{64}$",
    )
    config: dict[str, str | int | bool] = Field(default_factory=dict)
    eval_gate_passed: bool = Field(alias="evalGatePassed")
    eval_required_datasets: int = Field(alias="evalRequiredDatasets", ge=0)
    preview_id: str | None = Field(default=None, alias="previewId")
    created_by: str = Field(alias="createdBy", min_length=1)
    created_at: datetime = Field(alias="createdAt")


class Deployment(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    deployment_id: str = Field(alias="deploymentId", min_length=1)
    agent_name: str = Field(alias="agentName", pattern=r"^[a-z][a-z0-9-]*$")
    environment: EnvironmentName
    action: Literal["promote", "rollback"]
    target_snapshot_id: str = Field(alias="targetSnapshotId", min_length=1)
    previous_snapshot_id: str | None = Field(default=None, alias="previousSnapshotId")
    canary_percent: int = Field(alias="canaryPercent", ge=1, le=100)
    expected_environment_revision: int = Field(alias="expectedEnvironmentRevision", ge=0)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=256)
    requested_by: str = Field(alias="requestedBy", min_length=1)
    status: DeploymentStatus
    fencing_token: int = Field(default=0, alias="fencingToken", ge=0)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    error_code: str | None = Field(default=None, alias="errorCode")


class PromoteRequest(StudioModel):
    agent_name: str = Field(alias="agentName", pattern=r"^[a-z][a-z0-9-]*$")
    agent_version: str = Field(alias="agentVersion", min_length=1)
    environment: EnvironmentName
    expected_environment_revision: int = Field(alias="expectedEnvironmentRevision", ge=0)
    canary_percent: int = Field(default=100, alias="canaryPercent", ge=1, le=100)
    image_digest: str = Field(alias="imageDigest", pattern=r"^sha256:[a-f0-9]{64}$")
    execution_profile: str = Field(alias="executionProfile", min_length=1)
    config: dict[str, str | int | bool] = Field(default_factory=dict)
    preview_id: str | None = Field(default=None, alias="previewId")
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=256)

    @model_validator(mode="after")
    def config_is_non_secret(self) -> PromoteRequest:
        forbidden = (
            "secret",
            "token",
            "password",
            "credential",
            "api_key",
            "apikey",
            "provider",
            "sandbox",
            "cpu",
            "memory",
            "disk",
            "network",
            "egress",
            "ttl",
        )
        unsafe = sorted(
            key for key in self.config if any(word in key.lower() for word in forbidden)
        )
        if unsafe:
            raise ValueError(
                "deployment config contains secret-like or platform-managed keys"
            )
        return self


class RollbackRequest(StudioModel):
    snapshot_id: str = Field(alias="snapshotId", min_length=1)
    expected_environment_revision: int = Field(alias="expectedEnvironmentRevision", ge=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=256)


class DeploymentView(StudioModel):
    deployment: Deployment
    target: DeploymentSnapshot
    environment: Environment


class DeploymentResolution(StudioModel):
    agent_name: str = Field(alias="agentName")
    agent_version: str = Field(alias="agentVersion")
    environment: EnvironmentName
    snapshot_id: str = Field(alias="snapshotId")
