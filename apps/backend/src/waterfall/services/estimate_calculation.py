"""The deterministic cost calculation engine, on the cost facet of the revision node.

Two engines live here, and the module is read in that order.

**The engine** (E14-07b, #364) prices the ``wf_revision_cost_facet`` rows of a
revision. It resolves each line's bearing task through the pure domain -- INV-01,
the first *strict* ancestor carrying a planning facet, ``None`` at the root -- and
never reads a stored ``task_id``, which is what makes moving a cost node under
another task enough to change what bears it. It is also the
:data:`~waterfall.domain.revision.pricing.AmountResolver` the domain has been
taking since E14-02 (#328): :meth:`RevisionPricing.amount_of` is injected into
``plan_reimport``/``apply_reimport`` *and* into ``revision_tree.delete_nodes`` --
**every** entry point serving Rule 3's "you are about to lose this much chiffrage"
warning, so that the two routes that quote it quote the same figure -- and
``waterfall.domain.revision.pricing.default_amount`` goes back to being what it
always claimed to be -- a naive fallback, not the engine. Leaving one of them on
that fallback is not a smaller warning, it is a wrong one: it prices an MO facet
at ``quantity x hours x role.hourly_rate``, and ``Role.hourly_rate`` is never
loaded, so the answer would be ``0``.

**The legacy engine** below it prices ``EstimateRoleAssignment``/
``EstimateCostLine`` against ``ms_task``, and freezes the result into
``wf_estimate_line``. It is kept, untouched and still wired to
``POST .../estimates/{id}/validate``, for the reason the EPIC states -- "additif
d'abord, destruction en dernier" (#326) -- and for one more: it is the only thing
the new engine can be *compared* against, which is the central acceptance criterion
of #364 (``tests/test_revision_pricing.py`` runs both on the same figures and
asserts the amounts equal). E14-12 (#339) removes it, together with the tables it
reads.

What is deliberately **not** here: writing a priced line anywhere. Freezing the
lines of a validated revision is E14-08 (#334), and the exports and the
reconciliation are the exports' own issue (#365) -- an engine that returned
half-built ORM rows would have decided both.
"""

from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TypedDict

from sqlalchemy.orm import Session

from waterfall.core.observability import ESTIMATE_CALCULATION_DURATION, track_duration
from waterfall.domain import revision as domain
from waterfall.domain.revision.pricing import PricedYear
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
from waterfall.services.revision_store import LoadedRevision, load_revision


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

    The rule itself is `_missing_coverage`; this function is the variant that goes
    and *fetches* the coverage. ``price_loaded_revision`` does not call it: it needs
    the rates themselves anyway, so it loads them once (`_load_rate_table`) and reads
    the same rule off the tables it is already holding -- one query pair per pricing
    instead of two, which matters because it now also runs under the revision lock,
    on every node deletion.
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
    return _missing_coverage(category_years, existing_rate_pairs, existing_inflation_years)


def _missing_coverage(
    category_years: list[tuple[CostCategory, int]],
    covered_rate_pairs: Container[tuple[int, int]],
    covered_inflation_years: Container[int],
) -> tuple[list[tuple[CostCategory, int]], list[int]]:
    """Which of `category_years` the given coverage does not cover.

    The whole of `collect_missing_rate_coverage`'s rule, and none of its queries, so
    that a caller which has already loaded ``(category, year) -> rate`` and ``year ->
    inflation`` answers it from those keys rather than from two more `SELECT`s
    (`price_loaded_revision`). Both sources key on exactly the same columns -- the
    two tables are unique on them -- so "the pair is absent from the dict" and "the
    pair is absent from the table" are the same statement.
    """
    seen_missing_pairs: set[tuple[int, int]] = set()
    missing_cost_rates: list[tuple[CostCategory, int]] = []
    missing_inflation_years: set[int] = set()
    for category, year in category_years:
        pair_key = (category.id, year)
        if pair_key not in covered_rate_pairs and pair_key not in seen_missing_pairs:
            seen_missing_pairs.add(pair_key)
            missing_cost_rates.append((category, year))
        if year not in covered_inflation_years:
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


# --------------------------------------------------------------------------------------
# The engine, on the cost facet of the node (E14-07b, #364)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PricedLine:
    """One ``(cost facet, year)`` pair, priced.

    The same grain as the legacy engine's ``EstimateLine``: a labour facet borne by
    a task spanning two years produces two of these, a non-labour one produces
    exactly one. Deliberately a plain, immutable dataclass and **not** an ORM row:
    freezing a priced line into the immutable document of a validated revision is
    E14-08's (#334) business, not this module's, and an engine that returned
    half-built rows would decide that for it.

    ``bearing_*`` is INV-01's answer for this line -- the first *strict* ancestor
    carrying a planning facet -- resolved on read and stored in no column, which is
    exactly what makes moving the cost node under another task change the line's
    bearing task without touching a single one of its own attributes.

    ``hours``/``hourly_rate``/``inflation_coefficient`` carry the legacy engine's
    own neutral values on a non-labour line (``0``/``0``/``1``) rather than
    ``None``, so that the two engines can be compared field by field.
    """

    node_id: int
    work_item_id: int
    label: str
    nature: domain.CostNature
    bearing_node_id: int | None
    bearing_work_item_id: int | None
    bearing_task_name: str | None
    role_id: int | None
    role_name: str | None
    accounting_code: str
    category_code: str | None
    cost_code_id: int | None
    year: int
    quantity: Decimal
    hours: Decimal
    hourly_rate: Decimal
    inflation_coefficient: Decimal
    amount: Decimal


