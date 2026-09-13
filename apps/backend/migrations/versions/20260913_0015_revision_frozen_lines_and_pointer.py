"""revision frozen lines and the project's revision pointers (E14-08, issue #334)

Two additions, both **strictly additive**, in the same spirit as 20260911_0014:

* `wf_revision_frozen_line`, the immutable financial document a validated revision
  produces, which #329 deliberately left out -- its shape could only be judged once
  the calculation engine existed, and it does since #364. One row per (chiffrage,
  year), the grain `wf_estimate_line` already had and the only grain at which an
  annual rate and an inflation coefficient mean anything. It carries `cost_code` and
  `nature` as **copies**, both added while this migration was still unshipped: the
  two tables it replaces carried an imputation code (`cost_code_id`, #63/E6-02) and
  split MO from Achat by table name, and a document that dropped either would answer
  "which imputation code, which nature?" only by joining the mutable structure Règle
  2 forbids it to depend on. A copied string and not a foreign key, for that reason;
* `wf_project_revision_pointer`, the single reference/displayed pair replacing the
  four pointers that had to agree with each other.

Nothing is dropped, renamed or backfilled. `ms_project.planning_reference_id`,
`ms_project.displayed_planning_id`, `ms_project.reference_estimate_id`,
`wf_estimate.planning_id` and the three ``use_alter`` foreign keys that close their
cycle all stay exactly where they are: routes, services and the project lifecycle
still read them at this point of the EPIC, and E14-12 (#339) is the destructive
counterpart once no consumer is left.

**The pointers are a table and not two columns on `ms_project`**, and that is the
one decision worth reading twice: `wf_revision` references `ms_project`, so a
pointer column *on* `ms_project` would close a second foreign-key cycle -- the very
one E14-12 removes. One table further out, the schema stays sortable in a single
topological order (``ms_project``, ``wf_revision``, then this table) and nothing has
to be added by a deferred ``ALTER``. See
:class:`waterfall.models.revision.ProjectRevisionPointer`.

The unique index `uq_wf_revision_project_id` is added for the two composite foreign
keys of that table alone: it is what makes "a project points at a revision **of its
own**" a database constraint. An *index* rather than a ``UniqueConstraint`` because
SQLite has no ``ALTER TABLE ADD CONSTRAINT``, while PostgreSQL takes a unique index
as a foreign-key target just as happily.

`downgrade()` drops exactly what `upgrade()` creates, in the reverse order, and
nothing else.

Revision ID: 20260913_0015
Revises: 20260911_0014
Create Date: 2026-09-13 09:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260913_0015"
down_revision = "20260911_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_wf_revision_project_id", "wf_revision", ["project_id", "id"], unique=True)
    op.create_table(
        "wf_revision_frozen_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("bearing_work_item_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("nature", sa.String(length=16), nullable=False),
        sa.Column("bearing_task_name", sa.String(length=512), nullable=True),
        sa.Column("role_name", sa.String(length=255), nullable=True),
        sa.Column("accounting_code", sa.String(length=64), nullable=True),
        sa.Column("category_code", sa.String(length=64), nullable=True),
        sa.Column("cost_code", sa.String(length=64), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("hours", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("inflation_coefficient", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("amount", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_wf_revision_frozen_line_amount"),
        sa.CheckConstraint(
            "hourly_rate IS NULL OR hourly_rate >= 0", name="ck_wf_revision_frozen_line_rate"
        ),
        sa.CheckConstraint("hours IS NULL OR hours >= 0", name="ck_wf_revision_frozen_line_hours"),
        sa.CheckConstraint(
            "inflation_coefficient IS NULL OR inflation_coefficient > 0",
            name="ck_wf_revision_frozen_line_inflation",
        ),
        sa.CheckConstraint(
            "nature IN ('labor', 'non_labor')", name="ck_wf_revision_frozen_line_nature"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_wf_revision_frozen_line_quantity"),
        sa.CheckConstraint("year IS NULL OR year > 0", name="ck_wf_revision_frozen_line_year"),
        sa.ForeignKeyConstraint(["bearing_work_item_id"], ["wf_work_item.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["wf_revision.id"]),
        sa.ForeignKeyConstraint(["work_item_id"], ["wf_work_item.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id", "work_item_id", "year", name="uq_wf_revision_frozen_line_year"
        ),
    )
    op.create_index(
        "idx_wf_revision_frozen_line_bearing",
        "wf_revision_frozen_line",
        ["bearing_work_item_id"],
        unique=False,
    )
    op.create_index(
        "idx_wf_revision_frozen_line_work_item",
        "wf_revision_frozen_line",
        ["work_item_id"],
        unique=False,
    )
    op.create_table(
        "wf_project_revision_pointer",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("reference_revision_id", sa.Integer(), nullable=True),
        sa.Column("displayed_revision_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "displayed_revision_id"],
            ["wf_revision.project_id", "wf_revision.id"],
            name="fk_wf_project_revision_pointer_displayed",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "reference_revision_id"],
            ["wf_revision.project_id", "wf_revision.id"],
            name="fk_wf_project_revision_pointer_reference",
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index(
        "idx_wf_project_revision_pointer_displayed",
        "wf_project_revision_pointer",
        ["displayed_revision_id"],
        unique=False,
    )
    op.create_index(
        "idx_wf_project_revision_pointer_reference",
        "wf_project_revision_pointer",
        ["reference_revision_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_wf_project_revision_pointer_reference", table_name="wf_project_revision_pointer"
    )
    op.drop_index(
        "idx_wf_project_revision_pointer_displayed", table_name="wf_project_revision_pointer"
    )
    op.drop_table("wf_project_revision_pointer")
    op.drop_index("idx_wf_revision_frozen_line_work_item", table_name="wf_revision_frozen_line")
    op.drop_index("idx_wf_revision_frozen_line_bearing", table_name="wf_revision_frozen_line")
    op.drop_table("wf_revision_frozen_line")
    op.drop_index("uq_wf_revision_project_id", table_name="wf_revision")
