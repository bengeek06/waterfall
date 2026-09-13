"""Amount resolution for the test bench -- deliberately *not* the calculation engine.

The specification is explicit: MO/Achat/PRU amounts are **derived**, computed by
the calculation engine from annual rates and inflation coefficients, and are
neither attributes of the cost facet nor invariants of the model. The domain
still needs *an* amount in two places -- the frozen lines produced at validation
and the import diff's "you are about to lose this much chiffrage" warning -- so
every entry point takes an :data:`AmountResolver` and only falls back to the
naive :func:`default_amount` below when the caller provides none.

``default_amount`` applies no inflation and no annual rate interpolation; the
real engine lives in ``waterfall.services.estimate_calculation`` and is plugged in
as a resolver since E14-07b (#364).

Two resolvers, not one, since E14-08 (#334): the validation of a revision needs
more than a total. A frozen line carries the annual rate and the inflation
coefficient it was computed with, and those only exist **per year**, so
:data:`BreakdownResolver` hands the domain one :class:`PricedYear` per year rather
than one number per facet. :data:`AmountResolver` stays exactly what it was and
keeps serving the callers that need a single figure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from waterfall.domain.revision.entities import CostFacet, CostNature, Project

#: How an amount is obtained from a cost facet. Injected, never hardcoded.
AmountResolver = Callable[[Project, CostFacet], Decimal]


def default_amount(project: Project, facet: CostFacet) -> Decimal:
    """Naive amount: ``quantity x hours x hourly_rate`` (MO) or ``quantity x unit_cost``."""
    if facet.nature is CostNature.LABOR:
        role = project.roles.get(facet.role_id) if facet.role_id is not None else None
        rate = role.hourly_rate if role is not None and role.hourly_rate is not None else Decimal(0)
        hours = facet.hours if facet.hours is not None else Decimal(0)
        return facet.quantity * hours * rate
    unit_cost = facet.unit_cost if facet.unit_cost is not None else Decimal(0)
    return facet.quantity * unit_cost


@dataclass(frozen=True)
class PricedYear:
    """One year's share of a cost facet, priced -- the grain a frozen line is cut at.

    The same grain as the calculation engine's ``PricedLine`` (E14-07b, #364): a
    labour facet borne by a task spanning two years produces **two** of these, each
    with its own annual rate and its own inflation coefficient; a disbursement
    produces exactly one. That is why :data:`BreakdownResolver` returns a sequence
    where :data:`AmountResolver` returned a scalar -- a single ``hourly_rate`` on a
    line straddling two years could only ever be a weighted average no rate table
    contains, and a frozen line is read years later against a ``wf_cost_rate`` row
    it has to match.

    Carries the *numbers* alone. Every label of a frozen line (the role's name, the
    accounting code, the bearing task's name) stays the domain's to copy, out of the
    :class:`Project` it already holds, so that injecting an engine never moves the
    decision of *what a frozen line says* out of the domain.

    ``amount`` is expected **in the unit the document publishes**, that is in euros
    at the cent: the resolver rounds each year's share on its own and the frozen
    lines are then additive by construction -- the rule #364 fixed for every
    published figure (``estimate_calculation.amount_at_the_cent``). The domain does
    not round, having no publication rule of its own to apply.
    """

    amount: Decimal
    year: int | None = None
    hours: Decimal | None = None
    hourly_rate: Decimal | None = None
    inflation_coefficient: Decimal | None = None


#: How the yearly breakdown of a cost facet is obtained. Injected, never hardcoded,
#: exactly like :data:`AmountResolver` -- which it does not replace: the entry points
#: that need *one number* (the chiffrage-loss warning of Rule 3) keep taking that one.
BreakdownResolver = Callable[[Project, CostFacet], Sequence[PricedYear]]


def default_breakdown(project: Project, facet: CostFacet) -> tuple[PricedYear, ...]:
    """The naive breakdown of :func:`default_amount`: one entry, no year spreading.

    Deliberately **not** the engine, for the same reason :func:`default_amount` is
    not: it applies no annual rate and no inflation, and it dates the single entry it
    produces by the facet's own forecast cash-out date, which is the only year a
    project with no rate table at all can name.
    """
    return (
        PricedYear(
            amount=default_amount(project, facet),
            year=None if facet.planned_date is None else facet.planned_date.year,
            hours=facet.hours,
            hourly_rate=None if facet.role_id is None else _role_rate(project, facet.role_id),
            inflation_coefficient=None,
        ),
    )


def _role_rate(project: Project, role_id: int) -> Decimal | None:
    role = project.roles.get(role_id)
    return None if role is None else role.hourly_rate