class UnpriceableReason(StrEnum):
    """Why the engine could put a facet's hours in no year at all.

    Both values come out of :func:`_bearing_years` answering ``None``, and they are
    told apart because the user's remedy differs: one task needs dates, the other
    needs its dates the right way round.
    """

    #: The bearing task carries no ``start_at`` and/or no ``finish_at``.
    BEARING_TASK_UNDATED = "bearing_task_undated"
    #: The bearing task's ``finish_at`` precedes its ``start_at``: an empty range.
    BEARING_TASK_EMPTY_RANGE = "bearing_task_empty_range"


@dataclass(frozen=True)
class UnpriceableFacet:
    """A labour facet carrying hours that the engine priced into **no line at all**.

    The gap next to :attr:`RevisionPricing.missing_cost_rates`, and the one #334's
    review found it had left open. A missing rate makes a line worth zero *and says
    so*; a bearing task with no dates makes the facet produce no priced line at all,
    so it contributes nothing to ``missing_cost_rates`` either -- ``category_years``
    is built from ``cost_node.years``, which is exactly what is ``None`` here -- and
    a reader saw ``total_labor_cost: 0`` with ``missing_cost_rates: []``, that is a
    zero with nothing beside it.

    Reported on a read, **refused** on a validation, the same asymmetry and for the
    same reason: a draft whose task is not scheduled yet must stay readable, and an
    immutable document must not record 0,00 EUR for a chiffrage of a thousand.

    ``bearing_*`` names the task to fix, which is the whole point of publishing this:
    the facet itself is impeccable -- it carries its role and its hours -- and the
    thing to correct is somewhere else in the tree.
    """

    node_id: int
    work_item_id: int
    label: str
    hours: Decimal
    bearing_node_id: int | None
    bearing_work_item_id: int | None
    bearing_task_name: str | None
    reason: UnpriceableReason


