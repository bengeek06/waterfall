"""add project code and short description

Revision ID: 20260818_0011
Revises: 20260818_0010
Create Date: 2026-08-18 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0011"
down_revision = "20260818_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.add_column(sa.Column("code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("short_description", sa.String(length=500), nullable=True))
    op.create_index("idx_ms_project_code", "ms_project", ["code"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_ms_project_code", table_name="ms_project")
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.drop_column("short_description")
        batch_op.drop_column("code")
