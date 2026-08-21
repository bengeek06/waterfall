"""store MS Project manual scheduling mode

Revision ID: 20260821_0004
Revises: 20260820_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20260821_0004"
down_revision = "20260820_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.add_column(sa.Column("is_manual", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ms_task") as batch_op:
        batch_op.drop_column("is_manual")