@dataclass(frozen=True)
class RevisionPricing:
    """Everything the engine made of one revision: its priced lines and its gaps.

    ``missing_cost_rates``/``missing_inflation_years`` are **reported, not raised**,
    which is the one deliberate difference with ``calculate_estimate_lines``'s
    ``MissingRateCoverageError``. This object backs reads -- the aggregates
    endpoint, the import diff's "you are about to lose this much chiffrage"
    warning -- and a read that answers 500 because a 2031 rate has not been
    entered yet would make a perfectly editable draft unreadable. The line is
    still priced, at a zero rate and a neutral inflation, *and* the gap is named
    in the same breath, so nothing is silent about it. Refusing a **validation**
    outright on the same gap is the right answer and is the one E14-08 (#334) made,
    from these very lists: see
    :func:`waterfall.services.revision_tree.validate_revision`, which reads them and
    raises rather than freezing a zero into an immutable document.

    :attr:`unpriceable_facets` is the third of them and the one #334's review added:
    a labour facet whose bearing task has no dates produces *no* priced line, so it
    could never appear in ``missing_cost_rates`` -- and a zero was being frozen with
    nothing at all beside it. See :class:`UnpriceableFacet`.
    """

    revision_id: int
    lines: tuple[PricedLine, ...]
    #: Total amount of each cost node, summed over its years **at full precision**.
    #: Keyed by node id, so it is also the lookup :meth:`amount_of` answers from.
    amount_by_node: Mapping[int, Decimal]
    #: The same totals **in euros at the cent**: each priced line rounded on its own
    #: (:func:`amount_at_the_cent`) and only then added up. Keyed by node id, and the
    #: lookup :meth:`published_amount_of` answers from. See that method for why the
    #: two mappings both exist and are not each other's rounding.
    published_amount_by_node: Mapping[int, Decimal]
    #: The *year by year* detail behind that total, in the same unit, keyed by node
    #: id -- what :meth:`breakdown_of` answers from and what a frozen line is cut at.
    published_breakdown_by_node: Mapping[int, tuple[PricedYear, ...]]
    missing_cost_rates: tuple[tuple[CostCategory, int], ...]
    missing_inflation_years: tuple[int, ...]
    #: The facets the engine could price into no year at all -- reported here and
    #: refused by a validation, like the two lists above. See :class:`UnpriceableFacet`.
    unpriceable_facets: tuple[UnpriceableFacet, ...]

    def amount_of(self, project: domain.Project, facet: domain.CostFacet) -> Decimal:
        """This engine, as the :data:`~waterfall.domain.revision.pricing.AmountResolver`
        the pure domain has been taking since E14-02 (#328).

        The single way the engine reaches the domain: ``pricing.default_amount``
        describes itself as *not* being the engine, and the entry points that need
        an amount -- the frozen lines of a validated revision, Rule 3's chiffrage
        -loss warning -- all take a resolver rather than hardcoding one. Injecting
        this method is therefore the whole hookup, and the reason
        ``revision_store._load_roles`` still leaves ``Role.hourly_rate`` unset: a
        rate is per year, an amount is per year *and* per bearing task, and filling
        a single scalar on the role would be a second, weaker path to the same
        number.

        ``project`` is unread -- the amounts were resolved against the revision this
        pricing was computed from, whose project is that one -- and is part of the
        signature the protocol fixes.
        """
        return self.amount_by_node.get(facet.node_id, Decimal("0"))

    def breakdown_of(
        self, project: domain.Project, facet: domain.CostFacet
    ) -> tuple[PricedYear, ...]:
        """This engine, as the
        :data:`~waterfall.domain.revision.pricing.BreakdownResolver` the validation of
        a revision takes (E14-08, #334).

        The third and last way this engine reaches the pure domain, and the only one
        that hands over more than a number: a frozen line carries the annual rate and
        the inflation coefficient it was priced under, and those exist **per year**,
        so what crosses the boundary is one :class:`~waterfall.domain.revision.PricedYear`
        per year rather than a scalar no rate table could ever be checked against.
        The labels stay the domain's to copy -- see the class it feeds.

        Amounts are the **published** ones, rounded per priced line exactly as
        :meth:`published_amount_of` rounds them, so that the total of a frozen
        document equals the sum of the lines it shows. Rounding the node total
        instead would make a document whose own rows do not add up to it (#368).

        ``project`` is unread, like the two resolvers above, and is part of the
        signature the protocol fixes.
        """
        return self.published_breakdown_by_node.get(facet.node_id, ())

    def published_amount_of(self, project: domain.Project, facet: domain.CostFacet) -> Decimal:
        """:meth:`amount_of`, in the unit an API response is allowed to carry (#368).

        The same :data:`~waterfall.domain.revision.pricing.AmountResolver` protocol,
        and the one **every** caller quoting a
        :class:`~waterfall.domain.revision.CostLoss` injects -- four of them since
        #365: the node deletion (``POST .../nodes/delete``), the MS Project import
        diff, the MS Project import run, and the reconciliation round trip (preview
        and confirm) -- because the amount those routes carry is *published* money,
        shown in a confirmation dialog, and 28 significant digits is a decision
        nobody took (#368). :meth:`amount_of` stays the raw product for everything
        that has to keep computing with it.

        **Rounded per priced line, never on the node total**, which is the whole
        reason this is a second mapping rather than a ``quantize`` at the response
        boundary. :attr:`amount_by_node` is a sum of full-precision products: an MO
        facet borne by a task spanning three years answers
        ``999.9999999999999999999999999`` there, which rounds to ``1000.00`` as a
        total but to ``333.33 + 333.33 + 333.33 = 999.99`` line by line. The second
        is the figure every other published total of this module carries -- see
        :func:`calculate_revision_aggregates` -- and publishing the first on one
        route and the second on another is exactly the "two routes, two answers"
        #364 removed.

        ``project`` is unread, like :meth:`amount_of`'s, and is part of the
        signature the protocol fixes.
        """
        return self.published_amount_by_node.get(facet.node_id, Decimal("0"))


def _bearing_years(bearing_plan: domain.PlanFacet | None) -> list[int] | None:
    """The years a labour facet's hours are spread over, or ``None`` when it prices
    nothing at all.

    Reproduces ``_generate_labor_lines``/``_single_year_labor_line`` case for case,
    which is what the "same amounts as before the migration" criterion of #364 is
    about:

    * no bearing task (INV-01's project-wide global cost, the node model's answer to
      the legacy ``EstimateRoleAssignment.task_id IS NULL`` of #289) -> the current
      calendar year, one line, never dropped from a total;
    * a bearing task with no ``start_at``/``finish_at`` -> ``None``: the legacy
      engine returns an empty list for it, so the facet produces no line and
      contributes nothing. Preserved rather than improved on purpose -- turning it
      into a current-year line would change a total at the exact moment the engine
      moves, which is what this issue must not do;
    * a bearing task whose ``finish_at`` precedes its ``start_at`` -> ``None`` as
      well, for the same reason a dateless one does: the range is empty, so there
      is no year to spread the hours over. Nothing forbids that state today --
      neither a ``CheckConstraint`` on ``wf_revision_plan_facet``, nor a validator
      on the planning payloads, nor the MSPDI parser -- and **the engine is a
      read: it must refuse no stored state**. Answering ``None`` is what keeps it
      from dividing by ``len(years) == 0``, which would surface as a
      :class:`decimal.DivisionByZero` (a 500, and no rollback) on every caller
      that prices unconditionally, the import diff included. Forbidding the state
      on the *write* side is a separate question, and not this issue's;
    * a dated bearing task -> every year it touches, ends included.
    """
    if bearing_plan is None:
        return [datetime.now(UTC).year]
    if bearing_plan.start_at is None or bearing_plan.finish_at is None:
        return None
    years = list(range(bearing_plan.start_at.year, bearing_plan.finish_at.year + 1))
    return years or None


