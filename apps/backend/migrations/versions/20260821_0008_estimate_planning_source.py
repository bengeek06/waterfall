"""record estimate planning source

Revision ID: 20260821_0008
Revises: 20260821_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_0008"
down_revision = "20260821_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.add_column(sa.Column("planning_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_wf_estimate_planning",
            "wf_planning",
            ["planning_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.drop_constraint("fk_wf_estimate_planning", type_="foreignkey")
        batch_op.drop_column("planning_id")
