"""estimate role assignment (E12-01, issue #273)

Introduces `wf_estimate_role_assignment`, a devis-version-scoped counterpart to
`wf_task_role_assignment`: two draft estimates of the same project may each carry
their own, independently editable labor role assignment for the same task/role
pair -- structurally impossible on `wf_task_role_assignment`, which is unique on
`(task_id, role_id)` alone, project-wide.

`wf_task_role_assignment` itself (and its use by `services/calendar_schedule.py`)
is left entirely untouched by this migration -- a later issue (E12-02/#274)
resynchronizes it from a validated estimate's own `wf_estimate_role_assignment`
rows.

Backfill: every `Estimate` currently at status `draft` receives its own,
independent copy of its project's current `wf_task_role_assignment` rows (a
project with two simultaneous draft estimates gets two independent copies, one
per estimate -- never a shared reference). `validated`/`superseded`/`archived`
estimates receive no copy at all: their labor cost is already frozen into
`wf_estimate_line` at validation time (see `services/estimate_calculation.py`),
so there is nothing left to reconcile against a live `wf_task_role_assignment`.

Revision ID: 20260909_0012
Revises: 20260909_0011
Create Date: 2026-09-09 18:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260909_0012"
down_revision = "20260909_0011"
branch_labels = None
depends_on = None

_TABLE = "wf_estimate_role_assignment"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("cost_code_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("hours", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hours >= 0", name="ck_wf_estimate_role_assignment_hours"),
        sa.CheckConstraint("quantity > 0", name="ck_wf_estimate_role_assignment_quantity"),
        sa.ForeignKeyConstraint(["cost_code_id"], ["wf_project_cost_code.id"]),
        sa.ForeignKeyConstraint(["estimate_id"], ["wf_estimate.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["wf_resource_role.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["ms_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "estimate_id", "task_id", "role_id", name="uq_wf_estimate_role_assignment"
        ),
    )
    op.create_index(
        "idx_wf_estimate_role_assignment_estimate", _TABLE, ["estimate_id"], unique=False
    )
    op.create_index("idx_wf_estimate_role_assignment_role", _TABLE, ["role_id"], unique=False)
    op.create_index(
        "idx_wf_estimate_role_assignment_cost_code", _TABLE, ["cost_code_id"], unique=False
    )

    # Backfill: one independent copy of the project's current wf_task_role_assignment
    # rows per currently-draft estimate of that project (see module docstring). A
    # plain INSERT ... SELECT ... JOIN is portable across SQLite and PostgreSQL,
    # unlike a correlated-subquery UPDATE (used elsewhere in this repo for a
    # single-row-per-target backfill) which doesn't fit a fan-out of N assignments
    # per estimate.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"""
            INSERT INTO {_TABLE}
                (estimate_id, task_id, role_id, cost_code_id, quantity, hours,
                 comment, created_at, updated_at)
            SELECT e.id, tra.task_id, tra.role_id, tra.cost_code_id, tra.quantity,
                   tra.hours, tra.comment, tra.created_at, tra.updated_at
            FROM wf_task_role_assignment AS tra
            JOIN ms_task AS t ON t.id = tra.task_id
            JOIN wf_estimate AS e ON e.project_id = t.project_id
            WHERE e.status = :draft_status
            """
        ),
        {"draft_status": "draft"},
    )


def downgrade() -> None:
    op.drop_index("idx_wf_estimate_role_assignment_cost_code", table_name=_TABLE)
    op.drop_index("idx_wf_estimate_role_assignment_role", table_name=_TABLE)
    op.drop_index("idx_wf_estimate_role_assignment_estimate", table_name=_TABLE)
    op.drop_table(_TABLE)
