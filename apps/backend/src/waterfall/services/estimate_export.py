"""Excel export for a devis: cost grid, subtotals and aggregates.

Two builders live here, and the module is read in that order -- the same layout
:mod:`waterfall.services.estimate_calculation` already carries, and for the same
reason.

**The legacy builder** (:func:`build_estimate_workbook`) reads the frozen
``wf_estimate_line`` rows a validation wrote, plus ``wf_estimate_cost_line``. It
is still wired to ``GET .../estimates/{id}/export.xlsx`` and is removed by E14-12
(#339) together with the tables it reads.

**The revision builder** (:func:`build_revision_workbook`, E14-07c/#365) produces
the very same classeur off the cost facets of ``wf_revision_node``, priced live by
the engine. Keeping both alive is what makes #365's central criterion checkable at
all: the two are run on one set of figures and compared cell for cell
(``tests/test_revision_export.py``). This is the last issue in which that
comparison is possible.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
from waterfall.models.ms_core import MsProject
from waterfall.models.resources import (
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateLine,
    ProjectCostCode,
)
from waterfall.models.revision import ProjectRevision
from waterfall.services.estimate_calculation import (
    UNASSIGNED_COST_CODE_LABEL,
    EstimateAggregates,
    RevisionAggregates,
    RevisionPricing,
    aggregates_of_pricing,
    amount_at_the_cent,
    calculate_estimate_aggregates,
    price_loaded_revision,
)
from waterfall.services.revision_store import load_revision

HEADER_FONT = Font(bold=True)
TITLE_FONT = Font(bold=True, size=13)


def _write_header(sheet: Worksheet, project: MsProject, estimate: Estimate) -> None:
    sheet["A1"] = f"Devis — {project.name}"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = "Version"
    sheet["B2"] = f"V{estimate.version_number} ({estimate.kind})"
    sheet["A3"] = "Statut"
    sheet["B3"] = estimate.status
    sheet["A4"] = "Devise"
    sheet["B4"] = estimate.currency_code
    sheet["A5"] = "Créé le"
    sheet["B5"] = estimate.created_at.strftime("%Y-%m-%d %H:%M")
    sheet["A6"] = "Validé le"
    sheet["B6"] = estimate.validated_at.strftime("%Y-%m-%d %H:%M") if estimate.validated_at else "-"


def _resolve_cost_code(cost_code_id: int | None, cost_code_labels: dict[int, str]) -> str:
    """Resolve a line's `cost_code_id` to its `ProjectCostCode.code`, falling back to
    `UNASSIGNED_COST_CODE_LABEL` for a line with no cost code -- shared with the
    `by_cost_code` aggregate (estimate_calculation.py) so both views agree (#71 / E6-10)."""
    if cost_code_id is None:
        return UNASSIGNED_COST_CODE_LABEL
    return cost_code_labels.get(cost_code_id, UNASSIGNED_COST_CODE_LABEL)


def _write_grid_sheet(
    sheet: Worksheet,
    project: MsProject,
    estimate: Estimate,
    labor_lines: list[EstimateLine],
    cost_lines: list[EstimateCostLine],
    cost_code_labels: dict[int, str],
) -> None:
    _write_header(sheet, project, estimate)

    row = 8
    headers = [
        "Nature",
        "Catégorie",
        "Code d'imputation",
        "Libellé",
        "Quantité",
        "Coût unitaire / horaire",
        "Montant",
    ]
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=title)
        cell.font = HEADER_FONT
    row += 1

    total_labor = 0
    for line in labor_lines:
        sheet.cell(row=row, column=1, value="MO")
        sheet.cell(row=row, column=2, value=line.accounting_code)
        sheet.cell(row=row, column=3, value=_resolve_cost_code(line.cost_code_id, cost_code_labels))
        sheet.cell(row=row, column=4, value=f"{line.task_name} ({line.role_name})")
        sheet.cell(row=row, column=5, value=float(line.hours))
        sheet.cell(row=row, column=6, value=float(line.hourly_rate))
        sheet.cell(row=row, column=7, value=float(line.budget_cost))
        total_labor += float(line.budget_cost)
        row += 1

    total_purchase = 0
    for cost_line in cost_lines:
        sheet.cell(row=row, column=1, value=cost_line.cost_type_code)
        sheet.cell(row=row, column=2, value=cost_line.accounting_code)
        sheet.cell(
            row=row, column=3, value=_resolve_cost_code(cost_line.cost_code_id, cost_code_labels)
        )
        sheet.cell(row=row, column=4, value=cost_line.label)
        sheet.cell(row=row, column=5, value=float(cost_line.quantity))
        sheet.cell(row=row, column=6, value=float(cost_line.unit_cost))
        sheet.cell(row=row, column=7, value=float(cost_line.purchase_cost))
        total_purchase += float(cost_line.purchase_cost)
        row += 1

    row += 1
    for label, value in (
        ("Sous-total MO", total_labor),
        ("Sous-total Achat", total_purchase),
        ("PRU non chargé", total_labor + total_purchase),
    ):
        sheet.cell(row=row, column=6, value=label).font = HEADER_FONT
        sheet.cell(row=row, column=7, value=value).font = HEADER_FONT
        row += 1

    for column, width in enumerate([10, 16, 18, 40, 12, 20, 14], start=1):
        sheet.column_dimensions[chr(64 + column)].width = width


