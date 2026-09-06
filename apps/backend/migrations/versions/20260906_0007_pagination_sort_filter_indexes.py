"""pagination sort/filter indexes (E7-05, issue #116)

Adds the composite indexes needed to back every column exposed as sortable or
filterable by the pagination foundation added in EPIC E7 (#111-#115), so that
`WHERE <filter> ORDER BY <sort>, <tiebreaker>` queries can be satisfied by a
single index scan instead of a full-table sort.

Column order in each composite is [equality-filter column(s)..., sort column,
tiebreaker (the table's own primary key)], matching the ORDER BY clause built
by `apply_pagination` (services/pagination.py): `sort-or-default-or-tiebreaker,
tiebreaker`. The tiebreaker column is omitted where the sort column is already
unique within the filtered scope (e.g. a `UNIQUE` column, or unique together
with the leading filter column), since no ties can occur there and the plain
composite already yields a fully deterministic order.

Endpoints already covered by an existing `UniqueConstraint`/`unique=True`
column and left untouched here (verified by EXPLAIN on PostgreSQL, see PR
description): `wf_cost_rate` (both `/resources/categories/{id}/rates` via
`uq_wf_cost_rate_category_year`, and `/resources/rates` via the pre-existing
`idx_wf_cost_rate_year`), `wf_inflation_rate` (`year` is `unique=True`),
`wf_role_capacity` (`role_id` is `unique=True` via
`uq_wf_role_capacity_role`), and `wf_task_role_assignment` (the
`task_id`-leading `uq_wf_task_role_assignment` composite already narrows
`GET .../role-assignments` to a handful of rows per task before the sort/join
against `ResourceRole.name` even runs).

Revision ID: 20260906_0007
Revises: 20260903_0006
Create Date: 2026-09-06 00:00:00.000000

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260906_0007"
down_revision = "20260903_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GET /resources/calendars: filter is_active, sort code|name.
    op.create_index("idx_wf_calendar_is_active_code", "wf_calendar", ["is_active", "code"])
    op.create_index("idx_wf_calendar_is_active_name", "wf_calendar", ["is_active", "name", "id"])

    # GET /resources/roles: filter is_active (always), sort name.
    op.create_index(
        "idx_wf_resource_role_is_active_name", "wf_resource_role", ["is_active", "name", "id"]
    )

    # GET /resources/categories: filter is_active, sort accounting_code|category_code|name.
    op.create_index(
        "idx_wf_cost_category_is_active_accounting_code",
        "wf_cost_category",
        ["is_active", "accounting_code"],
    )
    op.create_index(
        "idx_wf_cost_category_is_active_category_code",
        "wf_cost_category",
        ["is_active", "category_code", "id"],
    )
    op.create_index(
        "idx_wf_cost_category_is_active_name", "wf_cost_category", ["is_active", "name", "id"]
    )

    # GET /resources/cost-types: filter is_active, sort code|name.
    op.create_index("idx_wf_cost_type_is_active_code", "wf_cost_type", ["is_active", "code"])
    op.create_index("idx_wf_cost_type_is_active_name", "wf_cost_type", ["is_active", "name", "id"])

    # GET /projects/{id}/estimates: filter project_id (always), sort
    # kind|status|created_at (version_number, the default sort, is already covered by
    # uq_wf_estimate_project_version).
    op.create_index("idx_wf_estimate_project_kind", "wf_estimate", ["project_id", "kind", "id"])
    op.create_index("idx_wf_estimate_project_status", "wf_estimate", ["project_id", "status", "id"])
    op.create_index(
        "idx_wf_estimate_project_created_at", "wf_estimate", ["project_id", "created_at", "id"]
    )

    # GET /projects/{id}/estimates/{id}/task-rows: filter estimate_id (always), sort
    # task_name|outline_number|outline_level (position, the default sort, is already
    # covered by idx_wf_estimate_task_row_estimate_position).
    op.create_index(
        "idx_wf_estimate_task_row_estimate_task_name",
        "wf_estimate_task_row",
        ["estimate_id", "task_name", "id"],
    )
    op.create_index(
        "idx_wf_estimate_task_row_estimate_outline_number",
        "wf_estimate_task_row",
        ["estimate_id", "outline_number", "id"],
    )
    op.create_index(
        "idx_wf_estimate_task_row_estimate_outline_level",
        "wf_estimate_task_row",
        ["estimate_id", "outline_level", "id"],
    )

    # GET /projects/{id}/estimates/{id}/cost-lines: filter estimate_id (always), no
    # default_sort -- every sortable column needs its own composite.
    op.create_index(
        "idx_wf_estimate_cost_line_estimate_label",
        "wf_estimate_cost_line",
        ["estimate_id", "label", "id"],
    )
    op.create_index(
        "idx_wf_estimate_cost_line_estimate_quantity",
        "wf_estimate_cost_line",
        ["estimate_id", "quantity", "id"],
    )
    op.create_index(
        "idx_wf_estimate_cost_line_estimate_unit_cost",
        "wf_estimate_cost_line",
        ["estimate_id", "unit_cost", "id"],
    )
    op.create_index(
        "idx_wf_estimate_cost_line_estimate_purchase_cost",
        "wf_estimate_cost_line",
        ["estimate_id", "purchase_cost", "id"],
    )
    op.create_index(
        "idx_wf_estimate_cost_line_estimate_created_at",
        "wf_estimate_cost_line",
        ["estimate_id", "created_at", "id"],
    )

    # GET /projects/{id}/plannings: filter project_id (always), sort
    # status|created_at (version_number, the default sort, is already covered by
    # uq_wf_planning_project_version).
    op.create_index("idx_wf_planning_project_status", "wf_planning", ["project_id", "status", "id"])
    op.create_index(
        "idx_wf_planning_project_created_at", "wf_planning", ["project_id", "created_at", "id"]
    )

    # GET /projects: filter owner_id (always), sort name|status|id.
    op.create_index("idx_ms_project_owner_name", "ms_project", ["owner_id", "name", "id"])
    op.create_index("idx_ms_project_owner_status", "ms_project", ["owner_id", "status", "id"])
    op.create_index("idx_ms_project_owner_id", "ms_project", ["owner_id", "id"])

    # GET /auth/users: no filter, sort created_at|is_active (email is already
    # unique+indexed).
    op.create_index("idx_users_created_at", "users", ["created_at", "id"])
    op.create_index("idx_users_is_active", "users", ["is_active", "id"])


def downgrade() -> None:
    op.drop_index("idx_users_is_active", table_name="users")
    op.drop_index("idx_users_created_at", table_name="users")

    op.drop_index("idx_ms_project_owner_id", table_name="ms_project")
    op.drop_index("idx_ms_project_owner_status", table_name="ms_project")
    op.drop_index("idx_ms_project_owner_name", table_name="ms_project")

    op.drop_index("idx_wf_planning_project_created_at", table_name="wf_planning")
    op.drop_index("idx_wf_planning_project_status", table_name="wf_planning")

    op.drop_index(
        "idx_wf_estimate_cost_line_estimate_created_at", table_name="wf_estimate_cost_line"
    )
    op.drop_index(
        "idx_wf_estimate_cost_line_estimate_purchase_cost", table_name="wf_estimate_cost_line"
    )
    op.drop_index(
        "idx_wf_estimate_cost_line_estimate_unit_cost", table_name="wf_estimate_cost_line"
    )
    op.drop_index("idx_wf_estimate_cost_line_estimate_quantity", table_name="wf_estimate_cost_line")
    op.drop_index("idx_wf_estimate_cost_line_estimate_label", table_name="wf_estimate_cost_line")

    op.drop_index(
        "idx_wf_estimate_task_row_estimate_outline_level", table_name="wf_estimate_task_row"
    )
    op.drop_index(
        "idx_wf_estimate_task_row_estimate_outline_number", table_name="wf_estimate_task_row"
    )
    op.drop_index("idx_wf_estimate_task_row_estimate_task_name", table_name="wf_estimate_task_row")

    op.drop_index("idx_wf_estimate_project_created_at", table_name="wf_estimate")
    op.drop_index("idx_wf_estimate_project_status", table_name="wf_estimate")
    op.drop_index("idx_wf_estimate_project_kind", table_name="wf_estimate")

    op.drop_index("idx_wf_cost_type_is_active_name", table_name="wf_cost_type")
    op.drop_index("idx_wf_cost_type_is_active_code", table_name="wf_cost_type")

    op.drop_index("idx_wf_cost_category_is_active_name", table_name="wf_cost_category")
    op.drop_index("idx_wf_cost_category_is_active_category_code", table_name="wf_cost_category")
    op.drop_index("idx_wf_cost_category_is_active_accounting_code", table_name="wf_cost_category")

    op.drop_index("idx_wf_resource_role_is_active_name", table_name="wf_resource_role")

    op.drop_index("idx_wf_calendar_is_active_name", table_name="wf_calendar")
    op.drop_index("idx_wf_calendar_is_active_code", table_name="wf_calendar")
