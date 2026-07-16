"""Add durable quality scores, alerts and sync outbox.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 0001 bootstraps the current metadata on a brand-new database.
    # Existing installations reach 0011 from 0010 and need the explicit DDL.
    if sa.inspect(op.get_bind()).has_table("quality_scores"):
        return
    op.create_table(
        "quality_scores",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("score_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "score_id"),
    )
    op.create_index("ix_quality_scores_run_id", "quality_scores", ["run_id"])
    op.create_index("ix_quality_scores_agent_name", "quality_scores", ["agent_name"])
    op.create_index("ix_quality_scores_name", "quality_scores", ["name"])
    op.create_table(
        "quality_alert_rules",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "rule_id"),
    )
    op.create_index("ix_quality_alert_rules_agent_name", "quality_alert_rules", ["agent_name"])
    op.create_table(
        "quality_alert_incidents",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("incident_id", sa.String(128), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "incident_id"),
    )
    op.create_index(
        "ix_quality_alert_incidents_agent_name", "quality_alert_incidents", ["agent_name"]
    )
    op.create_index("ix_quality_alert_incidents_state", "quality_alert_incidents", ["state"])
    op.create_table(
        "quality_sync_jobs",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("sync_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sync_id"),
    )
    op.create_index("ix_quality_sync_jobs_status", "quality_sync_jobs", ["status"])
    op.create_table(
        "quality_dataset_projections",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("projection_id", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "projection_id"),
    )


def downgrade() -> None:
    op.drop_table("quality_dataset_projections")
    op.drop_table("quality_sync_jobs")
    op.drop_table("quality_alert_incidents")
    op.drop_table("quality_alert_rules")
    op.drop_table("quality_scores")
