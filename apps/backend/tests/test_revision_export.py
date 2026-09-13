"""The devis exports and the reconciliation round trip, on the revision (E14-07c, #365).

The central acceptance criterion of the issue is a **comparison**: "the export of a
revision and that of its former equivalent produce the same classeur for an
equivalent tree and equivalent assignments". A test that built the revision workbook
and asserted it against itself would prove nothing, so the comparison below mounts
one single set of figures twice -- on the legacy socle and on the revision tree,
through the shared ``_estimate_socle_support`` seeds #364 established -- builds
*both* workbooks, and compares them cell for cell. This is the last issue in which
that is possible: E14-12 (#339) removes the legacy socle.

What the comparison covers, and what it cannot
----------------------------------------------

``export.xlsx`` is compared **cell for cell, both sheets, positionally**, header
block included. That is possible because the classeur names no identifier: it prints
accounting codes, cost-code codes, labels, quantities, rates and amounts, all of
which the two socles derive from the *same* referential rows. The two projects are
deliberately given the same name and the two records the same ``created_at``, so
that not one cell has to be excluded.

``export-reconciliation.xlsx`` cannot be compared that way, and the reason is not a
weakness of either side: it is a file of **identifiers**, and the two socles do not
identify the same things. A legacy row carries ``id`` (a devis row) *and*
``task_id`` (the ``ms_task`` it points at) plus ``outline_number``/``outline_level``;
a revision row carries ``node_id``, ``parent_node_id`` and ``position`` -- one
identity where there were two, and a derived level where there was a stored one.
There is no mapping to compare them through, because the whole point of the model is
that those columns describe the same structure twice. So the comparison there is on
every column both files state **that is not an identifier** -- the labels, the
natures, the quantities, the hours, the comments, the unit costs, the supply
statuses, the planned dates -- row for row and in order, which is what a user reads
and edits; and the identifier columns are asserted against the revision itself
rather than against the legacy file.

``cost_code_id`` is the one column that is an identifier on both sides and is
compared anyway, through its ``code``: the two projects carry two different
``wf_project_cost_code`` rows for the same ``CC-A``/``CC-B``, so resolving the id
to the code makes the imputation of every row comparable -- and the imputation is
not structure, it is data the user typed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, cast
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from _calendar_support import ensure_default_calendar
from _estimate_socle_support import (
    MO_LINES,
    PLANNED_MONTH_DAY,
    SUPPLY_STATUS,
    YEAR_ONE,
    BothSides,
    seed_both_sides,
)
from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_purchase_line,
    insert_revision,
    insert_task,
    seed_annual_rate,
)
from waterfall.api.revision_errors import (
    _TRANSLATIONS,  # pyright: ignore[reportPrivateUsage]
    REVISION_IMMUTABLE,
)
from waterfall.api.routes import revisions as revisions_routes
from waterfall.core.config import get_settings
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    CostCategory,
    CostType,
    Estimate,
    EstimateLine,
    EstimateTaskRow,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
)
from waterfall.models.revision import (
    ProjectRevision,
    RevisionCostFacet,
    RevisionNode,
    RevisionPlanFacet,
)
from waterfall.services import estimate_export
from waterfall.services.estimate_calculation import calculate_estimate_lines, price_revision
from waterfall.services.estimate_export import build_estimate_workbook, build_revision_workbook
from waterfall.services.estimate_reconciliation_export import (
    REVISION_COST_LINE_HEADERS,
    REVISION_LABOR_HEADERS,
    REVISION_TASK_HEADERS,
    build_estimate_reconciliation_workbook,
    build_revision_reconciliation_workbook,
)
from waterfall.services.estimate_reconciliation_import import (
    EstimateReconciliationFormatError,
    parse_revision_reconciliation_workbook,
    reconcile_revision,
)
from waterfall.services.revision_tree import RevisionLockConflictError

#: The instant both records are stamped with, so that the two "Créé le" cells are the
#: same cell and the comparison excludes nothing.
FROZEN_AT = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# 1. The two socles, on one set of figures
# --------------------------------------------------------------------------------------


@pytest.fixture
def both_sides() -> BothSides:
    """#364's doubly-mounted fixture, with the two halves made *printable* as one.

    Three things are aligned that the pricing comparison did not need, and each of
    them is a cell of the header block: the two projects get the same name, the two
    records the same ``created_at``/``validated_at``, and both are moved to
    ``validated`` -- the legacy grid's labour half reads ``wf_estimate_line``, which
    only a validation writes, so a draft legacy estimate has nothing to compare.
    That last point is itself a finding, and it has its own test below.
    """
    name = f"Devis {uuid4().hex[:8]}"
    sides = seed_both_sides(legacy_name=name, revision_name=name)
    with get_session_factory()() as session:
        session.add_all(calculate_estimate_lines(session, sides.legacy.estimate_id))
        estimate = session.get(Estimate, sides.legacy.estimate_id)
        assert estimate is not None
        estimate.status = "validated"
        estimate.created_at = FROZEN_AT
        estimate.validated_at = FROZEN_AT
        revision = session.get(ProjectRevision, sides.revision.revision_id)
        assert revision is not None
        revision.status = "validated"
        revision.created_at = FROZEN_AT
        revision.validated_at = FROZEN_AT
        _seed_legacy_task_rows(session, sides)
        session.commit()
    return sides


def _seed_legacy_task_rows(session: Session, sides: BothSides) -> None:
    """The ``wf_estimate_task_row`` twins of the fixture's four ``ms_task`` rows.

    Seeded here rather than in the shared socle fixture, because they are the one
    thing only the *reconciliation* comparison needs: the legacy ``Tâches`` sheet
    reads this table, which neither engine touches, so #364's seeds have no business
    carrying it. It is also, precisely, the table the revision model does not have --
    a task is a node, and ``EstimateTaskRow`` was the devis's second description of
    the same structure.
    """
    tasks = (
        session.query(MsTask)
        .filter(MsTask.project_id == sides.legacy.project_id)
        .order_by(MsTask.position)
        .all()
    )
    session.add_all(
        EstimateTaskRow(
            estimate_id=sides.legacy.estimate_id,
            task_id=task.id,
            parent_task_id=None,
            position=position,
            task_name=task.name,
            outline_number=str(position),
            outline_level=1,
            is_milestone=False,
        )
        for position, task in enumerate(tasks, start=1)
    )
    session.flush()


def _sheet_cells(content: bytes, title: str) -> list[tuple[object, ...]]:
    workbook = load_workbook(BytesIO(content), data_only=True)
    return [tuple(row) for row in workbook[title].iter_rows(values_only=True)]


def _records(content: bytes, title: str) -> list[dict[str, object]]:
    """The data rows of a header-first sheet, keyed by column name."""
    rows = _sheet_cells(content, title)
    headers = [str(header) for header in rows[0]]
    return [dict(zip(headers, row, strict=True)) for row in rows[1:]]


def test_the_two_devis_workbooks_are_the_same_classeur(both_sides: BothSides) -> None:
    """The acceptance criterion of #365, taken literally: cell for cell, both sheets.

    The expectation is produced by the **legacy** builder, off rows the revision one
    never reads, inside the same test -- not by a golden file and not by the new
    builder's own previous output. Nothing is excluded: the two projects carry the
    same name and the two records the same timestamps, so even ``Devis — <name>`` and
    ``Créé le`` are compared.

    T4 of the shared fixture is what makes this more than a comparison of exact
    arithmetic with itself: 10 hours over three years, the engine's one inexact
    operation. Its three lines print ``3.33`` hours and ``333.33`` each on both
    sides -- per line, which is what the ``Numeric(14, 2)``/``Numeric(16, 2)``
    columns of the legacy socle did before anything was added up, and what
    ``build_revision_workbook`` restates now that no column does it.
    """
    with get_session_factory()() as session:
        project = session.get(MsProject, both_sides.legacy.project_id)
        estimate = session.get(Estimate, both_sides.legacy.estimate_id)
        assert project is not None and estimate is not None
        legacy = build_estimate_workbook(session, project, estimate)

        revision_project = session.get(MsProject, both_sides.revision.project_id)
        revision = session.get(ProjectRevision, both_sides.revision.revision_id)
        assert revision_project is not None and revision is not None
        migrated = build_revision_workbook(session, revision_project, revision)

    assert load_workbook(BytesIO(migrated)).sheetnames == load_workbook(BytesIO(legacy)).sheetnames
    for title in ("Devis", "Agrégats"):
        assert _sheet_cells(migrated, title) == _sheet_cells(legacy, title), title

    # And the classeur is not empty on either side, so "identical" cannot be
    # "both produced nothing".
    grid = _sheet_cells(legacy, "Devis")
    # Seven MO lines: T1 spans two years, T4 three, T2 one, the root line one -- and
    # T3, which has no dates, prices nothing at all on either socle.
    assert sum(1 for row in grid if row[0] == "MO") == 7
    assert ("Sous-total MO", 24508.33) in {(row[5], row[6]) for row in grid}


def test_the_revision_workbook_prices_a_draft_the_legacy_one_could_not(
    both_sides: BothSides,
) -> None:
    """The one difference the comparison above hides, and the reason for the migration.

    The legacy grid's labour half reads ``wf_estimate_line``, written once by a
    validation: a **draft** devis therefore printed its disbursements and not one
    hour of MO, with a "Sous-total MO" of zero. The revision builder prices the
    facets themselves, so the same draft prints the same six MO lines as the
    validated revision above.
    """
    with get_session_factory()() as session:
        # The legacy draft, as it really was before a validation: the frozen lines the
        # grid's labour half reads simply do not exist yet.
        session.query(EstimateLine).filter(
            EstimateLine.estimate_id == both_sides.legacy.estimate_id
        ).delete()
        estimate = session.get(Estimate, both_sides.legacy.estimate_id)
        legacy_project = session.get(MsProject, both_sides.legacy.project_id)
        assert estimate is not None and legacy_project is not None
        estimate.status = "draft"
        estimate.validated_at = None
        session.flush()
        legacy_draft = build_estimate_workbook(session, legacy_project, estimate)

        revision = session.get(ProjectRevision, both_sides.revision.revision_id)
        project = session.get(MsProject, both_sides.revision.project_id)
        assert revision is not None and project is not None
        revision.status = "draft"
        revision.validated_at = None
        session.flush()
        migrated_draft = build_revision_workbook(session, project, revision)
        session.rollback()

    legacy_rows = _sheet_cells(legacy_draft, "Devis")
    migrated_rows = _sheet_cells(migrated_draft, "Devis")
    assert sum(1 for row in legacy_rows if row[0] == "MO") == 0
    assert ("Sous-total MO", 0) in {(row[5], row[6]) for row in legacy_rows}
    assert sum(1 for row in migrated_rows if row[0] == "MO") == 7
    assert ("Sous-total MO", 24508.33) in {(row[5], row[6]) for row in migrated_rows}


def test_the_two_reconciliation_workbooks_describe_the_same_lines(
    both_sides: BothSides,
) -> None:
    """The round-trip file, compared on everything the two socles both state.

    Same three sheets, same order, same number of rows, and the same human-readable
    content row for row. The identifier columns are *not* compared, and the module
    docstring says why: they are the duplication this EPIC removes, so there is
    nothing on the revision side for ``task_id``/``outline_number`` to equal.

    Everything else is, ``cost_code_id`` included -- resolved to its ``code``, since
    the two projects carry two rows for the same code. The shared fixture populates
    ``comment``, ``supply_status`` and ``planned_date`` for this test alone: they are
    stated by both files, and comparing two ``None``s proves nothing (#365 review,
    B8 -- and the legacy seed did in fact default ``supply_status`` where the
    revision seed left it unset, which no assertion caught).
    """
    with get_session_factory()() as session:
        project = session.get(MsProject, both_sides.legacy.project_id)
        estimate = session.get(Estimate, both_sides.legacy.estimate_id)
        assert project is not None and estimate is not None
        legacy = build_estimate_reconciliation_workbook(session, project, estimate)
        migrated = build_revision_reconciliation_workbook(session, both_sides.revision.revision_id)

    assert load_workbook(BytesIO(migrated)).sheetnames == ["Tâches", "MO", "Non-MO"]
    assert load_workbook(BytesIO(legacy)).sheetnames == ["Tâches", "MO", "Non-MO"]

    legacy_tasks = _records(legacy, "Tâches")
    migrated_tasks = _records(migrated, "Tâches")
    assert [(row["task_name"], row["is_milestone"]) for row in legacy_tasks] == [
        (row["name"], row["is_milestone"]) for row in migrated_tasks
    ]
    assert [row["name"] for row in migrated_tasks] == ["T1", "T2", "T3", "T4"]

    legacy_labor = _records(legacy, "MO")
    migrated_labor = _records(migrated, "MO")
    labor_columns = ("role_name", "cost_category_name", "quantity", "hours", "comment")
    assert [tuple(row[name] for name in labor_columns) for row in legacy_labor] == [
        tuple(row[name] for name in labor_columns) for row in migrated_labor
    ]
    # The bearing task is the column the legacy file stored and this one derives.
    assert [row["task_name"] for row in legacy_labor] == [
        row["bearing_task_name"] for row in migrated_labor
    ]
    # And the comments really are there to be compared, blank row included.
    assert [row["comment"] for row in migrated_labor] == [comment for *_rest, comment in MO_LINES]

    legacy_costs = _records(legacy, "Non-MO")
    migrated_costs = _records(migrated, "Non-MO")
    comparable = (
        "cost_type_code",
        "accounting_code",
        "category_code",
        "label",
        "quantity",
        "unit_cost",
        "purchase_cost",
        "supply_status",
        "planned_date",
    )
    assert [tuple(row[name] for name in comparable) for row in legacy_costs] == [
        tuple(row[name] for name in comparable) for row in migrated_costs
    ]
    assert [row["label"] for row in migrated_costs] == ["Cables", "Frais de dossier"]
    assert [row["supply_status"] for row in migrated_costs] == [SUPPLY_STATUS, SUPPLY_STATUS]
    assert [row["planned_date"] for row in migrated_costs] == [
        date(YEAR_ONE, *PLANNED_MONTH_DAY).isoformat(),
        None,
    ]

    # `cost_code_id` is an id on both sides and a *different* id on each, so it is
    # compared through the code it points at -- the imputation the user typed.
    with get_session_factory()() as session:
        code_by_id = {
            code.id: code.code
            for code in session.query(ProjectCostCode)
            .filter(
                ProjectCostCode.project_id.in_(
                    (both_sides.legacy.project_id, both_sides.revision.project_id)
                )
            )
            .all()
        }

    def codes(rows: list[dict[str, object]]) -> list[str | None]:
        return [
            None if row["cost_code_id"] is None else code_by_id[cast(int, row["cost_code_id"])]
            for row in rows
        ]

    assert codes(legacy_labor) == codes(migrated_labor) == ["CC-A", "CC-B", "CC-A", "CC-A", None]
    assert codes(legacy_costs) == codes(migrated_costs) == ["CC-B", None]

    # And the identifiers the revision file carries are the revision's own.
    with get_session_factory()() as session:
        stored = {
            node.id: node.parent_id
            for node in session.query(RevisionNode)
            .filter(RevisionNode.revision_id == both_sides.revision.revision_id)
            .all()
        }
    for row in migrated_tasks + migrated_labor + migrated_costs:
        node_id = cast(int, row["node_id"])
        assert node_id in stored
        assert row["parent_node_id"] == stored[node_id]


# --------------------------------------------------------------------------------------
# 2. The round trip over HTTP
# --------------------------------------------------------------------------------------


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"revision.export.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


class ApiFixture:
    """An owned project, a revision, one task, one MO line and one Non-MO line."""

    def __init__(
        self,
        project_id: int,
        revision_id: int,
        reference: ReferenceData,
        supply: ReferenceData,
        nodes: dict[str, int],
        cost_code_id: int,
    ) -> None:
        self.project_id = project_id
        self.revision_id = revision_id
        self.reference = reference
        self.supply = supply
        self.nodes = nodes
        self.cost_code_id = cost_code_id

    def url(self, suffix: str = "") -> str:
        return f"/projects/{self.project_id}/revisions/{self.revision_id}{suffix}"


def _seed_api_referential(
    session: Session, project_id: int, *, key: str, calendar_id: int
) -> tuple[ReferenceData, ReferenceData]:
    labor_type = CostType(code=f"MO-{key}", name="Main d'oeuvre", kind="labor")
    supply_type = CostType(code=f"SUP-{key}", name="Fourniture", kind="supply")
    session.add_all([labor_type, supply_type])
    session.flush()
    labor_category = CostCategory(
        cost_type_id=labor_type.id, accounting_code=f"DEV-{key}", name="Developpement"
    )
    supply_category = CostCategory(
        cost_type_id=supply_type.id, accounting_code=f"FOU-{key}", name="Fournitures"
    )
    resource_node = ResourceNode(code=f"IT-{key}", name="Informatique")
    session.add_all([labor_category, supply_category, resource_node])
    session.flush()
    role = ResourceRole(
        node_id=resource_node.id,
        cost_category_id=labor_category.id,
        calendar_id=calendar_id,
        name="Developpeur",
    )
    session.add(role)
    session.flush()
    labor = ReferenceData(
        project_id=project_id,
        calendar_id=calendar_id,
        role_id=role.id,
        cost_type_id=labor_type.id,
        cost_category_id=labor_category.id,
    )
    supply = ReferenceData(
        project_id=project_id,
        calendar_id=calendar_id,
        role_id=role.id,
        cost_type_id=supply_type.id,
        cost_category_id=supply_category.id,
    )
    return labor, supply


def _seed_api(client: TestClient, headers: dict[str, str], *, status: str = "draft") -> ApiFixture:
    """A revision whose MO line spans **three** years, on purpose.

    Ten hours over three years at a flat rate is the shape #368 is about: the raw
    product is ``999.9999...`` with 28 significant digits, the sum of the three
    lines at the cent is ``999.99``, and a ``quantize`` applied to the node total
    instead would answer ``1000.00``. Every figure this module asserts about a
    chiffrage loss is that one.
    """
    response = client.post("/projects", json={"name": "Revision export API"}, headers=headers)
    assert response.status_code == 201
    project_id = cast(int, response.json()["id"])
    calendar_id = ensure_default_calendar()
    year = datetime.now(UTC).year
    with get_session_factory()() as session:
        labor, supply = _seed_api_referential(
            session, project_id, key=uuid4().hex[:8], calendar_id=calendar_id
        )
        for offset in range(3):
            seed_annual_rate(session, labor, year=year + offset, hourly_rate=Decimal("100.00"))
        # `POST /projects` already created the project's single root cost code
        # (`uq_wf_project_cost_code_root`), so this hangs under it rather than beside it.
        root_code = (
            session.query(ProjectCostCode)
            .filter(ProjectCostCode.project_id == project_id, ProjectCostCode.parent_id.is_(None))
            .one()
        )
        cost_code = ProjectCostCode(
            project_id=project_id, parent_id=root_code.id, code="CC-A", name="CC-A"
        )
        session.add(cost_code)
        session.flush()
        revision = insert_revision(session, labor, status=status)
        task = insert_task(
            session,
            labor,
            revision,
            name="Etude",
            position=1,
            start_at=datetime(year, 10, 1, tzinfo=UTC),
            finish_at=datetime(year + 2, 2, 28, tzinfo=UTC),
        )
        # A second, childless task: the one shape the refusals about *placement* need
        # -- a parent a file can drop without dropping anything else with it.
        other = insert_task(session, labor, revision, name="Autre", position=2)
        mo = insert_labor_line(
            session,
            labor,
            revision,
            label="Heures d'etude",
            parent_id=task.id,
            quantity=Decimal("1"),
            hours=Decimal("10"),
            cost_code_id=cost_code.id,
        )
        purchase = insert_purchase_line(
            session,
            supply,
            revision,
            label="Cables",
            parent_id=task.id,
            position=2,
            quantity=Decimal("3"),
            unit_cost=Decimal("25.50"),
            # Set so that the ISO date column is exercised in both directions by the
            # unedited round trip, rather than only by a test that edits it.
            planned_date=date(year, 6, 1),
        )
        session.commit()
        return ApiFixture(
            project_id,
            revision.id,
            labor,
            supply,
            {"task": task.id, "other": other.id, "mo": mo.id, "purchase": purchase.id},
            cost_code.id,
        )


def _cost_facet(session: Session, node_id: int) -> RevisionCostFacet | None:
    """The cost facet of ``node_id``.

    Queried on ``node_id`` and never ``session.get``: the row's primary key is its
    own ``id``, the node it hangs off being a *unique* column rather than the key
    (``uq_wf_revision_cost_facet_node``), so ``get`` would silently answer about
    another facet.
    """
    return (
        session.query(RevisionCostFacet).filter(RevisionCostFacet.node_id == node_id).one_or_none()
    )


def _download(client: TestClient, headers: dict[str, str], fixture: ApiFixture) -> bytes:
    response = client.get(fixture.url("/export-reconciliation.xlsx"), headers=headers)
    assert response.status_code == 200, response.text
    return response.content


def _edited(content: bytes, sheet: str, edit: Any) -> bytes:
    """Apply ``edit(worksheet)`` to a downloaded workbook and hand back the bytes."""
    workbook = load_workbook(BytesIO(content))
    edit(workbook[sheet])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _post(client: TestClient, headers: dict[str, str], url: str, content: bytes) -> Any:
    return client.post(
        url,
        headers=headers,
        files={
            "file": (
                "reconciliation.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_a_round_trip_with_no_edit_changes_nothing() -> None:
    """Export, re-upload, and the plan is empty on every count.

    The property the legacy round trip established and this one keeps: an unedited
    file is a no-op, so a user can always re-submit what they were given without
    wondering what it will do. It is not free -- every "unchanged" comparison in the
    staging exists for it -- which is why it is asserted first.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), content)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), content)

    assert preview.status_code == 200, preview.text
    plan = cast(dict[str, Any], preview.json())
    assert plan["blocking_issues"] == []
    assert plan["warnings"] == []
    assert plan["applied"] is False
    assert (plan["tasks_to_create"], plan["labor_to_create"], plan["non_labor_to_create"]) == (
        0,
        0,
        0,
    )
    assert plan["tasks_to_delete"] == []
    assert plan["labor_to_update"] == [] and plan["labor_to_delete"] == []
    assert plan["non_labor_to_update"] == [] and plan["non_labor_to_delete"] == []
    assert plan["cost_losses"] == []

    assert confirm.status_code == 200, confirm.text
    applied = cast(dict[str, Any], confirm.json())
    assert applied["applied"] is True
    # Nothing changed, so the optimistic counter did not move either.
    assert applied["lock_version"] == plan["lock_version"] == 0


