"""Index durable approval expiry for worker reconciliation.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("approvals")}
    if "expires_at" not in columns:
        op.add_column(
            "approvals",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(
            "UPDATE approvals "
            "SET expires_at = CAST(payload ->> 'expires_at' AS TIMESTAMPTZ) "
            "WHERE expires_at IS NULL"
        )
        op.alter_column("approvals", "expires_at", nullable=False)
    indexes = {index["name"] for index in inspector.get_indexes("approvals")}
    if "ix_approvals_expires_at" not in indexes:
        op.create_index("ix_approvals_expires_at", "approvals", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_approvals_expires_at", table_name="approvals")
    op.drop_column("approvals", "expires_at")
