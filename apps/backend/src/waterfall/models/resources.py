from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from waterfall.db.base import Base


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


class ResourceRole(Base):
    __tablename__ = "wf_resource_role"
    __table_args__ = (
        UniqueConstraint("code", name="uq_wf_resource_role_code"),
        Index("idx_wf_resource_role_node", "node_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("wf_resource_node.id"), nullable=False)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_category.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
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

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CostCategory(Base):
    __tablename__ = "wf_cost_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    cost_type_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_type.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    accounting_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    calendar_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        CheckConstraint("period_end > period_start", name="ck_wf_role_capacity_period"),
        CheckConstraint("person_count >= 0", name="ck_wf_role_capacity_person_count"),
        CheckConstraint("available_hours >= 0", name="ck_wf_role_capacity_hours"),
        Index("idx_wf_role_capacity_role_period", "role_id", "period_start", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("ms_task.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=False)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("wf_estimate.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("ms_task.id"), nullable=False)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("wf_estimate.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("ms_task.id"), nullable=True)
    cost_type_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_type.id"), nullable=False)
    cost_category_id: Mapped[int] = mapped_column(ForeignKey("wf_cost_category.id"), nullable=False)
    cost_type_code: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    accounting_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    purchase_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    supply_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("wf_estimate.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("ms_task.id"), nullable=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=True)
    task_name: Mapped[str] = mapped_column(String(512), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    role_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cost_category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    inflation_coefficient: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    budget_cost: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
