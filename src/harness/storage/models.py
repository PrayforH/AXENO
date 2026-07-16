"""Authoritative relational persistence model."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthIdentityRow(Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_oauth_identity_subject"),
    )

    identity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    subject: Mapped[str] = mapped_column(String(256))
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    provider_email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TenantMembershipRow(Base):
    __tablename__ = "tenant_memberships"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RefreshTokenRow(Base):
    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64))


class AuditLogRow(Base):
    __tablename__ = "audit_logs"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(160), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(256))
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class AgentVersionRow(Base):
    __tablename__ = "agent_versions"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AgentDraftRow(Base):
    __tablename__ = "agent_drafts"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_agent_drafts_revision_positive"),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_agent_drafts_schema_version_positive",
        ),
        Index("ix_agent_drafts_tenant_name", "tenant_id", "name"),
        Index("ix_agent_drafts_tenant_updated", "tenant_id", "updated_at"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class CapabilityCatalogRow(Base):
    __tablename__ = "capability_catalogs"
    __table_args__ = (
        CheckConstraint(
            "revision >= 1", name="ck_capability_catalogs_revision_positive"
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class PreviewDeploymentRow(Base):
    __tablename__ = "preview_deployments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_preview_deployment_idempotency",
        ),
        Index(
            "ix_preview_deployments_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    preview_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class SessionRow(Base):
    __tablename__ = "sessions"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "session_id", "idempotency_key", name="uq_run_idempotency"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class EventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "sequence", name="uq_event_sequence"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class OutboxRow(Base):
    __tablename__ = "outbox"

    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SdkSessionEntryRow(Base):
    __tablename__ = "sdk_session_entries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "session_id",
            "subpath",
            "sequence",
            name="uq_sdk_entry_sequence",
        ),
    )

    entry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    subpath: Mapped[str] = mapped_column(String(512), default="")
    sequence: Mapped[int] = mapped_column(Integer)
    entry_uuid: Mapped[str | None] = mapped_column(String(128), index=True)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "tool_call_id", name="uq_approval_tool_call"
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class InputArtifactRow(Base):
    __tablename__ = "input_artifacts"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    input_artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class UserMemoryRow(Base):
    __tablename__ = "user_memories"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ThreadFileRow(Base):
    __tablename__ = "thread_files"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    parent_file_id: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class WorkspaceSnapshotRow(Base):
    __tablename__ = "workspace_snapshots"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AguiThreadBindingRow(Base):
    __tablename__ = "agui_thread_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "session_id", name="uq_agui_binding_session"
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
