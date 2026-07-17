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
    # Revision 0001 historically creates the current Base metadata during a
    # full-history replay. A database can therefore be stamped at 0013 while
    # already containing one or more 0014 objects. Check every object
    # independently so mixed legacy states can still upgrade without data loss.
    inspector = sa.inspect(op.get_bind())
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    if "updated_at" not in run_columns:
        op.add_column(
            "runs",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    run_indexes = {index["name"] for index in inspector.get_indexes("runs")}
    if "ix_runs_updated_at" not in run_indexes:
        op.create_index("ix_runs_updated_at", "runs", ["updated_at"])

    if not inspector.has_table("reliability_incidents"):
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

    if not inspector.has_table("reaper_actions"):
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

    if not inspector.has_table("capacity_snapshots"):
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
    inspector = sa.inspect(op.get_bind())
    for table in ("capacity_snapshots", "reaper_actions", "reliability_incidents"):
        if inspector.has_table(table):
            op.drop_table(table)
    run_indexes = {index["name"] for index in inspector.get_indexes("runs")}
    if "ix_runs_updated_at" in run_indexes:
        op.drop_index("ix_runs_updated_at", table_name="runs")
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    if "updated_at" in run_columns:
        op.drop_column("runs", "updated_at")
