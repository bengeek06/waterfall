"""drop resource role code

Revision ID: 20260831_0003
Revises: 20260829_0002
Create Date: 2026-08-31 09:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260831_0003"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wf_resource_role") as batch_op:
        batch_op.drop_constraint("uq_wf_resource_role_code", type_="unique")
        batch_op.drop_column("code")

    # EstimateLine.role_code is now derived from ResourceRole.name (String(255)) instead of
    # the removed ResourceRole.code (String(64)); widen the column to match so a long role
    # name doesn't raise a DataError at estimate-validation time.
    with op.batch_alter_table("wf_estimate_line") as batch_op:
        batch_op.alter_column(
            "role_code",
            existing_type=sa.String(64),
            type_=sa.String(255),
        )


def downgrade() -> None:
    with op.batch_alter_table("wf_estimate_line") as batch_op:
        # NOTE: if any role_code value exceeds 64 characters (possible now that it is
        # derived from ResourceRole.name, up to 255 chars), this downgrade will truncate
        # or fail depending on the backend. Not worse than the pre-fix state, where the
        # column was already String(64) and silently truncating was the status quo.
        batch_op.alter_column(
            "role_code",
            existing_type=sa.String(255),
            type_=sa.String(64),
        )

    with op.batch_alter_table("wf_resource_role") as batch_op:
        batch_op.add_column(sa.Column("code", sa.String(64), nullable=True))

    # Backfill a unique, non-empty code per existing row instead of a static server
    # default (which would collide on every row and break the unique constraint below
    # as soon as more than one row exists).
    connection = op.get_bind()
    role_table = sa.table(
        "wf_resource_role",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
    )
    role_ids = connection.execute(sa.select(role_table.c.id)).scalars().all()
    for role_id in role_ids:
        connection.execute(
            sa.update(role_table).where(role_table.c.id == role_id).values(code=f"role-{role_id}")
        )

    with op.batch_alter_table("wf_resource_role") as batch_op:
        batch_op.alter_column("code", existing_type=sa.String(64), nullable=False)
        batch_op.create_unique_constraint("uq_wf_resource_role_code", ["code"])
