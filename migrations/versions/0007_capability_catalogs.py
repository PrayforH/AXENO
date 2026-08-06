"""Add tenant-scoped Studio capability catalogs.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("capability_catalogs"):
        return
    op.create_table(
        "capability_catalogs",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name="ck_capability_catalogs_revision_positive"
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_index(
        "ix_capability_catalogs_updated_at", "capability_catalogs", ["updated_at"]
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("capability_catalogs"):
        op.drop_table("capability_catalogs")
