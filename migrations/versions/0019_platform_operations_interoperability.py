"""Platform operations and trigger interoperability.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 0001 historically creates the current Base metadata during a
    # full-history replay. Keep the delta explicit for databases upgrading from
    # 0018 while tolerating columns and indexes already materialized by that path.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("agent_triggers")}
    if "kind" not in columns:
        op.add_column(
            "agent_triggers",
            sa.Column(
                "kind",
                sa.String(length=32),
                nullable=False,
                server_default="webhook",
            ),
        )
        op.alter_column("agent_triggers", "kind", server_default=None)
    if "next_fire_at" not in columns:
        op.add_column(
            "agent_triggers",
            sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        )

    indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("agent_triggers")
    }
    if "ix_agent_triggers_kind" not in indexes:
        op.create_index("ix_agent_triggers_kind", "agent_triggers", ["kind"])
    if "ix_agent_triggers_next_fire_at" not in indexes:
        op.create_index(
            "ix_agent_triggers_next_fire_at", "agent_triggers", ["next_fire_at"]
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {
        index["name"] for index in inspector.get_indexes("agent_triggers")
    }
    if "ix_agent_triggers_next_fire_at" in indexes:
        op.drop_index("ix_agent_triggers_next_fire_at", table_name="agent_triggers")
    if "ix_agent_triggers_kind" in indexes:
        op.drop_index("ix_agent_triggers_kind", table_name="agent_triggers")
    columns = {column["name"] for column in inspector.get_columns("agent_triggers")}
    if "next_fire_at" in columns:
        op.drop_column("agent_triggers", "next_fire_at")
    if "kind" in columns:
        op.drop_column("agent_triggers", "kind")
