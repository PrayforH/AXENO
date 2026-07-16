"""Add environments, deployment snapshots and operations.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("deployment_environments"):
        op.create_table(
            "deployment_environments",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("agent_name", sa.String(128), nullable=False),
            sa.Column("name", sa.String(32), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint("revision >= 0", name="ck_environment_revision"),
            sa.PrimaryKeyConstraint("tenant_id", "agent_name", "name"),
        )
        op.create_index(
            "ix_deployment_environments_updated_at",
            "deployment_environments",
            ["updated_at"],
        )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("deployment_snapshots"):
        op.create_table(
            "deployment_snapshots",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("snapshot_id", sa.String(128), nullable=False),
            sa.Column("agent_name", sa.String(128), nullable=False),
            sa.Column("agent_version", sa.String(64), nullable=False),
            sa.Column("environment", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "snapshot_id"),
        )
        op.create_index(
            "ix_deployment_snapshots_environment",
            "deployment_snapshots",
            ["environment"],
        )
        op.create_index(
            "ix_deployment_snapshots_agent_created",
            "deployment_snapshots",
            ["tenant_id", "agent_name", "created_at"],
        )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("deployments"):
        op.create_table(
            "deployments",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("deployment_id", sa.String(128), nullable=False),
            sa.Column("agent_name", sa.String(128), nullable=False),
            sa.Column("environment", sa.String(32), nullable=False),
            sa.Column("idempotency_key", sa.String(256), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("fencing_token", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "deployment_id"),
            sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_deployment_idempotency"),
        )
        op.create_index("ix_deployments_status", "deployments", ["status"])
        op.create_index(
            "ix_deployments_agent_created",
            "deployments",
            ["tenant_id", "agent_name", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("deployments"):
        op.drop_table("deployments")
    if inspector.has_table("deployment_snapshots"):
        op.drop_table("deployment_snapshots")
    if inspector.has_table("deployment_environments"):
        op.drop_table("deployment_environments")
