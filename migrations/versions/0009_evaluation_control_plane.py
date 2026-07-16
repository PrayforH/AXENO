"""Add durable evaluation datasets, runs and case results.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("eval_dataset_versions"):
        op.create_table(
            "eval_dataset_versions",
            sa.Column("tenant_id", sa.String(length=128), nullable=False),
            sa.Column("dataset_id", sa.String(length=128), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("agent_name", sa.String(length=128), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint("version >= 1", name="ck_eval_dataset_version_positive"),
            sa.PrimaryKeyConstraint("tenant_id", "dataset_id", "version"),
        )
        op.create_index(
            "ix_eval_datasets_tenant_created",
            "eval_dataset_versions",
            ["tenant_id", "created_at"],
        )
        op.create_index(
            "ix_eval_datasets_tenant_agent",
            "eval_dataset_versions",
            ["tenant_id", "agent_name"],
        )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("eval_runs"):
        op.create_table(
            "eval_runs",
            sa.Column("tenant_id", sa.String(length=128), nullable=False),
            sa.Column("eval_run_id", sa.String(length=128), nullable=False),
            sa.Column("dataset_id", sa.String(length=128), nullable=False),
            sa.Column("dataset_version", sa.Integer(), nullable=False),
            sa.Column("agent_name", sa.String(length=128), nullable=False),
            sa.Column("agent_version", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=256), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("fencing_token", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint(
                "dataset_version >= 1", name="ck_eval_run_dataset_version_positive"
            ),
            sa.PrimaryKeyConstraint("tenant_id", "eval_run_id"),
            sa.UniqueConstraint(
                "tenant_id", "idempotency_key", name="uq_eval_run_idempotency"
            ),
        )
        op.create_index("ix_eval_runs_dataset_id", "eval_runs", ["dataset_id"])
        op.create_index("ix_eval_runs_status", "eval_runs", ["status"])
        op.create_index(
            "ix_eval_runs_tenant_created",
            "eval_runs",
            ["tenant_id", "created_at"],
        )
        op.create_index(
            "ix_eval_runs_agent_version",
            "eval_runs",
            ["tenant_id", "agent_name", "agent_version"],
        )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("eval_case_results"):
        op.create_table(
            "eval_case_results",
            sa.Column("tenant_id", sa.String(length=128), nullable=False),
            sa.Column("eval_run_id", sa.String(length=128), nullable=False),
            sa.Column("case_id", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "eval_run_id", "case_id"),
        )
        op.create_index(
            "ix_eval_case_results_status", "eval_case_results", ["status"]
        )
        op.create_index(
            "ix_eval_case_results_run",
            "eval_case_results",
            ["tenant_id", "eval_run_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("eval_case_results"):
        op.drop_table("eval_case_results")
    if inspector.has_table("eval_runs"):
        op.drop_table("eval_runs")
    if inspector.has_table("eval_dataset_versions"):
        op.drop_table("eval_dataset_versions")
