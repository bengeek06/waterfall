"""add project ownership

Revision ID: 20260818_0006
Revises: 20260816_0005
Create Date: 2026-08-18 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0006"
down_revision = "20260816_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_ms_project_owner", "users", ["owner_id"], ["id"])
        batch_op.create_index("idx_ms_project_owner", ["owner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.drop_index("idx_ms_project_owner")
        batch_op.drop_constraint("fk_ms_project_owner", type_="foreignkey")
        batch_op.drop_column("owner_id")