def _load_rate_table(
    db: Session, category_years: list[tuple[CostCategory, int]]
) -> tuple[dict[tuple[int, int], Decimal], dict[int, Decimal]]:
    """The ``(category, year) -> hourly rate`` and ``year -> inflation`` tables, in
    one query pair for the whole revision.

    Both source tables are unique on exactly these keys
    (``uq_wf_cost_rate_category_year``, ``InflationRate.year``), so reading them
    into a dict selects the same row the legacy engine's per-line ``.first()``
    picked -- there is only one.
    """
    if not category_years:
        return {}, {}
    category_ids = {category.id for category, _year in category_years}
    years = {year for _category, year in category_years}
    hourly_rates = {
        (row.cost_category_id, row.year): row.hourly_rate
        for row in db.query(CostRate)
        .filter(CostRate.cost_category_id.in_(category_ids))
        .filter(CostRate.year.in_(years))
        .all()
    }
    inflation = {
        row.year: row.coefficient
        for row in db.query(InflationRate).filter(InflationRate.year.in_(years)).all()
    }
    return hourly_rates, inflation


@dataclass(frozen=True)
class _CostNode:
    """A cost facet of the revision, with everything resolved that pricing needs."""

    node: domain.RevisionNode
    facet: domain.CostFacet
    bearing: domain.RevisionNode | None
    bearing_plan: domain.PlanFacet | None
    role: ResourceRole | None
    category: CostCategory | None
    years: list[int] | None


def _resolve_cost_nodes(db: Session, revision: domain.ProjectRevision) -> list[_CostNode]:
    """Every cost node of ``revision``, in depth-first display order, with its bearing
    task, its role, its cost category and the years it prices over.

    Depth-first because that is the order the tree is read in everywhere else
    (``revision_tree.read_revision_tree``); a set iteration order would make the
    priced lines -- and therefore an export built off them -- shuffle between two
    identical runs.
    """
    ordered = [node for node in domain.depth_first(revision) if node.id in revision.cost_facets]
    facets = [revision.cost_facets[node.id] for node in ordered]

    role_ids = {facet.role_id for facet in facets if facet.role_id is not None}
    roles: dict[int, ResourceRole] = (
        {row.id: row for row in db.query(ResourceRole).filter(ResourceRole.id.in_(role_ids)).all()}
        if role_ids
        else {}
    )
    category_ids = {role.cost_category_id for role in roles.values()}
    category_ids.update(
        facet.cost_category_id for facet in facets if facet.cost_category_id is not None
    )
    categories: dict[int, CostCategory] = (
        {
            row.id: row
            for row in db.query(CostCategory).filter(CostCategory.id.in_(category_ids)).all()
        }
        if category_ids
        else {}
    )

    resolved: list[_CostNode] = []
    for node, facet in zip(ordered, facets, strict=True):
        bearing = domain.resolve_bearing_task(revision, node.id)
        bearing_plan = None if bearing is None else revision.plan_facets.get(bearing.id)
        role = None if facet.role_id is None else roles.get(facet.role_id)
        is_labor = facet.nature is domain.CostNature.LABOR
        # INV-19: a labour line carries no cost category of its own, it inherits its
        # role's -- the single source of truth the legacy engine already used for
        # `accounting_code`, and the one the rate is looked up against.
        category_id = (
            role.cost_category_id if is_labor and role is not None else (facet.cost_category_id)
        )
        resolved.append(
            _CostNode(
                node=node,
                facet=facet,
                bearing=bearing,
                bearing_plan=bearing_plan,
                role=role,
                category=None if category_id is None else categories.get(category_id),
                years=_bearing_years(bearing_plan) if is_labor else None,
            )
        )
    return resolved


