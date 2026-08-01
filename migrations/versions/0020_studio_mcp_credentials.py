"""Add encrypted Studio-managed MCP credentials.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("mcp_credentials"):
        op.create_table(
            "mcp_credentials",
            sa.Column("tenant_id", sa.String(length=128), nullable=False),
            sa.Column("reference", sa.String(length=128), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("key_names", sa.JSON(), nullable=False),
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.Column("updated_by", sa.String(length=128), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("revision >= 1", name="ck_mcp_credentials_revision_positive"),
            sa.PrimaryKeyConstraint("tenant_id", "reference"),
        )
        op.create_index(
            "ix_mcp_credentials_tenant_updated",
            "mcp_credentials",
            ["tenant_id", "updated_at"],
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("mcp_credentials"):
        op.drop_table("mcp_credentials")