def test_editing_a_workbook_updates_the_facet_it_names() -> None:
    """The MO sheet's ``hours``/``quantity``/``label`` are written back to the facet.

    And the identifier that made it possible is the ``node_id``, not a devis row id
    and not the task the line hangs under: the file says which node, and the node is
    the line.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)
        hours_column = REVISION_LABOR_HEADERS.index("hours") + 1
        label_column = REVISION_LABOR_HEADERS.index("label") + 1

        def edit(sheet: Any) -> None:
            sheet.cell(row=2, column=hours_column, value=20)
            sheet.cell(row=2, column=label_column, value="Heures revues")

        edited = _edited(content, "MO", edit)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert preview.status_code == 200, preview.text
    assert cast(dict[str, Any], preview.json())["labor_to_update"] == [fixture.nodes["mo"]]
    assert confirm.status_code == 200, confirm.text
    assert cast(dict[str, Any], confirm.json())["applied"] is True

    with get_session_factory()() as session:
        facet = _cost_facet(session, fixture.nodes["mo"])
        assert facet is not None
        assert facet.hours == Decimal("20")
        assert facet.label == "Heures revues"


def test_adding_a_row_creates_a_cost_node_under_the_parent_it_names() -> None:
    """A blank ``node_id`` is a creation, placed by ``parent_node_id`` and nothing else.

    ``bearing_task_node_id`` is left blank on the new row on purpose: the bearing
    task is a *consequence* of the placement (INV-01), never an input, so the import
    does not read it -- and the line still comes out borne by the task it was hung
    under.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)
        columns = {name: index + 1 for index, name in enumerate(REVISION_COST_LINE_HEADERS)}

        def edit(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(row=row, column=columns["parent_node_id"], value=fixture.nodes["task"])
            sheet.cell(
                row=row,
                column=columns["cost_category_id"],
                value=fixture.supply.cost_category_id,
            )
            sheet.cell(row=row, column=columns["label"], value="Location")
            sheet.cell(row=row, column=columns["quantity"], value=2)
            sheet.cell(row=row, column=columns["unit_cost"], value=40)

        edited = _edited(content, "Non-MO", edit)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert preview.status_code == 200, preview.text
    assert cast(dict[str, Any], preview.json())["non_labor_to_create"] == 1
    assert confirm.status_code == 200, confirm.text

    with get_session_factory()() as session:
        created = (
            session.query(RevisionCostFacet).filter(RevisionCostFacet.label == "Location").one()
        )
        node = session.get(RevisionNode, created.node_id)
        assert node is not None
        assert node.parent_id == fixture.nodes["task"]
        assert created.unit_cost == Decimal("40")
        # The cost type was never read off the file: it is the category's own.
        assert created.cost_type_id == fixture.supply.cost_type_id


def test_removing_a_row_deletes_the_node_and_names_the_chiffrage_at_the_cent() -> None:
    """Règle 3 on the reconciliation path, in the unit #368 settled.

    A line the file no longer mentions is a deletion, and the plan names what it
    takes away rather than letting it go quietly. The amount is the MO line's --
    10 hours over three years at 100 €/h -- published as ``999.99``: the sum of the
    three priced lines each at the cent, which is what the ``Numeric(16, 2)`` column
    of the socle did. Neither ``1000.00`` (the node total rounded) nor the 28-digit
    raw product.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        def edit(sheet: Any) -> None:
            sheet.delete_rows(2)

        edited = _edited(content, "MO", edit)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert preview.status_code == 200, preview.text
    plan = cast(dict[str, Any], preview.json())
    assert plan["labor_to_delete"] == [fixture.nodes["mo"]]
    losses = cast(list[dict[str, Any]], plan["cost_losses"])
    assert [(loss["label"], loss["bearing_task_name"]) for loss in losses] == [
        ("Heures d'etude", "Etude")
    ]
    assert Decimal(str(losses[0]["amount"])) == Decimal("999.99")

    assert confirm.status_code == 200, confirm.text
    with get_session_factory()() as session:
        assert _cost_facet(session, fixture.nodes["mo"]) is None
        assert session.get(RevisionNode, fixture.nodes["mo"]) is None


def test_a_file_keeping_a_child_of_a_node_it_drops_is_refused_whole() -> None:
    """The cascade Règle 3 forbids, caught before anything is written.

    Dropping the task takes its two cost lines with it (INV-02), and the file keeps
    both. Applying it would remove rows the user explicitly left in the spreadsheet,
    which is precisely the silent removal the rule is about -- so the whole file is
    refused, with the plan and nothing written.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        def edit(sheet: Any) -> None:
            sheet.delete_rows(2)

        edited = _edited(content, "Tâches", edit)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert preview.status_code == 200, preview.text
    codes = [issue["code"] for issue in cast(dict[str, Any], preview.json())["blocking_issues"]]
    assert codes == ["NODE_DELETE_CASCADE", "NODE_DELETE_CASCADE"]

    assert confirm.status_code == 409, confirm.text
    body = cast(dict[str, Any], confirm.json())
    assert body["applied"] is False
    assert [issue["code"] for issue in body["blocking_issues"]] == codes
    with get_session_factory()() as session:
        assert session.get(RevisionNode, fixture.nodes["task"]) is not None


def test_an_unknown_node_id_is_a_blocking_issue_pointing_at_its_cell() -> None:
    """A file edited past what it identifies, refused with the row it came from."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        def edit(sheet: Any) -> None:
            sheet.cell(row=2, column=1, value=999_999)

        edited = _edited(content, "MO", edit)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)

    assert preview.status_code == 200, preview.text
    issues = cast(list[dict[str, Any]], cast(dict[str, Any], preview.json())["blocking_issues"])
    assert [(issue["code"], issue["sheet"], issue["row"]) for issue in issues] == [
        ("NODE_ID_UNKNOWN", "MO", 2)
    ]


def test_a_file_that_is_not_a_workbook_is_refused_with_every_problem_at_once() -> None:
    """The one refusal of these endpoints that is about the file, not the revision.

    It carries a code all the same -- ``RECONCILIATION_FORMAT_ERROR`` -- because no
    refusal of this API answers a free-text message.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        response = _post(
            client, headers, fixture.url("/import-reconciliation/preview"), b"not a workbook"
        )

    assert response.status_code == 400
    detail = cast(dict[str, Any], cast(dict[str, Any], response.json())["detail"])
    assert detail["code"] == "RECONCILIATION_FORMAT_ERROR"
    assert detail["issues"][0]["code"] == "INVALID_WORKBOOK"


@pytest.mark.parametrize("status", ["validated", "superseded"])
def test_a_frozen_revision_still_exports_and_still_previews_but_refuses_the_confirm(
    status: str,
) -> None:
    """The acceptance criterion of #365 on immutability, and its exact boundary.

    Both exports and the preview are **reads**: a validated revision is still
    printable and still analysable, and refusing that would leave a user unable to
    look at what they own. The confirm is the write, and it answers the one code
    #331 posted for INV-03 -- ``REVISION_IMMUTABLE``, from
    ``api.revision_errors._TRANSLATIONS``, the same table and the same string the
    planning facet answers. No second translation table exists here.

    ``superseded`` is parametrised beside ``validated`` because INV-03 covers both
    and the remedy is the same: copy the revision.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers, status=status)
        devis = client.get(fixture.url("/export.xlsx"), headers=headers)
        reconciliation = client.get(fixture.url("/export-reconciliation.xlsx"), headers=headers)
        content = cast(bytes, reconciliation.content)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), content)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), content)

    assert devis.status_code == 200
    assert reconciliation.status_code == 200
    assert preview.status_code == 200, preview.text
    assert cast(dict[str, Any], preview.json())["blocking_issues"] == []

    assert confirm.status_code == 409, confirm.text
    assert cast(dict[str, Any], confirm.json())["detail"] == {"code": "REVISION_IMMUTABLE"}


def test_the_immutable_code_is_the_one_the_planning_facet_answers() -> None:
    """The criterion said in the only way that cannot drift: by the constant itself.

    ``REVISION_IMMUTABLE`` is named once, in ``api.revision_errors``, and the
    reconciliation reaches it by raising the domain's own
    ``ImmutableRevisionError`` -- the very class ``_TRANSLATIONS`` maps. Asserting
    the string here would have let a second, identical-looking table exist.
    """
    immutable = {code for _error, _status, code in _TRANSLATIONS if code == REVISION_IMMUTABLE}
    assert immutable == {"REVISION_IMMUTABLE"}
    assert [
        error.__name__ for error, _status, code in _TRANSLATIONS if code == REVISION_IMMUTABLE
    ] == ["ImmutableRevisionError", "FrozenRevisionError"]


# --------------------------------------------------------------------------------------
# 3. #368: a published chiffrage loss is a euro amount, on every route that quotes one
# --------------------------------------------------------------------------------------


def test_the_deletion_route_and_the_aggregates_publish_the_same_euro_figure() -> None:
    """#368, folded into this issue: two of the three routes, on one figure.

    ``POST .../nodes/delete`` used to answer ``999.9999999999999999999999999`` for
    this MO line, because #364 bounded the ``quantize`` to the aggregates endpoint.
    Both now answer ``999.99``, and they answer it for the same reason: the engine
    rounds **each priced line** and sums the rounded amounts
    (``RevisionPricing.published_amount_of``), which is what the ``Numeric(16, 2)``
    column of the legacy socle did. Rounding the node total instead -- the obvious
    ``quantize`` at the response boundary -- would have answered ``1000.00`` here and
    made the deletion dialog disagree with the total shown beside it.

    The third route, the import diff, is pinned in ``test_revision_import.py``,
    where its plumbing lives.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        aggregates = client.get(fixture.url("/aggregates"), headers=headers)
        deleted = client.post(
            fixture.url("/nodes/delete"),
            json={"node_ids": [fixture.nodes["mo"]], "expected_lock_version": 0},
            headers=headers,
        )

    assert aggregates.status_code == 200
    totals = cast(dict[str, Any], aggregates.json())
    assert Decimal(str(totals["total_labor_cost"])) == Decimal("999.99")

    assert deleted.status_code == 200, deleted.text
    losses = cast(list[dict[str, Any]], cast(dict[str, Any], deleted.json())["cost_losses"])
    assert [Decimal(str(loss["amount"])) for loss in losses] == [Decimal("999.99")]

    # The MO node is gone, and the disbursement it sat beside is untouched: the
    # figure above was about the line that disappeared, nothing else.
    with get_session_factory()() as session:
        pricing = price_revision(session, fixture.revision_id)
    assert set(pricing.amount_by_node) == {fixture.nodes["purchase"]}


def test_the_raw_product_and_the_published_amount_are_two_different_numbers() -> None:
    """The reason the engine carries two mappings rather than rounding in place.

    ``amount_by_node`` is what the domain computes with; ``published_amount_by_node``
    is what an API answers. On a multi-year MO line they differ, and the difference
    is exactly the residue the legacy column dropped line by line. Pinned so that a
    future simplification collapsing the two is a red test rather than a silent
    change of what a confirmation dialog shows.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

    with get_session_factory()() as session:
        pricing = price_revision(session, fixture.revision_id)

    node_id = fixture.nodes["mo"]
    assert pricing.amount_by_node[node_id] == Decimal("999.9999999999999999999999999")
    assert pricing.published_amount_by_node[node_id] == Decimal("999.99")
    # The disbursement has no residue at all, and is the same figure either way.
    assert pricing.amount_by_node[fixture.nodes["purchase"]] == Decimal("76.50")
    assert pricing.published_amount_by_node[fixture.nodes["purchase"]] == Decimal("76.50")


# --------------------------------------------------------------------------------------
# 4. The refusals and the warnings, row by row
# --------------------------------------------------------------------------------------


def _column(headers: list[str], name: str) -> int:
    return headers.index(name) + 1


def _clear(sheet: Any, row: int, column: int) -> None:
    """Empty a cell.

    ``sheet.cell(row, column, value=None)`` does *not*: openpyxl's ``value`` keyword
    defaults to ``None`` and is only written when it is something else, so the call
    would silently leave the exported value in place -- and the test would assert
    against a file the user never produced.
    """
    sheet.cell(row=row, column=column).value = None


def _preview_plan(
    client: TestClient,
    headers: dict[str, str],
    fixture: ApiFixture,
    sheet: str,
    edit: Any,
) -> dict[str, Any]:
    edited = _edited(_download(client, headers, fixture), sheet, edit)
    response = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def _blocking(plan: dict[str, Any]) -> list[tuple[str, str | None, int | None]]:
    return [
        (issue["code"], issue["sheet"], issue["row"])
        for issue in cast(list[dict[str, Any]], plan["blocking_issues"])
    ]


def test_a_mo_row_missing_a_required_value_is_refused_at_its_own_row() -> None:
    """The values a MO line cannot do without, named against the cell they are missing
    from rather than as a refusal of the whole sheet."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def edit(sheet: Any) -> None:
            _clear(sheet, 2, _column(REVISION_LABOR_HEADERS, "hours"))

        plan = _preview_plan(client, headers, fixture, "MO", edit)

    assert _blocking(plan) == [("LABOR_ROW_INCOMPLETE", "MO", 2)]


def test_a_cost_code_of_another_project_is_refused_on_either_cost_sheet() -> None:
    """The one referential check both cost sheets share, so it is stated once.

    A cost code is scoped to a project and may be deactivated; either way the import
    refuses it here rather than letting the write fail on a foreign key, which is
    what makes the preview able to predict it.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def edit(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(REVISION_LABOR_HEADERS, "cost_code_id"), value=999_999)

        plan = _preview_plan(client, headers, fixture, "MO", edit)

    assert _blocking(plan) == [("COST_CODE_INVALID", "MO", 2)]


def test_changing_the_role_of_an_existing_mo_line_is_refused_rather_than_applied() -> None:
    """A different role is a different line, not an edit of this one.

    The legacy reconciliation refused it for the same reason and under a name this
    one keeps: the role decides the cost category, the rate, and -- through Règle 1
    -- the calendar of the tasks above. Swapping it in a spreadsheet cell would
    silently re-price and re-schedule; deleting the line and adding another says so.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def edit(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(REVISION_LABOR_HEADERS, "role_id"), value=999_999)

        plan = _preview_plan(client, headers, fixture, "MO", edit)

    assert _blocking(plan) == [("LABOR_IDENTITY_CHANGE_REJECTED", "MO", 2)]


def test_a_new_mo_row_needs_an_active_labour_role() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def edit(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(row=row, column=_column(REVISION_LABOR_HEADERS, "role_id"), value=999_999)
            sheet.cell(row=row, column=_column(REVISION_LABOR_HEADERS, "label"), value="Autre MO")
            sheet.cell(row=row, column=_column(REVISION_LABOR_HEADERS, "quantity"), value=1)
            sheet.cell(row=row, column=_column(REVISION_LABOR_HEADERS, "hours"), value=4)

        plan = _preview_plan(client, headers, fixture, "MO", edit)

    assert _blocking(plan) == [("LABOR_ROLE_INVALID", "MO", 3)]


@pytest.mark.parametrize(
    ("parent", "code"),
    [
        ("unknown", "NODE_PARENT_UNKNOWN"),
        ("purchase", "NODE_PARENT_IS_COST_LINE"),
        ("milestone", "NODE_PARENT_IS_MILESTONE"),
    ],
)
def test_a_creation_under_an_impossible_parent_is_refused_before_the_domain_sees_it(
    parent: str, code: str
) -> None:
    """The three placements the domain would refuse, restated at staging time.

    Not a second rule: each is the very refusal
    ``waterfall.domain.revision`` raises (an unknown node, INV-11's facet placement,
    INV-27's childless jalon). Restated here because a preview that reported nothing
    and a confirm that answered 400 would not be the same analysis -- which is the
    one property these two endpoints promise each other.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        if parent == "milestone":
            with get_session_factory()() as session:
                facet = (
                    session.query(RevisionPlanFacet)
                    .filter(RevisionPlanFacet.node_id == fixture.nodes["other"])
                    .one()
                )
                facet.is_milestone = True
                session.commit()
        parent_id = {
            "unknown": 999_999,
            "purchase": fixture.nodes["purchase"],
            "milestone": fixture.nodes["other"],
        }[parent]

        def edit(sheet: Any) -> None:
            row = sheet.max_row + 1
            columns = REVISION_COST_LINE_HEADERS
            sheet.cell(row=row, column=_column(columns, "parent_node_id"), value=parent_id)
            sheet.cell(
                row=row,
                column=_column(columns, "cost_category_id"),
                value=fixture.supply.cost_category_id,
            )
            sheet.cell(row=row, column=_column(columns, "label"), value="Location")
            sheet.cell(row=row, column=_column(columns, "quantity"), value=1)
            sheet.cell(row=row, column=_column(columns, "unit_cost"), value=10)

        plan = _preview_plan(client, headers, fixture, "Non-MO", edit)

    assert _blocking(plan) == [(code, "Non-MO", 3)]


def test_creating_under_a_node_the_same_file_drops_is_refused() -> None:
    """The other half of "a creation must find its parent alive".

    The file removes ``Autre`` -- which has no children, so no cascade issue -- and
    hangs a new line under it in the same breath. Applying the two in order would
    write against a node that no longer exists, so the file is refused whole.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        def drop_other(sheet: Any) -> None:
            sheet.delete_rows(3)

        content = _edited(content, "Tâches", drop_other)

        def add_line(sheet: Any) -> None:
            row = sheet.max_row + 1
            columns = REVISION_COST_LINE_HEADERS
            sheet.cell(
                row=row, column=_column(columns, "parent_node_id"), value=fixture.nodes["other"]
            )
            sheet.cell(
                row=row,
                column=_column(columns, "cost_category_id"),
                value=fixture.supply.cost_category_id,
            )
            sheet.cell(row=row, column=_column(columns, "label"), value="Location")
            sheet.cell(row=row, column=_column(columns, "quantity"), value=1)
            sheet.cell(row=row, column=_column(columns, "unit_cost"), value=10)

        content = _edited(content, "Non-MO", add_line)
        response = _post(client, headers, fixture.url("/import-reconciliation/preview"), content)

    assert response.status_code == 200, response.text
    assert _blocking(cast(dict[str, Any], response.json())) == [
        ("NODE_PARENT_DELETED", "Non-MO", 3)
    ]


def test_a_node_id_named_on_the_wrong_sheet_is_refused() -> None:
    """The three sheets are three views of one tree, so an id belongs to exactly one.

    A cost node listed under ``Tâches``, or a disbursement listed under ``MO``, is a
    file that no longer describes the tree it came from -- and the two refusals are
    not the same check: the first is "this node carries no planning facet", the
    second "this cost facet is not labour" (INV-19/INV-20 make the two natures
    exclusive).

    The sheet the id was *taken from* answers ``NODE_ID_DUPLICATED`` in the same
    breath, and that is correct rather than noise: one node, one row.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def on_tasks(sheet: Any) -> None:
            sheet.cell(row=2, column=1, value=fixture.nodes["mo"])

        tasks_plan = _preview_plan(client, headers, fixture, "Tâches", on_tasks)

        def on_labor(sheet: Any) -> None:
            sheet.cell(row=2, column=1, value=fixture.nodes["purchase"])

        labor_plan = _preview_plan(client, headers, fixture, "MO", on_labor)

    assert ("NODE_KIND_MISMATCH", "Tâches", 2) in _blocking(tasks_plan)
    assert ("NODE_KIND_MISMATCH", "MO", 2) in _blocking(labor_plan)


def test_the_same_node_named_twice_is_refused_once() -> None:
    """Two rows claiming one node would be two contradictory edits of one line."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def edit(sheet: Any) -> None:
            sheet.cell(row=sheet.max_row + 1, column=1, value=fixture.nodes["mo"])

        plan = _preview_plan(client, headers, fixture, "MO", edit)

    assert _blocking(plan) == [("NODE_ID_DUPLICATED", "MO", 3)]


def test_a_non_mo_row_is_refused_on_its_category_and_on_its_supply_status() -> None:
    """The two referential rules of a disbursement, each against its own cell."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        columns = REVISION_COST_LINE_HEADERS

        def unknown_category(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(columns, "cost_category_id"), value=999_999)

        category_plan = _preview_plan(client, headers, fixture, "Non-MO", unknown_category)

        def bogus_status(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(columns, "supply_status"), value="livree")

        status_plan = _preview_plan(client, headers, fixture, "Non-MO", bogus_status)

        def blank_label(sheet: Any) -> None:
            _clear(sheet, 2, _column(columns, "label"))

        label_plan = _preview_plan(client, headers, fixture, "Non-MO", blank_label)

    assert _blocking(category_plan) == [("COST_LINE_CATEGORY_INVALID", "Non-MO", 2)]
    assert _blocking(status_plan) == [("COST_LINE_SUPPLY_STATUS_INVALID", "Non-MO", 2)]
    assert _blocking(label_plan) == [("COST_LINE_ROW_INCOMPLETE", "Non-MO", 2)]


def test_a_blank_category_on_an_existing_non_mo_row_keeps_the_one_it_has() -> None:
    """ "Unchanged", not "detached" -- the rule the legacy round trip settled.

    The cell is the one a user is most likely to clear by accident, and reading it
    as "drop the category" would break the line's shape outright (INV-20). It is
    still *checked*: the stored category is the one the active/non-labour rule is
    applied to, so a category deactivated since the line was created is reported
    here rather than raised at apply time.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        columns = REVISION_COST_LINE_HEADERS

        def edit(sheet: Any) -> None:
            _clear(sheet, 2, _column(columns, "cost_category_id"))
            sheet.cell(row=2, column=_column(columns, "label"), value="Cables blindes")

        edited = _edited(_download(client, headers, fixture), "Non-MO", edit)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert confirm.status_code == 200, confirm.text
    assert cast(dict[str, Any], confirm.json())["non_labor_to_update"] == [
        fixture.nodes["purchase"]
    ]
    with get_session_factory()() as session:
        facet = _cost_facet(session, fixture.nodes["purchase"])
        assert facet is not None
        assert facet.label == "Cables blindes"
        assert facet.cost_category_id == fixture.supply.cost_category_id
        assert facet.cost_type_id == fixture.supply.cost_type_id


def test_a_new_task_row_needs_a_name_and_otherwise_creates_a_task() -> None:
    """The only two things the ``Tâches`` sheet can do, in one test.

    It creates and it deletes; it never updates -- see
    :func:`test_renaming_or_moving_an_existing_row_is_a_warning_not_a_write`.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def nameless(sheet: Any) -> None:
            sheet.cell(
                row=sheet.max_row + 1,
                column=_column(REVISION_TASK_HEADERS, "position"),
                value=9,
            )

        refused = _preview_plan(client, headers, fixture, "Tâches", nameless)

        def named(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(
                row=row,
                column=_column(REVISION_TASK_HEADERS, "parent_node_id"),
                value=fixture.nodes["task"],
            )
            sheet.cell(row=row, column=_column(REVISION_TASK_HEADERS, "name"), value="Recette")

        edited = _edited(_download(client, headers, fixture), "Tâches", named)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert _blocking(refused) == [("TASK_NAME_REQUIRED", "Tâches", 4)]
    assert confirm.status_code == 200, confirm.text
    assert cast(dict[str, Any], confirm.json())["tasks_to_create"] == 1

    with get_session_factory()() as session:
        created = session.query(RevisionPlanFacet).filter(RevisionPlanFacet.name == "Recette").one()
        node = session.get(RevisionNode, created.node_id)
        assert node is not None
        assert node.parent_id == fixture.nodes["task"]


def test_a_new_mo_row_creates_a_labour_line_borne_by_the_task_it_hangs_under() -> None:
    """The bearing task is a consequence of the placement, and never an input.

    The new row names its ``parent_node_id`` and nothing else about the tree, and
    comes out priced against that task's years -- INV-01 resolved on read, exactly
    as for a line created through ``POST .../cost-lines``.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        columns = REVISION_LABOR_HEADERS

        def edit(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(
                row=row, column=_column(columns, "parent_node_id"), value=fixture.nodes["task"]
            )
            sheet.cell(row=row, column=_column(columns, "role_id"), value=fixture.reference.role_id)
            sheet.cell(row=row, column=_column(columns, "cost_code_id"), value=fixture.cost_code_id)
            sheet.cell(row=row, column=_column(columns, "label"), value="Recette")
            sheet.cell(row=row, column=_column(columns, "quantity"), value=1)
            sheet.cell(row=row, column=_column(columns, "hours"), value=30)

        edited = _edited(_download(client, headers, fixture), "MO", edit)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert confirm.status_code == 200, confirm.text
    assert cast(dict[str, Any], confirm.json())["labor_to_create"] == 1

    with get_session_factory()() as session:
        pricing = price_revision(session, fixture.revision_id)
    created = [line for line in pricing.lines if line.label == "Recette"]
    assert [line.bearing_task_name for line in created] == ["Etude", "Etude", "Etude"]
    assert sum(line.hours for line in created) == Decimal("30")


def test_renaming_or_moving_an_existing_row_is_a_warning_not_a_write() -> None:
    """What the import deliberately does **not** do, said out loud in the response.

    Renaming a task, marking it a jalon, re-parenting a line: each has an endpoint
    of its own whose refusals (a cycle, a jalon gaining a child, a position outside
    the sibling band) are stated once. An import re-deriving the tree from a
    spreadsheet would be a second, weaker formulation of all three -- so it reports
    the change it ignored rather than applying it, and writes nothing.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def rename(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(REVISION_TASK_HEADERS, "name"), value="Etude bis")
            sheet.cell(row=2, column=_column(REVISION_TASK_HEADERS, "is_milestone"), value=True)

        task_plan = _preview_plan(client, headers, fixture, "Tâches", rename)

        def reparent(sheet: Any) -> None:
            sheet.cell(
                row=2,
                column=_column(REVISION_LABOR_HEADERS, "parent_node_id"),
                value=fixture.nodes["other"],
            )

        move_plan = _preview_plan(client, headers, fixture, "MO", reparent)

    assert _blocking(task_plan) == [] and _blocking(move_plan) == []
    warnings = [
        (issue["code"], issue["sheet"], issue["row"], issue["message"])
        for issue in cast(list[dict[str, Any]], task_plan["warnings"])
    ]
    assert [(code, sheet, row) for code, sheet, row, _message in warnings] == [
        ("TASK_FIELD_CHANGE_IGNORED", "Tâches", 2)
    ]
    assert "name, is_milestone" in warnings[0][3]
    assert [
        (issue["code"], issue["sheet"], issue["row"])
        for issue in cast(list[dict[str, Any]], move_plan["warnings"])
    ] == [("NODE_MOVE_IGNORED", "MO", 2)]
    # And nothing moved: the warning is the whole of the answer.
    with get_session_factory()() as session:
        node = session.get(RevisionNode, fixture.nodes["mo"])
        assert node is not None and node.parent_id == fixture.nodes["task"]


def test_dropping_a_task_with_its_lines_deletes_the_subtree_and_names_every_loss() -> None:
    """The file drops the task *and* both its lines, which is what INV-02 does anyway.

    The plan then reports one task deletion and the two cost nodes that go with it,
    each named with what it was worth -- Règle 3's safeguard on the reconciliation
    path, in the same euros-at-the-cent unit the deletion route and the import diff
    publish.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        def drop_first_row(sheet: Any) -> None:
            sheet.delete_rows(2)

        content = _edited(content, "Tâches", drop_first_row)
        content = _edited(content, "MO", drop_first_row)
        content = _edited(content, "Non-MO", drop_first_row)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), content)

    assert confirm.status_code == 200, confirm.text
    plan = cast(dict[str, Any], confirm.json())
    assert plan["tasks_to_delete"] == [fixture.nodes["task"]]
    assert plan["labor_to_delete"] == [fixture.nodes["mo"]]
    assert plan["non_labor_to_delete"] == [fixture.nodes["purchase"]]
    losses = {
        loss["label"]: Decimal(str(loss["amount"]))
        for loss in cast(list[dict[str, Any]], plan["cost_losses"])
    }
    assert losses == {"Heures d'etude": Decimal("999.99"), "Cables": Decimal("76.50")}

    with get_session_factory()() as session:
        remaining = (
            session.query(RevisionNode)
            .filter(RevisionNode.revision_id == fixture.revision_id)
            .all()
        )
    assert [node.id for node in remaining] == [fixture.nodes["other"]]


def test_a_line_created_at_the_root_needs_no_parent_at_all() -> None:
    """INV-01's project-wide global cost, reachable from the round trip too.

    A blank ``parent_node_id`` is not a missing value: it is the root, where a cost
    line has no bearing task and is explicitly allowed to sit. The line still counts
    towards every total, which is the behaviour the legacy socle lost more than once
    to an ``INNER JOIN`` (#289).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        columns = REVISION_COST_LINE_HEADERS

        def edit(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(
                row=row,
                column=_column(columns, "cost_category_id"),
                value=fixture.supply.cost_category_id,
            )
            sheet.cell(row=row, column=_column(columns, "label"), value="Frais de dossier")
            sheet.cell(row=row, column=_column(columns, "quantity"), value=2)
            sheet.cell(row=row, column=_column(columns, "unit_cost"), value=10)

        edited = _edited(_download(client, headers, fixture), "Non-MO", edit)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert confirm.status_code == 200, confirm.text
    with get_session_factory()() as session:
        created = (
            session.query(RevisionCostFacet)
            .filter(RevisionCostFacet.label == "Frais de dossier")
            .one()
        )
        node = session.get(RevisionNode, created.node_id)
        assert node is not None and node.parent_id is None
        pricing = price_revision(session, fixture.revision_id)
    assert pricing.published_amount_by_node[created.node_id] == Decimal("20.00")
    assert [
        line.bearing_task_name for line in pricing.lines if line.node_id == created.node_id
    ] == [None]


def test_the_parent_refusal_is_the_same_one_on_all_three_sheets() -> None:
    """One rule, three sheets: a creation hangs under an existing task or at the root.

    Stated once (``_Staging.parent``) and exercised from each sheet here, because
    "the same refusal" is the kind of claim that quietly stops being true when a
    fourth branch is added to one staging function and not the others.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def new_task(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(row=row, column=_column(REVISION_TASK_HEADERS, "parent_node_id"), value=9)
            sheet.cell(row=row, column=_column(REVISION_TASK_HEADERS, "name"), value="Recette")

        task_plan = _preview_plan(client, headers, fixture, "Tâches", new_task)

        def new_labor(sheet: Any) -> None:
            row = sheet.max_row + 1
            columns = REVISION_LABOR_HEADERS
            sheet.cell(row=row, column=_column(columns, "parent_node_id"), value=9)
            sheet.cell(row=row, column=_column(columns, "role_id"), value=fixture.reference.role_id)
            sheet.cell(row=row, column=_column(columns, "label"), value="Recette")
            sheet.cell(row=row, column=_column(columns, "quantity"), value=1)
            sheet.cell(row=row, column=_column(columns, "hours"), value=4)

        labor_plan = _preview_plan(client, headers, fixture, "MO", new_labor)

    assert _blocking(task_plan) == [("NODE_PARENT_UNKNOWN", "Tâches", 4)]
    assert _blocking(labor_plan) == [("NODE_PARENT_UNKNOWN", "MO", 3)]


def test_a_new_non_mo_row_without_a_category_has_none_to_fall_back_on() -> None:
    """The "blank means unchanged" rule has nothing to keep on a *creation*.

    An existing row falls back to the category its facet already carries; a new one
    has no facet, so the blank cell is simply a missing value and is named as one.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        columns = REVISION_COST_LINE_HEADERS

        def edit(sheet: Any) -> None:
            row = sheet.max_row + 1
            sheet.cell(row=row, column=_column(columns, "label"), value="Sans categorie")
            sheet.cell(row=row, column=_column(columns, "quantity"), value=1)
            sheet.cell(row=row, column=_column(columns, "unit_cost"), value=10)

        plan = _preview_plan(client, headers, fixture, "Non-MO", edit)

    assert _blocking(plan) == [("COST_LINE_ROW_INCOMPLETE", "Non-MO", 3)]


def test_the_non_mo_sheet_refuses_a_foreign_cost_code_and_a_misplaced_supply_status() -> None:
    """The two Non-MO refusals the MO sheet has no counterpart for.

    ``supply_status`` belongs to a *supply* cost line and to no other: a "frais"
    line has nothing to be ordered or received. The rule is the one the removed
    create route enforced and the legacy staging restated; here it is checked
    against the category the row actually lands on.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        columns = REVISION_COST_LINE_HEADERS
        with get_session_factory()() as session:
            other_type = CostType(code=f"OTH-{uuid4().hex[:8]}", name="Frais", kind="other")
            session.add(other_type)
            session.flush()
            other_category = CostCategory(
                cost_type_id=other_type.id,
                accounting_code=f"FRA-{uuid4().hex[:8]}",
                name="Frais divers",
            )
            session.add(other_category)
            session.commit()
            other_category_id = other_category.id

        def foreign_cost_code(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(columns, "cost_code_id"), value=999_999)

        code_plan = _preview_plan(client, headers, fixture, "Non-MO", foreign_cost_code)

        def misplaced_status(sheet: Any) -> None:
            sheet.cell(row=2, column=_column(columns, "cost_category_id"), value=other_category_id)
            sheet.cell(row=2, column=_column(columns, "supply_status"), value="ordered")

        status_plan = _preview_plan(client, headers, fixture, "Non-MO", misplaced_status)

    assert _blocking(code_plan) == [("COST_CODE_INVALID", "Non-MO", 2)]
    assert _blocking(status_plan) == [("COST_LINE_SUPPLY_STATUS_INVALID", "Non-MO", 2)]


def test_moving_a_non_mo_line_is_ignored_exactly_like_moving_a_mo_one() -> None:
    """The warning is on the *node*, not on the nature of the facet it carries.

    Which is the whole point of the model: there is one tree, so "moving a line" is
    one operation -- ``POST .../nodes/move`` -- and one thing this import declines
    to do, whichever sheet the row was edited on.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)

        def edit(sheet: Any) -> None:
            sheet.cell(
                row=2,
                column=_column(REVISION_COST_LINE_HEADERS, "parent_node_id"),
                value=fixture.nodes["other"],
            )

        plan = _preview_plan(client, headers, fixture, "Non-MO", edit)

    assert _blocking(plan) == []
    assert [
        (issue["code"], issue["sheet"], issue["row"])
        for issue in cast(list[dict[str, Any]], plan["warnings"])
    ] == [("NODE_MOVE_IGNORED", "Non-MO", 2)]


def test_a_labour_node_listed_under_non_mo_is_refused_on_its_nature() -> None:
    """The mirror of the MO-sheet check, reachable only once the MO row is gone.

    A node is claimed by the first sheet that names it, and ``MO`` is staged before
    ``Non-MO``; so the only file that reaches this branch is one that moved the row
    across sheets rather than duplicating it. That file is exactly the one this
    refusal is for.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

        def drop_mo(sheet: Any) -> None:
            sheet.delete_rows(2)

        content = _edited(content, "MO", drop_mo)

        def claim_it(sheet: Any) -> None:
            sheet.cell(row=2, column=1, value=fixture.nodes["mo"])

        content = _edited(content, "Non-MO", claim_it)
        response = _post(client, headers, fixture.url("/import-reconciliation/preview"), content)

    assert response.status_code == 200, response.text
    assert _blocking(cast(dict[str, Any], response.json())) == [("NODE_KIND_MISMATCH", "Non-MO", 2)]


def _workbook(sheets: Mapping[str, Sequence[Sequence[object]]]) -> bytes:
    workbook = Workbook()
    default = workbook.active
    assert default is not None
    workbook.remove(default)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_the_parser_reports_every_format_problem_of_a_revision_workbook_at_once() -> None:
    """A file that is not the file the export writes, refused whole rather than partly.

    Two kinds of problem, told apart on purpose and both checked here: a header row
    that does not match the exported layout (the file cannot be read as structured
    data at all) and a cell holding the wrong kind of value in a column that admits
    only one. Neither produces a partial parse -- the whole list comes back at once,
    which is what lets a user fix a spreadsheet in one pass instead of one cell per
    round trip.

    A trailing blank row is *not* a problem and is skipped: every spreadsheet
    acquires them, and refusing one would make the round trip fail on a file the
    user only scrolled through.
    """
    with pytest.raises(EstimateReconciliationFormatError) as bad_headers:
        parse_revision_reconciliation_workbook(
            _workbook(
                {
                    "Tâches": [["id", "task_id"]],
                    "MO": [REVISION_LABOR_HEADERS],
                    "Non-MO": [REVISION_COST_LINE_HEADERS],
                }
            )
        )

    assert [issue["code"] for issue in bad_headers.value.issues] == ["INVALID_HEADER"]

    blank = [None] * len(REVISION_LABOR_HEADERS)
    with pytest.raises(EstimateReconciliationFormatError) as bad_cells:
        parse_revision_reconciliation_workbook(
            _workbook(
                {
                    "Tâches": [REVISION_TASK_HEADERS, [*[None] * 8]],
                    "MO": [
                        REVISION_LABOR_HEADERS,
                        ["pas un entier", *blank[1:]],
                        blank,
                    ],
                    "Non-MO": [
                        REVISION_COST_LINE_HEADERS,
                        [
                            *[None] * 16,
                            None,
                            "pas une date",
                        ],
                    ],
                }
            )
        )

    assert [issue["code"] for issue in bad_cells.value.issues] == [
        "INVALID_INTEGER",
        "INVALID_DATE",
    ]
    assert [issue["sheet"] for issue in bad_cells.value.issues] == ["MO", "Non-MO"]


def test_a_missing_sheet_is_named_rather_than_crashed_on() -> None:
    with pytest.raises(EstimateReconciliationFormatError) as missing:
        parse_revision_reconciliation_workbook(
            _workbook({"Tâches": [REVISION_TASK_HEADERS], "MO": [REVISION_LABOR_HEADERS]})
        )

    assert [(issue["code"], issue["sheet"]) for issue in missing.value.issues] == [
        ("MISSING_SHEET", "Non-MO")
    ]


# --------------------------------------------------------------------------------------
# 5. Round-2 review findings
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["/export.xlsx", "/export-reconciliation.xlsx"])
@pytest.mark.parametrize("name", ["Projet € Étude", 'Projet "guillemets"', "Extension — 250 k€"])
def test_a_project_name_no_header_can_carry_still_downloads(name: str, suffix: str) -> None:
    """H1: both downloads answered 500 on a perfectly legal project name.

    ``MsProject.name`` is trimmed and bounded and otherwise unrestricted, and the
    filename was interpolated raw into ``Content-Disposition``. Starlette encodes
    response headers as latin-1, so ``€``/``—`` raised ``UnicodeEncodeError`` inside
    the response and a *read-only* route answered 500; a ``"`` closed the quoted
    string early and truncated what the browser saved.

    The fix is RFC 6266: a transliterated ASCII ``filename`` for the fallback and
    the real name percent-encoded in ``filename*=UTF-8''``. Both routes are
    parametrised because both built their filename the same way, and a fix applied
    to one of them is a fix applied to neither.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        with get_session_factory()() as session:
            project = session.get(MsProject, fixture.project_id)
            assert project is not None
            project.name = name
            session.commit()

        response = client.get(fixture.url(suffix), headers=headers)

    assert response.status_code == 200, response.text
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("attachment; ")
    assert "filename*=UTF-8''" in disposition
    # The fallback is ASCII, quote-free and non-empty -- the three things that broke.
    fallback = disposition.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback
    assert fallback.isascii()
    assert '"' not in fallback
    # And the real name survives, percent-encoded.
    assert quote(name.replace(" ", "-"), safe="") in disposition


def test_the_devis_workbook_loads_and_prices_the_revision_exactly_once() -> None:
    """M1: the two sheets of one file came from two independent snapshots.

    ``build_revision_workbook`` priced the revision for the ``Devis`` grid and then
    called ``calculate_revision_aggregates``, which loaded and priced it all over
    again. The route takes no lock and the session is READ COMMITTED, so an edit
    landing between the two reads produced one workbook whose ``Sous-total MO`` and
    whose ``Total MO`` disagreed -- printed and sent to a client.

    Counted rather than raced, because a race is exactly what a test cannot pin
    down: one load, one pricing, and the contradiction has nowhere to come from.
    """
    loads: list[int] = []
    prices: list[int] = []
    real_load = estimate_export.load_revision
    real_price = estimate_export.price_loaded_revision

    def counting_load(db: Session, revision_id: int) -> Any:
        loads.append(revision_id)
        return real_load(db, revision_id)

    def counting_price(db: Session, loaded: Any) -> Any:
        prices.append(loaded.revision.id)
        return real_price(db, loaded)

    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        with get_session_factory()() as session:
            project = session.get(MsProject, fixture.project_id)
            revision = session.get(ProjectRevision, fixture.revision_id)
            assert project is not None and revision is not None
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(estimate_export, "load_revision", counting_load)
                patch.setattr(estimate_export, "price_loaded_revision", counting_price)
                content = build_revision_workbook(session, project, revision)

    assert loads == [fixture.revision_id]
    assert prices == [fixture.revision_id]
    # And the file really does carry both sheets, so "once" is not "never".
    assert load_workbook(BytesIO(content)).sheetnames == ["Devis", "Agrégats"]


def test_the_grid_subtotals_and_the_aggregates_sheet_are_the_same_figures(
    both_sides: BothSides,
) -> None:
    """M1, on the file itself: the two sheets are two views of one pricing.

    The counting test above pins the *mechanism*; this one pins the property a user
    can see. ``Sous-total MO`` / ``Sous-total Achat`` / ``PRU non chargé`` on the
    ``Devis`` sheet and ``Total MO`` / ``Total Achat`` / ``Total PRU non chargé`` on
    ``Agrégats`` are now summed from one ``RevisionPricing``, so they cannot
    disagree.
    """
    with get_session_factory()() as session:
        project = session.get(MsProject, both_sides.revision.project_id)
        revision = session.get(ProjectRevision, both_sides.revision.revision_id)
        assert project is not None and revision is not None
        content = build_revision_workbook(session, project, revision)

    grid = {row[5]: row[6] for row in _sheet_cells(content, "Devis") if row[5] is not None}
    aggregates = {row[0]: row[1] for row in _sheet_cells(content, "Agrégats")}
    assert grid["Sous-total MO"] == aggregates["Total MO"] == 24508.33
    assert grid["Sous-total Achat"] == aggregates["Total Achat"]
    assert grid["PRU non chargé"] == aggregates["Total PRU non chargé"]


def test_a_node_created_between_the_precheck_and_the_apply_is_a_lock_conflict() -> None:
    """M2: the confirm's second pass does not catch a concurrent *creation*.

    Redoing the staging under the lock catches whatever the *file* is now
    inconsistent with -- a node somebody removed, a cost code deactivated. It cannot
    catch a node somebody **added**: the file does not mention it, and "a node no row
    claims is a deletion" is the reconciliation contract, so both passes agree to
    destroy it and neither reports a thing. The confirm answered 200 having silently
    taken away a task the user had never seen. The docstring claimed the second pass
    closed the window; for this class of race it never did.

    ``expected_lock_version`` closes it: the ``lock_version`` the unlocked precheck
    read is handed to the locked pass, and any write in between is
    ``REVISION_LOCK_CONFLICT``, nothing applied.

    The concurrent write is **injected into that exact window** -- between the
    precheck and ``_writable_project``'s row lock -- rather than raced for, because
    a race a test can lose is a test that flakes. Injecting it before the request
    would exercise the much wider preview-to-confirm window instead, which no
    version the client does not send can close: that one is #334's, with the rest of
    the revision lifecycle.
    """
    real_writable_project = revisions_routes._writable_project  # pyright: ignore[reportPrivateUsage]

    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)
        intruders: list[int] = []

        def intruding_writable_project(db: Session, project_id: int, owner_id: int) -> MsProject:
            if not intruders:
                # A separate session, committed: another request, landing in the
                # window the precheck has just left and the row lock has not closed.
                with get_session_factory()() as other:
                    revision = other.get(ProjectRevision, fixture.revision_id)
                    assert revision is not None
                    node = insert_task(other, fixture.reference, revision, name="Lot 4", position=9)
                    revision.lock_version += 1
                    other.commit()
                    intruders.append(node.id)
            return real_writable_project(db, project_id, owner_id)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(revisions_routes, "_writable_project", intruding_writable_project)
            confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), content)
        nodes = client.get(fixture.url("/nodes"), headers=headers)

    assert confirm.status_code == 409, confirm.text
    detail = cast(dict[str, Any], cast(dict[str, Any], confirm.json())["detail"])
    assert detail["code"] == "REVISION_LOCK_CONFLICT"
    assert (detail["expected_lock_version"], detail["current_lock_version"]) == (0, 1)
    # Nothing applied: the intruder the file never mentioned is still there.
    assert nodes.status_code == 200
    body = cast(dict[str, Any], nodes.json())
    present = {node["node_id"] for node in cast(list[dict[str, Any]], body["nodes"])}
    assert intruders[0] in present
    assert set(fixture.nodes.values()) <= present


def test_what_the_second_pass_catches_is_the_referential_moving_under_the_file() -> None:
    """M2's other half: the locked pass really does re-decide, and refuses on its own.

    The rewritten docstring of the confirm splits the window in two, and both halves
    need a test. ``expected_lock_version`` covers a write to the *revision*; this one
    covers what no lock version can see, because it does not touch the revision at
    all -- the **referential** moving while the file is in flight. Deactivating the
    cost code every MO row of the workbook points at leaves ``lock_version`` exactly
    where it was, and the second pass refuses the very file the first one cleared.

    It is also the only path to the confirm's "second pass disagreed" branch, which
    answers a 409 carrying the full plan rather than an error envelope -- the shape
    the preview answers with, so a client renders one thing either way.
    """
    real_writable_project = revisions_routes._writable_project  # pyright: ignore[reportPrivateUsage]

    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)
        deactivated: list[int] = []

        def deactivating_writable_project(db: Session, project_id: int, owner_id: int) -> MsProject:
            if not deactivated:
                with get_session_factory()() as other:
                    code = other.get(ProjectCostCode, fixture.cost_code_id)
                    assert code is not None
                    code.is_active = False
                    other.commit()
                    deactivated.append(code.id)
            return real_writable_project(db, project_id, owner_id)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(revisions_routes, "_writable_project", deactivating_writable_project)
            confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), content)

    assert confirm.status_code == 409, confirm.text
    plan = cast(dict[str, Any], confirm.json())
    # The plan itself, not an error envelope -- the preview's shape.
    assert plan["applied"] is False
    assert [issue["code"] for issue in cast(list[Any], plan["blocking_issues"])] == [
        "COST_CODE_INVALID"
    ]


def test_the_reconciliation_refuses_a_stale_lock_version_before_staging_anything() -> None:
    """M2, at the seam: the refusal is the shared optimistic lock, raised on the load.

    The route test above pins the behaviour a client sees; this one pins *where* it
    comes from -- ``reconcile_revision`` compares the version on the revision it has
    just loaded, before a single row is staged and before any domain call -- and that
    the error is ``revision_tree.RevisionLockConflictError``, the same class
    ``api.revision_errors`` already maps to ``REVISION_LOCK_CONFLICT`` for every other
    write of either facet. A refusal of its own would have been a second table.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)

    parsed = parse_revision_reconciliation_workbook(content)
    with get_session_factory()() as session:
        with pytest.raises(RevisionLockConflictError) as conflict:
            reconcile_revision(
                session, fixture.revision_id, parsed, apply=True, expected_lock_version=7
            )
        # And the preview, which writes nothing, compares nothing.
        preview = reconcile_revision(session, fixture.revision_id, parsed, apply=False)

    assert conflict.value.expected_lock_version == 7
    assert conflict.value.current_lock_version == 0
    assert preview.blocking_issues == () and preview.applied is False


