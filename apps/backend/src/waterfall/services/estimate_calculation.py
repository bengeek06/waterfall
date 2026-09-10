"""Deterministic cost calculation engine for estimate versioning."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    CostType,
    EstimateCostLine,
    EstimateLine,
    EstimateRoleAssignment,
    InflationRate,
    ProjectCostCode,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.schemas.projects import EstimateValidationWarning
from waterfall.schemas.resources import CostTypeKind


def collect_missing_rate_coverage(
    db: Session, category_years: list[tuple[CostCategory, int]]
) -> tuple[list[tuple[CostCategory, int]], list[int]]:
    """Check a set of (cost category, year) combinations for `CostRate`/`InflationRate`
    coverage, in a single pair of bulk queries.

    Shared by `create_estimate_role_assignment` (creation-time guard,
    `api/routes/estimates.py`) and `calculate_estimate_lines` (validation-time guard) so both
    report the exact same missing combinations for the exact same input, and so a devis with
    many affected assignments still gets one query pair, not one per assignment/year
    (E6-11/#175).

    Returns a `(missing_cost_rates, missing_inflation_years)` pair, both sorted for a
    deterministic, human-readable message: `missing_cost_rates` is deduplicated and
    sorted by `(category.accounting_code, year)`, `missing_inflation_years` is the
    deduplicated, sorted set of years (from `category_years`) with no `InflationRate`,
    independently of category. Empty lists mean full coverage -- caller behavior is
    unchanged in that case.
    """
    if not category_years:
        return [], []

    category_ids = {category.id for category, _year in category_years}
    years = {year for _category, year in category_years}

    existing_rate_pairs = {
        (cost_category_id, year)
        for cost_category_id, year in db.query(CostRate.cost_category_id, CostRate.year)
        .filter(CostRate.cost_category_id.in_(category_ids))
        .filter(CostRate.year.in_(years))
        .all()
    }
    existing_inflation_years = {
        year for (year,) in db.query(InflationRate.year).filter(InflationRate.year.in_(years)).all()
    }

    seen_missing_pairs: set[tuple[int, int]] = set()
    missing_cost_rates: list[tuple[CostCategory, int]] = []
    missing_inflation_years: set[int] = set()
    for category, year in category_years:
        pair_key = (category.id, year)
        if pair_key not in existing_rate_pairs and pair_key not in seen_missing_pairs:
            seen_missing_pairs.add(pair_key)
            missing_cost_rates.append((category, year))
        if year not in existing_inflation_years:
            missing_inflation_years.add(year)

    missing_cost_rates.sort(key=lambda pair: (pair[0].accounting_code, pair[1]))
    return missing_cost_rates, sorted(missing_inflation_years)


def format_missing_rate_message(
    missing_cost_rates: list[tuple[CostCategory, int]], missing_inflation_years: list[int]
) -> str:
    """Render `collect_missing_rate_coverage`'s result as a single actionable message
    that names every missing (category, year) `CostRate` and every missing
    `InflationRate` year -- not just the first one found (E6-11/#175).

    Human-readable only: kept for internal logging (``MissingRateCoverageError``'s
    ``str()``, e.g. in application logs) and as a building block for a future
    frontend text rendering of ``missing_rate_coverage_detail``'s structured
    payload -- it must never be passed to ``HTTPException(detail=...)`` directly,
    since a plain string/list ``detail`` is rewritten into an opaque
    ``{"code": "GENERIC_ERROR"}`` by ``_generic_http_exception_handler`` before it
    reaches any real HTTP client (E6-11/#175 review finding).
    """
    parts: list[str] = []
    if missing_cost_rates:
        pairs = ", ".join(
            f"{category.name} ({category.accounting_code})/{year}"
            for category, year in missing_cost_rates
        )
        parts.append(f"Missing hourly cost rate for: {pairs}")
    if missing_inflation_years:
        years = ", ".join(str(year) for year in missing_inflation_years)
        parts.append(f"Missing inflation rate for year(s): {years}")
    return "; ".join(parts)


def missing_rate_coverage_detail(
    missing_cost_rates: list[tuple[CostCategory, int]], missing_inflation_years: list[int]
) -> dict[str, object]:
    """Build the structured ``HTTPException.detail`` payload -- ``{"code":
    "MISSING_RATE_COVERAGE", ...}``, matching
    ``schemas.projects.MissingRateCoverageDetail`` -- for a missing (cost
    category, year) ``CostRate``/``InflationRate`` combination.

    Shared by ``create_estimate_role_assignment`` (``api/routes/estimates.py``, calls
    ``collect_missing_rate_coverage`` directly) and ``validate_project_estimate``
    (``api/routes/estimates.py``, via ``MissingRateCoverageError``) so both
    endpoints report the exact same JSON shape for the exact same input
    (E6-11/#175 review finding: a plain-string ``detail`` never reaches a real
    HTTP client, see ``format_missing_rate_message``).
    """
    return {
        "code": "MISSING_RATE_COVERAGE",
        "missing_cost_rates": [
            {
                "category_id": category.id,
                "category_name": category.name,
                "accounting_code": category.accounting_code,
                "year": year,
            }
            for category, year in missing_cost_rates
        ],
        "missing_inflation_years": missing_inflation_years,
    }


class MissingRateCoverageError(ValueError):
    """Raised by ``calculate_estimate_lines`` when a labor assignment covers a
    (cost category, year) with no ``CostRate``, or a year with no
    ``InflationRate`` (E6-11/#175).

    Carries ``collect_missing_rate_coverage``'s raw result (not just a rendered
    string) so the caller (``validate_project_estimate``,
    ``api/routes/estimates.py``) can build a structured, machine-readable
    ``HTTPException.detail`` via ``missing_rate_coverage_detail`` instead of a
    human-readable message -- ``_generic_http_exception_handler`` would
    otherwise rewrite the latter into an opaque ``{"code": "GENERIC_ERROR"}``
    before it reaches the client (review finding).
    """

    def __init__(
        self,
        missing_cost_rates: list[tuple[CostCategory, int]],
        missing_inflation_years: list[int],
    ) -> None:
        self.missing_cost_rates = missing_cost_rates
        self.missing_inflation_years = missing_inflation_years
        super().__init__(format_missing_rate_message(missing_cost_rates, missing_inflation_years))


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
    - Every (cost category, year) a labor assignment covers must have a `CostRate`, and
      every such year must have an `InflationRate` -- validation is refused outright
      (via `MissingRateCoverageError`, see below) rather than silently emitting a
      zero-rate/neutral-inflation line (E6-11/#175).
    - A labor assignment detached from every task (`EstimateRoleAssignment.task_id IS
      NULL` -- a devis-root MO line, see issue #289/E12-07) is never dropped: it has no
      task dates to derive a multi-year split from, so it produces exactly one
      `EstimateLine` snapshotted at the current calendar year, mirroring how a
      task-less non-labor `EstimateCostLine` (section "2." below) already snapshots at
      `datetime.now(UTC).year` rather than being silently excluded from every total
      (review finding on #289: an `INNER JOIN` on `MsTask` here used to make such a
      line vanish from `assignments`, and therefore from `total_labor_cost`, with no
      signal at all).

    Raises:
        ValueError: assignments reference a task outside the estimate's planning
            snapshot.
        MissingRateCoverageError: at least one (cost category, year) combination
            used by a labor assignment has no `CostRate`/`InflationRate` --
            carries every missing combination found, not just the first (see
            `missing_rate_coverage_detail` for how a caller turns this into an
            actionable HTTP response). No `EstimateLine` is generated (and
            therefore nothing is persisted by the caller) when this is raised.

    Returns list of EstimateLine records to persist.
    """
    from waterfall.models.resources import Estimate

    estimate = db.query(Estimate).filter(Estimate.id == estimate_id).one()

    lines: list[EstimateLine] = []

    # 1. Process labor (MO) lines from this estimate's own role assignments
    # (E12-02/#274: EstimateRoleAssignment is devis-version-scoped, unlike the
    # legacy project-wide TaskRoleAssignment it replaces here).
    # Issue #289 (E12-07) review finding: `task_id` is nullable (a devis-root MO
    # line, detached from every task) -- an INNER JOIN here would silently drop
    # such a row from `assignments`, and therefore from every total below, with
    # no signal at all. LEFT JOIN keeps it, with `task=None` handled explicitly
    # everywhere below (see `_generate_labor_lines`).
    assignments = (
        db.query(EstimateRoleAssignment, MsTask, ResourceRole, CostCategory)
        .outerjoin(MsTask, EstimateRoleAssignment.task_id == MsTask.id)
        .join(ResourceRole, EstimateRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
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
        outside_source = [
            task.uid
            for _, task, _, _ in assignments
            if task is not None and task.uid not in source_tasks
        ]
        if outside_source:
            raise ValueError(
                "Estimate has role assignments outside its planning snapshot: "
                + ", ".join(str(uid) for uid in sorted(outside_source))
            )

    # E6-11/#175: collect every (category, year) a dated assignment needs *before*
    # generating a single EstimateLine, so a gap anywhere blocks the whole
    # validation -- never a partial devis with some lines silently priced at a
    # zero rate/neutral inflation. A root assignment (task is None) has no task
    # dates to derive years from, so it needs the current calendar year's
    # coverage instead -- the same year `_generate_labor_lines` prices it at
    # (E12-07/#289 review finding).
    snapshot_year = datetime.now(UTC).year
    category_years: list[tuple[CostCategory, int]] = []
    for _assignment, task, _role, category in assignments:
        if task is None:
            category_years.append((category, snapshot_year))
            continue
        schedule_task = source_tasks.get(task.uid) or task
        if not schedule_task.start_at or not schedule_task.finish_at:
            continue
        category_years.extend(
            (category, year)
            for year in range(schedule_task.start_at.year, schedule_task.finish_at.year + 1)
        )
    missing_cost_rates, missing_inflation_years = collect_missing_rate_coverage(db, category_years)
    if missing_cost_rates or missing_inflation_years:
        raise MissingRateCoverageError(missing_cost_rates, missing_inflation_years)

    for assignment, task, role, category in assignments:
        labor_lines = _generate_labor_lines(
            db,
            estimate_id,
            assignment,
            task,
            role,
            category,
            source_tasks.get(task.uid) if task is not None else None,
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
            # Issue #63 (E6-02): snapshot the source EstimateCostLine's cost-imputation
            # code at validation time, independently of accounting_code above.
            cost_code_id=cost_line.cost_code_id,
            year=snapshot_year,
            quantity=cost_line.quantity,
            hours=Decimal("0"),
            hourly_rate=Decimal("0"),
            inflation_coefficient=Decimal("1"),
            budget_cost=cost_line.purchase_cost,
        )
        lines.append(line)

    return lines


def _single_year_labor_line(
    db: Session,
    estimate_id: int,
    assignment: EstimateRoleAssignment,
    role: ResourceRole,
    category: CostCategory,
) -> EstimateLine:
    """Price a devis-root MO line (``task_id IS NULL``, issue #289/E12-07) as a
    single `EstimateLine` at the current calendar year, mirroring how a task-less
    non-labor `EstimateCostLine` is already snapshotted at ``datetime.now(UTC).year``
    in ``calculate_estimate_lines``'s own "2." section -- the same "no task to date
    it from" situation, already solved there.

    Rate/inflation coverage for (``category``, this year) is guaranteed by
    ``calculate_estimate_lines``'s own `collect_missing_rate_coverage` call before
    this is ever reached, exactly like the year-split case in
    `_generate_labor_lines` below -- the ``is None`` branches here are the same
    defensive-in-depth fallback, never expected to trigger.
    """
    year = datetime.now(UTC).year
    rate_record = (
        db.query(CostRate)
        .filter(CostRate.cost_category_id == role.cost_category_id)
        .filter(CostRate.year == year)
        .first()
    )
    hourly_rate = rate_record.hourly_rate if rate_record else Decimal("0")
    inflation_record = db.query(InflationRate).filter(InflationRate.year == year).first()
    inflation_coefficient = inflation_record.coefficient if inflation_record else Decimal("1")
    budget_cost = assignment.quantity * assignment.hours * hourly_rate * inflation_coefficient

    return EstimateLine(
        estimate_id=estimate_id,
        task_id=None,
        role_id=role.id,
        # Mirrors the non-labor root cost line's own role_code=""/role_name=""
        # symmetry (calculate_estimate_lines, section "2."): here it is task_name
        # that has no source to snapshot, since this line has no ancestor task.
        task_name="",
        role_code=role.name,
        role_name=role.name,
        accounting_code=category.accounting_code,
        cost_code_id=assignment.cost_code_id,
        year=year,
        quantity=assignment.quantity,
        hours=assignment.hours,
        hourly_rate=hourly_rate,
        inflation_coefficient=inflation_coefficient,
        budget_cost=budget_cost,
    )


def _generate_labor_lines(
    db: Session,
    estimate_id: int,
    assignment: EstimateRoleAssignment,
    task: MsTask | None,
    role: ResourceRole,
    category: CostCategory,
    source_task: WfPlanningTaskSnapshot | None = None,
) -> list[EstimateLine]:
    """
    Generate EstimateLines for a task-role assignment, split by year if needed.

    If task spans multiple years (start_year != end_year), distribute hours uniformly
    across years. Apply year-specific rates and inflation coefficients.

    ``task`` is ``None`` for a devis-root MO line (``EstimateRoleAssignment.task_id
    IS NULL``, issue #289/E12-07): with no task to derive dates from, it produces a
    single `EstimateLine` at the current calendar year instead of a per-year split
    -- see ``_single_year_labor_line`` -- rather than being silently dropped (review
    finding: this case must never omit the line from any total).
    """
    if task is None:
        return [_single_year_labor_line(db, estimate_id, assignment, role, category)]

    lines: list[EstimateLine] = []

    schedule_task = source_task or task
    if not schedule_task.start_at or not schedule_task.finish_at:
        # Skip tasks without dates
        return lines

    years = range(schedule_task.start_at.year, schedule_task.finish_at.year + 1)

    # Distribute total hours uniformly across years
    hours_per_year = assignment.hours / Decimal(len(years))

    for year in years:
        # Fetch rate for this category and year
        rate_record = (
            db.query(CostRate)
            .filter(CostRate.cost_category_id == role.cost_category_id)
            .filter(CostRate.year == year)
            .first()
        )
        # The `rate_record is None` branch is unreachable in practice: this
        # function's only caller, `calculate_estimate_lines`, always runs
        # `collect_missing_rate_coverage` first and raises
        # `MissingRateCoverageError` before generating any line if a `CostRate`
        # is missing for this exact (category, year) -- so by the time we get
        # here, coverage is guaranteed complete (E6-11/#175 invariant, checked
        # upstream). Kept as defensive-in-depth rather than an assertion since
        # this is a private, single-caller helper.
        hourly_rate = rate_record.hourly_rate if rate_record else Decimal("0")

        # Fetch inflation coefficient. Same guarantee as above: an `InflationRate`
        # gap for this year would already have raised `MissingRateCoverageError`
        # upstream, so `inflation_record is None` is unreachable here too.
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
            # Issue #63 (E6-02): snapshot the source EstimateRoleAssignment's
            # cost-imputation code at validation time, independently of
            # accounting_code above.
            cost_code_id=assignment.cost_code_id,
            year=year,
            quantity=assignment.quantity,
            hours=hours_per_year,
            hourly_rate=hourly_rate,
            inflation_coefficient=inflation_coefficient,
            budget_cost=budget_cost,
        )
        lines.append(line)

    return lines


def sync_task_role_assignments_from_estimate(
    db: Session, project_id: int, estimate_id: int
) -> None:
    """Resynchronize the legacy, project-wide ``TaskRoleAssignment`` from the
    devis-version-scoped ``EstimateRoleAssignment`` rows of the estimate that
    just got validated (E12-02/#274).

    Called by ``validate_project_estimate`` (``api/routes/estimates.py``) right
    after ``calculate_estimate_lines`` succeeds, in the same transaction: a
    validated devis is the project's new officially staffed plan, and
    ``TaskRoleAssignment`` must end up reflecting it *exactly* -- this is a
    full replacement, not an additive merge, since it is also the table
    ``services/calendar_schedule.py::resolve_task_calendar_ids`` reads from to
    resolve a task's working calendar for planning/export purposes.

    For every ``(task_id, role_id)`` pair carried by this estimate's
    ``EstimateRoleAssignment`` rows: updates the matching ``TaskRoleAssignment``
    row's ``quantity``/``hours``/``cost_code_id``/``comment`` if one already
    exists (``TaskRoleAssignment`` is unique on ``(task_id, role_id)``,
    project-wide, never scoped by estimate), or creates one. Any
    ``TaskRoleAssignment`` of the project whose ``(task_id, role_id)`` pair is
    *not* among them is deleted outright -- a deliberate, project-wide side
    effect of validating a devis (see the E12 epic scoping), not a
    per-assignment operation.
    """
    assignments = (
        db.query(EstimateRoleAssignment)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
        .all()
    )
    # Issue #289 (E12-07): task_id is nullable (a grid node unindented all the way
    # to the devis root has no ancestor task) -- such an assignment has nothing
    # for TaskRoleAssignment (task_id NOT NULL, project-wide) to key off, so it
    # is excluded here explicitly. Unlike calculate_estimate_lines above (which
    # keeps this same row via a LEFT JOIN, priced as a single-year line since a
    # review finding on #289), TaskRoleAssignment genuinely has no column to
    # store a task-less row in -- this exclusion is a structural necessity, not
    # a silent-drop bug.
    assignment_by_pair = {
        (assignment.task_id, assignment.role_id): assignment
        for assignment in assignments
        if assignment.task_id is not None
    }

    existing_assignments = (
        db.query(TaskRoleAssignment)
        .join(MsTask, TaskRoleAssignment.task_id == MsTask.id)
        .filter(MsTask.project_id == project_id)
        .all()
    )
    existing_by_pair = {
        (existing.task_id, existing.role_id): existing for existing in existing_assignments
    }

    for pair, assignment in assignment_by_pair.items():
        existing = existing_by_pair.get(pair)
        if existing is not None:
            existing.quantity = assignment.quantity
            existing.hours = assignment.hours
            existing.cost_code_id = assignment.cost_code_id
            existing.comment = assignment.comment
            db.add(existing)
        else:
            task_id, role_id = pair
            db.add(
                TaskRoleAssignment(
                    task_id=task_id,
                    role_id=role_id,
                    cost_code_id=assignment.cost_code_id,
                    quantity=assignment.quantity,
                    hours=assignment.hours,
                    comment=assignment.comment,
                )
            )

    for pair, existing in existing_by_pair.items():
        if pair not in assignment_by_pair:
            db.delete(existing)

    db.flush()


class EstimateAggregates(TypedDict):
    total_labor_cost: Decimal
    total_purchase_cost: Decimal
    total_unburdened_cost: Decimal
    by_category: dict[str, Decimal]
    by_cost_code: dict[str, Decimal]


# Issue #71 (E6-10): shared fallback label for a line with no `cost_code_id`, used both
# by this aggregate and by the human-readable Excel export (services/estimate_export.py)
# so the two views never disagree on how an unassigned line is displayed.
UNASSIGNED_COST_CODE_LABEL = "—"


def _resolve_cost_code_labels(db: Session, cost_code_ids: set[int]) -> dict[int, str]:
    """Resolve a set of `cost_code_id` values to their `ProjectCostCode.code` in a
    single query, avoiding one lookup per estimate line."""
    if not cost_code_ids:
        return {}
    codes = db.query(ProjectCostCode).filter(ProjectCostCode.id.in_(cost_code_ids)).all()
    return {code.id: code.code for code in codes}


def calculate_estimate_aggregates(db: Session, estimate_id: int) -> EstimateAggregates:
    """
    Calculate aggregate totals for an estimate by type, category, accounting code, etc.

    Returns dict of aggregate metrics for reporting and validation.
    """
    lines = db.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all()

    cost_code_ids = {line.cost_code_id for line in lines if line.cost_code_id is not None}
    cost_code_labels = _resolve_cost_code_labels(db, cost_code_ids)

    total_labor_cost: Decimal = Decimal("0")
    total_purchase_cost: Decimal = Decimal("0")
    total_unburdened_cost: Decimal = Decimal("0")
    by_category: dict[str, Decimal] = {}
    by_cost_code: dict[str, Decimal] = {}

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

        # By cost-imputation code (issue #71 / E6-10)
        cost_code_label = (
            cost_code_labels.get(line.cost_code_id, UNASSIGNED_COST_CODE_LABEL)
            if line.cost_code_id is not None
            else UNASSIGNED_COST_CODE_LABEL
        )
        if cost_code_label not in by_cost_code:
            by_cost_code[cost_code_label] = Decimal("0")
        by_cost_code[cost_code_label] += line.budget_cost

    return {
        "total_labor_cost": total_labor_cost,
        "total_purchase_cost": total_purchase_cost,
        "total_unburdened_cost": total_unburdened_cost,
        "by_category": by_category,
        "by_cost_code": by_cost_code,
    }


def get_estimate_validation_warnings(
    db: Session, project_id: int, estimate_id: int
) -> list[EstimateValidationWarning]:
    """
    Issue #65 (E6-04): flag every "real" planning task (excludes summaries and
    milestones, per `MsTask.is_summary`/`MsTask.is_milestone`) that has
    neither an `EstimateRoleAssignment` nor an `EstimateCostLine.task_id` of
    this estimate referencing it -- i.e. a task the pricing exercise likely
    forgot.

    Purely advisory: this never blocks `POST .../validate`, it only backs a
    non-blocking warning surfaced to the user after validation succeeds.

    Role assignments and cost lines are now both scoped to `estimate_id`
    (E12-02/#274: `EstimateRoleAssignment` is devis-version-scoped, unlike the
    legacy project-wide `TaskRoleAssignment` this used to read from) --
    matching exactly what `calculate_estimate_lines` itself reads from for
    this same estimate.
    """
    tasks = (
        db.query(MsTask)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.is_summary.is_(False))
        .filter(MsTask.is_milestone.is_(False))
        .all()
    )
    if not tasks:
        return []

    assigned_task_ids = {
        task_id
        for (task_id,) in db.query(EstimateRoleAssignment.task_id)
        .join(MsTask, EstimateRoleAssignment.task_id == MsTask.id)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
        .filter(MsTask.project_id == project_id)
        .all()
    }
    costed_task_ids = {
        task_id
        for (task_id,) in db.query(EstimateCostLine.task_id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .filter(EstimateCostLine.task_id.isnot(None))
        .all()
    }
    covered_task_ids = assigned_task_ids | costed_task_ids

    return [
        EstimateValidationWarning(task_uid=task.uid, task_name=task.name)
        for task in tasks
        if task.id not in covered_task_ids
    ]
