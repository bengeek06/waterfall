"""drop task id_display column (E9-01, issue #146)

`id_display` on `MsTask`/`WfPlanningTaskSnapshot` was allocated once as
`max(...) + 1` and never recalculated afterwards: it behaved as a second,
never-reused stable identifier (like `uid`) rather than a positional one, so
it never actually reflected a task's current rank in the planning's display
order. EPIC E9 (#145) replaces it with a `row_number` computed on the fly at
read time (landing in #147/E9-02), never stored in the database. This
migration only drops the now-unused persisted column (and its supporting
index on `ms_task`); it does not introduce any new column, since `row_number`
is never persisted.

Revision ID: 20260908_0008
Revises: 20260906_0007
Create Date: 2026-09-08 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260908_0008"
down_revision = "20260906_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.drop_index("idx_ms_task_project_id_display")
        batch_op.drop_column("id_display")

    with op.batch_alter_table("wf_planning_task_snapshot") as batch_op:
        batch_op.drop_column("id_display")


def downgrade() -> None:
    # Recreates the column/index shape only -- the original id_display values
    # are not restored (they were dropped by upgrade() and never captured
    # anywhere else). Acceptable here: id_display was already a stale,
    # never-recalculated value with no functional meaning to preserve (see
    # module docstring); every row simply comes back NULL until repopulated.
    with op.batch_alter_table("wf_planning_task_snapshot") as batch_op:
        batch_op.add_column(sa.Column("id_display", sa.Integer(), nullable=True))

    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.add_column(sa.Column("id_display", sa.Integer(), nullable=True))
        batch_op.create_index(
            "idx_ms_task_project_id_display", ["project_id", "id_display"], unique=False
        )
