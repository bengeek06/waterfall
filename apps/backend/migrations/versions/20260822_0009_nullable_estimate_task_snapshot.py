"""allow estimate task rows to originate from planning snapshots"""

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
    with op.batch_alter_table("wf_estimate_task_row") as batch_op:
        batch_op.alter_column(
            "task_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
