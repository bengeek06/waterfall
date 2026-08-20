"""constrain canonical planning parent metadata

Revision ID: 20260820_0003
Revises: 20260820_0002
"""

from __future__ import annotations

from alembic import op

revision = "20260820_0003"
down_revision = "20260820_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.create_foreign_key(
            "fk_ms_task_parent",
            "ms_task",
            ["project_id", "parent_uid"],
            ["project_id", "uid"],
        )
        batch_op.create_check_constraint(
            "ck_ms_task_parent_uid_positive",
            "parent_uid IS NULL OR parent_uid > 0",
        )
        batch_op.create_check_constraint(
            "ck_ms_task_position_positive",
            "position IS NULL OR position > 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.drop_constraint("ck_ms_task_parent_uid_positive", type_="check")
        batch_op.drop_constraint("ck_ms_task_position_positive", type_="check")
        batch_op.drop_constraint("fk_ms_task_parent", type_="foreignkey")