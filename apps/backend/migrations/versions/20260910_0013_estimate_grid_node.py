"""estimate grid node tree (E12-07, issue #289)

Introduces `wf_estimate_grid_node`: a devis-scoped, freely reorderable tree
position for `EstimateCostLine`/`EstimateRoleAssignment` rows, mirroring
`wf_planning_task_snapshot`'s own `uid`/`parent_uid`/`position` model. `uid`
is allocated downward from -1 per estimate (see
`waterfall.services.estimate_grid.next_estimate_grid_node_uid`), deliberately
disjoint from the positive `ms_task.id` space a node's `parent_uid` also
draws from when the node is attached directly under a task belonging to this
estimate's own `wf_estimate_task_row`s.

Also adds `wf_estimate.revision` (optimistic-concurrency counter for the new
`POST .../grid-nodes/move` endpoint, mirroring `wf_planning.revision`, see
20260903_0006) and makes `wf_estimate_role_assignment.task_id` nullable: a
role assignment can now be unindented all the way to the devis root, with no
ancestor task left to reference.

Backfill: every existing `wf_estimate_cost_line`/`wf_estimate_role_assignment`
row receives its own node -- `parent_uid` copied verbatim from the row's own
(possibly NULL) `task_id` (already the positive `ms_task.id` a node's
`parent_uid` uses for a task-attached node, no translation needed),
`position` the row's insertion order (`ORDER BY id`) within its own
`(estimate_id, parent_uid)` group, a group shared across both tables since
they occupy the same grid -- cost lines are allocated before role
assignments within a shared group, an arbitrary but deterministic tie-break.
No data is lost: every pre-existing line ends up attached to a valid node.

Revision ID: 20260910_0013
Revises: 20260909_0012
Create Date: 2026-09-10 10:00:00.000000

"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260910_0013"
down_revision = "20260909_0012"
branch_labels = None
depends_on = None

_NODE_TABLE = "wf_estimate_grid_node"


def upgrade() -> None:
    op.create_table(
        _NODE_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("parent_uid", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint("kind IN ('cost_line', 'labor')", name="ck_wf_estimate_grid_node_kind"),
        sa.ForeignKeyConstraint(["estimate_id"], ["wf_estimate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("estimate_id", "uid", name="uq_wf_estimate_grid_node_uid"),
    )
    op.create_index(
        "idx_wf_estimate_grid_node_estimate_parent",
        _NODE_TABLE,
        ["estimate_id", "parent_uid"],
        unique=False,
    )

    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.alter_column("revision", server_default=None)

    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.add_column(sa.Column("node_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("wf_estimate_role_assignment") as batch_op:
        batch_op.add_column(sa.Column("node_id", sa.Integer(), nullable=True))
        batch_op.alter_column("task_id", existing_type=sa.Integer(), nullable=True)

    _backfill_grid_nodes()

    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.alter_column("node_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_wf_estimate_cost_line_node", _NODE_TABLE, ["node_id"], ["id"]
        )
        batch_op.create_unique_constraint("uq_wf_estimate_cost_line_node", ["node_id"])
    with op.batch_alter_table("wf_estimate_role_assignment") as batch_op:
        batch_op.alter_column("node_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_wf_estimate_role_assignment_node", _NODE_TABLE, ["node_id"], ["id"]
        )
        batch_op.create_unique_constraint("uq_wf_estimate_role_assignment_node", ["node_id"])


def _backfill_grid_nodes() -> None:
    connection = op.get_bind()

    # A full `sa.Table` (not the lighter `sa.table`/`sa.column` used for the two
    # source tables below) is needed here so SQLAlchemy knows `id` is the
    # generated primary key and populates `result.inserted_primary_key` on
    # insert -- via RETURNING on PostgreSQL, `cursor.lastrowid` on SQLite --
    # which every other node the backfill loop below inserts is referenced by.
    node_metadata = sa.MetaData()
    node_table = sa.Table(
        _NODE_TABLE,
        node_metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("estimate_id", sa.Integer()),
        sa.Column("uid", sa.Integer()),
        sa.Column("parent_uid", sa.Integer()),
        sa.Column("position", sa.Integer()),
        sa.Column("kind", sa.String(16)),
    )
    cost_line_table = sa.table(
        "wf_estimate_cost_line",
        sa.column("id", sa.Integer),
        sa.column("estimate_id", sa.Integer),
        sa.column("task_id", sa.Integer),
        sa.column("node_id", sa.Integer),
    )
    role_assignment_table = sa.table(
        "wf_estimate_role_assignment",
        sa.column("id", sa.Integer),
        sa.column("estimate_id", sa.Integer),
        sa.column("task_id", sa.Integer),
        sa.column("node_id", sa.Integer),
    )

    cost_lines = connection.execute(
        sa.select(
            cost_line_table.c.id, cost_line_table.c.estimate_id, cost_line_table.c.task_id
        ).order_by(cost_line_table.c.id)
    ).all()
    role_assignments = connection.execute(
        sa.select(
            role_assignment_table.c.id,
            role_assignment_table.c.estimate_id,
            role_assignment_table.c.task_id,
        ).order_by(role_assignment_table.c.id)
    ).all()

    # -1, -2, ... per estimate -- mirrors next_estimate_grid_node_uid.
    next_uid_by_estimate: dict[int, int] = defaultdict(int)
    # Position counter per (estimate_id, parent_uid) group, shared across both
    # source tables (they occupy the same grid) -- see module docstring.
    next_position: dict[tuple[int, int | None], int] = defaultdict(int)

    def _allocate(estimate_id: int, task_id: int | None, kind: str) -> int:
        next_uid_by_estimate[estimate_id] -= 1
        uid = next_uid_by_estimate[estimate_id]
        position_key = (estimate_id, task_id)
        next_position[position_key] += 1
        position = next_position[position_key]
        result = connection.execute(
            sa.insert(node_table).values(
                estimate_id=estimate_id,
                uid=uid,
                parent_uid=task_id,
                position=position,
                kind=kind,
            )
        )
        inserted_id = result.inserted_primary_key
        assert inserted_id is not None
        return int(inserted_id[0])

    for row in cost_lines:
        node_id = _allocate(row.estimate_id, row.task_id, "cost_line")
        connection.execute(
            sa.update(cost_line_table).where(cost_line_table.c.id == row.id).values(node_id=node_id)
        )

    for row in role_assignments:
        node_id = _allocate(row.estimate_id, row.task_id, "labor")
        connection.execute(
            sa.update(role_assignment_table)
            .where(role_assignment_table.c.id == row.id)
            .values(node_id=node_id)
        )


def downgrade() -> None:
    with op.batch_alter_table("wf_estimate_role_assignment") as batch_op:
        batch_op.drop_constraint("uq_wf_estimate_role_assignment_node", type_="unique")
        batch_op.drop_constraint("fk_wf_estimate_role_assignment_node", type_="foreignkey")
        batch_op.drop_column("node_id")
        # Best-effort revert: fails if any role assignment was unindented to the
        # devis root (task_id set to NULL) by the feature this migration enabled
        # since it was applied -- an expected, called-out limitation of reverting
        # a NOT NULL constraint onto data that may no longer satisfy it.
        batch_op.alter_column("task_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("wf_estimate_cost_line") as batch_op:
        batch_op.drop_constraint("uq_wf_estimate_cost_line_node", type_="unique")
        batch_op.drop_constraint("fk_wf_estimate_cost_line_node", type_="foreignkey")
        batch_op.drop_column("node_id")
    with op.batch_alter_table("wf_estimate") as batch_op:
        batch_op.drop_column("revision")
    op.drop_index("idx_wf_estimate_grid_node_estimate_parent", table_name=_NODE_TABLE)
    op.drop_table(_NODE_TABLE)
