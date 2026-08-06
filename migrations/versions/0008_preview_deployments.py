"""Add short-lived Studio Preview Deployments.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("preview_deployments"):
        return
    op.create_table(
        "preview_deployments",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("preview_id", sa.String(length=128), nullable=False),
        sa.Column("draft_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "preview_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_preview_deployment_idempotency",
        ),
    )
    op.create_index(
        "ix_preview_deployments_draft_id",
        "preview_deployments",
        ["draft_id"],
    )
    op.create_index(
        "ix_preview_deployments_status", "preview_deployments", ["status"]
    )
    op.create_index(
        "ix_preview_deployments_expires_at",
        "preview_deployments",
        ["expires_at"],
    )
    op.create_index(
        "ix_preview_deployments_tenant_created",
        "preview_deployments",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("preview_deployments"):
        op.drop_table("preview_deployments")