def _priced_lines_of(
    cost_node: _CostNode,
    hourly_rates: Mapping[tuple[int, int], Decimal],
    inflation: Mapping[int, Decimal],
) -> list[PricedLine]:
    """The lines one cost facet produces, priced.

    Arithmetic is the legacy engine's, digit for digit and in the same order:
    ``quantity x (hours / number of years) x hourly_rate x inflation`` for labour,
    ``quantity x unit_cost`` for the rest, every operand a :class:`Decimal` and no
    rounding step anywhere -- the division is the only inexact operation and it
    keeps the 28 significant digits of the default decimal context, exactly as
    ``assignment.hours / Decimal(len(years))`` did.

    On a **labour** line that makes the two engines equal digit for digit: they run
    the same division, in the same order, and neither rounds it. On a
    **disbursement** they cannot be, and the reason is not arithmetic at all -- the
    legacy engine did not compute one, it read it back from a ``Numeric(16, 2)``
    column, since ``EstimateCostLine.purchase_cost`` stores the product and not its
    two operands. ``1.33 x 1.33`` is therefore ``1.77`` there and ``1.7689`` here,
    which is the one place the two engines answer different *amounts*
    (``tests/test_revision_pricing.py`` pins it, and pins that the two agree again
    as soon as either is expressed in euros).

    What no line of this function does is round, and that is deliberate twice over.
    This is the object the pure domain takes as its
    :data:`~waterfall.domain.revision.pricing.AmountResolver`, and
    ``pricing.default_amount`` carries no rounding rule either; and a caller that
    wants the product back could not recover it from an amount already rounded,
    where the reverse is free. Turning an amount into a figure **in euros** is a
    publication rule, it applies per line, and it is applied by
    :func:`calculate_revision_aggregates` -- see there for why per line and not per
    total.
    """
    facet = cost_node.facet
    node = cost_node.node
    category = cost_node.category
    role = cost_node.role

    def priced(
        *,
        year: int,
        role_id: int | None,
        role_name: str | None,
        hours: Decimal,
        hourly_rate: Decimal,
        inflation_coefficient: Decimal,
        amount: Decimal,
    ) -> PricedLine:
        return PricedLine(
            node_id=node.id,
            work_item_id=node.work_item_id,
            label=facet.label,
            nature=facet.nature,
            bearing_node_id=None if cost_node.bearing is None else cost_node.bearing.id,
            bearing_work_item_id=(
                None if cost_node.bearing is None else cost_node.bearing.work_item_id
            ),
            bearing_task_name=(
                None if cost_node.bearing_plan is None else cost_node.bearing_plan.name
            ),
            role_id=role_id,
            role_name=role_name,
            accounting_code="" if category is None else category.accounting_code,
            category_code=None if category is None else category.category_code,
            cost_code_id=facet.cost_code_id,
            year=year,
            quantity=facet.quantity,
            hours=hours,
            hourly_rate=hourly_rate,
            inflation_coefficient=inflation_coefficient,
            amount=amount,
        )

    if facet.nature is not domain.CostNature.LABOR:
        unit_cost = facet.unit_cost if facet.unit_cost is not None else Decimal("0")
        return [
            priced(
                # A disbursement is not spread over a bearing task's years -- the legacy
                # engine snapshots it at the current year, and the facet's own forecast
                # cash-out date is the better answer the node model makes available.
                # Neither feeds the amount, which is year-independent.
                year=(
                    facet.planned_date.year
                    if facet.planned_date is not None
                    else datetime.now(UTC).year
                ),
                role_id=None,
                role_name=None,
                hours=Decimal("0"),
                hourly_rate=Decimal("0"),
                inflation_coefficient=Decimal("1"),
                amount=facet.quantity * unit_cost,
            )
        ]

    years = cost_node.years
    if years is None:
        return []
    hours = facet.hours if facet.hours is not None else Decimal("0")
    hours_per_year = hours / Decimal(len(years))
    lines: list[PricedLine] = []
    for year in years:
        # Both fallbacks are the gap `RevisionPricing` reports rather than raises on:
        # a zero rate and a neutral inflation are the legacy engine's own
        # defensive-in-depth values, reached here on a read instead of being
        # unreachable behind an upstream refusal.
        hourly_rate = (
            Decimal("0")
            if category is None
            else hourly_rates.get((category.id, year), Decimal("0"))
        )
        inflation_coefficient = inflation.get(year, Decimal("1"))
        lines.append(
            priced(
                year=year,
                role_id=facet.role_id,
                role_name=None if role is None else role.name,
                hours=hours_per_year,
                hourly_rate=hourly_rate,
                inflation_coefficient=inflation_coefficient,
                amount=facet.quantity * hours_per_year * hourly_rate * inflation_coefficient,
            )
        )
    return lines


@track_duration(ESTIMATE_CALCULATION_DURATION)
def price_loaded_revision(db: Session, loaded: LoadedRevision) -> RevisionPricing:
    """Price every cost facet of an already-loaded revision.

    The entry point for a caller that has just loaded the revision for another
    reason -- the MS Project import, which needs the amounts to tell the user what a
    removal would destroy -- so that one load serves both. :func:`price_revision`
    is the same thing for a caller holding only an id.
    """
    revision = loaded.revision
    cost_nodes = _resolve_cost_nodes(db, revision)

    category_years = [
        (cost_node.category, year)
        for cost_node in cost_nodes
        if cost_node.category is not None and cost_node.years is not None
        for year in cost_node.years
    ]
    hourly_rates, inflation = _load_rate_table(db, category_years)
    missing_cost_rates, missing_inflation_years = _missing_coverage(
        category_years, hourly_rates.keys(), inflation.keys()
    )

    lines: list[PricedLine] = []
    amount_by_node: dict[int, Decimal] = {}
    published_amount_by_node: dict[int, Decimal] = {}
    published_breakdown_by_node: dict[int, tuple[PricedYear, ...]] = {}
    unpriceable_facets: list[UnpriceableFacet] = []
    for cost_node in cost_nodes:
        node_lines = _priced_lines_of(cost_node, hourly_rates, inflation)
        lines.extend(node_lines)
        amount_by_node[cost_node.node.id] = sum((line.amount for line in node_lines), Decimal("0"))
        # The publication rule, applied once per line and before anything is added
        # up -- never to the full-precision total just above it. See
        # `RevisionPricing.published_amount_of`.
        published_amount_by_node[cost_node.node.id] = sum(
            (amount_at_the_cent(line.amount) for line in node_lines), Decimal("0")
        )
        published_breakdown_by_node[cost_node.node.id] = _priced_years(cost_node, node_lines)
        unpriceable = _unpriceable_facet(cost_node, node_lines)
        if unpriceable is not None:
            unpriceable_facets.append(unpriceable)

    return RevisionPricing(
        revision_id=revision.id,
        lines=tuple(lines),
        amount_by_node=amount_by_node,
        published_amount_by_node=published_amount_by_node,
        published_breakdown_by_node=published_breakdown_by_node,
        missing_cost_rates=tuple(missing_cost_rates),
        missing_inflation_years=tuple(missing_inflation_years),
        unpriceable_facets=tuple(unpriceable_facets),
    )


