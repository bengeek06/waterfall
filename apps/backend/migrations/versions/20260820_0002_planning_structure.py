"""add canonical planning structure metadata

Revision ID: 20260820_0002
Revises: 20260819_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260820_0002"
down_revision = "20260819_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.add_column(sa.Column("structure_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("structure_kind", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("parent_uid", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_ms_task_project_structure_key", ["project_id", "structure_key"]
        )
        batch_op.create_check_constraint(
            "ck_ms_task_structure_kind",
            "structure_kind IN ('poste', 'lot', 'livrable', 'milestone', 'task') "
            "OR structure_kind IS NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.drop_constraint("ck_ms_task_structure_kind", type_="check")
        batch_op.drop_constraint("uq_ms_task_project_structure_key", type_="unique")
        batch_op.drop_column("position")
        batch_op.drop_column("parent_uid")
        batch_op.drop_column("structure_kind")
        batch_op.drop_column("structure_key")
