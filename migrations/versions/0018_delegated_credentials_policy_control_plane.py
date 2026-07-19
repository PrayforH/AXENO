"""Add delegated credential connections and governed policy publications.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("credential_connections"):
        op.create_table(
            "credential_connections",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("connection_id", sa.String(128), nullable=False),
            sa.Column("resource_kind", sa.String(32), nullable=False),
            sa.Column("resource_reference", sa.String(256), nullable=False),
            sa.Column("scope", sa.String(32), nullable=False),
            sa.Column("principal_id", sa.String(256), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint(
                "revision >= 1",
                name="ck_credential_connections_revision_positive",
            ),
            sa.PrimaryKeyConstraint("tenant_id", "connection_id"),
        )
        op.create_index(
            "ix_credential_connections_resource",
            "credential_connections",
            ["tenant_id", "resource_kind", "resource_reference"],
        )
        op.create_index(
            "ix_credential_connections_principal",
            "credential_connections",
            ["tenant_id", "scope", "principal_id", "status"],
        )
    if not inspector.has_table("governed_policies"):
        op.create_table(
            "governed_policies",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("policy_id", sa.String(128), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("published_revision", sa.Integer(), nullable=True),
            sa.Column("published_hash", sa.String(64), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.CheckConstraint(
                "revision >= 1",
                name="ck_governed_policies_revision_positive",
            ),
            sa.PrimaryKeyConstraint("tenant_id", "policy_id"),
        )
        op.create_index(
            "ix_governed_policies_tenant_updated",
            "governed_policies",
            ["tenant_id", "updated_at"],
        )
    if not inspector.has_table("governed_policy_publications"):
        op.create_table(
            "governed_policy_publications",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("policy_id", sa.String(128), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "policy_id", "revision"),
        )
        op.create_index(
            "ix_governed_policy_publications_published",
            "governed_policy_publications",
            ["tenant_id", "policy_id", "published_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in (
        "governed_policy_publications",
        "governed_policies",
        "credential_connections",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