def _write_aggregates_sheet(sheet: Worksheet, aggregates: EstimateAggregates) -> None:
    sheet["A1"] = "Agrégats"
    sheet["A1"].font = TITLE_FONT

    sheet["A3"] = "Total MO"
    sheet["B3"] = float(aggregates["total_labor_cost"])
    sheet["A4"] = "Total Achat"
    sheet["B4"] = float(aggregates["total_purchase_cost"])
    sheet["A5"] = "Total PRU non chargé"
    sheet["B5"] = float(aggregates["total_unburdened_cost"])

    row = 7
    sheet.cell(row=row, column=1, value="Catégorie").font = HEADER_FONT
    sheet.cell(row=row, column=2, value="Montant").font = HEADER_FONT
    row += 1
    for category_code, amount in aggregates["by_category"].items():
        sheet.cell(row=row, column=1, value=category_code)
        sheet.cell(row=row, column=2, value=float(amount))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Code d'imputation").font = HEADER_FONT
    sheet.cell(row=row, column=2, value="Montant").font = HEADER_FONT
    row += 1
    for cost_code, amount in aggregates["by_cost_code"].items():
        sheet.cell(row=row, column=1, value=cost_code)
        sheet.cell(row=row, column=2, value=float(amount))
        row += 1

    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 16


def build_estimate_workbook(db: Session, project: MsProject, estimate: Estimate) -> bytes:
    """Build the devis Excel workbook: cost grid, subtotals and category aggregates."""
    labor_lines = (
        db.query(EstimateLine)
        .filter(EstimateLine.estimate_id == estimate.id)
        .filter(EstimateLine.role_id.isnot(None))
        .order_by(EstimateLine.id)
        .all()
    )
    cost_lines = (
        db.query(EstimateCostLine)
        .filter(EstimateCostLine.estimate_id == estimate.id)
        .order_by(EstimateCostLine.id)
        .all()
    )
    aggregates = calculate_estimate_aggregates(db, estimate.id)
    cost_code_labels = {
        cost_code.id: cost_code.code
        for cost_code in db.query(ProjectCostCode)
        .filter(ProjectCostCode.project_id == project.id)
        .all()
    }

    workbook = Workbook()
    grid_sheet = workbook.active
    assert grid_sheet is not None
    grid_sheet.title = "Devis"
    _write_grid_sheet(grid_sheet, project, estimate, labor_lines, cost_lines, cost_code_labels)

    aggregates_sheet = workbook.create_sheet("Agrégats")
    _write_aggregates_sheet(aggregates_sheet, aggregates)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------------------