def _unpriceable_facet(
    cost_node: _CostNode, node_lines: Sequence[PricedLine]
) -> UnpriceableFacet | None:
    """The facet, when it carries hours and the engine priced it into no line at all.

    Keyed on the **observed outcome** -- hours on one side, an empty breakdown on the
    other -- rather than on the one cause known today, so that any future way of
    reaching "a chiffrage worth a thousand euros freezes at zero" is reported by this
    same check instead of slipping past it. See :class:`UnpriceableFacet`.
    """
    facet = cost_node.facet
    hours = facet.hours if facet.hours is not None else Decimal("0")
    if node_lines or facet.nature is not domain.CostNature.LABOR or hours <= 0:
        return None
    plan = cost_node.bearing_plan
    return UnpriceableFacet(
        node_id=cost_node.node.id,
        work_item_id=cost_node.node.work_item_id,
        label=facet.label,
        hours=hours,
        bearing_node_id=None if cost_node.bearing is None else cost_node.bearing.id,
        bearing_work_item_id=(
            None if cost_node.bearing is None else cost_node.bearing.work_item_id
        ),
        bearing_task_name=None if plan is None else plan.name,
        reason=(
            UnpriceableReason.BEARING_TASK_UNDATED
            if plan is None or plan.start_at is None or plan.finish_at is None
            else UnpriceableReason.BEARING_TASK_EMPTY_RANGE
        ),
    )


def _priced_years(cost_node: _CostNode, node_lines: Sequence[PricedLine]) -> tuple[PricedYear, ...]:
    """The priced lines of one facet, in the shape the pure domain takes them in.

    A projection and not a second computation, with two publication rules applied on
    the way across -- and only on the way across, so that :class:`PricedLine` itself
    stays the full-precision object every other consumer already reads.

    **Amounts** are put into euros at the cent (:func:`amount_at_the_cent`), per
    line, so that a frozen document totals to the sum of the rows it shows (#368).

    **Hours** are put at the hundredth, the precision
    `wf_revision_frozen_line.hours` stores at, and distributed so that the rows of
    one facet add up to exactly the hours the facet carries
    (:func:`frozen_hours`). Rounding each line on its own instead -- which is what
    the column silently did, and what `wf_estimate_line` did before it -- turned ten
    hours over three years into ``3.33 + 3.33 + 3.33 = 9.99``: a document whose own
    hours contradicted the chiffrage it froze.

    **Hours, rate and inflation are dropped entirely on a non-labour line.** The
    engine fills them with ``0``/``0``/``1`` there, which are
    :class:`PricedLine`'s deliberate neutral values -- they exist so the two engines
    can be compared field by field (#364) -- but no ``wf_cost_rate`` row was read to
    produce them: a disbursement is ``quantity x unit_cost``. Freezing ``0.0000`` in
    the column whose documentation says "copied from `wf_cost_rate.hourly_rate`"
    would give a filler the shape of a figure; the columns are nullable so that a
    line can say "not applicable", and this is where it says it.

    The identities and the labels are deliberately not projected -- the domain holds
    them already and copies them itself, so that plugging an engine in never moves
    the decision of *what a frozen line says* out of the domain (Règle 2).
    """
    if not node_lines:
        return ()
    if cost_node.facet.nature is not domain.CostNature.LABOR:
        return tuple(
            PricedYear(amount=amount_at_the_cent(line.amount), year=line.year)
            for line in node_lines
        )
    facet_hours = cost_node.facet.hours if cost_node.facet.hours is not None else Decimal("0")
    return tuple(
        PricedYear(
            amount=amount_at_the_cent(line.amount),
            year=line.year,
            hours=share,
            hourly_rate=line.hourly_rate,
            inflation_coefficient=line.inflation_coefficient,
        )
        for line, share in zip(node_lines, frozen_hours(facet_hours, len(node_lines)), strict=True)
    )


#: The hundredth of an hour: the precision `wf_revision_frozen_line.hours` stores at,
#: and therefore the unit a frozen document *publishes* hours in -- the same kind of
#: rule :data:`CENTS` is for money.
HOURS = Decimal("0.01")


def frozen_hours(total: Decimal, years: int) -> list[Decimal]:
    """``total`` hours spread over ``years`` years, at the hundredth, **summing to it**.

    Largest remainder: every share is the exact quotient rounded down to the
    hundredth, and the cents left over are handed out one per year starting from the
    **last**, so no share is ever more than one hundredth away from the exact
    quotient and the total is exact. Ten hours over three years gives
    ``3.33 + 3.33 + 3.34 = 10.00`` where a plain division stored in a
    ``Numeric(14, 2)`` column gave ``9.99``.

    The residue goes to the latest years and not the earliest by convention, that
    being the direction the reading goes: a reader checking a multi-year chiffrage
    reads the first year against the rate table and meets the adjustment last.

    Amounts are **not** recomputed from these shares, and deliberately so: they are
    the engine's own full-precision products rounded per line (#364's central
    acceptance criterion is that those amounts have not moved, and #368's rule is
    that they add up to the published total). So a frozen row is the record of what
    was charged, not an invitation to re-multiply it -- what this function buys is
    that the *hours* of a document add up to the chiffrage it froze.
    """
    if years <= 0:
        return []
    target = total.quantize(HOURS, rounding=ROUND_HALF_UP)
    base = (target / years).quantize(HOURS, rounding=ROUND_DOWN)
    shares = [base] * years
    # `base` is the quotient rounded *down*, so the residue is non-negative and
    # strictly smaller than one hundredth per year: the loop below can never run
    # past the end of the list.
    for offset in range(int((target - base * years) / HOURS)):
        shares[years - 1 - offset] += HOURS
    return shares


