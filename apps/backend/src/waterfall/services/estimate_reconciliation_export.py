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

The revision builder (E14-07c, #365)
------------------------------------
:func:`build_revision_reconciliation_workbook`, at the bottom of this module,
writes the same three sheets off the **single** tree of ``wf_revision_node``. Its
columns are documented on :data:`REVISION_TASK_HEADERS`,
:data:`REVISION_LABOR_HEADERS` and :data:`REVISION_COST_LINE_HEADERS`, and the
stable identifier of every row is the ``node_id`` -- one identifier where the
legacy sheets carried two (a devis row id *and* the ``ms_task``/``MsTask`` id it
pointed at). Everything above it is the legacy builder, alive until E14-12 (#339)
removes it with the three tables it reads, and kept meanwhile because it is the
only thing the new one can be compared against.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
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
from waterfall.services import revision_tree
from waterfall.services.estimate_calculation import amount_at_the_cent
from waterfall.services.estimate_export import HEADER_FONT
from waterfall.services.estimate_task_display import ResolvedTaskDisplay, resolve_live_task_display

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
    resolved_by_row_id: dict[int, ResolvedTaskDisplay],
) -> None:
    """Write the ``Tâches`` sheet.

    ``parent_task_id``/``position``/``task_name``/``outline_number``/
    ``outline_level`` are read from ``resolved_by_row_id`` when present (a
    draft estimate, E12-08/#290 -- see
    ``services.estimate_task_display.resolve_live_task_display``), falling
    back to ``row``'s own frozen stored columns otherwise -- the same rule
    ``to_estimate_task_row_read`` applies for the JSON endpoint, so a
    reconciliation export always shows the same task label/position a
    concurrent ``GET .../task-rows`` call would.
    """
    _write_headers(sheet, TASK_HEADERS)
    for row_index, row in enumerate(rows, start=2):
        resolved = resolved_by_row_id.get(row.id)
        values: list[_CellValue] = [
            row.id,
            row.task_id,
            task_uid_by_id.get(row.task_id) if row.task_id is not None else None,
            resolved.parent_task_id if resolved is not None else row.parent_task_id,
            resolved.position if resolved is not None else row.position,
            resolved.task_name if resolved is not None else row.task_name,
            resolved.outline_number if resolved is not None else row.outline_number,
            resolved.outline_level if resolved is not None else row.outline_level,
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
    # Issue #290 (E12-08): only a draft estimate's task rows are live -- a
    # validated estimate exports its own frozen stored columns instead (see
    # resolve_live_task_display's docstring).
    resolved_by_row_id = (
        resolve_live_task_display(db, project, task_rows) if estimate.status == "draft" else {}
    )
    assignments = _scoped_estimate_role_assignments(db, project, estimate)
    cost_lines = _non_labor_cost_lines(db, estimate.id)

    workbook = Workbook()
    tasks_sheet = workbook.active
    assert tasks_sheet is not None
    tasks_sheet.title = "Tâches"
    _write_tasks_sheet(tasks_sheet, task_rows, task_uid_by_id, resolved_by_row_id)

    labor_sheet = workbook.create_sheet("MO")
    _write_labor_sheet(labor_sheet, assignments)

    non_labor_sheet = workbook.create_sheet("Non-MO")
    _write_non_labor_sheet(non_labor_sheet, cost_lines)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------------------
# The revision reconciliation export (E14-07c, #365)
#
# The same three sheets, read off the single tree of `wf_revision_node` instead of
# the three parallel tables above. The legacy builder stays until E14-12 (#339)
# removes it with the tables it reads -- and because it is the only thing this one
# can be compared against (`tests/test_revision_export.py`).
# --------------------------------------------------------------------------------------

#: Columns of the ``Tâches`` sheet of a revision workbook.
#:
#: Shared with the reimport side (``estimate_reconciliation_import``) exactly as
#: :data:`TASK_HEADERS` is, so both directions of the round trip read one source of
#: truth.
#:
#: Three legacy columns have no counterpart and are gone rather than filled in:
#: ``id``/``task_id`` were two identifiers for one thing (a devis row and the task
#: it pointed at) and are now the single ``node_id``; ``outline_number`` and
#: ``outline_level`` were stored columns that a move had to renumber, and the node
#: model derives the second (``level``) on read and does not carry the first at all
#: -- the principle E9 (#145-#149) settled. ``parent_node_id``/``position`` are what
#: actually describe the structure, and they are the two the reimport reads.
#:
#: ``external_uid`` is the MS Project identity of the work item (E14-06) and is
#: **read-only through this file**: rebinding a node to another MS Project task is
#: the XML re-import's business, not a spreadsheet's. Editing the cell is not
#: silently dropped, though -- the reimport reports it as
#: ``TASK_FIELD_CHANGE_IGNORED``, exactly like an edited ``name``.
REVISION_TASK_HEADERS = [
    "node_id",
    "work_item_id",
    "external_uid",
    "parent_node_id",
    "position",
    "level",
    "name",
    "is_milestone",
]

#: Columns of the ``MO`` sheet of a revision workbook.
#:
#: ``hors_perimetre_planning`` is **absent**, and its absence is the model change:
#: it flagged an assignment pointing at a task outside the estimate's source
#: planning snapshot -- a state that existed only because the devis described a
#: second structure. A labour facet is a node of the one tree, so there is no
#: outside to be in. ``bearing_task_node_id``/``bearing_task_name`` replace the
#: legacy ``task_id``/``task_name``: they are INV-01's answer, resolved on read and
#: stored in no column, which is why they are informational here -- the reimport
#: reads ``parent_node_id`` to place a line, never the bearing task, since the
#: bearing task is a *consequence* of the placement.
REVISION_LABOR_HEADERS = [
    "node_id",
    "work_item_id",
    "parent_node_id",
    "position",
    "bearing_task_node_id",
    "bearing_task_name",
    "role_id",
    "role_name",
    "cost_category_id",
    "cost_category_name",
    "cost_code_id",
    "label",
    "quantity",
    "hours",
    "comment",
]

#: Columns of the ``Non-MO`` sheet of a revision workbook. ``purchase_cost`` is the
#: echo of ``quantity x unit_cost`` the legacy sheet already carried as a read-only
#: convenience: it is published at the cent, like every amount this API serves, and
#: the reimport ignores it.
REVISION_COST_LINE_HEADERS = [
    "node_id",
    "work_item_id",
    "parent_node_id",
    "position",
    "bearing_task_node_id",
    "bearing_task_name",
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


@dataclass(frozen=True)
class _Referential:
    """The rows the facets point at, resolved once for the whole workbook."""

    roles: dict[int, ResourceRole]
    categories: dict[int, CostCategory]
    cost_types: dict[int, CostType]


def _load_referential(db: Session, rows: Sequence[revision_tree.TreeRow]) -> _Referential:
    role_ids = {row.cost.role_id for row in rows if row.cost is not None and row.cost.role_id}
    roles = (
        {row.id: row for row in db.query(ResourceRole).filter(ResourceRole.id.in_(role_ids)).all()}
        if role_ids
        else {}
    )
    category_ids = {role.cost_category_id for role in roles.values()}
    category_ids.update(
        row.cost.cost_category_id
        for row in rows
        if row.cost is not None and row.cost.cost_category_id is not None
    )
    categories = (
        {
            row.id: row
            for row in db.query(CostCategory).filter(CostCategory.id.in_(category_ids)).all()
        }
        if category_ids
        else {}
    )
    cost_type_ids = {
        row.cost.cost_type_id
        for row in rows
        if row.cost is not None and row.cost.cost_type_id is not None
    }
    cost_types = (
        {row.id: row for row in db.query(CostType).filter(CostType.id.in_(cost_type_ids)).all()}
        if cost_type_ids
        else {}
    )
    return _Referential(roles=roles, categories=categories, cost_types=cost_types)


def _write_revision_task_sheet(sheet: Worksheet, rows: Sequence[revision_tree.TreeRow]) -> None:
    _write_headers(sheet, REVISION_TASK_HEADERS)
    row_index = 2
    for row in rows:
        if row.plan is None:
            continue
        values: list[_CellValue] = [
            row.node_id,
            row.work_item_id,
            row.external_uid,
            row.parent_id,
            row.position,
            row.level,
            row.plan.name,
            row.plan.is_milestone,
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)
        row_index += 1


def _write_revision_labor_sheet(
    sheet: Worksheet, rows: Sequence[revision_tree.TreeRow], referential: _Referential
) -> None:
    _write_headers(sheet, REVISION_LABOR_HEADERS)
    row_index = 2
    for row in rows:
        facet = row.cost
        if facet is None or facet.nature is not domain.CostNature.LABOR:
            continue
        role = None if facet.role_id is None else referential.roles.get(facet.role_id)
        # INV-19: a labour facet carries no category of its own, it inherits its
        # role's -- the same single source of truth the engine prices against.
        category = None if role is None else referential.categories.get(role.cost_category_id)
        values: list[_CellValue] = [
            row.node_id,
            row.work_item_id,
            row.parent_id,
            row.position,
            None if row.bearing_task is None else row.bearing_task.node_id,
            None if row.bearing_task is None else row.bearing_task.name,
            facet.role_id,
            None if role is None else role.name,
            None if role is None else role.cost_category_id,
            None if category is None else category.name,
            facet.cost_code_id,
            facet.label,
            float(facet.quantity),
            None if facet.hours is None else float(facet.hours),
            facet.comment,
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)
        row_index += 1


def _write_revision_non_labor_sheet(
    sheet: Worksheet, rows: Sequence[revision_tree.TreeRow], referential: _Referential
) -> None:
    _write_headers(sheet, REVISION_COST_LINE_HEADERS)
    row_index = 2
    for row in rows:
        facet = row.cost
        if facet is None or facet.nature is domain.CostNature.LABOR:
            continue
        category = (
            None
            if facet.cost_category_id is None
            else referential.categories.get(facet.cost_category_id)
        )
        cost_type = (
            None if facet.cost_type_id is None else referential.cost_types.get(facet.cost_type_id)
        )
        unit_cost = facet.unit_cost if facet.unit_cost is not None else Decimal("0")
        values: list[_CellValue] = [
            row.node_id,
            row.work_item_id,
            row.parent_id,
            row.position,
            None if row.bearing_task is None else row.bearing_task.node_id,
            None if row.bearing_task is None else row.bearing_task.name,
            facet.cost_type_id,
            None if cost_type is None else cost_type.code,
            facet.cost_category_id,
            None if category is None else category.accounting_code,
            None if category is None else category.category_code,
            facet.cost_code_id,
            facet.label,
            float(facet.quantity),
            float(unit_cost),
            float(amount_at_the_cent(facet.quantity * unit_cost)),
            None if facet.supply_status is None else facet.supply_status.value,
            None if facet.planned_date is None else facet.planned_date.isoformat(),
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)
        row_index += 1


def build_revision_reconciliation_workbook(db: Session, revision_id: int) -> bytes:
    """The round-trip reconciliation workbook of one revision.

    The node-model counterpart of :func:`build_estimate_reconciliation_workbook`:
    the same three sheets, under the same names, in the same order -- but all three
    are now views of **one** tree rather than three tables describing three
    structures, which is the whole of EPIC #326 seen from an export.

    Every row is written in the depth-first order of
    :func:`~waterfall.services.revision_tree.read_revision_tree`, the order the
    application reads a revision in everywhere else, and it carries
    ``parent_node_id``/``position``: those two are what the reimport reads to place
    a line, and what makes the placement -- and therefore the bearing task of every
    cost line under it -- reconstructible from the file alone.

    A **read**, refused on nothing: a validated revision exports exactly like a
    draft. What a validated revision refuses is the *reimport* of that file
    (``REVISION_IMMUTABLE``, INV-03), which is where the refusal belongs -- hiding
    the export would leave a user unable to so much as look at what they own.
    """
    tree = revision_tree.read_revision_tree(db, revision_id)
    referential = _load_referential(db, tree.rows)

    workbook = Workbook()
    tasks_sheet = workbook.active
    assert tasks_sheet is not None
    tasks_sheet.title = "Tâches"
    _write_revision_task_sheet(tasks_sheet, tree.rows)

    labor_sheet = workbook.create_sheet("MO")
    _write_revision_labor_sheet(labor_sheet, tree.rows, referential)

    non_labor_sheet = workbook.create_sheet("Non-MO")
    _write_revision_non_labor_sheet(non_labor_sheet, tree.rows, referential)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
