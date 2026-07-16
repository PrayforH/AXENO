"""Add retention policies, legal holds and durable lifecycle jobs.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("data_lifecycle_jobs"):
        return
    op.create_table(
        "retention_policies",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("policy_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "policy_id"),
    )
    op.create_table(
        "legal_holds",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("hold_id", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(256), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "hold_id"),
    )
    op.create_index(
        "ix_legal_holds_tenant_active",
        "legal_holds",
        ["tenant_id", "active"],
    )
    op.create_table(
        "data_lifecycle_jobs",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "job_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_data_lifecycle_job_idempotency",
        ),
    )
    op.create_index(
        "ix_data_lifecycle_jobs_status",
        "data_lifecycle_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_data_lifecycle_jobs_tenant_created",
        "data_lifecycle_jobs",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("data_lifecycle_jobs")
    op.drop_table("legal_holds")
    op.drop_table("retention_policies")
