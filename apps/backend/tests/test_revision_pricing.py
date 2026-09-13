"""The cost calculation engine, on the cost facet of the revision node (E14-07b, #364).

The central acceptance criterion of the issue is a **comparison**, not a
reconduction: "the engine produces, on an equivalent tree and equivalent
assignments, the same amounts as before the migration". A test that priced a
revision with the new engine and then asserted the result against that same engine
would prove nothing at all, so :func:`test_the_two_engines_agree_amount_for_amount`
mounts one single set of figures **twice** -- once on the legacy socle
(``ms_task`` / ``EstimateRoleAssignment`` / ``EstimateCostLine``, still alive until
E14-12/#339 removes it) and once on the revision tree and its cost facets -- runs
*both* engines, and asserts the amounts equal. This is the last issue in which that
comparison is possible; it is the whole reason the EPIC was amended to be "additif
d'abord".

That doubly-mounted fixture now lives in ``_estimate_socle_support.py``: #365 has to
build the two *workbooks* from the same figures and compare them, which is this same
comparison one level up, and two copies of the seeds would have made "the same
figures" a claim rather than a fact. The figures themselves, and why every year is
derived from the current one, are documented there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import pytest

from _calendar_support import ensure_default_calendar
from _estimate_grid_support import seed_cost_line, seed_root_grid_node
from _estimate_socle_support import (
    INFLATION_ONE,
    RATE_ONE,
    YEAR_ONE,
    YEAR_THREE,
    YEAR_TWO,
    BothSides,
    seed_both_sides,
    seed_project,
    seed_referential,
)
from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_purchase_line,
    insert_revision,
    insert_task,
    seed_annual_rate,
)
from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsTask
from waterfall.models.resources import (
    CostRate,
    Estimate,
    EstimateLine,
    EstimateRoleAssignment,
)
from waterfall.services import revision_tree
from waterfall.services.estimate_calculation import (
    UNASSIGNED_COST_CODE_LABEL,
    PricedLine,
    calculate_estimate_aggregates,
    calculate_estimate_lines,
    calculate_revision_aggregates,
    price_revision,
)

#: A euro amount at the cent, as the API publishes it.
#:
#: Restates ``estimate_calculation.amount_at_the_cent`` rather than importing it:
#: what the comparison below needs is "rounded the way the legacy ``Numeric(16, 2)``
#: column rounded", and the engine is one *consumer* of that rule, not its owner.
#: Spelling it out here is also what keeps the two ways of applying it -- per line,
#: as the column did and as ``calculate_revision_aggregates`` does, and on the total,
#: which is the rule that was *not* retained -- visibly different objects.
CENTS = Decimal("0.01")


def at_the_cent(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


@pytest.fixture
def both_sides() -> BothSides:
    """One set of figures, mounted on the legacy socle *and* on the revision model."""
    return seed_both_sides()


def _comparable(line: EstimateLine | PricedLine) -> tuple[str, int, Decimal, Decimal, Decimal]:
    """The five figures that *are* the amount, in a shape both engines answer in.

    Not the identities: the two sides are two different projects, so they carry
    different task ids, role ids and cost-code ids for the same figures. The
    accounting code is the one label both snapshot from the same source of truth
    (the cost category), so it stands in for "which category this money lands in",
    and ``by_cost_code`` of the aggregates covers the cost code by its ``code``.
    """
    amount = line.budget_cost if isinstance(line, EstimateLine) else line.amount
    return (line.accounting_code, line.year, line.quantity, line.hours, amount)


# --------------------------------------------------------------------------------------
# 1. The central criterion: the two engines agree, amount for amount
# --------------------------------------------------------------------------------------


def test_the_two_engines_agree_amount_for_amount(both_sides: BothSides) -> None:
    """Both engines run on the same figures, and the lines they produce are equal.

    Not "the new engine returns what it returned last time": the expectation is
    produced by the **legacy** engine, on rows the new one never reads, inside the
    same test. The legacy socle is still here precisely so that this comparison can
    be made once before E14-12 (#339) takes it away.
    """
    with get_session_factory()() as session:
        legacy_lines = calculate_estimate_lines(session, both_sides.legacy.estimate_id)
        pricing = price_revision(session, both_sides.revision.revision_id)

    assert legacy_lines, "the legacy engine produced nothing: the fixture says nothing"
    assert sorted(_comparable(line) for line in legacy_lines) == sorted(
        _comparable(line) for line in pricing.lines
    )
    # And the coverage is complete on both sides, so neither total is a zero-rate
    # fallback that happens to match another zero-rate fallback.
    assert pricing.missing_cost_rates == ()
    assert pricing.missing_inflation_years == ()


def test_the_two_engines_agree_on_every_aggregate(both_sides: BothSides) -> None:
    """The same comparison one level up, and on the figures a user actually reads.

    The legacy aggregate can only sum `wf_estimate_line` rows a validation has
    written, so the legacy lines are persisted here exactly as
    ``validate_project_estimate`` persists them -- which also puts the comparison
    through the ``Numeric(16, 2)`` round trip the legacy totals really go through.
    The comparison is an **equality**, with nothing rounded on either side at the
    moment of comparing: ``calculate_revision_aggregates`` has already rounded each
    priced line to the cent before summing it, which is exactly what that column did
    to each legacy line before ``calculate_estimate_aggregates`` summed anything.
    That is the acceptance criterion of #364 -- "les mêmes montants qu'avant la
    migration" -- taken literally, on the figures a user reads. T4 is in the fixture
    for exactly that reason -- 10 hours over three years, the engine's one inexact
    operation -- so that this comparison is not a comparison of exact arithmetic
    with itself.
    """
    with get_session_factory()() as session:
        session.add_all(calculate_estimate_lines(session, both_sides.legacy.estimate_id))
        session.commit()

    with get_session_factory()() as session:
        legacy = calculate_estimate_aggregates(session, both_sides.legacy.estimate_id)
        engine = calculate_revision_aggregates(session, both_sides.revision.revision_id)

    assert engine["total_labor_cost"] == legacy["total_labor_cost"]
    assert engine["total_purchase_cost"] == legacy["total_purchase_cost"]
    assert engine["total_unburdened_cost"] == legacy["total_unburdened_cost"]
    assert engine["by_category"] == legacy["by_category"]
    assert engine["by_cost_code"] == legacy["by_cost_code"]
    # Pinned to literals as well, so that "the two agree" cannot degenerate into
    # "both engines returned nothing".
    assert engine["total_labor_cost"] == Decimal("24508.33")
    assert engine["total_purchase_cost"] == Decimal("96.50")
    assert engine["by_cost_code"] == {
        "CC-A": Decimal("22708.33"),
        "CC-B": Decimal("876.50"),
        UNASSIGNED_COST_CODE_LABEL: Decimal("1020.00"),
    }
    # And the five figures add up, which is what rounding per line buys and rounding
    # each total on its own would lose -- see
    # `test_the_aggregates_endpoint_publishes_every_amount_at_the_cent`.
    assert (
        engine["total_labor_cost"] + engine["total_purchase_cost"]
        == engine["total_unburdened_cost"]
    )
    assert sum(engine["by_category"].values(), Decimal("0")) == engine["total_unburdened_cost"]
    assert sum(engine["by_cost_code"].values(), Decimal("0")) == engine["total_unburdened_cost"]
    # Underneath, the engine itself has rounded nothing: T4's 10 hours over three
    # years leave a residue in the products, and it is the aggregate that drops it
    # line by line, exactly where the legacy column dropped it.
    with get_session_factory()() as session:
        pricing = price_revision(session, both_sides.revision.revision_id)
    assert sum((line.amount for line in pricing.lines), Decimal("0")) == Decimal(
        "24604.83333333333333333333333"
    )


def test_the_two_engines_agree_on_which_task_bears_each_labour_line(
    both_sides: BothSides,
) -> None:
    """INV-01 resolved by walking the tree lands on the same task the stored
    ``EstimateRoleAssignment.task_id`` pointed at.

    Complements the amount comparison above, which deliberately compares no
    identity: this is the one field the new engine derives where the old one read
    it, so it is the one worth comparing by name.
    """
    with get_session_factory()() as session:
        legacy_lines = calculate_estimate_lines(session, both_sides.legacy.estimate_id)
        pricing = price_revision(session, both_sides.revision.revision_id)

    legacy_labor = sorted(
        (line.task_name, line.year, line.budget_cost)
        for line in legacy_lines
        if line.role_id is not None
    )
    engine_labor = sorted(
        (line.bearing_task_name or "", line.year, line.amount)
        for line in pricing.lines
        if line.nature.value == "labor"
    )
    assert engine_labor == legacy_labor
    assert ("", YEAR_ONE, Decimal("1000.00")) in engine_labor


def test_a_bearing_task_without_dates_prices_nothing_on_either_engine(
    both_sides: BothSides,
) -> None:
    """T3 carries a 40-hour assignment and no dates, on both sides, and costs nothing.

    The legacy ``_generate_labor_lines`` returns an empty list for it. Reproduced
    rather than improved on: turning it into a current-year line would change a
    total at the very moment the engine moves, which is exactly what this issue
    must not do.
    """
    with get_session_factory()() as session:
        legacy_lines = calculate_estimate_lines(session, both_sides.legacy.estimate_id)
        pricing = price_revision(session, both_sides.revision.revision_id)

    assert [line for line in legacy_lines if line.task_name == "T3"] == []
    assert pricing.amount_by_node[both_sides.revision.cost_nodes["Etude T3"]] == Decimal("0")
    assert [line for line in pricing.lines if line.bearing_task_name == "T3"] == []


# --------------------------------------------------------------------------------------
# 2. A cost facet at the root counts towards the total of the revision
# --------------------------------------------------------------------------------------


def test_a_cost_facet_at_the_root_counts_towards_the_total(both_sides: BothSides) -> None:
    """INV-01's project-wide global cost: no bearing task, and a real amount anyway.

    The state the legacy model reached as ``EstimateRoleAssignment.task_id IS NULL``
    (#289) and lost a line to more than once -- an ``INNER JOIN`` used to drop it
    from every total with no signal at all. On the node model it is simply a node
    whose strict ancestors carry no planning facet, and nothing in the aggregate
    filters on a bearing task.
    """
    with get_session_factory()() as session:
        pricing = price_revision(session, both_sides.revision.revision_id)
        aggregates = calculate_revision_aggregates(session, both_sides.revision.revision_id)

    nodes = both_sides.revision.cost_nodes
    root_labor = pricing.amount_by_node[nodes["Etude transverse"]]
    root_purchase = pricing.amount_by_node[nodes["Frais de dossier"]]
    assert root_labor == Decimal("1000.00")
    assert root_purchase == Decimal("20.00")
    # T4 (10 h over three years) makes the priced lines inexact; the aggregate is
    # the sum of each of them at the cent (`estimate_calculation.amount_at_the_cent`),
    # and the endpoint publishes it unchanged.
    assert all(
        line.bearing_node_id is None and line.bearing_task_name is None
        for line in pricing.lines
        if line.node_id in {nodes["Etude transverse"], nodes["Frais de dossier"]}
    )
    assert aggregates["total_unburdened_cost"] == Decimal("24604.83")


# --------------------------------------------------------------------------------------
# 3. Moving a cost node changes its bearing task and nothing else about it
# --------------------------------------------------------------------------------------


def test_moving_a_cost_node_changes_the_bearing_task_and_not_the_line(
    both_sides: BothSides,
) -> None:
    """The facet keeps quantity, disbursement, category -- and, here, its amount.

    "Cables" is a disbursement: its amount is ``quantity x unit_cost``, which owes
    nothing to a bearing task, so re-parenting it must change *which* task bears it
    and leave every figure alone. That is the criterion of #364, and it holds for
    free because the bearing task is resolved and stored nowhere.
    """
    fixture = both_sides.revision
    with get_session_factory()() as session:
        before = price_revision(session, fixture.revision_id)
        cables = next(line for line in before.lines if line.label == "Cables")
        assert cables.bearing_task_name == "T2"

        revision_tree.move_nodes(
            session,
            fixture.revision_id,
            [fixture.cost_nodes["Cables"]],
            expected_lock_version=0,
            target_parent_id=fixture.task_nodes["T1"],
        )
        session.commit()

    with get_session_factory()() as session:
        after = price_revision(session, fixture.revision_id)
    moved = next(line for line in after.lines if line.label == "Cables")

    assert moved.bearing_task_name == "T1"
    assert moved.bearing_node_id == fixture.task_nodes["T1"]
    assert (moved.quantity, moved.amount, moved.accounting_code, moved.cost_code_id) == (
        cables.quantity,
        cables.amount,
        cables.accounting_code,
        cables.cost_code_id,
    )


def test_moving_a_labour_node_under_a_task_of_other_years_reprices_it(
    both_sides: BothSides,
) -> None:
    """The other half of the same criterion, and the reason it is worth having.

    A labour line's amount *does* depend on its bearing task, because the hours are
    spread over that task's years. Moving "Etude T2" (8 h, one year) under T1 (two
    years) must therefore split it in two and reprice it -- while its own stored
    attributes, quantity and hours included, stay exactly what they were.
    """
    fixture = both_sides.revision
    with get_session_factory()() as session:
        before = price_revision(session, fixture.revision_id)
        assert before.amount_by_node[fixture.cost_nodes["Etude T2"]] == Decimal("800.00")

        revision_tree.move_nodes(
            session,
            fixture.revision_id,
            [fixture.cost_nodes["Etude T2"]],
            expected_lock_version=0,
            target_parent_id=fixture.task_nodes["T1"],
        )
        session.commit()

    with get_session_factory()() as session:
        after = price_revision(session, fixture.revision_id)
    moved = [line for line in after.lines if line.label == "Etude T2"]

    assert [line.year for line in moved] == [YEAR_ONE, YEAR_TWO]
    assert {line.bearing_task_name for line in moved} == {"T1"}
    # 4 h in each year: 1 x 4 x 100.00 x 1 + 1 x 4 x 110.00 x 1.05
    assert after.amount_by_node[fixture.cost_nodes["Etude T2"]] == Decimal("862.00")
    assert {line.quantity for line in moved} == {Decimal("1")}


# --------------------------------------------------------------------------------------
# 4. Moving a bearing task leaves the role, the hours and the amount alone
# --------------------------------------------------------------------------------------


def test_moving_a_bearing_task_leaves_role_hours_and_amount_unchanged(
    both_sides: BothSides,
) -> None:
    """T2 is re-parented under T1; the MO line it bears follows it and is unchanged.

    The line moves with its task -- a node takes its subtree, INV-02 -- so it keeps
    the same bearing task, the same role, the same hours and therefore the same
    amount. What would break this is an engine that derived a year from a node's
    *position* rather than from its bearing task's dates.
    """
    fixture = both_sides.revision
    with get_session_factory()() as session:
        before = [line for line in price_revision(session, fixture.revision_id).lines]

        revision_tree.move_nodes(
            session,
            fixture.revision_id,
            [fixture.task_nodes["T2"]],
            expected_lock_version=0,
            target_parent_id=fixture.task_nodes["T1"],
        )
        session.commit()

    with get_session_factory()() as session:
        after = [line for line in price_revision(session, fixture.revision_id).lines]

    def by_label(lines: list[PricedLine]) -> dict[str, tuple[int | None, Decimal, Decimal]]:
        return {
            line.label: (line.role_id, line.hours, line.amount)
            for line in lines
            if line.label == "Etude T2"
        }

    assert by_label(after) == by_label(before)
    assert by_label(after)["Etude T2"] == (
        both_sides.referential.labor.role_id,
        Decimal("8"),
        Decimal("800.00"),
    )
    assert {line.bearing_task_name for line in after if line.label == "Etude T2"} == {"T2"}


# --------------------------------------------------------------------------------------
# 5. A gap in the rate table is reported, never raised on a read
# --------------------------------------------------------------------------------------


def test_a_missing_rate_is_reported_and_the_read_still_answers(both_sides: BothSides) -> None:
    """The one deliberate difference with ``calculate_estimate_lines``.

    The legacy engine raises ``MissingRateCoverageError`` and refuses the whole
    validation, which is right for a validation and wrong for a read: a draft whose
    next-year rate has not been entered yet still has to be readable. So the line is
    priced at a zero rate, and the gap is named in the same answer -- it is E14-08
    (#334) that will turn these two lists back into a refusal, at validation time.
    """
    with get_session_factory()() as session:
        # The rate of the second year -- the one T1 spills into -- and only that one.
        session.query(CostRate).filter(CostRate.year == YEAR_TWO).delete()
        session.commit()

    with get_session_factory()() as session:
        pricing = price_revision(session, both_sides.revision.revision_id)
        aggregates = calculate_revision_aggregates(session, both_sides.revision.revision_id)

    assert [year for _category, year in pricing.missing_cost_rates] == [YEAR_TWO]
    assert pricing.missing_inflation_years == ()
    second_year = [line for line in pricing.lines if line.year == YEAR_TWO]
    assert second_year and all(line.hourly_rate == Decimal("0") for line in second_year)
    # T1 loses its second year (11550.00) and T4 the middle one of its three.
    assert aggregates["total_labor_cost"] == Decimal("12573.33")
    assert [year for _category, year in aggregates["missing_cost_rates"]] == [YEAR_TWO]


# --------------------------------------------------------------------------------------
# 6. The two places the two engines do not answer the same thing, each named --
#    and the one place they look like they would, and do not
#
# The first is a legacy *amount* that was stored in a two-decimal column before
# anything read it back, and it survives only inside `PricedLine.amount`: every
# published figure rounds each line to the cent, which is what that column did. The
# second is a deliberate improvement of the node model, and changes no amount at
# all. Between them sits the hour split -- the engine's one inexact operation --
# which the per-line rounding rule makes a *non*-divergence, and which is pinned as
# such because the arbitration could have gone the other way.
# --------------------------------------------------------------------------------------


def test_the_first_divergence_is_the_legacy_two_decimal_storage_of_a_disbursement() -> None:
    """A legacy non-labour line read its amount back from a ``Numeric(16, 2)`` column.

    ``EstimateCostLine.purchase_cost`` stores the product, so ``1.33 x 1.33`` comes
    back as ``1.77``. The cost facet stores the two operands and no product, so the
    engine multiplies them at full precision and answers ``1.7689``. Rounding inside
    the engine to make the two agree would be inventing a rounding rule the domain
    does not have -- ``pricing.default_amount`` has none either, and this object is
    the resolver the domain calls -- so the divergence is pinned here instead.

    It is a divergence of ``PricedLine.amount`` and of nothing a caller ever reads:
    the last assertion below is the publication rule of
    ``calculate_revision_aggregates`` (each line at the cent, *then* summed), and
    under it the two engines answer the same euro figure.
    """
    key = uuid4().hex[:8]
    calendar_id = ensure_default_calendar()
    with get_session_factory()() as session:
        legacy_project = seed_project(session, f"Legacy odd {key}")
        revision_project = seed_project(session, f"Revision odd {key}")
        referential = seed_referential(session, legacy_project.id, key=key, calendar_id=calendar_id)
        estimate = Estimate(
            project_id=legacy_project.id,
            planning_id=None,
            version_number=1,
            kind="initial",
            status="draft",
            currency_code="EUR",
        )
        session.add(estimate)
        session.flush()
        seed_cost_line(
            session,
            estimate_id=estimate.id,
            cost_category_id=referential.supply.cost_category_id,
            label="Odd",
            quantity="1.33",
            unit_cost="1.33",
        )
        supply = ReferenceData(
            project_id=revision_project.id,
            calendar_id=referential.supply.calendar_id,
            role_id=referential.supply.role_id,
            cost_type_id=referential.supply.cost_type_id,
            cost_category_id=referential.supply.cost_category_id,
        )
        revision = insert_revision(session, supply)
        insert_purchase_line(
            session,
            supply,
            revision,
            label="Odd",
            quantity=Decimal("1.33"),
            unit_cost=Decimal("1.33"),
        )
        session.commit()
        estimate_id = estimate.id
        revision_id = revision.id

    with get_session_factory()() as session:
        legacy_lines = calculate_estimate_lines(session, estimate_id)
        pricing = price_revision(session, revision_id)

    assert [line.budget_cost for line in legacy_lines] == [Decimal("1.77")]
    assert [line.amount for line in pricing.lines] == [Decimal("1.7689")]
    # And no figure a caller ever reads carries the difference: the publication rule
    # is each line at the cent, which lands both engines on 1.77.
    assert legacy_lines[0].budget_cost == at_the_cent(pricing.lines[0].amount)


def test_the_hour_split_does_not_diverge_because_each_line_is_published_at_the_cent() -> None:
    """The engine's one inexact operation, and the rounding rule that answers it.

    ``hours / Decimal(len(years))`` is the only inexact operation in the module, and
    the legacy engine ran the very same division -- but it wrote each result into
    ``EstimateLine.budget_cost``, a ``Numeric(16, 2)`` column, **before**
    ``calculate_estimate_aggregates`` summed anything. A legacy total was therefore
    never a rounded sum, it was a sum of rounded amounts. Ten hours over three years
    at a flat rate is the whole demonstration: three lines of ``333.33...``, which
    make ``999.99`` rounded one by one and ``1000.00`` summed first and rounded
    afterwards.

    The arbitration, restated here because it is the point of the test:
    ``calculate_revision_aggregates`` rounds **per line** and then sums, which is
    what the column did, so the two engines answer the same total -- ``999.99`` --
    and #364's "les mêmes montants qu'avant la migration" holds on totals too.
    Rounding the five totals instead would have answered ``1000.00`` here, and would
    have cost additivity everywhere else: five partitions of the same lines, rounded
    independently, do not add up (see ``calculate_revision_aggregates``, and
    ``test_the_aggregates_endpoint_publishes_every_amount_at_the_cent``).

    The engine below the aggregate keeps every digit, and that is asserted here as
    well: ``PricedLine.amount`` is the raw product, because that object is also the
    resolver the pure domain calls.
    """
    key = uuid4().hex[:8]
    calendar_id = ensure_default_calendar()
    with get_session_factory()() as session:
        legacy_project = seed_project(session, f"Legacy split {key}")
        revision_project = seed_project(session, f"Revision split {key}")
        referential = seed_referential(session, legacy_project.id, key=key, calendar_id=calendar_id)
        # A flat rate on all three years, so that every one of the three lines carries
        # the same residue -- three thirds of a cent, which round *down* one by one and
        # *up* once added.
        for year in (YEAR_ONE, YEAR_TWO, YEAR_THREE):
            seed_annual_rate(
                session,
                referential.labor,
                year=year,
                hourly_rate=RATE_ONE,
                inflation=INFLATION_ONE,
            )
        start_at = datetime(YEAR_ONE, 10, 1, tzinfo=UTC)
        finish_at = datetime(YEAR_THREE, 2, 28, tzinfo=UTC)
        task = MsTask(
            project_id=legacy_project.id,
            uid=1,
            name="Trois ans",
            position=1,
            start_at=start_at,
            finish_at=finish_at,
        )
        estimate = Estimate(
            project_id=legacy_project.id,
            planning_id=None,
            version_number=1,
            kind="initial",
            status="draft",
            currency_code="EUR",
        )
        session.add_all([task, estimate])
        session.flush()
        session.add(
            EstimateRoleAssignment(
                estimate_id=estimate.id,
                task_id=task.id,
                role_id=referential.labor.role_id,
                quantity=Decimal("1"),
                hours=Decimal("10"),
                cost_code_id=None,
                node_id=seed_root_grid_node(session, estimate.id, "labor"),
            )
        )
        labor = ReferenceData(
            project_id=revision_project.id,
            calendar_id=referential.labor.calendar_id,
            role_id=referential.labor.role_id,
            cost_type_id=referential.labor.cost_type_id,
            cost_category_id=referential.labor.cost_category_id,
        )
        revision = insert_revision(session, labor)
        bearing = insert_task(
            session,
            labor,
            revision,
            name="Trois ans",
            start_at=start_at,
            finish_at=finish_at,
        )
        insert_labor_line(
            session,
            labor,
            revision,
            label="Etude",
            parent_id=bearing.id,
            quantity=Decimal("1"),
            hours=Decimal("10"),
        )
        session.commit()
        estimate_id = estimate.id
        revision_id = revision.id

    with get_session_factory()() as session:
        legacy_lines = calculate_estimate_lines(session, estimate_id)
        pricing = price_revision(session, revision_id)
        # Line for line, before the legacy lines reach a column: the two engines run
        # the same division and answer the same twenty-eight digits.
        assert sorted(line.budget_cost for line in legacy_lines) == sorted(
            line.amount for line in pricing.lines
        )
        session.add_all(legacy_lines)
        session.commit()

    with get_session_factory()() as session:
        legacy = calculate_estimate_aggregates(session, estimate_id)
        engine = calculate_revision_aggregates(session, revision_id)

    assert legacy["total_labor_cost"] == Decimal("999.99")
    assert engine["total_labor_cost"] == Decimal("999.99")
    # ... which is the sum of the three lines rounded one by one, and not the rounding
    # of their sum: that one is a cent away, and is the rule this engine does *not*
    # apply.
    assert (
        sum((at_the_cent(line.amount) for line in pricing.lines), Decimal("0"))
        == engine["total_labor_cost"]
    )
    assert sum((line.amount for line in pricing.lines), Decimal("0")) == Decimal(
        "999.9999999999999999999999999"
    )
    assert (
        at_the_cent(sum((line.amount for line in pricing.lines), Decimal("0")))
        - engine["total_labor_cost"]
        == CENTS
    )


def test_the_year_of_a_disbursement_follows_its_planned_date_not_the_current_one() -> None:
    """The one divergence that is an improvement, pinned because it is still one.

    ``EstimateLine.year`` was ``datetime.now(UTC).year`` for every non-labour line,
    whatever the line said about when the money goes out -- the legacy engine had a
    ``planned_date`` column right there (``EstimateCostLine.planned_date``) and read
    it for nothing. The cost facet's own ``planned_date`` is what
    :class:`PricedLine` dates a disbursement by, and the current year only when
    there is none.

    No amount moves: a disbursement is not spread over years. But
    ``PricedLine.year`` is a public field, and #365 ventilates an export by it, so
    the arbitration is written down here rather than only in a docstring -- exactly
    as the rounding arbitrations above are.
    """
    key = uuid4().hex[:8]
    calendar_id = ensure_default_calendar()
    cash_out = datetime(YEAR_TWO, 7, 15, tzinfo=UTC)
    with get_session_factory()() as session:
        legacy_project = seed_project(session, f"Legacy dated {key}")
        revision_project = seed_project(session, f"Revision dated {key}")
        referential = seed_referential(session, legacy_project.id, key=key, calendar_id=calendar_id)
        estimate = Estimate(
            project_id=legacy_project.id,
            planning_id=None,
            version_number=1,
            kind="initial",
            status="draft",
            currency_code="EUR",
        )
        session.add(estimate)
        session.flush()
        seed_cost_line(
            session,
            estimate_id=estimate.id,
            cost_category_id=referential.supply.cost_category_id,
            label="Cables",
            quantity="3.00",
            unit_cost="25.50",
            planned_date=cash_out,
        )
        supply = ReferenceData(
            project_id=revision_project.id,
            calendar_id=referential.supply.calendar_id,
            role_id=referential.supply.role_id,
            cost_type_id=referential.supply.cost_type_id,
            cost_category_id=referential.supply.cost_category_id,
        )
        revision = insert_revision(session, supply)
        insert_purchase_line(
            session,
            supply,
            revision,
            label="Cables",
            quantity=Decimal("3.00"),
            unit_cost=Decimal("25.50"),
            planned_date=cash_out.date(),
        )
        session.commit()
        estimate_id = estimate.id
        revision_id = revision.id

    with get_session_factory()() as session:
        legacy_lines = calculate_estimate_lines(session, estimate_id)
        pricing = price_revision(session, revision_id)

    assert [line.year for line in legacy_lines] == [YEAR_ONE]
    assert [line.year for line in pricing.lines] == [YEAR_TWO]
    assert YEAR_TWO != YEAR_ONE
    # The divergence is the year and only the year.
    assert [line.budget_cost for line in legacy_lines] == [line.amount for line in pricing.lines]
