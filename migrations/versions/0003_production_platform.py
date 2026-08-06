"""Add production platform state tables.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

from harness.storage.models import Base

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "agent_versions",
    "sessions",
    "approvals",
    "artifacts",
    "input_artifacts",
    "user_memories",
    "thread_files",
    "workspace_snapshots",
    "agui_thread_bindings",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
