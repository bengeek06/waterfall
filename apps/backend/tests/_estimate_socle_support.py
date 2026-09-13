"""The one set of figures both devis socles are mounted on (E14-07b #364, E14-07c #365).

Extracted from ``test_revision_pricing.py``, where #364 wrote it, the moment a
second suite needed the very same thing: #365 has to build the legacy workbook and
the revision workbook **from one set of figures** and compare them, which is
exactly the comparison #364 made one level down, on the amounts. Two copies of a
fixture would have made "the same figures" a claim rather than a fact.

Everything here is a *seed*, never an assertion: the two suites that consume it
keep their own expectations.

Four columns carry a value for one reason only, and it is #365's: ``comment`` on
the MO lines, ``supply_status``/``planned_date`` on the non-MO ones, and a cost
code on most of them. They are *stated by both reconciliation workbooks* and were
left ``NULL`` on both sides, which made "the two files agree on them" a comparison
of ``None`` with ``None`` -- and hid, for a while, that the legacy seed defaulted
``supply_status`` to ``planned`` where the revision seed left it unset. None of the
four feeds an amount, so #364's pricing comparison is unaffected by their presence.

The figures themselves are deliberately mundane -- an hourly
rate, an inflation coefficient, a task spanning two years, and one spanning three
with hours no number of years divides -- and every year is derived from the
*current* calendar year rather than hardcoded, because both socles price an undated
line at ``datetime.now(UTC).year`` and a fixed year would make the suite go red on
the 1st of January.

Deliberately not named ``test_*.py`` (same reasoning as ``_revision_db_support.py``):
pytest would otherwise collect it as a test module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from _calendar_support import ensure_default_calendar
from _estimate_grid_support import seed_cost_line, seed_root_grid_node
from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_purchase_line,
    insert_revision,
    insert_task,
    seed_annual_rate,
)
from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    CostCategory,
    CostType,
    Estimate,
    EstimateRoleAssignment,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
)

#: Both engines price a line with no dated bearing task at the current calendar year.
YEAR_ONE = datetime.now(UTC).year
YEAR_TWO = YEAR_ONE + 1
YEAR_THREE = YEAR_ONE + 2

#: The five MO lines, stated once and mounted twice: ``(bearing task uid, quantity,
#: hours, cost code key, comment)``. The cost code key is ``"A"``/``"B"``/``None``
#: rather than an id, because the two sides are two different projects carrying two
#: different rows for the same ``code`` -- which is exactly what makes the column
#: comparable through :func:`seed_cost_codes`.
MO_LINES: tuple[tuple[int | None, Decimal, Decimal, str | None, str | None], ...] = (
    (1, Decimal("2"), Decimal("100"), "A", "Relevé sur site"),
    (2, Decimal("1"), Decimal("8"), "B", "Revue de plans"),
    (3, Decimal("1"), Decimal("40"), "A", None),
    (4, Decimal("1"), Decimal("10"), "A", "Suivi pluriannuel"),
    (None, Decimal("1"), Decimal("10"), None, "Transverse, hors tâche"),
)

#: Both non-MO lines are of a *supply* cost type, which is the only kind that may
#: carry a supply status at all -- on either socle.
SUPPLY_STATUS = "planned"

#: The forecast cash-out date of the ``Cables`` line, and it is in :data:`YEAR_ONE`
#: for a reason that is not decorative: the revision engine dates a disbursement by
#: ``facet.planned_date.year`` where the legacy one snapshots it at
#: ``datetime.now(UTC).year`` (see ``estimate_calculation._priced_lines_of``). The
#: two agree on the *amount* either way -- a disbursement carries no inflation -- but
#: ``test_revision_pricing.test_the_two_engines_agree_amount_for_amount`` compares
#: the ``year`` of every priced line too, and a date in any other year makes it red
#: for a divergence the fixture invented. The current year is the one value that lets
#: the column be non-``NULL`` on both sides and keeps #364's comparison honest.
PLANNED_MONTH_DAY = (6, 1)

RATE_ONE = Decimal("100.00")
RATE_TWO = Decimal("110.00")
RATE_THREE = Decimal("120.00")
INFLATION_ONE = Decimal("1.00000000")
INFLATION_TWO = Decimal("1.05000000")
INFLATION_THREE = Decimal("1.10000000")

# --------------------------------------------------------------------------------------
# The referential both sides share
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Referential:
    """One role with an annual rate, one supply category, and two cost codes per project.

    Two :class:`ReferenceData` over the same project, calendar and role: the labour
    one carries the MO cost type and the category the *role* points at (INV-19: a
    labour line has no category of its own), the supply one carries the non-labour
    pair ``insert_purchase_line`` reads. That is exactly the split the cost facet
    itself makes.
    """

    labor: ReferenceData
    supply: ReferenceData
    role_name: str
    labor_code: str
    supply_code: str


def seed_referential(
    session: Session, project_id: int, *, key: str, calendar_id: int
) -> Referential:
    """``calendar_id`` comes from :func:`ensure_default_calendar`, called by the caller
    **before** this session was opened: that helper commits on a session of its own, and
    SQLite refuses a second writer while an outer transaction is open."""
    labor_type = CostType(code=f"MO-{key}", name="Main d'oeuvre", kind="labor")
    supply_type = CostType(code=f"SUP-{key}", name="Fourniture", kind="supply")
    session.add_all([labor_type, supply_type])
    session.flush()
    labor_category = CostCategory(
        cost_type_id=labor_type.id,
        accounting_code=f"MO-DEV-{key}",
        category_code="IDEX",
        name="Developpement",
    )
    supply_category = CostCategory(
        cost_type_id=supply_type.id,
        accounting_code=f"SUP-FOU-{key}",
        category_code="FOU",
        name="Fournitures",
    )
    resource_node = ResourceNode(code=f"IT-{key}", name="Informatique")
    session.add_all([labor_category, supply_category, resource_node])
    session.flush()
    role = ResourceRole(
        node_id=resource_node.id,
        cost_category_id=labor_category.id,
        calendar_id=calendar_id,
        name=f"Developpeur {key}",
    )
    session.add(role)
    session.flush()
    return Referential(
        labor=ReferenceData(
            project_id=project_id,
            calendar_id=calendar_id,
            role_id=role.id,
            cost_type_id=labor_type.id,
            cost_category_id=labor_category.id,
        ),
        supply=ReferenceData(
            project_id=project_id,
            calendar_id=calendar_id,
            role_id=role.id,
            cost_type_id=supply_type.id,
            cost_category_id=supply_category.id,
        ),
        role_name=role.name,
        labor_code=labor_category.accounting_code,
        supply_code=supply_category.accounting_code,
    )


def seed_rates(session: Session, referential: Referential) -> None:
    seed_annual_rate(
        session, referential.labor, year=YEAR_ONE, hourly_rate=RATE_ONE, inflation=INFLATION_ONE
    )
    seed_annual_rate(
        session, referential.labor, year=YEAR_TWO, hourly_rate=RATE_TWO, inflation=INFLATION_TWO
    )
    seed_annual_rate(
        session,
        referential.labor,
        year=YEAR_THREE,
        hourly_rate=RATE_THREE,
        inflation=INFLATION_THREE,
    )


def seed_project(session: Session, name: str) -> MsProject:
    project = MsProject(
        source_version=2016,
        save_version_out=16,
        name=name,
        schedule_from_start=True,
        start_date=datetime(YEAR_ONE, 1, 1, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
    )
    session.add(project)
    session.flush()
    return project


def seed_cost_codes(session: Session, project_id: int) -> tuple[int, int]:
    """``CC-A``/``CC-B``, by the same two ``code`` strings on either project.

    ``by_cost_code`` is keyed by the *code*, not by the id, which is what lets the
    two sides be compared at all: they are two different projects, so they carry two
    different rows for the same code.
    """
    # A project holds exactly one root code (#62/E6-01, `uq_wf_project_cost_code_root`),
    # so the two compared codes hang under it rather than beside it.
    root = ProjectCostCode(
        project_id=project_id, parent_id=None, code=f"PRJ-{project_id}", name="Projet"
    )
    session.add(root)
    session.flush()
    codes = [
        ProjectCostCode(project_id=project_id, parent_id=root.id, code=code, name=code)
        for code in ("CC-A", "CC-B")
    ]
    session.add_all(codes)
    session.flush()
    return codes[0].id, codes[1].id


# --------------------------------------------------------------------------------------
# The legacy side: ms_task / EstimateRoleAssignment / EstimateCostLine
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LegacyFixture:
    project_id: int
    estimate_id: int


def seed_legacy(session: Session, referential: Referential, project: MsProject) -> LegacyFixture:
    """The very same figures as :func:`seed_revision`, on the tables the engine replaces."""
    code_a, code_b = seed_cost_codes(session, project.id)
    tasks = {
        1: MsTask(
            project_id=project.id,
            uid=1,
            name="T1",
            position=1,
            start_at=datetime(YEAR_ONE, 3, 2, tzinfo=UTC),
            finish_at=datetime(YEAR_TWO, 6, 30, tzinfo=UTC),
        ),
        2: MsTask(
            project_id=project.id,
            uid=2,
            name="T2",
            position=2,
            start_at=datetime(YEAR_ONE, 4, 1, tzinfo=UTC),
            finish_at=datetime(YEAR_ONE, 9, 30, tzinfo=UTC),
        ),
        # Dateless on purpose: the legacy engine returns no line at all for it, and
        # the new one must not start inventing one.
        3: MsTask(project_id=project.id, uid=3, name="T3", position=3),
        # Three years, and hours below that no number of years divides: the engine's
        # one inexact operation, `hours / Decimal(len(years))`. Without it the whole
        # comparison would only ever exercise exact arithmetic -- see
        # `test_the_two_engines_agree_on_every_aggregate`.
        4: MsTask(
            project_id=project.id,
            uid=4,
            name="T4",
            position=4,
            start_at=datetime(YEAR_ONE, 10, 1, tzinfo=UTC),
            finish_at=datetime(YEAR_THREE, 2, 28, tzinfo=UTC),
        ),
    }
    session.add_all(tasks.values())
    session.flush()

    estimate = Estimate(
        project_id=project.id,
        planning_id=None,
        version_number=1,
        kind="initial",
        status="draft",
        currency_code="EUR",
    )
    session.add(estimate)
    session.flush()

    codes = {"A": code_a, "B": code_b, None: None}
    for task_uid, quantity, hours, code_key, comment in MO_LINES:
        session.add(
            EstimateRoleAssignment(
                estimate_id=estimate.id,
                task_id=None if task_uid is None else tasks[task_uid].id,
                role_id=referential.labor.role_id,
                quantity=quantity,
                hours=hours,
                cost_code_id=codes[code_key],
                comment=comment,
                node_id=seed_root_grid_node(session, estimate.id, "labor"),
            )
        )
    seed_cost_line(
        session,
        estimate_id=estimate.id,
        cost_category_id=referential.supply.cost_category_id,
        label="Cables",
        quantity="3.00",
        unit_cost="25.50",
        task_id=tasks[2].id,
        cost_code_id=code_b,
        supply_status=SUPPLY_STATUS,
        planned_date=datetime(YEAR_ONE, *PLANNED_MONTH_DAY, tzinfo=UTC),
    )
    seed_cost_line(
        session,
        estimate_id=estimate.id,
        cost_category_id=referential.supply.cost_category_id,
        label="Frais de dossier",
        quantity="2.00",
        unit_cost="10.00",
        task_id=None,
        supply_status=SUPPLY_STATUS,
    )
    session.flush()
    return LegacyFixture(project_id=project.id, estimate_id=estimate.id)


# --------------------------------------------------------------------------------------
# The revision side: one tree, two facets
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RevisionFixture:
    project_id: int
    revision_id: int
    task_nodes: dict[str, int]
    cost_nodes: dict[str, int]


def seed_revision(
    session: Session, referential: Referential, project: MsProject
) -> RevisionFixture:
    """The very same figures as :func:`seed_legacy`, on ``wf_revision_node``."""
    code_a, code_b = seed_cost_codes(session, project.id)
    labor = ReferenceData(
        project_id=project.id,
        calendar_id=referential.labor.calendar_id,
        role_id=referential.labor.role_id,
        cost_type_id=referential.labor.cost_type_id,
        cost_category_id=referential.labor.cost_category_id,
    )
    supply = ReferenceData(
        project_id=project.id,
        calendar_id=referential.supply.calendar_id,
        role_id=referential.supply.role_id,
        cost_type_id=referential.supply.cost_type_id,
        cost_category_id=referential.supply.cost_category_id,
    )
    revision = insert_revision(session, labor)

    t1 = insert_task(
        session,
        labor,
        revision,
        name="T1",
        position=1,
        start_at=datetime(YEAR_ONE, 3, 2, tzinfo=UTC),
        finish_at=datetime(YEAR_TWO, 6, 30, tzinfo=UTC),
    )
    t2 = insert_task(
        session,
        labor,
        revision,
        name="T2",
        position=2,
        start_at=datetime(YEAR_ONE, 4, 1, tzinfo=UTC),
        finish_at=datetime(YEAR_ONE, 9, 30, tzinfo=UTC),
    )
    t3 = insert_task(session, labor, revision, name="T3", position=3)
    t4 = insert_task(
        session,
        labor,
        revision,
        name="T4",
        position=4,
        start_at=datetime(YEAR_ONE, 10, 1, tzinfo=UTC),
        finish_at=datetime(YEAR_THREE, 2, 28, tzinfo=UTC),
    )

    codes = {"A": code_a, "B": code_b, None: None}
    mo_nodes = [
        insert_labor_line(
            session,
            labor,
            revision,
            label=label,
            parent_id=parent_id,
            position=position,
            quantity=quantity,
            hours=hours,
            cost_code_id=codes[code_key],
            comment=comment,
        )
        # Same five lines as the legacy side, off the same tuple, and in the same
        # order -- which is the order both reconciliation workbooks list them in.
        # The last one is INV-01's project-wide global cost: no strict ancestor
        # carries a planning facet.
        for (_uid, quantity, hours, code_key, comment), label, parent_id, position in zip(
            MO_LINES,
            ("Etude T1", "Etude T2", "Etude T3", "Etude T4", "Etude transverse"),
            (t1.id, t2.id, t3.id, t4.id, None),
            (1, 1, 1, 1, 5),
            strict=True,
        )
    ]
    mo_t1, mo_t2, mo_t3, mo_t4, mo_root = mo_nodes
    cables = insert_purchase_line(
        session,
        supply,
        revision,
        label="Cables",
        parent_id=t2.id,
        position=2,
        quantity=Decimal("3.00"),
        unit_cost=Decimal("25.50"),
        cost_code_id=code_b,
        supply_status=SUPPLY_STATUS,
        planned_date=date(YEAR_ONE, *PLANNED_MONTH_DAY),
    )
    fees = insert_purchase_line(
        session,
        supply,
        revision,
        label="Frais de dossier",
        parent_id=None,
        position=6,
        quantity=Decimal("2.00"),
        unit_cost=Decimal("10.00"),
        supply_status=SUPPLY_STATUS,
    )
    session.flush()
    return RevisionFixture(
        project_id=project.id,
        revision_id=revision.id,
        task_nodes={"T1": t1.id, "T2": t2.id, "T3": t3.id, "T4": t4.id},
        cost_nodes={
            "Etude T1": mo_t1.id,
            "Etude T2": mo_t2.id,
            "Etude T3": mo_t3.id,
            "Etude T4": mo_t4.id,
            "Etude transverse": mo_root.id,
            "Cables": cables.id,
            "Frais de dossier": fees.id,
        },
    )


@dataclass(frozen=True)
class BothSides:
    legacy: LegacyFixture
    revision: RevisionFixture
    referential: Referential


def seed_both_sides(
    *, legacy_name: str | None = None, revision_name: str | None = None
) -> BothSides:
    """One set of figures, mounted on the legacy socle *and* on the revision model.

    ``legacy_name``/``revision_name`` default to two distinct project names, which is
    all #364 needs. #365 passes the **same** name on both sides on purpose: the devis
    workbook prints ``Devis — <project name>`` in cell A1, and a comparison that had
    to exclude a cell would no longer be a comparison of the whole classeur.
    """
    key = uuid4().hex[:8]
    # `revision_store.ensure_project_calendar` refuses to materialise a project without
    # an organisation default calendar (Règle 1, INV-15), and it has to be committed
    # before the seeding transaction opens -- see `seed_referential`.
    calendar_id = ensure_default_calendar()
    with get_session_factory()() as session:
        legacy_project = seed_project(session, legacy_name or f"Legacy {key}")
        revision_project = seed_project(session, revision_name or f"Revision {key}")
        referential = seed_referential(session, legacy_project.id, key=key, calendar_id=calendar_id)
        seed_rates(session, referential)
        legacy = seed_legacy(session, referential, legacy_project)
        revision = seed_revision(session, referential, revision_project)
        session.commit()
        return BothSides(legacy=legacy, revision=revision, referential=referential)
