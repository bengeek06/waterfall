"""widen project external uid

Revision ID: 20260901_0005
Revises: 20260901_0004
Create Date: 2026-09-01 22:15:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260901_0005"
down_revision = "20260901_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.alter_column(
            "external_uid",
            existing_type=sa.String(16),
            type_=sa.String(36),
        )


def downgrade() -> None:
    connection = op.get_bind()
    long_external_uid_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM ms_project WHERE LENGTH(external_uid) > 16")
    ).scalar()
    if long_external_uid_count:
        raise RuntimeError(
            f"Cannot downgrade: {long_external_uid_count} ms_project row(s) have an "
            "external_uid longer than 16 characters. Manually shorten or clear those "
            "values before downgrading."
        )

    with op.batch_alter_table("ms_project") as batch_op:
        batch_op.alter_column(
            "external_uid",
            existing_type=sa.String(36),
            type_=sa.String(16),
        )
