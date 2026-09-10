"""Excel export for a project estimate meant to be reconciled on reimport (E6-08, #69).

Unlike ``estimate_export.build_estimate_workbook`` (the pre-existing
human-readable summary served by ``GET .../export.xlsx``, with a cost grid and
category aggregates), this generator produces a machine-reconcilable workbook
meant to be re-imported later (E6-09, future issue #70): one sheet per line
nature, every row carrying the internal ids needed to match it back to its
source row on reimport, in addition to human-readable labels.

Only a *draft* estimate has anything meaningful to reconcile: ``EstimateLine``
(the cost-calculation snapshot written once by ``calculate_estimate_lines`` at
``POST .../validate``) does not exist yet for a draft, and a validated
estimate is no longer editable. So the labor ("MO") sheet is **not** sourced
from ``EstimateLine`` -- it reads the devis-version-scoped ``EstimateRoleAssignment``
rows instead (E12-01/#273, the same table ``estimate_calculation.calculate_estimate_lines``
reads for its own cost calculation since E12-02/#274 -- see
``_scoped_estimate_role_assignments`` below), but without any of that function's
cost/hours-per-year computation -- only line identification.

Sheets
------
``Tâches``
    One row per ``EstimateTaskRow`` of this estimate (``wf_estimate_task_row``,
    already scoped to the estimate).
    Columns: ``id`` (stable id), ``task_id``, ``task_uid`` (resolved from
    ``task_id`` via ``MsTask.uid``, blank when ``task_id`` is null),
    ``parent_task_id``, ``position``, ``task_name``, ``outline_number``,
    ``outline_level``, ``is_milestone``.

``MO``
    One row per ``EstimateRoleAssignment`` (``wf_estimate_role_assignment``,
    scoped to this estimate version -- E12-01/#273) belonging to this estimate.
    When the estimate has a source planning (``estimate.planning_id``),
    assignments whose task uid is *not* present in that planning's snapshot are
    still included (never silently dropped) but
    flagged via ``hors_perimetre_planning=True`` -- this is the same condition
    ``calculate_estimate_lines`` would otherwise reject at validation time, but
    an export is a read-only reconciliation aid, not a validation gate, so it
    stays usable instead of failing. This flag stays relevant even though
    ``EstimateRoleAssignment`` is itself estimate-scoped from creation on
    (E12-01/#273): nothing at creation time
    (``create_estimate_role_assignment``, ``api/routes/estimates.py``) checks
    that the assigned task is actually a node of *this* estimate's own source
    planning snapshot, only that it belongs to the project -- so a row can
    still exist entirely outside that snapshot. On reimport (E6-09), a flagged
    row is not expected to be reprised without explicit user action. A row whose
    ``task_id`` is ``NULL`` (a devis-root MO line, detached from every task --
    issue #289/E12-07) is likewise always included, never dropped: ``task_name``
    is blank and ``hors_perimetre_planning`` is ``False`` for it, since "outside
    the planning snapshot" presupposes a task to begin with. Columns: ``id``
    (stable id), ``task_id``, ``task_name`` (via ``MsTask.name``, blank when
    ``task_id`` is null), ``role_id``,
    ``role_name`` (via ``ResourceRole.name`` -- ``ResourceRole`` carries no
    separate ``code`` field), ``cost_category_id`` (via
    ``role.cost_category_id``), ``cost_category_name`` (via
    ``CostCategory.name``), ``cost_code_id``, ``quantity``, ``hours``,
    ``comment``, ``hors_perimetre_planning`` (``True`` when the task falls
    outside the estimate's source planning snapshot, ``False`` when the
    estimate has no source planning, the task is within it, or there is no task
    at all).

``Non-MO``
    One row per ``EstimateCostLine`` (``wf_estimate_cost_line``, scoped to the
    estimate) whose cost type is not labor -- defensive filter mirroring
    ``calculate_estimate_lines``'s own ``if cost_type.kind == LABOR: continue``,
    even though in practice every ``EstimateCostLine`` is already non-labor.
    Columns: ``id`` (stable id), ``task_id``, ``cost_type_id``,
    ``cost_type_code``, ``cost_category_id``, ``accounting_code``,
    ``category_code``, ``cost_code_id``, ``label``, ``quantity``,
    ``unit_cost``, ``purchase_cost``, ``supply_status``, ``planned_date``
    (ISO date, blank when unset).

Stable identifiers
-------------------
The first column of every sheet (``id``) is the row's stable identifier: it
is the source row's own primary key (``EstimateTaskRow.id`` /
``EstimateRoleAssignment.id`` / ``EstimateCostLine.id``), never recalculated
by this export. On reimport (E6-09), a present id means "update this existing
row"; an absent/blank id means "create a new row".
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateRoleAssignment,
    EstimateTaskRow,
    ResourceRole,
)
from waterfall.schemas.resources import CostTypeKind
from waterfall.services.estimate_export import HEADER_FONT

# Not underscore-prefixed: shared with the reimport side of the round-trip
# (services/estimate_reconciliation_import.py, E6-09/#70) so both directions of
# the file agree on the exact column layout from a single source of truth.
TASK_HEADERS = [
    "id",
    "task_id",
    "task_uid",
    "parent_task_id",
    "position",
    "task_name",
    "outline_number",
    "outline_level",
    "is_milestone",
]

LABOR_HEADERS = [
    "id",
    "task_id",
    "task_name",
    "role_id",
    "role_name",
    "cost_category_id",
    "cost_category_name",
    "cost_code_id",
    "quantity",
    "hours",
    "comment",
    "hors_perimetre_planning",
]

COST_LINE_HEADERS = [
    "id",
    "task_id",
    "cost_type_id",
    "cost_type_code",
    "cost_category_id",
    "accounting_code",
    "category_code",
    "cost_code_id",
    "label",
    "quantity",
    "unit_cost",
    "purchase_cost",
    "supply_status",
    "planned_date",
]

_LaborAssignmentRow = tuple[EstimateRoleAssignment, MsTask | None, ResourceRole, CostCategory, bool]
_CostLineRow = tuple[EstimateCostLine, CostType]
# openpyxl's `Cell.value` accepts this exact union (see `openpyxl.cell._CellSetValue`);
# `int` isn't itself part of it but is accepted at both runtime and by pyright's numeric
# tower (int is assignable wherever `float` is expected).
_CellValue = bool | float | str | None


def _write_headers(sheet: Worksheet, headers: list[str]) -> None:
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.font = HEADER_FONT
        sheet.column_dimensions[get_column_letter(column)].width = 20


def _scoped_estimate_role_assignments(
    db: Session, project: MsProject, estimate: Estimate
) -> list[_LaborAssignmentRow]:
    """Reads this estimate's own devis-scoped `EstimateRoleAssignment` rows
    (E12-01/#273), the same table `calculate_estimate_lines` reads for its cost
    calculation since E12-02/#274 -- migrated from the legacy, project-wide
    `TaskRoleAssignment` by E12-03/#275.

    Unlike `calculate_estimate_lines`, an assignment whose task uid falls outside
    the estimate's source planning snapshot is never excluded here: this export is
    a read-only reconciliation aid, not a validation gate, so every assignment of
    this estimate is kept. Instead, the out-of-scope condition (the same one
    `calculate_estimate_lines` would reject with a `ValueError` at validation
    time) is surfaced via the returned row's ``hors_perimetre_planning`` flag --
    still reachable today since `create_estimate_role_assignment` only checks
    that the task belongs to the project, not that it is a node of this
    estimate's own source planning snapshot.

    ``task_id`` is nullable (issue #289/E12-07: a devis-root MO line, detached
    from every task) -- this reads ``MsTask`` via a LEFT JOIN, not an INNER JOIN,
    so such a row is never silently excluded (review finding: an INNER JOIN used
    to drop it from this export -- and from the import staging that reads this
    same helper -- exactly like it used to drop it from `calculate_estimate_lines`).
    ``task`` is ``None`` in the returned row for these; ``hors_perimetre_planning``
    is always ``False`` for them since "outside the planning snapshot" doesn't
    apply to a line with no task at all.
    """
    assignments = (
        db.query(EstimateRoleAssignment, MsTask, ResourceRole, CostCategory)
        .outerjoin(MsTask, EstimateRoleAssignment.task_id == MsTask.id)
        .join(ResourceRole, EstimateRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(EstimateRoleAssignment.estimate_id == estimate.id)
        .order_by(EstimateRoleAssignment.id)
        .all()
    )
    if estimate.planning_id is None:
        return [
            (assignment, task, role, category, False)
            for assignment, task, role, category in assignments
        ]

    source_uids = {
        uid
        for (uid,) in db.query(WfPlanningTaskSnapshot.uid)
        .filter(WfPlanningTaskSnapshot.planning_id == estimate.planning_id)
        .all()
    }
    return [
        (assignment, task, role, category, task is not None and task.uid not in source_uids)
        for assignment, task, role, category in assignments
    ]


def _non_labor_cost_lines(db: Session, estimate_id: int) -> list[_CostLineRow]:
    rows = (
        db.query(EstimateCostLine, CostType)
        .join(CostType, EstimateCostLine.cost_type_id == CostType.id)
        .filter(EstimateCostLine.estimate_id == estimate_id)
        .filter(CostType.kind != CostTypeKind.LABOR)
        .order_by(EstimateCostLine.id)
        .all()
    )
    return [(line, cost_type) for line, cost_type in rows]


def _write_tasks_sheet(
    sheet: Worksheet,
    rows: list[EstimateTaskRow],
    task_uid_by_id: dict[int, int],
) -> None:
    _write_headers(sheet, TASK_HEADERS)
    for row_index, row in enumerate(rows, start=2):
        values: list[_CellValue] = [
            row.id,
            row.task_id,
            task_uid_by_id.get(row.task_id) if row.task_id is not None else None,
            row.parent_task_id,
            row.position,
            row.task_name,
            row.outline_number,
            row.outline_level,
            row.is_milestone,
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)


def _write_labor_sheet(sheet: Worksheet, assignments: list[_LaborAssignmentRow]) -> None:
    _write_headers(sheet, LABOR_HEADERS)
    for row_index, (assignment, task, role, category, hors_perimetre) in enumerate(
        assignments, start=2
    ):
        values: list[_CellValue] = [
            assignment.id,
            assignment.task_id,
            task.name if task is not None else None,
            assignment.role_id,
            role.name,
            role.cost_category_id,
            category.name,
            assignment.cost_code_id,
            float(assignment.quantity),
            float(assignment.hours),
            assignment.comment,
            hors_perimetre,
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)


def _write_non_labor_sheet(sheet: Worksheet, cost_lines: list[_CostLineRow]) -> None:
    _write_headers(sheet, COST_LINE_HEADERS)
    for row_index, (line, _cost_type) in enumerate(cost_lines, start=2):
        values: list[_CellValue] = [
            line.id,
            line.task_id,
            line.cost_type_id,
            line.cost_type_code,
            line.cost_category_id,
            line.accounting_code,
            line.category_code,
            line.cost_code_id,
            line.label,
            float(line.quantity),
            float(line.unit_cost),
            float(line.purchase_cost),
            line.supply_status,
            line.planned_date.date().isoformat() if line.planned_date is not None else None,
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)


def build_estimate_reconciliation_workbook(
    db: Session, project: MsProject, estimate: Estimate
) -> bytes:
    """Build the round-trip reconciliation workbook: `Tâches` / `MO` / `Non-MO` sheets.

    See the module docstring for the exact column layout of each sheet and for
    why labor lines are sourced from `EstimateRoleAssignment` rather than
    `EstimateLine`.
    """
    task_rows = (
        db.query(EstimateTaskRow)
        .filter(EstimateTaskRow.estimate_id == estimate.id)
        .order_by(EstimateTaskRow.position, EstimateTaskRow.id)
        .all()
    )
    task_uid_by_id = {
        task.id: task.uid for task in db.query(MsTask).filter(MsTask.project_id == project.id).all()
    }
    assignments = _scoped_estimate_role_assignments(db, project, estimate)
    cost_lines = _non_labor_cost_lines(db, estimate.id)

    workbook = Workbook()
    tasks_sheet = workbook.active
    assert tasks_sheet is not None
    tasks_sheet.title = "Tâches"
    _write_tasks_sheet(tasks_sheet, task_rows, task_uid_by_id)

    labor_sheet = workbook.create_sheet("MO")
    _write_labor_sheet(labor_sheet, assignments)

    non_labor_sheet = workbook.create_sheet("Non-MO")
    _write_non_labor_sheet(non_labor_sheet, cost_lines)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
