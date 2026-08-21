"""store task notes in planning snapshots

Revision ID: 20260821_0007
Revises: 20260821_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_0007"
down_revision = "20260821_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wf_planning_task_snapshot",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wf_planning_task_snapshot", "notes")