# The revision export (E14-07c, #365)
#
# Same workbook, read off `wf_revision_node` and its cost facets instead of the
# `wf_estimate_line`/`wf_estimate_cost_line` pair above. The legacy builder stays
# until E14-12 (#339) removes it with the tables it reads -- it is also the only
# thing this one can be *compared* against, which is the central acceptance
# criterion of #365 (`tests/test_revision_export.py` builds both workbooks from one
# set of figures and asserts them cell for cell).
# --------------------------------------------------------------------------------------

#: Display precisions of the grid, named after the columns that used to carry them.
#:
#: The legacy workbook does not render what the engine computed: it renders what
#: came back out of ``wf_estimate_line``, whose ``Numeric`` columns had already
#: rounded it. ``hours`` is a ``Numeric(14, 2)`` and ``hourly_rate`` a
#: ``Numeric(14, 4)``, so a labour line spread over three years shows ``3.33``
#: hours and not ``3.3333333333333333333333333333``. That is a **publication**
#: rule of exactly the same kind as
#: :func:`~waterfall.services.estimate_calculation.amount_at_the_cent`, and it is
#: restated here rather than dropped: an export is a publication, and #365's
#: criterion is that the two produce the same classeur.
#:
#: None of them feeds an amount. The engine keeps every digit of the product (see
#: :func:`~waterfall.services.estimate_calculation._priced_lines_of`), so the
#: ``Montant`` column below is the full-precision amount taken to the cent, exactly
#: as ``budget_cost`` was -- never a recomputation from these rounded operands.
#:
#: Four constants and not three, although two of them are equal: the non-labour
#: half of the grid prints a quantity **and** a unit cost, and they are two
#: separate columns of ``wf_estimate_cost_line`` that happen to be declared
#: ``Numeric(14, 2)`` and ``Numeric(16, 2)``. Naming one after both would have made
#: this block claim a justification it did not have, and would have moved the two
#: together the day one of the columns changes.
_HOURS_PRECISION = Decimal("0.01")
_RATE_PRECISION = Decimal("0.0001")
_QUANTITY_PRECISION = Decimal("0.01")
_UNIT_COST_PRECISION = Decimal("0.01")


def _published(value: Decimal, precision: Decimal) -> float:
    return float(value.quantize(precision, rounding=ROUND_HALF_UP))


def _write_revision_header(sheet: Worksheet, project: MsProject, revision: ProjectRevision) -> None:
    """The same six-cell block :func:`_write_header` writes, off the revision row.

    ``version_number``/``kind``/``status``/``currency_code``/``created_at``/
    ``validated_at`` are carried by ``wf_revision`` under the very same names the
    legacy ``wf_estimate`` carried them under, which is why this block is a
    transcription and not a redesign.
    """
    sheet["A1"] = f"Devis — {project.name}"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = "Version"
    sheet["B2"] = f"V{revision.version_number} ({revision.kind})"
    sheet["A3"] = "Statut"
    sheet["B3"] = revision.status
    sheet["A4"] = "Devise"
    sheet["B4"] = revision.currency_code
    sheet["A5"] = "Créé le"
    sheet["B5"] = revision.created_at.strftime("%Y-%m-%d %H:%M")
    sheet["A6"] = "Validé le"
    sheet["B6"] = revision.validated_at.strftime("%Y-%m-%d %H:%M") if revision.validated_at else "-"


def _cost_type_codes(db: Session, cost_type_ids: set[int]) -> dict[int, str]:
    if not cost_type_ids:
        return {}
    return {
        row.id: row.code for row in db.query(CostType).filter(CostType.id.in_(cost_type_ids)).all()
    }