def test_an_oversized_workbook_is_refused_by_both_reconciliation_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1: ``RECONCILIATION_TOO_LARGE`` was declared emitted and exercised by nothing.

    ``_PROJECT_CODES`` lists it as one of the codes these routes emit, and
    ``test_every_emitted_error_code_is_documented_in_the_contract`` says in so many
    words that a documented code nothing emits is a dead branch in a frontend's
    translation table -- so the claim needs a test, exactly as the legacy route's
    ``test_reconciliation_import_rejects_files_over_configured_limit`` has one.
    """
    monkeypatch.setenv("IMPORT_MAX_UPLOAD_BYTES", "8")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            headers = _auth_headers(client)
            fixture = _seed_api(client, headers)
            oversized = b"0123456789"

            preview = _post(
                client, headers, fixture.url("/import-reconciliation/preview"), oversized
            )
            confirm = _post(
                client, headers, fixture.url("/import-reconciliation/confirm"), oversized
            )
    finally:
        get_settings.cache_clear()

    for response in (preview, confirm):
        assert response.status_code == 413, response.text
        assert cast(dict[str, Any], response.json())["detail"] == {
            "code": "RECONCILIATION_TOO_LARGE"
        }


@pytest.mark.parametrize("project_status", ["perdu", "termine", "abandonne"])
def test_a_read_only_project_refuses_the_confirm_and_nothing_else(project_status: str) -> None:
    """B1: ``PROJECT_READ_ONLY`` on this route was declared emitted and never exercised.

    The refusal is the *project*'s and not the revision's -- the revision below is a
    perfectly editable draft -- which is why it is a code the route decides itself
    rather than one ``api.revision_errors`` translates. Both exports and the preview
    stay allowed: a finished project is consultable, only frozen.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)
        with get_session_factory()() as session:
            project = session.get(MsProject, fixture.project_id)
            assert project is not None
            project.status = project_status
            session.commit()

        devis = client.get(fixture.url("/export.xlsx"), headers=headers)
        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), content)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), content)

    assert devis.status_code == 200
    assert preview.status_code == 200, preview.text
    assert confirm.status_code == 409, confirm.text
    assert cast(dict[str, Any], confirm.json())["detail"] == {"code": "PROJECT_READ_ONLY"}


