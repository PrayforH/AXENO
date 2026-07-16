"""Add reliability incidents, reaper actions and capacity snapshots.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("reliability_incidents"):
        return
    op.add_column(
        "runs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_runs_updated_at", "runs", ["updated_at"])
    op.create_table(
        "reliability_incidents",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("incident_id", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(256), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "incident_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "fingerprint",
            name="uq_reliability_incident_fingerprint",
        ),
    )
    op.create_index(
        "ix_reliability_incidents_status",
        "reliability_incidents",
        ["tenant_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_reliability_incidents_recovery",
        "reliability_incidents",
        ["kind", "status", "updated_at"],
    )
    op.create_table(
        "reaper_actions",
        sa.Column("action_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("reaper", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(256), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("action_id"),
    )
    op.create_index(
        "ix_reaper_actions_tenant_occurred",
        "reaper_actions",
        ["tenant_id", "occurred_at"],
    )
    op.create_table(
        "capacity_snapshots",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("snapshot_id", sa.String(128), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "snapshot_id"),
    )
    op.create_index(
        "ix_capacity_snapshots_captured",
        "capacity_snapshots",
        ["tenant_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_table("capacity_snapshots")
    op.drop_table("reaper_actions")
    op.drop_table("reliability_incidents")
    op.drop_index("ix_runs_updated_at", table_name="runs")
    op.drop_column("runs", "updated_at")
