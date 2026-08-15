"""create wf task enrichment table

Revision ID: 20260815_0003
Revises: 20260812_0002
Create Date: 2026-08-15 10:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260815_0003"
down_revision = "20260812_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wf_task_enrichment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_uid", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "task_uid"],
            ["ms_task.project_id", "ms_task.uid"],
            name="fk_wf_task_enrichment_task",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "task_uid", name="uq_wf_task_enrichment_task"),
    )
    op.create_index(
        "idx_wf_task_enrichment_task",
        "wf_task_enrichment",
        ["project_id", "task_uid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_wf_task_enrichment_task", table_name="wf_task_enrichment")
    op.drop_table("wf_task_enrichment")
