"""simplify role capacity to one row per role

Revision ID: 20260819_0013
Revises: 20260818_0011
Create Date: 2026-08-19 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260819_0013"
down_revision = "20260818_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_wf_role_capacity_role_period", table_name="wf_role_capacity")
    op.drop_constraint("ck_wf_role_capacity_period", "wf_role_capacity", type_="check")
    op.drop_column("wf_role_capacity", "period_start")
    op.drop_column("wf_role_capacity", "period_end")
    op.create_unique_constraint("uq_wf_role_capacity_role", "wf_role_capacity", ["role_id"])


def downgrade() -> None:
    op.drop_constraint("uq_wf_role_capacity_role", "wf_role_capacity", type_="unique")
    op.add_column("wf_role_capacity", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("wf_role_capacity", sa.Column("period_end", sa.Date(), nullable=True))
    op.execute(
        "UPDATE wf_role_capacity SET period_start = CURRENT_DATE, "
        "period_end = CURRENT_DATE + INTERVAL '1 year'"
    )
    op.alter_column("wf_role_capacity", "period_start", nullable=False)
    op.alter_column("wf_role_capacity", "period_end", nullable=False)
    op.create_check_constraint(
        "ck_wf_role_capacity_period",
        "wf_role_capacity",
        "period_end > period_start",
    )
    op.create_index(
        "idx_wf_role_capacity_role_period",
        "wf_role_capacity",
        ["role_id", "period_start", "period_end"],
    )
