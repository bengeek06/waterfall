"""add planning revision for optimistic concurrency

Revision ID: 20260903_0006
Revises: 20260901_0005
Create Date: 2026-09-03 20:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260903_0006"
down_revision = "20260901_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wf_planning") as batch_op:
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("wf_planning") as batch_op:
        batch_op.alter_column("revision", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("wf_planning") as batch_op:
        batch_op.drop_column("revision")
