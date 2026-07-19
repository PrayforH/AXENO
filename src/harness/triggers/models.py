"""Contracts for invoking a deployed Agent through external triggers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from harness.core.models import RunStatus
from harness.deployments.models import EnvironmentName
from harness.studio.models import StudioModel


class AgentTrigger(StudioModel):
    tenant_id: str = Field(alias="tenantId", min_length=1)
    trigger_id: str = Field(alias="triggerId", min_length=1)
    kind: Literal["webhook"] = "webhook"
    name: str = Field(min_length=1, max_length=120)
    agent_name: str = Field(alias="agentName", pattern=r"^[a-z][a-z0-9-]*$")
    environment: EnvironmentName
    enabled: bool = True
    revision: int = Field(ge=1)
    created_by: str = Field(alias="createdBy", min_length=1)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    last_invoked_at: datetime | None = Field(default=None, alias="lastInvokedAt")


class StoredAgentTrigger(AgentTrigger):
    secret_digest: str = Field(alias="secretDigest", pattern=r"^[a-f0-9]{64}$")

    def public(self) -> AgentTrigger:
        return AgentTrigger.model_validate(
            self.model_dump(mode="json", by_alias=True, exclude={"secret_digest"})
        )


class CreateAgentTriggerRequest(StudioModel):
    name: str = Field(min_length=1, max_length=120)
    environment: EnvironmentName


class UpdateAgentTriggerRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool


class RotateAgentTriggerSecretRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)


class CreatedAgentTrigger(StudioModel):
    trigger: AgentTrigger
    secret: str = Field(min_length=32)


class InvokeAgentTriggerRequest(StudioModel):
    prompt: str = Field(min_length=1, max_length=200_000)


class TriggerInvocation(StudioModel):
    trigger_id: str = Field(alias="triggerId")
    session_id: str = Field(alias="sessionId")
    run_id: str = Field(alias="runId")
    status: RunStatus
    environment: EnvironmentName
    agent_name: str = Field(alias="agentName")
    agent_version: str = Field(alias="agentVersion")
    deployment_snapshot_id: str = Field(alias="deploymentSnapshotId")
