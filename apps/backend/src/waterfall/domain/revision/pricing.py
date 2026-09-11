"""Amount resolution for the test bench -- deliberately *not* the calculation engine.

The specification is explicit: MO/Achat/PRU amounts are **derived**, computed by
the calculation engine from annual rates and inflation coefficients, and are
neither attributes of the cost facet nor invariants of the model. The domain
still needs *an* amount in two places -- the frozen lines produced at validation
and the import diff's "you are about to lose this much chiffrage" warning -- so
every entry point takes an :data:`AmountResolver` and only falls back to the
naive :func:`default_amount` below when the caller provides none.

``default_amount`` applies no inflation and no annual rate interpolation; the
real engine lives in ``waterfall.services.estimate_calculation`` and will be
plugged in as a resolver by E14-07.
"""

from __future__ import annotations

from collections.abc import Callable
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
