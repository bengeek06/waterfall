"""cost line cost code attachment (E6-02, issue #63)

Adds a nullable `cost_code_id` FK to `wf_project_cost_code` on three tables:

- `wf_task_role_assignment` (labor lines, source of `EstimateLine`'s MO rows).
- `wf_estimate_cost_line` (non-labor lines: Fourniture/Frais/UO).
- `wf_estimate_line` (the frozen snapshot generated at estimate validation).

`wf_task_role_assignment` and `wf_estimate_cost_line` are backfilled to their
project's active root cost code -- the same default the API now applies to every
row created without an explicit `cost_code_id` (see `resolve_cost_code_id` in
api/routes/project_cost_codes.py). Both are live rows with a project to resolve a
root from, via `ms_task.project_id` and `wf_estimate.project_id` respectively.

`wf_estimate_line` is deliberately left NULL for every pre-existing row instead of
backfilled: it is a frozen snapshot taken at validation time, and by the time this
migration runs, an already-validated estimate's lines have no live source
(`TaskRoleAssignment`/`EstimateCostLine`) to reliably attribute a cost code from --
the source row's own `cost_code_id` did not exist yet at the moment that snapshot
was taken, so there is no historically accurate value to reconstruct. Falling back
to "the project's current root" for old snapshots would silently fabricate
attribution data for lines that were never actually classified, which is worse than
an honest NULL. Only new estimates validated after this migration ships copy a real
`cost_code_id` into `wf_estimate_line` (see `services/estimate_calculation.py`).

Revision ID: 20260909_0010
Revises: 20260909_0009
Create Date: 2026-09-09 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260909_0010"
down_revision = "20260909_0009"
branch_labels = None
depends_on = None

_TASK_ROLE_ASSIGNMENT_FK = "fk_wf_task_role_assignment_cost_code"
_TASK_ROLE_ASSIGNMENT_INDEX = "idx_wf_task_role_assignment_cost_code"
_ESTIMATE_COST_LINE_FK = "fk_wf_estimate_cost_line_cost_code"
_ESTIMATE_COST_LINE_INDEX = "idx_wf_estimate_cost_line_cost_code"
_ESTIMATE_LINE_FK = "fk_wf_estimate_line_cost_code"
_ESTIMATE_LINE_INDEX = "idx_wf_estimate_line_cost_code"


def upgrade() -> None:
    with op.batch_alter_table("wf_task_role_assignment") as batch_op:
        batch_op.add_column(sa.Column("cost_code_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            _TASK_ROLE_ASSIGNMENT_FK, "wf_project_cost_code", ["cost_code_id"], ["id"]
        )
        batch_op.create_index(_TASK_ROLE_ASSIGNMENT_INDEX, ["cost_code_id"], unique=False)

    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.add_column(sa.Column("cost_code_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            _ESTIMATE_COST_LINE_FK, "wf_project_cost_code", ["cost_code_id"], ["id"]
        )
        batch_op.create_index(_ESTIMATE_COST_LINE_INDEX, ["cost_code_id"], unique=False)

    with op.batch_alter_table("wf_estimate_line") as batch_op:
        batch_op.add_column(sa.Column("cost_code_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            _ESTIMATE_LINE_FK, "wf_project_cost_code", ["cost_code_id"], ["id"]
        )
        batch_op.create_index(_ESTIMATE_LINE_INDEX, ["cost_code_id"], unique=False)

    connection = op.get_bind()

    # Backfill wf_task_role_assignment from its task's project's active root cost
    # code. A correlated subquery (rather than a Python-side fetch-then-update loop)
    # keeps this portable across SQLite and PostgreSQL without pulling every row into
    # memory -- both dialects support a scalar subquery inside UPDATE ... SET.
    connection.execute(
        sa.text(
            """
            UPDATE wf_task_role_assignment
            SET cost_code_id = (
                SELECT root.id
                FROM wf_project_cost_code AS root
                JOIN ms_task AS t ON t.project_id = root.project_id
                WHERE t.id = wf_task_role_assignment.task_id
                  AND root.parent_id IS NULL
                  AND root.is_active = :is_active
            )
            WHERE cost_code_id IS NULL
            """
        ),
        {"is_active": True},
    )

    # Backfill wf_estimate_cost_line from its estimate's project's active root cost
    # code, same rationale as above.
    connection.execute(
        sa.text(
            """
            UPDATE wf_estimate_cost_line
            SET cost_code_id = (
                SELECT root.id
                FROM wf_project_cost_code AS root
                JOIN wf_estimate AS e ON e.project_id = root.project_id
                WHERE e.id = wf_estimate_cost_line.estimate_id
                  AND root.parent_id IS NULL
                  AND root.is_active = :is_active
            )
            WHERE cost_code_id IS NULL
            """
        ),
        {"is_active": True},
    )

    # wf_estimate_line is intentionally NOT backfilled -- see module docstring.


def downgrade() -> None:
    with op.batch_alter_table("wf_estimate_line") as batch_op:
        batch_op.drop_index(_ESTIMATE_LINE_INDEX)
        batch_op.drop_constraint(_ESTIMATE_LINE_FK, type_="foreignkey")
        batch_op.drop_column("cost_code_id")

    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.drop_index(_ESTIMATE_COST_LINE_INDEX)
        batch_op.drop_constraint(_ESTIMATE_COST_LINE_FK, type_="foreignkey")
        batch_op.drop_column("cost_code_id")

    with op.batch_alter_table("wf_task_role_assignment") as batch_op:
        batch_op.drop_index(_TASK_ROLE_ASSIGNMENT_INDEX)
        batch_op.drop_constraint(_TASK_ROLE_ASSIGNMENT_FK, type_="foreignkey")
        batch_op.drop_column("cost_code_id")
