"""Add tenant-scoped Agent Studio drafts.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 0001 historically calls the current Base.metadata.create_all(). On a
    # brand-new database that legacy behavior can create this future table before
    # Alembic reaches 0006. Existing databases at 0005 do not have it, so keep this
    # revision explicit while making full-history replay idempotent.
    if sa.inspect(op.get_bind()).has_table("agent_drafts"):
        return
    op.create_table(
        "agent_drafts",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("draft_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name="ck_agent_drafts_revision_positive"
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_agent_drafts_schema_version_positive",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "draft_id"),
    )
    op.create_index(
        "ix_agent_drafts_tenant_name", "agent_drafts", ["tenant_id", "name"]
    )
    op.create_index(
        "ix_agent_drafts_tenant_updated",
        "agent_drafts",
        ["tenant_id", "updated_at"],
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("agent_drafts"):
        op.drop_table("agent_drafts")
