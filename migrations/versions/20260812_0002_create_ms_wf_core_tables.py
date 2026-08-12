"""create ms and wf core tables

Revision ID: 20260812_0002
Revises: 20260812_0001
Create Date: 2026-08-12 00:30:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260812_0002"
down_revision = "20260812_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ms_project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_uid", sa.String(length=16), nullable=True),
        sa.Column("source_version", sa.SmallInteger(), nullable=False),
        sa.Column("save_version_out", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("schedule_from_start", sa.Boolean(), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finish_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calendar_uid", sa.Integer(), nullable=True),
        sa.Column("minutes_per_day", sa.Integer(), nullable=False),
        sa.Column("minutes_per_week", sa.Integer(), nullable=False),
        sa.Column("days_per_month", sa.Integer(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_version IN (2010, 2013, 2016)",
            name="ck_ms_project_source_version",
        ),
        sa.CheckConstraint(
            "save_version_out IN (14, 15, 16)",
            name="ck_ms_project_save_version_out",
        ),
        sa.CheckConstraint(
            "(schedule_from_start = 1 AND start_date IS NOT NULL) OR "
            "(schedule_from_start = 0 AND finish_date IS NOT NULL)",
            name="ck_ms_project_schedule_dates",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ms_project_name", "ms_project", ["name"], unique=False)

    op.create_table(
        "ms_task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("id_display", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("task_type", sa.SmallInteger(), nullable=True),
        sa.Column("outline_number", sa.String(length=512), nullable=True),
        sa.Column("outline_level", sa.Integer(), nullable=True),
        sa.Column("wbs", sa.String(length=255), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("duration_format", sa.SmallInteger(), nullable=True),
        sa.Column("work_minutes", sa.Integer(), nullable=True),
        sa.Column("percent_complete", sa.SmallInteger(), nullable=True),
        sa.Column("is_summary", sa.Boolean(), nullable=False),
        sa.Column("is_milestone", sa.Boolean(), nullable=False),
        sa.Column("calendar_uid", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("task_type IN (0, 1, 2) OR task_type IS NULL", name="ck_ms_task_type"),
        sa.CheckConstraint(
            "percent_complete BETWEEN 0 AND 100 OR percent_complete IS NULL",
            name="ck_ms_task_percent_complete",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_ms_task_duration_non_negative",
        ),
        sa.CheckConstraint(
            "work_minutes IS NULL OR work_minutes >= 0",
            name="ck_ms_task_work_non_negative",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "uid", name="uq_ms_task_project_uid"),
    )
    op.create_index(
        "idx_ms_task_project_outline",
        "ms_task",
        ["project_id", "outline_level", "outline_number"],
        unique=False,
    )
    op.create_index(
        "idx_ms_task_project_id_display",
        "ms_task",
        ["project_id", "id_display"],
        unique=False,
    )

    op.create_table(
        "ms_task_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_uid", sa.Integer(), nullable=False),
        sa.Column("predecessor_uid", sa.Integer(), nullable=False),
        sa.Column("link_type", sa.SmallInteger(), nullable=False),
        sa.Column("lag_tenth_minute", sa.Integer(), nullable=True),
        sa.Column("lag_format", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("link_type IN (0, 1, 2, 3)", name="ck_ms_task_link_type"),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "predecessor_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_ms_task_link_pred",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "task_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_ms_task_link_task",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "task_uid",
            "predecessor_uid",
            "link_type",
            name="uq_ms_task_link",
        ),
    )
    op.create_index(
        "idx_ms_task_link_task_uid",
        "ms_task_link",
        ["project_id", "task_uid"],
        unique=False,
    )
    op.create_index(
        "idx_ms_task_link_predecessor_uid",
        "ms_task_link",
        ["project_id", "predecessor_uid"],
        unique=False,
    )

    op.create_table(
        "wf_import_batch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("import_mode", sa.String(length=16), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("log_json", sa.String(), nullable=True),
        sa.CheckConstraint("import_mode IN ('standard', 'full')", name="ck_wf_import_batch_mode"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed')",
            name="ck_wf_import_batch_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wf_excel_import",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("log_json", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_wf_excel_import_status",
        ),
        sa.ForeignKeyConstraint(["import_batch_id"], ["wf_import_batch.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wf_charge_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_uid", sa.Integer(), nullable=False),
        sa.Column("load_minutes", sa.Integer(), nullable=False),
        sa.Column("budget_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("source_excel_import_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("load_minutes >= 0", name="ck_wf_charge_line_load_non_negative"),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "task_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_wf_charge_line_task",
        ),
        sa.ForeignKeyConstraint(["source_excel_import_id"], ["wf_excel_import.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_wf_charge_line_task",
        "wf_charge_line",
        ["project_id", "task_uid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_wf_charge_line_task", table_name="wf_charge_line")
    op.drop_table("wf_charge_line")
    op.drop_table("wf_excel_import")
    op.drop_table("wf_import_batch")
    op.drop_index("idx_ms_task_link_predecessor_uid", table_name="ms_task_link")
    op.drop_index("idx_ms_task_link_task_uid", table_name="ms_task_link")
    op.drop_table("ms_task_link")
    op.drop_index("idx_ms_task_project_id_display", table_name="ms_task")
    op.drop_index("idx_ms_task_project_outline", table_name="ms_task")
    op.drop_table("ms_task")
    op.drop_index("idx_ms_project_name", table_name="ms_project")
    op.drop_table("ms_project")
