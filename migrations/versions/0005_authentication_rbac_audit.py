"""Add users, SSO identities, tenant roles, refresh tokens and audit logs.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

from harness.storage.models import Base

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "users",
    "oauth_identities",
    "tenant_memberships",
    "refresh_tokens",
    "audit_logs",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
