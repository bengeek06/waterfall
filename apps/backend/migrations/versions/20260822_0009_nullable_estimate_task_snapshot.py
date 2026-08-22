"""Allow estimate task rows to originate from planning snapshots.

Downgrade is intentionally refused while NULL task references exist because no
reversible mapping to the legacy MS Project task table is available.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260822_0009"
down_revision = "20260821_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wf_estimate_task_row") as batch_op:
        batch_op.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    null_rows = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM wf_estimate_task_row WHERE task_id IS NULL")
    )
    if null_rows:
        raise RuntimeError(
            "Cannot downgrade 0009 while estimate task rows have NULL task_id; "
            "restore their legacy task references first"
        )
    with op.batch_alter_table("wf_estimate_task_row") as batch_op:
        batch_op.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