def price_revision(db: Session, revision_id: int) -> RevisionPricing:
    """Price every cost facet of ``revision_id``.

    Raises :class:`~waterfall.services.revision_store.RevisionNotFoundError` for an
    unknown revision, like every other revision service: the load is what decides,
    and a caller behind :func:`waterfall.api.revision_errors.revision_operation`
    gets the same ``REVISION_NOT_FOUND`` as anywhere else.
    """
    return price_loaded_revision(db, load_revision(db, revision_id))


#: A euro amount, at the cent: the unit of every figure this module *publishes*,
#: and the precision the ``Numeric(16, 2)`` columns of the legacy socle carried
#: before #364 took them off the read path. See
#: :func:`calculate_revision_aggregates` for why the rounding happens per priced
#: line rather than per total.
CENTS = Decimal("0.01")


def amount_at_the_cent(amount: Decimal) -> Decimal:
    """One amount in euros, at the cent, ``ROUND_HALF_UP`` -- the rounding the
    ``Numeric(16, 2)`` column applied. See :data:`CENTS`.

    Public because it is *the* publication rule and there must be one: every
    caller that quotes a ``CostLoss`` -- the node deletion, the MS Project import
    diff, the MS Project import run and the reconciliation round trip, four since
    #365 -- is on it too since #368, through
    :attr:`RevisionPricing.published_amount_by_node`, which applies it per line and
    then sums, so that a loss and a total of losses stay additive exactly as the
    five figures below do.
    """
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class RevisionAggregates(TypedDict):
    """Totals of a revision, the node-model counterpart of :class:`EstimateAggregates`.

    Same five figures, computed from the cost facets of a **draft** as readily as
    from a validated revision, where the legacy ones could only ever be summed from
    the ``EstimateLine`` rows a validation had already written -- a devis in
    progress had no total at all. Every amount is in euros at the cent
    (:data:`CENTS`), unlike :class:`PricedLine`'s.
    """

    total_labor_cost: Decimal
    total_purchase_cost: Decimal
    total_unburdened_cost: Decimal
    by_category: dict[str, Decimal]
    by_cost_code: dict[str, Decimal]
    #: The facets the engine could put in no year at all, carried through from
    #: :attr:`RevisionPricing.unpriceable_facets` so that a reader of the totals sees
    #: *why* a labour total is zero, and knows what to fix before a validation
    #: refuses it. See :class:`UnpriceableFacet`.
    unpriceable_facets: list[UnpriceableFacet]
    missing_cost_rates: list[tuple[CostCategory, int]]
    missing_inflation_years: list[int]


@track_duration(ESTIMATE_CALCULATION_DURATION)
def calculate_revision_aggregates(db: Session, revision_id: int) -> RevisionAggregates:
    """Aggregate the priced lines of a revision by nature, accounting code and cost code.

    Splits labour from the rest on :class:`~waterfall.domain.revision.CostNature`
    rather than on "does the line carry a role", which is what the legacy aggregate
    had to infer it from: the node model states the nature on the facet, and INV-19
    /INV-20 make it exclusive.

    A cost facet sitting at the **root** of the tree -- no bearing task, INV-01's
    project-wide global cost -- is counted like any other: it has a node, so it has
    a facet, so it has an amount. Nothing here filters on a bearing task.

    Every figure returned is in **euros at the cent**, and gets there the way the
    socle this replaces got there: each priced line is rounded on its own
    (:func:`amount_at_the_cent`), and the rounded amounts are what is added up. A
    legacy total was never a rounded sum -- it was a sum of amounts that had each
    been through a ``Numeric(16, 2)`` column (``EstimateLine.budget_cost``,
    ``EstimateCostLine.purchase_cost``) before ``calculate_estimate_aggregates``
    added anything. Summing the products at full precision and rounding the total
    instead would answer ``1000.00`` where the endpoint this replaces answers
    ``999.99`` -- ten hours split over three years at a flat rate, three residues of
    a third of a cent the column dropped one by one -- and "les mêmes montants
    qu'avant la migration" is the acceptance criterion of #364.

    Rounding per line is also the only one of the two rules that is **additive**,
    which matters because these five figures are five partitions of the same set of
    lines and a client reads three of them side by side: with an hourly rate at four
    decimals -- ``CostRate.hourly_rate`` is a ``Numeric(14, 4)`` precisely to allow
    it -- rounding each total on its own publishes ``MO 100.00`` and ``Achats 0.00``
    under a ``Total 100.01``. A sum of amounts already at the cent is additive over
    any partition, by construction, so ``total_labor_cost + total_purchase_cost``,
    ``sum(by_category.values())`` and ``sum(by_cost_code.values())`` all equal
    ``total_unburdened_cost``.

    The engine itself keeps every digit -- :attr:`PricedLine.amount` and
    :attr:`RevisionPricing.amount_by_node` are the raw products, because that object
    is also the resolver the pure domain calls (see :func:`_priced_lines_of`).
    Publication starts here and not before.

    Loads and prices the revision **once** and hands the result to
    :func:`aggregates_of_pricing`, which is where the summation itself lives: a
    caller that already holds a :class:`RevisionPricing` -- the devis workbook
    builder, which prints the priced grid and these totals in the same file -- calls
    that one directly instead of asking for a second, independent snapshot of the
    same revision. See its docstring for why that is a correctness matter and not an
    optimisation.
    """
    return aggregates_of_pricing(db, price_revision(db, revision_id))