def test_editing_the_external_uid_of_a_task_is_reported_rather_than_dropped() -> None:
    """B3: the column was exported, ignored on the way back, and warned about by nothing.

    ``external_uid`` is not a derived echo like ``work_item_id`` or ``level``: it is
    the MS Project identity of the work item (E14-06), writable elsewhere, with a
    refusal of its own (INV-25). A user who retyped it here had the edit vanish in
    silence, while the very same edit to ``name`` on the very same row produced a
    warning. It still is not applied -- rebinding a node to another MS Project task
    is the XML re-import's business -- but it is now said.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_api(client, headers)
        content = _download(client, headers, fixture)
        column = _column(REVISION_TASK_HEADERS, "external_uid")

        def retype_external_uid(sheet: Any) -> None:
            sheet.cell(row=2, column=column, value=4242)

        edited = _edited(content, "Tâches", retype_external_uid)

        preview = _post(client, headers, fixture.url("/import-reconciliation/preview"), edited)
        confirm = _post(client, headers, fixture.url("/import-reconciliation/confirm"), edited)

    assert preview.status_code == 200, preview.text
    plan = cast(dict[str, Any], preview.json())
    assert plan["blocking_issues"] == []
    warnings = [
        (issue["code"], issue["sheet"], issue["row"], issue["message"])
        for issue in cast(list[Any], plan["warnings"])
    ]
    assert len(warnings) == 1
    code, sheet, row, message = warnings[0]
    assert (code, sheet, row) == ("TASK_FIELD_CHANGE_IGNORED", "Tâches", 2)
    assert "external_uid" in message
    # And the confirm agrees with the preview, warning included, having written nothing.
    assert confirm.status_code == 200, confirm.text
    applied = cast(dict[str, Any], confirm.json())
    assert [issue["code"] for issue in cast(list[Any], applied["warnings"])] == [
        "TASK_FIELD_CHANGE_IGNORED"
    ]
    assert applied["tasks_to_delete"] == [] and applied["applied"] is True
