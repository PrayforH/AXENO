"""Add consent-governed long-term memory bank.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 0001 historically creates the current Base metadata during a
    # full-history replay. Keep this revision explicit for databases upgrading
    # from 0014, while tolerating tables already materialized by that legacy path.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("memory_entries"):
        op.create_table(
            "memory_entries",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("user_id", sa.String(128), nullable=False),
            sa.Column("entry_id", sa.String(128), nullable=False),
            sa.Column("agent_name", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "user_id", "entry_id"),
        )
        op.create_index(
            "ix_memory_entries_scope_status",
            "memory_entries",
            ["tenant_id", "user_id", "agent_name", "status", "updated_at"],
        )
        op.create_index(
            "ix_memory_entries_expiry", "memory_entries", ["status", "expires_at"]
        )
    for table in ("memory_consents", "memory_retentions"):
        if not inspector.has_table(table):
            op.create_table(
                table,
                sa.Column("tenant_id", sa.String(128), nullable=False),
                sa.Column("user_id", sa.String(128), nullable=False),
                sa.Column("agent_name", sa.String(128), nullable=False),
                sa.Column("version", sa.Integer(), nullable=False),
                sa.Column("payload", sa.JSON(), nullable=False),
                sa.PrimaryKeyConstraint("tenant_id", "user_id", "agent_name"),
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("memory_retentions", "memory_consents", "memory_entries"):
        if inspector.has_table(table):
            op.drop_table(table)