def _write_revision_grid_sheet(
    sheet: Worksheet,
    db: Session,
    project: MsProject,
    revision: ProjectRevision,
    pricing: RevisionPricing,
    facets: Mapping[int, domain.CostFacet],
    cost_code_labels: dict[int, str],
) -> None:
    """The ``Devis`` grid, labour lines first and disbursements after.

    Two orderings meet here and neither is arbitrary. Within each block the lines
    come in the engine's own order -- depth-first over the tree, then by year for a
    labour facet spread over several -- which is the order the whole application
    reads a revision in. Labour before non-labour reproduces the two sections the
    legacy grid was built from (``wf_estimate_line`` filtered on ``role_id``, then
    ``wf_estimate_cost_line``), and it is what the two subtotals below are about:
    the block boundary *is* "Sous-total MO".

    The ``Libellé`` of a labour line is ``"<bearing task> (<role>)"``, the bearing
    task being INV-01's -- resolved by walking the tree, where the legacy line read
    a stored ``task_id``. A line at the root has none, and shows the empty task name
    the legacy engine snapshotted for exactly that case (``_single_year_labor_line``).
    """
    _write_revision_header(sheet, project, revision)

    row = 8
    headers = [
        "Nature",
        "Catégorie",
        "Code d'imputation",
        "Libellé",
        "Quantité",
        "Coût unitaire / horaire",
        "Montant",
    ]
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=title)
        cell.font = HEADER_FONT
    row += 1

    cost_type_codes = _cost_type_codes(
        db, {facet.cost_type_id for facet in facets.values() if facet.cost_type_id is not None}
    )

    total_labor = 0.0
    total_purchase = 0.0
    for nature in (domain.CostNature.LABOR, domain.CostNature.NON_LABOR):
        for line in pricing.lines:
            if line.nature is not nature:
                continue
            facet = facets[line.node_id]
            is_labor = nature is domain.CostNature.LABOR
            # The publication rule, once per line and before either subtotal moves --
            # see `estimate_calculation.calculate_revision_aggregates` for why the
            # rounding is per line and never on a node total.
            amount = float(amount_at_the_cent(line.amount))
            sheet.cell(
                row=row,
                column=1,
                value=(
                    "MO"
                    if is_labor
                    else (
                        ""
                        if facet.cost_type_id is None
                        else cost_type_codes.get(facet.cost_type_id, "")
                    )
                ),
            )
            sheet.cell(row=row, column=2, value=line.accounting_code)
            sheet.cell(
                row=row, column=3, value=_resolve_cost_code(line.cost_code_id, cost_code_labels)
            )
            sheet.cell(
                row=row,
                column=4,
                value=(
                    f"{line.bearing_task_name or ''} ({line.role_name or ''})"
                    if is_labor
                    else facet.label
                ),
            )
            sheet.cell(
                row=row,
                column=5,
                value=(
                    _published(line.hours, _HOURS_PRECISION)
                    if is_labor
                    else _published(facet.quantity, _QUANTITY_PRECISION)
                ),
            )
            sheet.cell(
                row=row,
                column=6,
                value=(
                    _published(line.hourly_rate, _RATE_PRECISION)
                    if is_labor
                    else _published(
                        facet.unit_cost if facet.unit_cost is not None else Decimal("0"),
                        _UNIT_COST_PRECISION,
                    )
                ),
            )
            sheet.cell(row=row, column=7, value=amount)
            if is_labor:
                total_labor += amount
            else:
                total_purchase += amount
            row += 1

    row += 1
    for label, value in (
        ("Sous-total MO", total_labor),
        ("Sous-total Achat", total_purchase),
        ("PRU non chargé", total_labor + total_purchase),
    ):
        sheet.cell(row=row, column=6, value=label).font = HEADER_FONT
        sheet.cell(row=row, column=7, value=value).font = HEADER_FONT
        row += 1

    for column, width in enumerate([10, 16, 18, 40, 12, 20, 14], start=1):
        sheet.column_dimensions[chr(64 + column)].width = width


