"""Immutable domain models shared by all Harness adapters."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    """Base model for facts that are replaced instead of mutated."""

    model_config = ConfigDict(frozen=True)


class AgentVersionStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"

    @classmethod
    def terminal_statuses(cls) -> tuple["RunStatus", ...]:
        return (cls.CANCELLED, cls.SUCCEEDED, cls.FAILED, cls.TIMED_OUT, cls.REJECTED)

    @property
    def is_terminal(self) -> bool:
        return self in self.terminal_statuses()


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class ModelCompatibility(StrEnum):
    FULL = "full"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


class AgentVersion(FrozenModel):
    tenant_id: str
    name: str
    version: str
    status: AgentVersionStatus
    manifest_hash: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Session(FrozenModel):
    session_id: str
    tenant_id: str
    user_id: str
    agent_name: str
    agent_version: str
    created_at: datetime
    claude_session_id: str | None = None
    workspace_snapshot_id: str | None = None


class Run(FrozenModel):
    run_id: str
    session_id: str
    tenant_id: str
    status: RunStatus
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    fencing_token: int = 0
    error_code: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    trace_context: dict[str, str] = Field(default_factory=dict)


class Message(FrozenModel):
    message_id: str
    run_id: str
    session_id: str
    tenant_id: str
    role: MessageRole
    content: list[dict[str, Any]]
    created_at: datetime


class ToolCall(FrozenModel):
    tool_call_id: str
    run_id: str
    name: str
    arguments: dict[str, Any]
    created_at: datetime


class ApprovalRequest(FrozenModel):
    approval_id: str
    run_id: str
    tenant_id: str
    tool_call_id: str
    status: ApprovalStatus
    reason: str
    expires_at: datetime
    created_at: datetime


class Artifact(FrozenModel):
    artifact_id: str
    run_id: str
    tenant_id: str
    name: str
    media_type: str
    status: ArtifactStatus
    object_key: str
    sha256: str | None = None
    size_bytes: int | None = None


class WorkspaceSnapshot(FrozenModel):
    snapshot_id: str
    session_id: str
    tenant_id: str
    object_key: str
    sha256: str
    created_at: datetime


class ModelRoute(FrozenModel):
    route_id: str
    provider: str
    base_url: str
    model: str
    compatibility: ModelCompatibility
    capabilities: frozenset[str] = frozenset()
    fallback_route_id: str | None = None
