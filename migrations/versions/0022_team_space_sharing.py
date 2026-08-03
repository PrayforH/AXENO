"""Add team spaces and immutable shared Agent grants.

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

from alembic import op

from harness.storage.models import Base

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for name in (
        "team_spaces",
        "team_space_members",
        "shared_agent_versions",
        "shared_knowledge_bases",
    ):
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in (
        "shared_knowledge_bases",
        "shared_agent_versions",
        "team_space_members",
        "team_spaces",
    ):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