def aggregates_of_pricing(db: Session, pricing: RevisionPricing) -> RevisionAggregates:
    """The five totals of an **already priced** revision -- the body of
    :func:`calculate_revision_aggregates`, minus the loading.

    Split out so that a caller publishing a priced grid *and* its totals derives
    both from one snapshot. ``build_revision_workbook`` used to price the revision
    itself and then call :func:`calculate_revision_aggregates`, which priced it a
    second time: the route takes no lock and the session is READ COMMITTED, so a
    concurrent edit landing between the two reads put a line in the ``Devis`` sheet
    that the ``Agrégats`` sheet of the *same file* did not count -- one workbook,
    two contradictory totals. The legacy builder had the same shape but summed
    **frozen** ``wf_estimate_line`` rows, which only a validation writes, so its
    window was all but closed; pricing a draft live reopens it on any edit, and that
    is an exposure this lot introduced rather than inherited.

    ``db`` is read for one thing only: the ``code`` of each
    :class:`~waterfall.models.resources.ProjectCostCode` the priced lines point at,
    which is a label and not a figure.
    """
    cost_code_ids = {line.cost_code_id for line in pricing.lines if line.cost_code_id is not None}
    cost_code_labels = _resolve_cost_code_labels(db, cost_code_ids)

    aggregates: RevisionAggregates = {
        "total_labor_cost": Decimal("0"),
        "total_purchase_cost": Decimal("0"),
        "total_unburdened_cost": Decimal("0"),
        "by_category": {},
        "by_cost_code": {},
        "unpriceable_facets": list(pricing.unpriceable_facets),
        "missing_cost_rates": list(pricing.missing_cost_rates),
        "missing_inflation_years": list(pricing.missing_inflation_years),
    }
    for line in pricing.lines:
        # The publication rule, applied once per line and before anything is added
        # up: every partition below therefore sums the same rounded amounts, and
        # stays additive against the total. See this function's docstring.
        amount = amount_at_the_cent(line.amount)
        if line.nature is domain.CostNature.LABOR:
            aggregates["total_labor_cost"] += amount
        else:
            aggregates["total_purchase_cost"] += amount
        aggregates["total_unburdened_cost"] += amount
        by_category = aggregates["by_category"]
        by_category[line.accounting_code] = (
            by_category.get(line.accounting_code, Decimal("0")) + amount
        )
        label = (
            cost_code_labels.get(line.cost_code_id, UNASSIGNED_COST_CODE_LABEL)
            if line.cost_code_id is not None
            else UNASSIGNED_COST_CODE_LABEL
        )
        by_cost_code = aggregates["by_cost_code"]
        by_cost_code[label] = by_cost_code.get(label, Decimal("0")) + amount
    return aggregates


# --------------------------------------------------------------------------------------
# The legacy engine, on `ms_task`/`EstimateCostLine`/`EstimateRoleAssignment`
#
# Alive until E14-12 (#339) removes it with the tables it reads. Still wired to
# `POST .../estimates/{id}/validate`, and the reference the engine above is compared
# against -- see this module's docstring.
# --------------------------------------------------------------------------------------


@track_duration(ESTIMATE_CALCULATION_DURATION)
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
    # `ORDER BY id`, like `_scoped_estimate_role_assignments` in the reconciliation
    # export: without it the row order is whatever PostgreSQL feels like returning --
    # stable in practice until a `VACUUM` or an `UPDATE` moves a tuple. The
    # `EstimateLine` rows below come out in this order, and the devis workbook prints
    # them in it, which is what #365's cell-for-cell comparison against the revision
    # builder walks positionally. An unordered query would make that proof go red for
    # a reason that has nothing to do with either engine.
    assignments = (
        db.query(EstimateRoleAssignment, MsTask, ResourceRole, CostCategory)
        .outerjoin(MsTask, EstimateRoleAssignment.task_id == MsTask.id)
        .join(ResourceRole, EstimateRoleAssignment.role_id == ResourceRole.id)
        .join(CostCategory, ResourceRole.cost_category_id == CostCategory.id)
        .filter(EstimateRoleAssignment.estimate_id == estimate_id)
        .order_by(EstimateRoleAssignment.id)
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


@track_duration(ESTIMATE_CALCULATION_DURATION)
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
