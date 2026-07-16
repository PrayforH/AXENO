"""Add SDK transcript idempotency and modification metadata.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("sdk_session_entries")}
    if "entry_uuid" not in columns:
        op.add_column("sdk_session_entries", sa.Column("entry_uuid", sa.String(128), nullable=True))
        op.create_index(
            "ix_sdk_session_entries_entry_uuid",
            "sdk_session_entries",
            ["entry_uuid"],
        )
    if "modified_at" not in columns:
        op.add_column(
            "sdk_session_entries",
            sa.Column(
                "modified_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.alter_column("sdk_session_entries", "modified_at", server_default=None)
        op.create_index(
            "ix_sdk_session_entries_modified_at",
            "sdk_session_entries",
            ["modified_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("sdk_session_entries")}
    if "modified_at" in columns:
        op.drop_index("ix_sdk_session_entries_modified_at", table_name="sdk_session_entries")
        op.drop_column("sdk_session_entries", "modified_at")
    if "entry_uuid" in columns:
        op.drop_index("ix_sdk_session_entries_entry_uuid", table_name="sdk_session_entries")
        op.drop_column("sdk_session_entries", "entry_uuid")
