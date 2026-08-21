"""add project status and versioned planning snapshots

Revision ID: 20260821_0005
Revises: 20260821_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_0005"
down_revision = "20260821_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="draft")
        )
        batch_op.add_column(sa.Column("planning_reference_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("displayed_planning_id", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_ms_project_status", "status IN ('draft', 'active', 'archived')"
        )

    op.create_table(
        "wf_planning",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version_number > 0", name="ck_wf_planning_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'superseded')",
            name="ck_wf_planning_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version_number", name="uq_wf_planning_project_version"),
        sa.UniqueConstraint("project_id", "id", name="uq_wf_planning_project_id"),
    )
    op.create_table(
        "wf_planning_task_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("planning_id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("id_display", sa.Integer(), nullable=True),
        sa.Column("structure_key", sa.String(length=128), nullable=True),
        sa.Column("structure_kind", sa.String(length=16), nullable=True),
        sa.Column("parent_uid", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
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
        sa.Column("is_manual", sa.Boolean(), nullable=True),
        sa.Column("calendar_uid", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["planning_id"], ["wf_planning.id"]),
        sa.ForeignKeyConstraint(
            ["planning_id", "parent_uid"],
            ["wf_planning_task_snapshot.planning_id", "wf_planning_task_snapshot.uid"],
            name="fk_wf_planning_task_snapshot_parent",
        ),
        sa.CheckConstraint(
            "task_type IN (0, 1, 2) OR task_type IS NULL",
            name="ck_wf_planning_task_snapshot_type",
        ),
        sa.CheckConstraint(
            "structure_kind IN ('poste', 'lot', 'livrable', 'milestone', 'task') "
            "OR structure_kind IS NULL",
            name="ck_wf_planning_task_snapshot_structure_kind",
        ),
        sa.CheckConstraint(
            "parent_uid IS NULL OR parent_uid > 0",
            name="ck_wf_planning_task_snapshot_parent_uid",
        ),
        sa.CheckConstraint(
            "position IS NULL OR position > 0",
            name="ck_wf_planning_task_snapshot_position",
        ),
        sa.CheckConstraint(
            "percent_complete BETWEEN 0 AND 100 OR percent_complete IS NULL",
            name="ck_wf_planning_task_snapshot_percent_complete",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_wf_planning_task_snapshot_duration",
        ),
        sa.CheckConstraint(
            "work_minutes IS NULL OR work_minutes >= 0",
            name="ck_wf_planning_task_snapshot_work",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("planning_id", "uid", name="uq_wf_planning_task_snapshot_uid"),
        sa.UniqueConstraint(
            "planning_id", "structure_key", name="uq_wf_planning_task_snapshot_structure_key"
        ),
    )
    op.create_table(
        "wf_planning_link_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("planning_id", sa.Integer(), nullable=False),
        sa.Column("task_uid", sa.Integer(), nullable=False),
        sa.Column("predecessor_uid", sa.Integer(), nullable=False),
        sa.Column("link_type", sa.SmallInteger(), nullable=False),
        sa.Column("lag_tenth_minute", sa.Integer(), nullable=True),
        sa.Column("lag_format", sa.SmallInteger(), nullable=True),
        sa.ForeignKeyConstraint(["planning_id"], ["wf_planning.id"]),
        sa.ForeignKeyConstraint(
            ["planning_id", "task_uid"],
            ["wf_planning_task_snapshot.planning_id", "wf_planning_task_snapshot.uid"],
            name="fk_wf_planning_link_snapshot_task",
        ),
        sa.ForeignKeyConstraint(
            ["planning_id", "predecessor_uid"],
            ["wf_planning_task_snapshot.planning_id", "wf_planning_task_snapshot.uid"],
            name="fk_wf_planning_link_snapshot_pred",
        ),
        sa.CheckConstraint("link_type IN (0, 1, 2, 3)", name="ck_wf_planning_link_snapshot_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "planning_id",
            "task_uid",
            "predecessor_uid",
            "link_type",
            name="uq_wf_planning_link_snapshot",
        ),
    )

    op.execute(
        sa.text(
            "INSERT INTO wf_planning "
            "(project_id, version_number, status, note, created_at) "
            "SELECT p.id, 1, 'draft', 'Backfilled from MS Project', CURRENT_TIMESTAMP "
            "FROM ms_project p"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO wf_planning_task_snapshot "
            "(planning_id, uid, id_display, structure_key, structure_kind, parent_uid, position, "
            "name, task_type, outline_number, outline_level, wbs, start_at, finish_at, "
            "duration_minutes, duration_format, work_minutes, percent_complete, is_summary, "
            "is_milestone, is_manual, calendar_uid) "
            "SELECT w.id, t.uid, t.id_display, t.structure_key, t.structure_kind, t.parent_uid, "
            "t.position, t.name, t.task_type, t.outline_number, t.outline_level, t.wbs, "
            "t.start_at, t.finish_at, t.duration_minutes, t.duration_format, t.work_minutes, "
            "t.percent_complete, t.is_summary, t.is_milestone, t.is_manual, t.calendar_uid "
            "FROM ms_task t JOIN wf_planning w ON w.project_id = t.project_id"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO wf_planning_link_snapshot "
            "(planning_id, task_uid, predecessor_uid, link_type, lag_tenth_minute, lag_format) "
            "SELECT w.id, l.task_uid, l.predecessor_uid, l.link_type, l.lag_tenth_minute, "
            "l.lag_format FROM ms_task_link l JOIN wf_planning w ON w.project_id = l.project_id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ms_project SET displayed_planning_id = "
            "(SELECT w.id FROM wf_planning w WHERE w.project_id = ms_project.id) "
            "WHERE EXISTS (SELECT 1 FROM ms_task t WHERE t.project_id = ms_project.id)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ms_project SET status = 'active' "
            "WHERE EXISTS (SELECT 1 FROM ms_task t WHERE t.project_id = ms_project.id)"
        )
    )
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.create_foreign_key(
            "fk_ms_project_planning_reference",
            "wf_planning",
            ["id", "planning_reference_id"],
            ["project_id", "id"],
        )
        batch_op.create_foreign_key(
            "fk_ms_project_displayed_planning",
            "wf_planning",
            ["id", "displayed_planning_id"],
            ["project_id", "id"],
        )


def downgrade() -> None:
    foreign_keys = {
        foreign_key.get("name")
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("ms_project")
    }
    constraints_to_drop = {
        "fk_ms_project_displayed_planning",
        "fk_ms_project_planning_reference",
    } & foreign_keys
    if constraints_to_drop:
        with op.batch_alter_table("ms_project") as batch_op:
            for constraint_name in constraints_to_drop:
                batch_op.drop_constraint(constraint_name, type_="foreignkey")
    op.drop_table("wf_planning_link_snapshot")
    op.drop_table("wf_planning_task_snapshot")
    op.drop_table("wf_planning")
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.drop_constraint("ck_ms_project_status", type_="check")
        batch_op.drop_column("displayed_planning_id")
        batch_op.drop_column("planning_reference_id")
        batch_op.drop_column("status")
