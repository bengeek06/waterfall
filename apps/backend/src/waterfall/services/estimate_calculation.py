"""Deterministic cost calculation engine for estimate versioning."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    CostType,
    EstimateCostLine,
    EstimateLine,
    InflationRate,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.schemas.resources import CostTypeKind


def calculate_estimate_lines(db: Session, estimate_id: int) -> list[EstimateLine]:
    """
    Calculate and snapshot all estimate lines for a validated estimate.

    Rules:
    - Labor cost = quantity × hours_per_year × hourly_rate(year) × inflation(year)
    - Hours are distributed uniformly across task years when task spans multiple years.
    - Purchase cost for non-labor items is pre-calculated (quantity × unit_cost).
    - All snapshots (rate, inflation, codes) are frozen at validation.
    - `accounting_code` on labor lines is always derived from
      `role.cost_category.accounting_code` (the single source of truth), never from the
      role itself.

    Returns list of EstimateLine records to persist.
    """
    from waterfall.models.resources import Estimate

    estimate = db.query(Estimate).filter(Estimate.id == estimate_id).one()
    project = db.query(MsProject).filter(MsProject.id == estimate.project_id).one()

    lines: list[EstimateLine] = []

    # 1. Process labor (MO) lines from task role assignments
    assignments = (
        db.query(TaskRoleAssignment, MsTask, ResourceRole, CostCategory)
        .join(MsTask, TaskRoleAssignment.task_id == MsTask.id)
        .join(ResourceRole, TaskRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(MsTask.project_id == project.id)
        .all()
    )

    source_tasks: dict[int, WfPlanningTaskSnapshot] = {}
    if estimate.planning_id is not None:
        source_tasks = {
            task.uid: task
            for task in db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == estimate.planning_id)
            .all()
        }
        outside_source = [task.uid for _, task, _, _ in assignments if task.uid not in source_tasks]
        if outside_source:
            raise ValueError(
                "Estimate has role assignments outside its planning snapshot: "
                + ", ".join(str(uid) for uid in sorted(outside_source))
            )

    for assignment, task, role, category in assignments:
        labor_lines = _generate_labor_lines(
            db, estimate_id, assignment, task, role, category, source_tasks.get(task.uid)
        )
        lines.extend(labor_lines)

    # 2. Process non-labor lines (Fourniture, Frais, UO)
    cost_lines = (
        db.query(EstimateCostLine, CostType)
        .join(CostType, EstimateCostLine.cost_type_id == CostType.id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .all()
    )

    for cost_line, cost_type in cost_lines:
        # Skip MO cost types; they come from role assignments
        if cost_type.kind == CostTypeKind.LABOR:
            continue

        # Create a single EstimateLine snapshot for non-labor
        # Year is snapshot year (current year); these don't span years typically
        snapshot_year = datetime.now(UTC).year
        line = EstimateLine(
            estimate_id=estimate_id,
            task_id=cost_line.task_id,
            role_id=None,
            task_name=cost_line.label,
            role_code="",
            role_name="",
            accounting_code=cost_line.accounting_code,
            year=snapshot_year,
            quantity=cost_line.quantity,
            hours=Decimal("0"),
            hourly_rate=Decimal("0"),
            inflation_coefficient=Decimal("1"),
            budget_cost=cost_line.purchase_cost,
        )
        lines.append(line)

    return lines


def _generate_labor_lines(
    db: Session,
    estimate_id: int,
    assignment: TaskRoleAssignment,
    task: MsTask,
    role: ResourceRole,
    category: CostCategory,
    source_task: WfPlanningTaskSnapshot | None = None,
) -> list[EstimateLine]:
    """
    Generate EstimateLines for a task-role assignment, split by year if needed.

    If task spans multiple years (start_year != end_year), distribute hours uniformly
    across years. Apply year-specific rates and inflation coefficients.
    """
    lines: list[EstimateLine] = []

    schedule_task = source_task or task
    if not schedule_task.start_at or not schedule_task.finish_at:
        # Skip tasks without dates
        return lines

    start_year = schedule_task.start_at.year
    end_year = schedule_task.finish_at.year
    years_spanned = end_year - start_year + 1

    # Distribute total hours uniformly across years
    hours_per_year = assignment.hours / Decimal(years_spanned)

    for year_offset in range(years_spanned):
        year = start_year + year_offset

        # Fetch rate for this category and year
        rate_record = (
            db.query(CostRate)
            .filter(CostRate.cost_category_id == role.cost_category_id)
            .filter(CostRate.year == year)
            .first()
        )
        hourly_rate = rate_record.hourly_rate if rate_record else Decimal("0")

        # Fetch inflation coefficient
        inflation_record = db.query(InflationRate).filter(InflationRate.year == year).first()
        inflation_coefficient = inflation_record.coefficient if inflation_record else Decimal("1")

        # Calculate cost
        budget_cost = assignment.quantity * hours_per_year * hourly_rate * inflation_coefficient

        line = EstimateLine(
            estimate_id=estimate_id,
            task_id=task.id,
            role_id=role.id,
            task_name=schedule_task.name,
            role_code=role.name,
            role_name=role.name,
            accounting_code=category.accounting_code,
            year=year,
            quantity=assignment.quantity,
            hours=hours_per_year,
            hourly_rate=hourly_rate,
            inflation_coefficient=inflation_coefficient,
            budget_cost=budget_cost,
        )
        lines.append(line)

    return lines


class EstimateAggregates(TypedDict):
    total_labor_cost: Decimal
    total_purchase_cost: Decimal
    total_unburdened_cost: Decimal
    by_category: dict[str, Decimal]


def calculate_estimate_aggregates(db: Session, estimate_id: int) -> EstimateAggregates:
    """
    Calculate aggregate totals for an estimate by type, category, accounting code, etc.

    Returns dict of aggregate metrics for reporting and validation.
    """
    lines = db.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all()

    total_labor_cost: Decimal = Decimal("0")
    total_purchase_cost: Decimal = Decimal("0")
    total_unburdened_cost: Decimal = Decimal("0")
    by_category: dict[str, Decimal] = {}

    for line in lines:
        # Accumulate totals
        if line.role_id:  # Labor line
            total_labor_cost += line.budget_cost
        else:  # Non-labor line
            total_purchase_cost += line.budget_cost

        total_unburdened_cost += line.budget_cost

        # By category
        if line.accounting_code not in by_category:
            by_category[line.accounting_code] = Decimal("0")
        by_category[line.accounting_code] += line.budget_cost

    return {
        "total_labor_cost": total_labor_cost,
        "total_purchase_cost": total_purchase_cost,
        "total_unburdened_cost": total_unburdened_cost,
        "by_category": by_category,
    }
