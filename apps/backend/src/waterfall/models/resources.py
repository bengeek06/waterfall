from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from waterfall.db.base import Base


class Calendar(Base):
    __tablename__ = "wf_calendar"
    __table_args__ = (
        UniqueConstraint("code", name="uq_wf_calendar_code"),
        CheckConstraint(
            "weeks_per_year >= 1 AND weeks_per_year <= 53",
            name="ck_wf_calendar_weeks_per_year",
        ),
        # At most one calendar system-wide may be flagged as the org-wide default
        # (issue #51): a partial unique index enforces this at the DB layer as the
        # backstop for the API-layer promotion guard in api/routes/resources.py.
        # SQLite (default test suite) and PostgreSQL (prod target) both need their own
        # dialect-specific partial-index kwarg to actually produce a partial index.
        Index(
            "uq_wf_calendar_is_default_true",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        # Issue #116 (E7-05): GET /resources/calendars filters on is_active and sorts
        # by code or name. uq_wf_calendar_code already covers the unfiltered
        # sort-by-code case (code is globally unique, so no tiebreaker column is
        # needed there); these two composites cover the WHERE is_active = ? ORDER BY
        # ... path -- the id tiebreaker column is only needed on the name index since
        # name (unlike code) is not unique and ties must be broken deterministically.
        Index("idx_wf_calendar_is_active_code", "is_active", "code"),
        Index("idx_wf_calendar_is_active_name", "is_active", "name", "id"),
        # include_inactive=true drops the is_active filter entirely, so a plain
        # ORDER BY name (no filter at all) can no longer be served by the
        # is_active-prefixed index above -- it groups rows by is_active first, so a
        # global name order can't be read off it without an extra sort step. code
        # needs no such counterpart: uq_wf_calendar_code already covers it globally.
        Index("idx_wf_calendar_name", "name", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    weeks_per_year: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CalendarWeekday(Base):
    """Weekly working hours per MS Project DayType (1=Sunday .. 7=Saturday)."""

    __tablename__ = "wf_calendar_weekday"
    __table_args__ = (
        UniqueConstraint("calendar_id", "day_type", name="uq_wf_calendar_weekday_day"),
        CheckConstraint(
            "day_type >= 1 AND day_type <= 7",
            name="ck_wf_calendar_weekday_day_type",
        ),
        CheckConstraint(
            "hours_per_day >= 0 AND hours_per_day <= 24",
            name="ck_wf_calendar_weekday_hours",
        ),
        Index("idx_wf_calendar_weekday_calendar", "calendar_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("wf_calendar.id"), nullable=False)
    day_type: Mapped[int] = mapped_column(Integer, nullable=False)
    hours_per_day: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ResourceNode(Base):
    __tablename__ = "wf_resource_node"
    __table_args__ = (
        UniqueConstraint("code", name="uq_wf_resource_node_code"),
        Index("idx_wf_resource_node_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("wf_resource_node.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ProjectCostCode(Base):
    """A project-scoped tree of user-defined cost-imputation codes (issue #62 / E6-01).

    Structurally identical to `ResourceNode` (self-referencing `parent_id`, `code` +
    `name` + `is_active`), but the uniqueness of `code` is scoped to `project_id`
    rather than global: two different projects may freely reuse the same code, so the
    unique constraint below is `(project_id, code)`, not a bare `code` unique index.
    Exactly one root row (`parent_id IS NULL`) is allowed per project -- enforced by
    the partial unique index below, the same pattern as
    `uq_wf_calendar_is_default_true` (issue #51) -- and is created automatically when
    the project itself is created (see `create_project` in api/routes/projects.py).
    """

    __tablename__ = "wf_project_cost_code"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_wf_project_cost_code_project_code"),
        Index("idx_wf_project_cost_code_project", "project_id"),
        Index("idx_wf_project_cost_code_parent", "parent_id"),
        Index(
            "uq_wf_project_cost_code_single_root",
            "project_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
            sqlite_where=text("parent_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_project_cost_code.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ResourceRole(Base):
    __tablename__ = "wf_resource_role"
    __table_args__ = (
        Index("idx_wf_resource_role_node", "node_id"),
        Index("idx_wf_resource_role_calendar", "calendar_id"),
        # Issue #116 (E7-05): GET /resources/roles always filters is_active and
        # defaults (and only) sorts by name. node_id is an optional extra equality/IN
        # filter, but it stays served by idx_wf_resource_role_node above rather than a
        # 3-column composite -- the roles under a single node are few enough that
        # applying it as a residual filter on top of this index is not worth doubling
        # the composite's write cost.
        Index("idx_wf_resource_role_is_active_name", "is_active", "name", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("wf_resource_node.id"), nullable=False)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_category.id"), nullable=False)
    calendar_id: Mapped[int | None] = mapped_column(ForeignKey("wf_calendar.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CostType(Base):
    __tablename__ = "wf_cost_type"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('labor', 'supply', 'other')",
            name="ck_wf_cost_type_kind",
        ),
        # Issue #116 (E7-05): GET /resources/cost-types filters on is_active and sorts
        # by code or name. code's own unique=True already covers the unfiltered
        # sort-by-code case, so idx_wf_cost_type_is_active_code (also unique-in-effect
        # since code alone is unique) needs no tiebreaker; name is not unique so its
        # composite carries the id tiebreaker.
        Index("idx_wf_cost_type_is_active_code", "is_active", "code"),
        Index("idx_wf_cost_type_is_active_name", "is_active", "name", "id"),
        # include_inactive=true drops the is_active filter, so a global ORDER BY name
        # can't be served by the is_active-prefixed index above (grouped by
        # is_active first). code needs no counterpart: its own unique=True already
        # covers it globally.
        Index("idx_wf_cost_type_name", "name", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CostCategory(Base):
    __tablename__ = "wf_cost_category"
    __table_args__ = (
        # Issue #116 (E7-05): GET /resources/categories filters on is_active and sorts
        # by accounting_code, category_code, or name. accounting_code is globally
        # unique (unique=True below) so its composite needs no tiebreaker; the other
        # two are not unique and carry the id tiebreaker.
        Index("idx_wf_cost_category_is_active_accounting_code", "is_active", "accounting_code"),
        Index("idx_wf_cost_category_is_active_category_code", "is_active", "category_code", "id"),
        Index("idx_wf_cost_category_is_active_name", "is_active", "name", "id"),
        # include_inactive=true drops the is_active filter, so global ORDER BY
        # category_code/name can't be served by the is_active-prefixed indexes above
        # (grouped by is_active first). accounting_code needs no counterpart: its
        # own unique=True already covers it globally.
        Index("idx_wf_cost_category_category_code", "category_code", "id"),
        Index("idx_wf_cost_category_name", "name", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cost_type_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_type.id"), nullable=False)
    accounting_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CostRate(Base):
    __tablename__ = "wf_cost_rate"
    __table_args__ = (
        UniqueConstraint("cost_category_id", "year", name="uq_wf_cost_rate_category_year"),
        CheckConstraint("year >= 2000", name="ck_wf_cost_rate_year"),
        CheckConstraint("hourly_rate >= 0", name="ck_wf_cost_rate_hourly_rate"),
        Index("idx_wf_cost_rate_year", "year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_category.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class InflationRate(Base):
    __tablename__ = "wf_inflation_rate"
    __table_args__ = (
        CheckConstraint("year >= 2000", name="ck_wf_inflation_rate_year"),
        CheckConstraint("coefficient > 0", name="ck_wf_inflation_rate_coefficient"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    coefficient: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class RoleCapacity(Base):
    __tablename__ = "wf_role_capacity"
    __table_args__ = (
        CheckConstraint("person_count >= 0", name="ck_wf_role_capacity_person_count"),
        CheckConstraint("available_hours >= 0", name="ck_wf_role_capacity_hours"),
        UniqueConstraint("role_id", name="uq_wf_role_capacity_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=False)
    person_count: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    available_hours: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class TaskRoleAssignment(Base):
    __tablename__ = "wf_task_role_assignment"
    __table_args__ = (
        UniqueConstraint("task_id", "role_id", name="uq_wf_task_role_assignment"),
        CheckConstraint("quantity > 0", name="ck_wf_task_role_quantity"),
        CheckConstraint("hours >= 0", name="ck_wf_task_role_hours"),
        Index("idx_wf_task_role_assignment_role", "role_id"),
        Index("idx_wf_task_role_assignment_cost_code", "cost_code_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("ms_task.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=False)
    # Issue #63 (E6-02): the project cost-imputation code this line of labor cost is
    # attached to. Nullable at the column level only because pre-existing rows have no
    # value to backfill from other than the project's root (see the migration); every
    # row created going forward always receives one -- either the caller's explicit
    # choice or the project's active root code (see resolve_cost_code_id).
    cost_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_project_cost_code.id"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class Estimate(Base):
    __tablename__ = "wf_estimate"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_wf_estimate_project_version"),
        CheckConstraint("version_number > 0", name="ck_wf_estimate_version"),
        CheckConstraint(
            "kind IN ('initial', 'contract_reference', 'forecast_remaining')",
            name="ck_wf_estimate_kind",
        ),
        CheckConstraint(
            "status IN ('draft', 'validated', 'superseded', 'archived')",
            name="ck_wf_estimate_status",
        ),
        # Issue #116 (E7-05): GET /projects/{id}/estimates always filters on
        # project_id. uq_wf_estimate_project_version already covers the default
        # sort-by-version_number path (version_number is unique per project, so no
        # ties, no tiebreaker column needed); kind, status and created_at are each
        # reachable via ?sort= and are not unique per project, so their composites
        # carry the id tiebreaker.
        Index("idx_wf_estimate_project_kind", "project_id", "kind", "id"),
        Index("idx_wf_estimate_project_status", "project_id", "status", "id"),
        Index("idx_wf_estimate_project_created_at", "project_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    planning_id: Mapped[int | None] = mapped_column(ForeignKey("wf_planning.id"), nullable=True)
    reference_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_estimate.id"), nullable=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class EstimateTaskRow(Base):
    __tablename__ = "wf_estimate_task_row"
    __table_args__ = (
        UniqueConstraint("estimate_id", "task_id", name="uq_wf_estimate_task_row"),
        Index("idx_wf_estimate_task_row_estimate_position", "estimate_id", "position"),
        # Issue #116 (E7-05): task_name, outline_number and outline_level are also
        # reachable via ?sort= on GET .../task-rows (position, the default sort, is
        # already covered above). None of the three is unique per estimate, so each
        # composite carries the id tiebreaker.
        Index("idx_wf_estimate_task_row_estimate_task_name", "estimate_id", "task_name", "id"),
        Index(
            "idx_wf_estimate_task_row_estimate_outline_number",
            "estimate_id",
            "outline_number",
            "id",
        ),
        Index(
            "idx_wf_estimate_task_row_estimate_outline_level",
            "estimate_id",
            "outline_level",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("wf_estimate.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("ms_task.id"), nullable=True)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("ms_task.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    task_name: Mapped[str] = mapped_column(String(512), nullable=False)
    outline_number: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outline_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_milestone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EstimateCostLine(Base):
    __tablename__ = "wf_estimate_cost_line"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_wf_estimate_cost_line_quantity"),
        CheckConstraint("unit_cost >= 0", name="ck_wf_estimate_cost_line_unit_cost"),
        CheckConstraint("purchase_cost >= 0", name="ck_wf_estimate_cost_line_purchase_cost"),
        CheckConstraint(
            "supply_status IN ('planned', 'ordered', 'received', 'cancelled') "
            "OR supply_status IS NULL",
            name="ck_wf_estimate_cost_line_supply_status",
        ),
        Index("idx_wf_estimate_cost_line_estimate", "estimate_id"),
        Index("idx_wf_estimate_cost_line_task", "task_id"),
        Index("idx_wf_estimate_cost_line_category", "cost_category_id"),
        # Issue #116 (E7-05): GET .../cost-lines always filters on estimate_id and has
        # no default_sort (any of label/quantity/unit_cost/purchase_cost/created_at
        # can be requested via ?sort=, none is unique per estimate), so each needs its
        # own composite with the id tiebreaker. An absent `?sort=` falls back to the
        # tiebreaker alone (`WHERE estimate_id = ? ORDER BY id`); the pre-existing
        # single-column idx_wf_estimate_cost_line_estimate above doesn't include id,
        # so that default path still needs its own composite too.
        Index("idx_wf_estimate_cost_line_estimate_id", "estimate_id", "id"),
        Index("idx_wf_estimate_cost_line_estimate_label", "estimate_id", "label", "id"),
        Index("idx_wf_estimate_cost_line_estimate_quantity", "estimate_id", "quantity", "id"),
        Index("idx_wf_estimate_cost_line_estimate_unit_cost", "estimate_id", "unit_cost", "id"),
        Index(
            "idx_wf_estimate_cost_line_estimate_purchase_cost",
            "estimate_id",
            "purchase_cost",
            "id",
        ),
        Index("idx_wf_estimate_cost_line_estimate_created_at", "estimate_id", "created_at", "id"),
        Index("idx_wf_estimate_cost_line_cost_code", "cost_code_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("wf_estimate.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("ms_task.id"), nullable=True)
    # Issue #63 (E6-02): see TaskRoleAssignment.cost_code_id above for the same
    # rationale -- nullable only because pre-existing rows are backfilled to the
    # project's root, every new row gets one via resolve_cost_code_id.
    cost_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_project_cost_code.id"), nullable=True
    )
    cost_type_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_type.id"), nullable=False)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_category.id"), nullable=False)
    cost_type_code: Mapped[str] = mapped_column(String(32), nullable=False)
    accounting_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    purchase_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    supply_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Issue #66 (E6-05): a forecast date for future cashflow curves, entirely
    # independent from task_id -- either, both, or neither may be set.
    planned_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class EstimateLine(Base):
    __tablename__ = "wf_estimate_line"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_wf_estimate_line_quantity"),
        CheckConstraint("hours >= 0", name="ck_wf_estimate_line_hours"),
        CheckConstraint("hourly_rate >= 0", name="ck_wf_estimate_line_rate"),
        CheckConstraint("inflation_coefficient > 0", name="ck_wf_estimate_line_inflation"),
        CheckConstraint("budget_cost >= 0", name="ck_wf_estimate_line_budget"),
        Index("idx_wf_estimate_line_estimate", "estimate_id"),
        Index("idx_wf_estimate_line_task", "task_id"),
        Index("idx_wf_estimate_line_role", "role_id"),
        Index("idx_wf_estimate_line_cost_code", "cost_code_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("wf_estimate.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("ms_task.id"), nullable=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=True)
    # Issue #63 (E6-02): frozen snapshot of the source line's cost_code_id at
    # validation time. Estimates validated before this issue shipped have no source to
    # retroactively recover this from, so those pre-existing EstimateLine rows are left
    # NULL by the migration (see 20260909_0010's docstring) rather than backfilled to
    # the project's root -- unlike TaskRoleAssignment/EstimateCostLine, which are still
    # live rows with a project to resolve a root from.
    cost_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_project_cost_code.id"), nullable=True
    )
    task_name: Mapped[str] = mapped_column(String(512), nullable=False)
    role_code: Mapped[str] = mapped_column(String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(String(255), nullable=False)
    accounting_code: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    inflation_coefficient: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    budget_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
