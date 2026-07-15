"""Add created_at/updated_at columns for listing queries.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add columns conditionally (ignore if they already exist)
    for table, column in [
        ("sessions", "created_at"),
        ("runs", "created_at"),
        ("runs", "updated_at"),
    ]:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} TIMESTAMP WITH TIME ZONE"
        )


def downgrade() -> None:
    for table, column in [
        ("runs", "updated_at"),
        ("runs", "created_at"),
        ("sessions", "created_at"),
    ]:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
