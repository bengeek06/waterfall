"""add estimate task rows

Revision ID: 20260818_0009
Revises: 20260818_0008
Create Date: 2026-08-18 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0009"
down_revision = "20260818_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE wf_estimate SET kind = 'forecast_remaining' WHERE kind = 'remaining'")
    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.add_column(sa.Column("reference_estimate_id", sa.Integer(), nullable=True))
        batch_op.drop_constraint("ck_wf_estimate_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_wf_estimate_kind",
            "kind IN ('initial', 'contract_reference', 'forecast_remaining')",
        )
        batch_op.create_foreign_key(
            "fk_wf_estimate_reference",
            "wf_estimate",
            ["reference_estimate_id"],
            ["id"],
        )
    op.create_table(
        "wf_estimate_task_row",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("parent_task_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=512), nullable=False),
        sa.Column("outline_number", sa.String(length=512), nullable=True),
        sa.Column("outline_level", sa.Integer(), nullable=True),
        sa.Column("is_milestone", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["estimate_id"], ["wf_estimate.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ms_task.id"]),
        sa.ForeignKeyConstraint(["parent_task_id"], ["ms_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("estimate_id", "task_id", name="uq_wf_estimate_task_row"),
    )
    op.create_index(
        "idx_wf_estimate_task_row_estimate_position",
        "wf_estimate_task_row",
        ["estimate_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_wf_estimate_task_row_estimate_position", table_name="wf_estimate_task_row")
    op.drop_table("wf_estimate_task_row")
    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.drop_constraint("fk_wf_estimate_reference", type_="foreignkey")
        batch_op.drop_constraint("ck_wf_estimate_kind", type_="check")
        batch_op.create_check_constraint("ck_wf_estimate_kind", "kind IN ('initial', 'remaining')")
        batch_op.drop_column("reference_estimate_id")
