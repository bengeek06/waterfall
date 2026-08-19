"""add cost types and accounting codes

Revision ID: 20260818_0008
Revises: 20260818_0007
Create Date: 2026-08-18 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0008"
down_revision = "20260818_0007"
branch_labels = None
depends_on = None


COST_TYPES: list[dict[str, object]] = []


def upgrade() -> None:
    op.create_table(
        "wf_cost_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('labor', 'supply', 'other')",
            name="ck_wf_cost_type_kind",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    cost_type_table = sa.table(
        "wf_cost_type",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(cost_type_table, COST_TYPES)

    op.add_column("wf_cost_category", sa.Column("cost_type_id", sa.Integer(), nullable=True))
    op.add_column(
        "wf_cost_category",
        sa.Column("accounting_code", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE wf_cost_category SET cost_type_id = 1 WHERE cost_type_id IS NULL")

    with op.batch_alter_table("wf_cost_category") as batch_op:
        batch_op.alter_column("cost_type_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_wf_cost_category_type",
            "wf_cost_type",
            ["cost_type_id"],
            ["id"],
        )
        batch_op.create_index("idx_wf_cost_category_type", ["cost_type_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("wf_cost_category") as batch_op:
        batch_op.drop_index("idx_wf_cost_category_type")
        batch_op.drop_constraint("fk_wf_cost_category_type", type_="foreignkey")
        batch_op.drop_column("accounting_code")
        batch_op.drop_column("cost_type_id")
    op.drop_table("wf_cost_type")