def _write_revision_aggregates_sheet(sheet: Worksheet, aggregates: RevisionAggregates) -> None:
    """The ``Agrégats`` sheet, from the five figures of the revision engine.

    Written by hand rather than by widening :func:`_write_aggregates_sheet` to a
    union of the two ``TypedDict``s: the two aggregates share five keys and differ
    on two (this one also reports the rate gaps it priced through), and a single
    writer taking either would have to narrow the type back on every access. The
    duplication is five ``sheet.cell`` calls and it disappears with #339.

    The rate gaps are deliberately **not** written: they are a diagnostic of the
    read (see :class:`~waterfall.services.estimate_calculation.RevisionAggregates`),
    the endpoint publishes them as structured JSON, and adding a block here would
    make this sheet differ from the one the legacy builder writes for no reason a
    reader of the classeur could act on.
    """
    sheet["A1"] = "Agrégats"
    sheet["A1"].font = TITLE_FONT

    sheet["A3"] = "Total MO"
    sheet["B3"] = float(aggregates["total_labor_cost"])
    sheet["A4"] = "Total Achat"
    sheet["B4"] = float(aggregates["total_purchase_cost"])
    sheet["A5"] = "Total PRU non chargé"
    sheet["B5"] = float(aggregates["total_unburdened_cost"])

    row = 7
    sheet.cell(row=row, column=1, value="Catégorie").font = HEADER_FONT
    sheet.cell(row=row, column=2, value="Montant").font = HEADER_FONT
    row += 1
    for category_code, amount in aggregates["by_category"].items():
        sheet.cell(row=row, column=1, value=category_code)
        sheet.cell(row=row, column=2, value=float(amount))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Code d'imputation").font = HEADER_FONT
    sheet.cell(row=row, column=2, value="Montant").font = HEADER_FONT
    row += 1
    for cost_code, amount in aggregates["by_cost_code"].items():
        sheet.cell(row=row, column=1, value=cost_code)
        sheet.cell(row=row, column=2, value=float(amount))
        row += 1

    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 16


def build_revision_workbook(db: Session, project: MsProject, revision: ProjectRevision) -> bytes:
    """The devis workbook of one revision: cost grid, subtotals and aggregates.

    The node-model counterpart of :func:`build_estimate_workbook`, and deliberately
    the same classeur: same two sheets under the same names, same header block, same
    seven columns, same three subtotals. What changed is where every figure comes
    from -- the cost facets of ``wf_revision_node``, priced live by the engine
    (E14-07b, #364) -- and that is what makes this one work on a **draft**, where
    the legacy grid could only ever show the disbursement lines: its labour half
    read ``wf_estimate_line``, which does not exist before a validation.

    A read, and therefore refused on nothing: a validated revision exports exactly
    like a draft, and a missing ``CostRate`` prices its line at zero and is reported
    by the aggregates endpoint rather than raised here -- an export that answered
    500 because a 2031 rate is missing would make a perfectly editable draft
    unprintable.
    """
    # Loaded once and priced once, and the ``Agrégats`` sheet is summed from *that*
    # pricing: this route takes no lock, so a second `load_revision` here would let a
    # concurrent edit land between the two and put a line in the grid that the totals
    # of the same file do not count. See `aggregates_of_pricing`.
    loaded = load_revision(db, revision.id)
    pricing = price_loaded_revision(db, loaded)
    aggregates = aggregates_of_pricing(db, pricing)
    cost_code_labels = {
        cost_code.id: cost_code.code
        for cost_code in db.query(ProjectCostCode)
        .filter(ProjectCostCode.project_id == project.id)
        .all()
    }

    workbook = Workbook()
    grid_sheet = workbook.active
    assert grid_sheet is not None
    grid_sheet.title = "Devis"
    _write_revision_grid_sheet(
        grid_sheet,
        db,
        project,
        revision,
        pricing,
        loaded.revision.cost_facets,
        cost_code_labels,
    )

    aggregates_sheet = workbook.create_sheet("Agrégats")
    _write_revision_aggregates_sheet(aggregates_sheet, aggregates)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
