"""create resource and estimate models

Revision ID: 20260816_0005
Revises: 20260815_0004
Create Date: 2026-08-16 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260816_0005"
down_revision = "20260815_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wf_resource_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("accounting_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["wf_resource_node.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_wf_resource_node_code"),
    )
    op.create_index("idx_wf_resource_node_parent", "wf_resource_node", ["parent_id"])

    op.create_table(
        "wf_cost_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accounting_code"),
    )

    op.create_table(
        "wf_resource_role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("cost_category_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cost_category_id"], ["wf_cost_category.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["wf_resource_node.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_wf_resource_role_code"),
    )
    op.create_index("idx_wf_resource_role_node", "wf_resource_role", ["node_id"])

    op.create_table(
        "wf_cost_rate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cost_category_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("hourly_rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("year >= 2000", name="ck_wf_cost_rate_year"),
        sa.CheckConstraint("hourly_rate >= 0", name="ck_wf_cost_rate_hourly_rate"),
        sa.ForeignKeyConstraint(["cost_category_id"], ["wf_cost_category.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cost_category_id", "year", name="uq_wf_cost_rate_category_year"),
    )
    op.create_index("idx_wf_cost_rate_year", "wf_cost_rate", ["year"])

    op.create_table(
        "wf_inflation_rate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("coefficient", sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("year >= 2000", name="ck_wf_inflation_rate_year"),
        sa.CheckConstraint("coefficient > 0", name="ck_wf_inflation_rate_coefficient"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year"),
    )

    op.create_table(
        "wf_role_capacity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("person_count", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("available_hours", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("period_end > period_start", name="ck_wf_role_capacity_period"),
        sa.CheckConstraint("person_count >= 0", name="ck_wf_role_capacity_person_count"),
        sa.CheckConstraint("available_hours >= 0", name="ck_wf_role_capacity_hours"),
        sa.ForeignKeyConstraint(["role_id"], ["wf_resource_role.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_wf_role_capacity_role_period",
        "wf_role_capacity",
        ["role_id", "period_start", "period_end"],
    )
    op.create_table(
        "wf_task_role_assignment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("hours", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_wf_task_role_quantity"),
        sa.CheckConstraint("hours >= 0", name="ck_wf_task_role_hours"),
        sa.ForeignKeyConstraint(["role_id"], ["wf_resource_role.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ms_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "role_id", name="uq_wf_task_role_assignment"),
    )
    op.create_index("idx_wf_task_role_assignment_role", "wf_task_role_assignment", ["role_id"])

    op.create_table(
        "wf_estimate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("version_number > 0", name="ck_wf_estimate_version"),
        sa.CheckConstraint("kind IN ('initial', 'remaining')", name="ck_wf_estimate_kind"),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'superseded', 'archived')",
            name="ck_wf_estimate_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version_number", name="uq_wf_estimate_project_version"),
    )

    op.create_table(
        "wf_estimate_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(length=512), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False),
        sa.Column("accounting_code", sa.String(length=64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("hours", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("hourly_rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("inflation_coefficient", sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column("budget_cost", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_wf_estimate_line_quantity"),
        sa.CheckConstraint("hours >= 0", name="ck_wf_estimate_line_hours"),
        sa.CheckConstraint("hourly_rate >= 0", name="ck_wf_estimate_line_rate"),
        sa.CheckConstraint("inflation_coefficient > 0", name="ck_wf_estimate_line_inflation"),
        sa.CheckConstraint("budget_cost >= 0", name="ck_wf_estimate_line_budget"),
        sa.ForeignKeyConstraint(["estimate_id"], ["wf_estimate.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["wf_resource_role.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ms_task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_wf_estimate_line_estimate", "wf_estimate_line", ["estimate_id"])
    op.create_index("idx_wf_estimate_line_task", "wf_estimate_line", ["task_id"])
    op.create_index("idx_wf_estimate_line_role", "wf_estimate_line", ["role_id"])


def downgrade() -> None:
    op.drop_index("idx_wf_estimate_line_role", table_name="wf_estimate_line")
    op.drop_index("idx_wf_estimate_line_task", table_name="wf_estimate_line")
    op.drop_index("idx_wf_estimate_line_estimate", table_name="wf_estimate_line")
    op.drop_table("wf_estimate_line")
    op.drop_table("wf_estimate")
    op.drop_index("idx_wf_task_role_assignment_role", table_name="wf_task_role_assignment")
    op.drop_table("wf_task_role_assignment")
    op.drop_index("idx_wf_role_capacity_role_period", table_name="wf_role_capacity")
    op.drop_table("wf_role_capacity")
    op.drop_table("wf_inflation_rate")
    op.drop_index("idx_wf_cost_rate_year", table_name="wf_cost_rate")
    op.drop_table("wf_cost_rate")
    op.drop_table("wf_resource_role")
    op.drop_table("wf_cost_category")
    op.drop_index("idx_wf_resource_node_parent", table_name="wf_resource_node")
    op.drop_table("wf_resource_node")
