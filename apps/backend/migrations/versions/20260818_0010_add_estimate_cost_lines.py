"""add estimate cost lines

Revision ID: 20260818_0010
Revises: 20260818_0009
Create Date: 2026-08-18 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0010"
down_revision = "20260818_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wf_estimate_cost_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("cost_type_id", sa.Integer(), nullable=False),
        sa.Column("cost_category_id", sa.Integer(), nullable=False),
        sa.Column("cost_type_code", sa.String(length=32), nullable=False),
        sa.Column("accounting_code", sa.String(length=64), nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("purchase_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("supply_status", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_wf_estimate_cost_line_quantity"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_wf_estimate_cost_line_unit_cost"),
        sa.CheckConstraint("purchase_cost >= 0", name="ck_wf_estimate_cost_line_purchase_cost"),
        sa.CheckConstraint(
            "supply_status IN ('planned', 'ordered', 'received', 'cancelled') "
            "OR supply_status IS NULL",
            name="ck_wf_estimate_cost_line_supply_status",
        ),
        sa.ForeignKeyConstraint(["estimate_id"], ["wf_estimate.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ms_task.id"]),
        sa.ForeignKeyConstraint(["cost_type_id"], ["wf_cost_type.id"]),
        sa.ForeignKeyConstraint(["cost_category_id"], ["wf_cost_category.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_wf_estimate_cost_line_estimate", "wf_estimate_cost_line", ["estimate_id"])
    op.create_index("idx_wf_estimate_cost_line_task", "wf_estimate_cost_line", ["task_id"])
    op.create_index(
        "idx_wf_estimate_cost_line_category",
        "wf_estimate_cost_line",
        ["cost_category_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_wf_estimate_cost_line_category", table_name="wf_estimate_cost_line")
    op.drop_index("idx_wf_estimate_cost_line_task", table_name="wf_estimate_cost_line")
    op.drop_index("idx_wf_estimate_cost_line_estimate", table_name="wf_estimate_cost_line")
    op.drop_table("wf_estimate_cost_line")
