"""Add quota policy, atomic counters, reservations and usage ledger.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("quota_policies"):
        return
    op.create_table(
        "quota_policies",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("policy_id", sa.String(128), nullable=False),
        sa.Column("scope_key", sa.String(384), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "policy_id"),
    )
    op.create_index(
        "ix_quota_policies_tenant_scope",
        "quota_policies",
        ["tenant_id", "scope_key"],
    )
    op.create_table(
        "quota_counters",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("scope_key", sa.String(384), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("window_key", sa.String(32), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column("committed", sa.BigInteger(), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "scope_key", "resource", "window_key"),
    )
    op.create_table(
        "quota_reservations",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("reservation_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "reservation_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_quota_reservation_idempotency",
        ),
    )
    op.create_index(
        "ix_quota_reservations_tenant_state",
        "quota_reservations",
        ["tenant_id", "state"],
    )
    op.create_index(
        "ix_quota_reservations_expires", "quota_reservations", ["expires_at"]
    )
    op.create_table(
        "usage_ledger",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("entry_id", sa.String(128), nullable=False),
        sa.Column("reservation_id", sa.String(128), nullable=True),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        sa.Column("cost_state", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "entry_id"),
    )
    op.create_index(
        "ix_usage_ledger_tenant_resource",
        "usage_ledger",
        ["tenant_id", "resource"],
    )
    op.create_index(
        "ix_usage_ledger_tenant_occurred",
        "usage_ledger",
        ["tenant_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("usage_ledger")
    op.drop_table("quota_reservations")
    op.drop_table("quota_counters")
    op.drop_table("quota_policies")
