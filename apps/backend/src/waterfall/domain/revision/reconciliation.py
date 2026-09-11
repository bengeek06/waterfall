"""Reconciliation of a forecast (RAE) against its reference budget, by identity.

Rule 2 of the specification: a frozen line carries the ``work_item`` identity of
what it prices, and nothing mutable. Comparing "reste à engager" to "budget de
référence" therefore joins the two sides on ``work_item_id`` alone -- which is
exactly what replaces the never-created ``EstimateCostLine.source_line_id``.

No new attribute and no new table are needed to enter a RAE: it is the same cost
facet, on a revision of kind ``forecast_remaining``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from waterfall.domain.revision.entities import Project, ProjectRevision
from waterfall.domain.revision.pricing import AmountResolver, default_amount


@dataclass(frozen=True)
class ReconciliationEntry:
    """One element of work, seen from the budget and from the forecast."""

    work_item_id: int
    budget_amount: Decimal | None
    forecast_amount: Decimal | None

    @property
    def variance(self) -> Decimal:
        """Forecast minus budget, missing side counted as zero."""
        budget = self.budget_amount if self.budget_amount is not None else Decimal(0)
        forecast = self.forecast_amount if self.forecast_amount is not None else Decimal(0)
        return forecast - budget


def reconcile_forecast_to_budget(
    project: Project,
    *,
    budget: ProjectRevision,
    forecast: ProjectRevision,
    amount_of: AmountResolver = default_amount,
) -> list[ReconciliationEntry]:
    """Join the frozen lines of ``budget`` with the cost facets of ``forecast``.

    The join key is ``work_item_id`` and nothing else: no node id, no facet id,
    no pointer chain between revisions. ``budget`` keeps working even if every
    draft of the project has been deleted in the meantime.
    """
    budget_amounts: dict[int, Decimal] = {}
    for line in budget.frozen_lines:
        budget_amounts[line.work_item_id] = (
            budget_amounts.get(line.work_item_id, Decimal(0)) + line.amount
        )

    forecast_amounts: dict[int, Decimal] = {}
    for node_id, facet in forecast.cost_facets.items():
        node = forecast.nodes.get(node_id)
        if node is None:
            continue
        forecast_amounts[node.work_item_id] = forecast_amounts.get(
            node.work_item_id, Decimal(0)
        ) + amount_of(project, facet)

    return [
        ReconciliationEntry(
            work_item_id=work_item_id,
            budget_amount=budget_amounts.get(work_item_id),
            forecast_amount=forecast_amounts.get(work_item_id),
        )
        for work_item_id in sorted(set(budget_amounts) | set(forecast_amounts))
    ]
