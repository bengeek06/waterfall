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
    op.execute(
        sa.text(
            "UPDATE wf_planning_task_snapshot "
            "SET notes = ("
            "SELECT enrichment.description FROM wf_planning AS planning "
            "JOIN wf_task_enrichment AS enrichment "
            "ON enrichment.project_id = planning.project_id "
            "AND enrichment.task_uid = wf_planning_task_snapshot.uid "
            "WHERE wf_planning_task_snapshot.planning_id = planning.id"
            ") "
            "WHERE notes IS NULL AND EXISTS ("
            "SELECT 1 FROM wf_planning AS planning "
            "JOIN wf_task_enrichment AS enrichment "
            "ON enrichment.project_id = planning.project_id "
            "AND enrichment.task_uid = wf_planning_task_snapshot.uid "
            "WHERE wf_planning_task_snapshot.planning_id = planning.id"
            ")"
        )
    )


def downgrade() -> None:
    op.drop_column("wf_planning_task_snapshot", "notes")
