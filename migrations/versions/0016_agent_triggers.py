"""Add published Agent webhook triggers.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("agent_triggers"):
        return
    op.create_table(
        "agent_triggers",
        sa.Column("trigger_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agent_triggers_revision_positive",
        ),
        sa.PrimaryKeyConstraint("trigger_id"),
    )
    op.create_index(
        "ix_agent_triggers_tenant_id",
        "agent_triggers",
        ["tenant_id"],
    )
    op.create_index(
        "ix_agent_triggers_environment",
        "agent_triggers",
        ["environment"],
    )
    op.create_index(
        "ix_agent_triggers_enabled",
        "agent_triggers",
        ["enabled"],
    )
    op.create_index(
        "ix_agent_triggers_updated_at",
        "agent_triggers",
        ["updated_at"],
    )
    op.create_index(
        "ix_agent_triggers_tenant_agent",
        "agent_triggers",
        ["tenant_id", "agent_name", "created_at"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("agent_triggers"):
        op.drop_table("agent_triggers")
