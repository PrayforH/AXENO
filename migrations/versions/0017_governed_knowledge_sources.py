"""Add governed Knowledge Bases, connectors and immutable snapshots.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("knowledge_bases"):
        op.create_table(
            "knowledge_bases",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("reference", sa.String(128), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint(
                "revision >= 1",
                name="ck_knowledge_bases_revision_positive",
            ),
            sa.PrimaryKeyConstraint("tenant_id", "reference"),
        )
        op.create_index(
            "ix_knowledge_bases_tenant_updated",
            "knowledge_bases",
            ["tenant_id", "updated_at"],
        )
    if not inspector.has_table("knowledge_sources"):
        op.create_table(
            "knowledge_sources",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("reference", sa.String(128), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("health", sa.String(32), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("active_snapshot_id", sa.String(128), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint(
                "revision >= 1",
                name="ck_knowledge_sources_revision_positive",
            ),
            sa.PrimaryKeyConstraint("tenant_id", "reference"),
        )
        op.create_index(
            "ix_knowledge_sources_tenant_health",
            "knowledge_sources",
            ["tenant_id", "health"],
        )
        op.create_index(
            "ix_knowledge_sources_tenant_updated",
            "knowledge_sources",
            ["tenant_id", "updated_at"],
        )
        op.create_index(
            "ix_knowledge_sources_active_snapshot_id",
            "knowledge_sources",
            ["active_snapshot_id"],
        )
    if not inspector.has_table("knowledge_snapshots"):
        op.create_table(
            "knowledge_snapshots",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("snapshot_id", sa.String(128), nullable=False),
            sa.Column("source_reference", sa.String(128), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "snapshot_id"),
        )
        op.create_index(
            "ix_knowledge_snapshots_source_created",
            "knowledge_snapshots",
            ["tenant_id", "source_reference", "created_at"],
        )
    if not inspector.has_table("knowledge_chunks"):
        op.create_table(
            "knowledge_chunks",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("snapshot_id", sa.String(128), nullable=False),
            sa.Column("chunk_id", sa.String(128), nullable=False),
            sa.Column("source_reference", sa.String(128), nullable=False),
            sa.Column("document_id", sa.String(256), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "snapshot_id", "chunk_id"),
        )
        op.create_index(
            "ix_knowledge_chunks_snapshot",
            "knowledge_chunks",
            ["tenant_id", "snapshot_id", "document_id", "ordinal"],
        )
    if not inspector.has_table("knowledge_sync_runs"):
        op.create_table(
            "knowledge_sync_runs",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("sync_id", sa.String(128), nullable=False),
            sa.Column("source_reference", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "sync_id"),
        )
        op.create_index(
            "ix_knowledge_sync_runs_source_created",
            "knowledge_sync_runs",
            ["tenant_id", "source_reference", "created_at"],
        )
        op.create_index(
            "ix_knowledge_sync_runs_status",
            "knowledge_sync_runs",
            ["status", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in (
        "knowledge_sync_runs",
        "knowledge_chunks",
        "knowledge_snapshots",
        "knowledge_sources",
        "knowledge_bases",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
