"""revision model tables (E14-03, issue #329)

Creates the six tables of the revision model -- `wf_work_item`, `wf_revision`,
`wf_revision_node`, its two facets `wf_revision_plan_facet` and
`wf_revision_cost_facet`, and the node-to-node precedence links
`wf_revision_node_link` -- as a translation of the pure domain proven on the test
bench of E14-02 (#328), see `waterfall.models.revision` for the invariant each
constraint carries.

**Strictly additive, deliberately.** Nothing is dropped, renamed or copied: the
new tables are created *next to* `ms_task`, `ms_task_link`,
`wf_planning_task_snapshot`, `wf_planning_link_snapshot`, `wf_estimate_task_row`,
`wf_estimate_grid_node`, `wf_charge_line`, `wf_task_enrichment` and
`wf_task_role_assignment`, which stay in place and keep serving every route,
service and calculation that still references them at this point of the EPIC.
The three `ms_project` revision pointers, `wf_estimate.planning_id` and their
`use_alter` foreign-key cycle are untouched for the same reason, and the
optimistic-lock counters `wf_planning.revision`/`wf_estimate.revision` are *not*
renamed to `lock_version` -- the current code still reads them. `wf_revision`
gets a `lock_version` column of its own, which is a new column, not a rename.
E14-12 (#339) is the destructive counterpart, once no consumer is left.

No backfill either: no production data exists to preserve (confirmed on the
EPIC), so the new tables start empty.

`downgrade()` drops exactly the six tables this migration creates, and nothing
else.

Revision ID: 20260911_0014
Revises: 20260910_0013
Create Date: 2026-09-11 18:14:38.233892

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260911_0014"
down_revision = "20260910_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wf_revision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('initial', 'contract_reference', 'forecast_remaining')",
            name="ck_wf_revision_kind",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'superseded')",
            name="ck_wf_revision_status",
        ),
        sa.CheckConstraint("lock_version >= 0", name="ck_wf_revision_lock_version"),
        sa.CheckConstraint("version_number > 0", name="ck_wf_revision_version"),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.ForeignKeyConstraint(["source_revision_id"], ["wf_revision.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version_number", name="uq_wf_revision_project_version"),
    )
    op.create_index(
        "idx_wf_revision_project_status",
        "wf_revision",
        ["project_id", "status", "id"],
        unique=False,
    )
    op.create_index(
        "idx_wf_revision_source_revision", "wf_revision", ["source_revision_id"], unique=False
    )
    # INV-22: at most one validated revision per (project, kind). Partial unique
    # index, hence the two dialect-specific kwargs -- same shape as
    # `uq_wf_calendar_is_default_true` (20260901_0004).
    op.create_index(
        "uq_wf_revision_validated_per_kind",
        "wf_revision",
        ["project_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'validated'"),
        sqlite_where=sa.text("status = 'validated'"),
    )
    op.create_table(
        "wf_work_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("external_uid", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "external_uid IS NULL OR kind = 'task'",
            name="ck_wf_work_item_external_uid_task_only",
        ),
        sa.CheckConstraint("kind IN ('task', 'cost')", name="ck_wf_work_item_kind"),
        sa.CheckConstraint(
            "external_uid IS NULL OR external_uid >= 0",
            name="ck_wf_work_item_external_uid_non_negative",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["ms_project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "kind", name="uq_wf_work_item_id_kind"),
        sa.UniqueConstraint("project_id", "external_uid", name="uq_wf_work_item_external_uid"),
    )
    op.create_table(
        "wf_revision_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('task', 'cost')", name="ck_wf_revision_node_kind"),
        sa.CheckConstraint("position > 0", name="ck_wf_revision_node_position"),
        sa.ForeignKeyConstraint(
            ["revision_id", "parent_id"],
            ["wf_revision_node.revision_id", "wf_revision_node.id"],
            name="fk_wf_revision_node_parent",
        ),
        sa.ForeignKeyConstraint(["revision_id"], ["wf_revision.id"]),
        sa.ForeignKeyConstraint(
            ["work_item_id", "kind"],
            ["wf_work_item.id", "wf_work_item.kind"],
            name="fk_wf_revision_node_work_item",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "kind", name="uq_wf_revision_node_id_kind"),
        sa.UniqueConstraint("parent_id", "position", name="uq_wf_revision_node_sibling_position"),
        sa.UniqueConstraint("revision_id", "id", name="uq_wf_revision_node_revision_id"),
        sa.UniqueConstraint("revision_id", "work_item_id", name="uq_wf_revision_node_work_item"),
    )
    op.create_index(
        "idx_wf_revision_node_revision_parent",
        "wf_revision_node",
        ["revision_id", "parent_id", "position"],
        unique=False,
    )
    # "In which revisions does this work item appear?", and the referencing side
    # of `fk_wf_revision_node_work_item`, unindexed otherwise.
    op.create_index(
        "idx_wf_revision_node_work_item", "wf_revision_node", ["work_item_id"], unique=False
    )
    # INV-05 for the root siblings: `uq_wf_revision_node_sibling_position` above
    # cannot see them, SQL comparing NULL to NULL as unknown.
    op.create_index(
        "uq_wf_revision_node_root_position",
        "wf_revision_node",
        ["revision_id", "position"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
        sqlite_where=sa.text("parent_id IS NULL"),
    )
    op.create_table(
        "wf_revision_cost_facet",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("node_kind", sa.String(length=16), nullable=False),
        sa.Column("nature", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("hours", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("cost_type_id", sa.Integer(), nullable=True),
        sa.Column("cost_category_id", sa.Integer(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("supply_status", sa.String(length=16), nullable=True),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("cost_code_id", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(nature = 'labor' AND role_id IS NOT NULL AND hours IS NOT NULL "
            "AND cost_type_id IS NULL AND cost_category_id IS NULL "
            "AND unit_cost IS NULL AND supply_status IS NULL) OR "
            "(nature = 'non_labor' AND role_id IS NULL AND hours IS NULL "
            "AND cost_type_id IS NOT NULL AND cost_category_id IS NOT NULL "
            "AND unit_cost IS NOT NULL)",
            name="ck_wf_revision_cost_facet_shape",
        ),
        sa.CheckConstraint(
            "nature IN ('labor', 'non_labor')", name="ck_wf_revision_cost_facet_nature"
        ),
        sa.CheckConstraint("node_kind = 'cost'", name="ck_wf_revision_cost_facet_node_kind"),
        sa.CheckConstraint(
            "supply_status IN ('planned', 'ordered', 'received', 'cancelled') "
            "OR supply_status IS NULL",
            name="ck_wf_revision_cost_facet_supply_status",
        ),
        sa.CheckConstraint("hours IS NULL OR hours >= 0", name="ck_wf_revision_cost_facet_hours"),
        sa.CheckConstraint("quantity > 0", name="ck_wf_revision_cost_facet_quantity"),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0", name="ck_wf_revision_cost_facet_unit_cost"
        ),
        sa.ForeignKeyConstraint(["cost_category_id"], ["wf_cost_category.id"]),
        sa.ForeignKeyConstraint(["cost_code_id"], ["wf_project_cost_code.id"]),
        sa.ForeignKeyConstraint(["cost_type_id"], ["wf_cost_type.id"]),
        sa.ForeignKeyConstraint(
            ["node_id", "node_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_cost_facet_node",
        ),
        sa.ForeignKeyConstraint(["role_id"], ["wf_resource_role.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", name="uq_wf_revision_cost_facet_node"),
    )
    op.create_index(
        "idx_wf_revision_cost_facet_category",
        "wf_revision_cost_facet",
        ["cost_category_id"],
        unique=False,
    )
    op.create_index(
        "idx_wf_revision_cost_facet_cost_code",
        "wf_revision_cost_facet",
        ["cost_code_id"],
        unique=False,
    )
    op.create_index(
        "idx_wf_revision_cost_facet_cost_type",
        "wf_revision_cost_facet",
        ["cost_type_id"],
        unique=False,
    )
    op.create_index(
        "idx_wf_revision_cost_facet_role", "wf_revision_cost_facet", ["role_id"], unique=False
    )
    op.create_table(
        "wf_revision_node_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("node_kind", sa.String(length=16), nullable=False),
        sa.Column("predecessor_node_id", sa.Integer(), nullable=False),
        sa.Column("predecessor_kind", sa.String(length=16), nullable=False),
        sa.Column("link_type", sa.SmallInteger(), nullable=False),
        sa.Column("lag_tenth_minute", sa.Integer(), nullable=False),
        sa.Column("lag_format", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("link_type IN (0, 1, 2, 3)", name="ck_wf_revision_node_link_type"),
        sa.CheckConstraint(
            "node_id <> predecessor_node_id", name="ck_wf_revision_node_link_not_self"
        ),
        # INV-17: both ends of a precedence link are task nodes.
        sa.CheckConstraint("node_kind = 'task'", name="ck_wf_revision_node_link_node_kind"),
        sa.CheckConstraint(
            "predecessor_kind = 'task'", name="ck_wf_revision_node_link_predecessor_kind"
        ),
        sa.ForeignKeyConstraint(
            ["node_id", "node_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_node_link_node_kind",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_node_id", "predecessor_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_node_link_predecessor_kind",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "node_id"],
            ["wf_revision_node.revision_id", "wf_revision_node.id"],
            name="fk_wf_revision_node_link_node",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "predecessor_node_id"],
            ["wf_revision_node.revision_id", "wf_revision_node.id"],
            name="fk_wf_revision_node_link_predecessor",
        ),
        sa.ForeignKeyConstraint(["revision_id"], ["wf_revision.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "node_id", "predecessor_node_id", "link_type", name="uq_wf_revision_node_link"
        ),
    )
    op.create_index(
        "idx_wf_revision_node_link_predecessor",
        "wf_revision_node_link",
        ["revision_id", "predecessor_node_id"],
        unique=False,
    )
    op.create_table(
        "wf_revision_plan_facet",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("node_kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("calendar_id", sa.Integer(), nullable=False),
        sa.Column("calendar_source", sa.String(length=16), nullable=False),
        sa.Column("is_milestone", sa.Boolean(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("duration_format", sa.SmallInteger(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("work_minutes", sa.Integer(), nullable=True),
        sa.Column("percent_complete", sa.SmallInteger(), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "calendar_source IN ('project', 'role', 'manual')",
            name="ck_wf_revision_plan_facet_calendar_source",
        ),
        sa.CheckConstraint("node_kind = 'task'", name="ck_wf_revision_plan_facet_node_kind"),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_wf_revision_plan_facet_duration",
        ),
        sa.CheckConstraint(
            "percent_complete BETWEEN 0 AND 100",
            name="ck_wf_revision_plan_facet_percent_complete",
        ),
        sa.CheckConstraint(
            "work_minutes IS NULL OR work_minutes >= 0", name="ck_wf_revision_plan_facet_work"
        ),
        sa.ForeignKeyConstraint(["calendar_id"], ["wf_calendar.id"]),
        sa.ForeignKeyConstraint(
            ["node_id", "node_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_plan_facet_node",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", name="uq_wf_revision_plan_facet_node"),
    )
    op.create_index(
        "idx_wf_revision_plan_facet_calendar",
        "wf_revision_plan_facet",
        ["calendar_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_wf_revision_plan_facet_calendar", table_name="wf_revision_plan_facet")
    op.drop_table("wf_revision_plan_facet")
    op.drop_index("idx_wf_revision_node_link_predecessor", table_name="wf_revision_node_link")
    op.drop_table("wf_revision_node_link")
    op.drop_index("idx_wf_revision_cost_facet_role", table_name="wf_revision_cost_facet")
    op.drop_index("idx_wf_revision_cost_facet_cost_type", table_name="wf_revision_cost_facet")
    op.drop_index("idx_wf_revision_cost_facet_cost_code", table_name="wf_revision_cost_facet")
    op.drop_index("idx_wf_revision_cost_facet_category", table_name="wf_revision_cost_facet")
    op.drop_table("wf_revision_cost_facet")
    op.drop_index(
        "uq_wf_revision_node_root_position",
        table_name="wf_revision_node",
        postgresql_where=sa.text("parent_id IS NULL"),
        sqlite_where=sa.text("parent_id IS NULL"),
    )
    op.drop_index("idx_wf_revision_node_work_item", table_name="wf_revision_node")
    op.drop_index("idx_wf_revision_node_revision_parent", table_name="wf_revision_node")
    op.drop_table("wf_revision_node")
    op.drop_table("wf_work_item")
    op.drop_index(
        "uq_wf_revision_validated_per_kind",
        table_name="wf_revision",
        postgresql_where=sa.text("status = 'validated'"),
        sqlite_where=sa.text("status = 'validated'"),
    )
    op.drop_index("idx_wf_revision_source_revision", table_name="wf_revision")
    op.drop_index("idx_wf_revision_project_status", table_name="wf_revision")
    op.drop_table("wf_revision")
