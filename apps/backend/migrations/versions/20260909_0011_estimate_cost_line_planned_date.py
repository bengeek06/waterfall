"""estimate cost line planned date (E6-05, issue #66)

Adds a nullable `planned_date` (`DateTime(timezone=True)`) column to
`wf_estimate_cost_line`, entirely independent from `task_id`: either, both, or
neither may be set on a given row. This prepares future cashflow curves (out of
scope here) without imposing any consistency constraint between the two fields.

No backfill is required or possible -- pre-existing rows simply keep `NULL`.

Revision ID: 20260909_0011
Revises: 20260909_0010
Create Date: 2026-09-09 13:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260909_0011"
down_revision = "20260909_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.add_column(sa.Column("planned_date", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.drop_column("planned_date")
