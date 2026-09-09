"""Parse an Excel reconciliation workbook back into typed rows (E6-09, #70).

Mirror of ``estimate_reconciliation_export.py``: reads the exact three-sheet
layout (``Tâches`` / ``MO`` / ``Non-MO``) that module writes, sharing its
column headers (``TASK_HEADERS`` / ``LABOR_HEADERS`` / ``COST_LINE_HEADERS``)
as the single source of truth for both directions of the round trip.

Deliberately narrow scope: this module only turns workbook bytes into typed,
per-row dataclasses (or raises :class:`EstimateReconciliationFormatError` when
the file cannot even be read as structured data). It has no FastAPI
dependency and never touches the database -- the actual reconciliation
diff/apply logic (which needs project/estimate context, existing rows, and
route-layer helpers like ``resolve_cost_code_id``) lives in
``api/routes/estimates.py``, next to the two routes that call it
(``.../import-reconciliation/preview`` and ``.../import-reconciliation/confirm``).

Two classes of problem are told apart on purpose:

* A **format** problem (missing sheet, header row that doesn't match the
  exported layout, or a cell holding a value of the wrong type where a
  specific one is required, e.g. text in a numeric column) means the file
  itself cannot be trusted as structured data -- collected into
  :class:`EstimateReconciliationFormatError` (mirroring
  ``waterfall.services.msproject_xml.MsProjectValidationError``'s shape) and
  reported as a single 400 with the full list of problems, never a partial
  parse.
* A **business** problem (a blank cell where a value is only required for
  *some* rows, e.g. ``label`` on a new Non-MO line but not on one already
  flagged for deletion) is left as ``None`` here and turned into a precisely
  attributed :class:`~waterfall.schemas.projects.ReconciliationIssue` by the
  diff/apply step instead, since only that step knows whether the row is a
  create, an update, or a mutation-ignored existing row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from waterfall.services.estimate_reconciliation_export import (
    COST_LINE_HEADERS,
    LABOR_HEADERS,
    TASK_HEADERS,
)

_TASK_SHEET = "Tâches"
_LABOR_SHEET = "MO"
_COST_LINE_SHEET = "Non-MO"


class EstimateReconciliationFormatError(ValueError):
    """The uploaded workbook cannot be parsed into reconciliation rows.

    ``issues`` is a list of structured dicts (``code``/``message``, plus
    ``sheet`` and, for a row-scoped problem, ``row``) -- the same shape as
    ``waterfall.services.msproject_xml.MsProjectValidationError.issues`` --
    collected across the *whole* workbook before raising, so a caller gets
    every format problem in one round trip instead of fixing them one at a
    time.
    """

    def __init__(self, issues: list[dict[str, object]]) -> None:
        self.issues = issues
        super().__init__("Estimate reconciliation workbook is invalid")


@dataclass(frozen=True)
class TaskFileRow:
    row_number: int
    id: int | None
    task_id: int | None
    parent_task_id: int | None
    position: int | None
    task_name: str | None
    outline_number: str | None
    outline_level: int | None
    is_milestone: bool


@dataclass(frozen=True)
class LaborFileRow:
    row_number: int
    id: int | None
    task_id: int | None
    role_id: int | None
    cost_code_id: int | None
    quantity: Decimal | None
    hours: Decimal | None
    comment: str | None
    hors_perimetre_planning: bool


@dataclass(frozen=True)
class CostLineFileRow:
    row_number: int
    id: int | None
    task_id: int | None
    cost_category_id: int | None
    cost_code_id: int | None
    label: str | None
    quantity: Decimal | None
    unit_cost: Decimal | None
    supply_status: str | None
    planned_date: datetime | None


@dataclass(frozen=True)
class ParsedReconciliationWorkbook:
    tasks: list[TaskFileRow]
    labor: list[LaborFileRow]
    cost_lines: list[CostLineFileRow]


def _is_blank_row(values: tuple[object, ...]) -> bool:
    return all(value is None or value == "" for value in values)


def _pad(values: tuple[object, ...], length: int) -> tuple[object, ...]:
    if len(values) >= length:
        return values
    return values + (None,) * (length - len(values))


def _cell_int(
    value: object,
    *,
    sheet: str,
    row_number: int,
    column: str,
    issues: list[dict[str, object]],
) -> int | None:
    if value is None or value == "":
        return None
    if not isinstance(value, bool):
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.lstrip("-").isdigit():
                return int(stripped)
    issues.append(
        {
            "code": "INVALID_INTEGER",
            "message": f"Column '{column}' must be a whole number",
            "sheet": sheet,
            "row": row_number,
        }
    )
    return None


def _cell_decimal(
    value: object,
    *,
    sheet: str,
    row_number: int,
    column: str,
    issues: list[dict[str, object]],
) -> Decimal | None:
    if value is None or value == "":
        return None
    if not isinstance(value, bool):
        if isinstance(value, int | float):
            return Decimal(str(value))
        if isinstance(value, str):
            try:
                return Decimal(value.strip())
            except InvalidOperation:
                pass
    issues.append(
        {
            "code": "INVALID_NUMBER",
            "message": f"Column '{column}' must be a number",
            "sheet": sheet,
            "row": row_number,
        }
    )
    return None


def _cell_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "vrai", "oui", "yes"}
    return False


def _cell_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cell_datetime(
    value: object,
    *,
    sheet: str,
    row_number: int,
    column: str,
    issues: list[dict[str, object]],
) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            pass
    issues.append(
        {
            "code": "INVALID_DATE",
            "message": f"Column '{column}' must be an ISO date",
            "sheet": sheet,
            "row": row_number,
        }
    )
    return None


def _check_headers(
    workbook: Workbook,
    sheet_name: str,
    expected: list[str],
    issues: list[dict[str, object]],
) -> None:
    if sheet_name not in workbook.sheetnames:
        issues.append(
            {
                "code": "MISSING_SHEET",
                "message": f"Missing sheet '{sheet_name}'",
                "sheet": sheet_name,
            }
        )
        return
    sheet = workbook[sheet_name]
    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
    actual = list(_pad(tuple(header_row), len(expected)))[: len(expected)]
    if actual != expected:
        issues.append(
            {
                "code": "INVALID_HEADER",
                "message": f"Sheet '{sheet_name}' must start with columns {expected}",
                "sheet": sheet_name,
            }
        )


def _parse_task_rows(sheet: Worksheet, issues: list[dict[str, object]]) -> list[TaskFileRow]:
    rows: list[TaskFileRow] = []
    for row_number, raw_values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        values = _pad(tuple(raw_values), len(TASK_HEADERS))
        if _is_blank_row(values):
            continue
        (
            raw_id,
            raw_task_id,
            _raw_task_uid,
            raw_parent_task_id,
            raw_position,
            raw_task_name,
            raw_outline_number,
            raw_outline_level,
            raw_is_milestone,
        ) = values[: len(TASK_HEADERS)]
        rows.append(
            TaskFileRow(
                row_number=row_number,
                id=_cell_int(
                    raw_id, sheet=_TASK_SHEET, row_number=row_number, column="id", issues=issues
                ),
                task_id=_cell_int(
                    raw_task_id,
                    sheet=_TASK_SHEET,
                    row_number=row_number,
                    column="task_id",
                    issues=issues,
                ),
                parent_task_id=_cell_int(
                    raw_parent_task_id,
                    sheet=_TASK_SHEET,
                    row_number=row_number,
                    column="parent_task_id",
                    issues=issues,
                ),
                position=_cell_int(
                    raw_position,
                    sheet=_TASK_SHEET,
                    row_number=row_number,
                    column="position",
                    issues=issues,
                ),
                task_name=_cell_text(raw_task_name),
                outline_number=_cell_text(raw_outline_number),
                outline_level=_cell_int(
                    raw_outline_level,
                    sheet=_TASK_SHEET,
                    row_number=row_number,
                    column="outline_level",
                    issues=issues,
                ),
                is_milestone=_cell_bool(raw_is_milestone),
            )
        )
    return rows


def _parse_labor_rows(sheet: Worksheet, issues: list[dict[str, object]]) -> list[LaborFileRow]:
    rows: list[LaborFileRow] = []
    for row_number, raw_values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        values = _pad(tuple(raw_values), len(LABOR_HEADERS))
        if _is_blank_row(values):
            continue
        (
            raw_id,
            raw_task_id,
            _raw_task_name,
            raw_role_id,
            _raw_role_name,
            _raw_cost_category_id,
            _raw_cost_category_name,
            raw_cost_code_id,
            raw_quantity,
            raw_hours,
            raw_comment,
            raw_hors_perimetre,
        ) = values[: len(LABOR_HEADERS)]
        rows.append(
            LaborFileRow(
                row_number=row_number,
                id=_cell_int(
                    raw_id, sheet=_LABOR_SHEET, row_number=row_number, column="id", issues=issues
                ),
                task_id=_cell_int(
                    raw_task_id,
                    sheet=_LABOR_SHEET,
                    row_number=row_number,
                    column="task_id",
                    issues=issues,
                ),
                role_id=_cell_int(
                    raw_role_id,
                    sheet=_LABOR_SHEET,
                    row_number=row_number,
                    column="role_id",
                    issues=issues,
                ),
                cost_code_id=_cell_int(
                    raw_cost_code_id,
                    sheet=_LABOR_SHEET,
                    row_number=row_number,
                    column="cost_code_id",
                    issues=issues,
                ),
                quantity=_cell_decimal(
                    raw_quantity,
                    sheet=_LABOR_SHEET,
                    row_number=row_number,
                    column="quantity",
                    issues=issues,
                ),
                hours=_cell_decimal(
                    raw_hours,
                    sheet=_LABOR_SHEET,
                    row_number=row_number,
                    column="hours",
                    issues=issues,
                ),
                comment=_cell_text(raw_comment),
                hors_perimetre_planning=_cell_bool(raw_hors_perimetre),
            )
        )
    return rows


def _parse_cost_line_rows(
    sheet: Worksheet, issues: list[dict[str, object]]
) -> list[CostLineFileRow]:
    rows: list[CostLineFileRow] = []
    for row_number, raw_values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        values = _pad(tuple(raw_values), len(COST_LINE_HEADERS))
        if _is_blank_row(values):
            continue
        (
            raw_id,
            raw_task_id,
            _raw_cost_type_id,
            _raw_cost_type_code,
            raw_cost_category_id,
            _raw_accounting_code,
            _raw_category_code,
            raw_cost_code_id,
            raw_label,
            raw_quantity,
            raw_unit_cost,
            _raw_purchase_cost,
            raw_supply_status,
            raw_planned_date,
        ) = values[: len(COST_LINE_HEADERS)]
        rows.append(
            CostLineFileRow(
                row_number=row_number,
                id=_cell_int(
                    raw_id,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="id",
                    issues=issues,
                ),
                task_id=_cell_int(
                    raw_task_id,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="task_id",
                    issues=issues,
                ),
                cost_category_id=_cell_int(
                    raw_cost_category_id,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="cost_category_id",
                    issues=issues,
                ),
                cost_code_id=_cell_int(
                    raw_cost_code_id,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="cost_code_id",
                    issues=issues,
                ),
                label=_cell_text(raw_label),
                quantity=_cell_decimal(
                    raw_quantity,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="quantity",
                    issues=issues,
                ),
                unit_cost=_cell_decimal(
                    raw_unit_cost,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="unit_cost",
                    issues=issues,
                ),
                supply_status=_cell_text(raw_supply_status),
                planned_date=_cell_datetime(
                    raw_planned_date,
                    sheet=_COST_LINE_SHEET,
                    row_number=row_number,
                    column="planned_date",
                    issues=issues,
                ),
            )
        )
    return rows


def parse_estimate_reconciliation_workbook(content: bytes) -> ParsedReconciliationWorkbook:
    """Parse the three reconciliation sheets, or raise with every format problem at once.

    Read-only/data-only: values already computed by Excel are read verbatim,
    formulas are never evaluated by this parser.
    """
    issues: list[dict[str, object]] = []
    try:
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        raise EstimateReconciliationFormatError(
            [
                {
                    "code": "INVALID_WORKBOOK",
                    "message": f"File is not a readable Excel workbook: {exc}",
                }
            ]
        ) from exc

    try:
        _check_headers(workbook, _TASK_SHEET, TASK_HEADERS, issues)
        _check_headers(workbook, _LABOR_SHEET, LABOR_HEADERS, issues)
        _check_headers(workbook, _COST_LINE_SHEET, COST_LINE_HEADERS, issues)
        if issues:
            raise EstimateReconciliationFormatError(issues)

        tasks = _parse_task_rows(workbook[_TASK_SHEET], issues)
        labor = _parse_labor_rows(workbook[_LABOR_SHEET], issues)
        cost_lines = _parse_cost_line_rows(workbook[_COST_LINE_SHEET], issues)
        if issues:
            raise EstimateReconciliationFormatError(issues)
    finally:
        workbook.close()

    return ParsedReconciliationWorkbook(tasks=tasks, labor=labor, cost_lines=cost_lines)
