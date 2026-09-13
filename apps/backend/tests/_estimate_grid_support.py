"""Shared helpers for tests that seed `EstimateCostLine`/`EstimateRoleAssignment`
rows directly via the ORM. Issue #289 (E12-07) made every such row require its
own `EstimateGridNode` (`node_id`, a NOT NULL unique FK) -- this factors that
one-off allocation out instead of duplicating it at every call site.

"Bypassing the create routes" stopped being a choice with E14-07 (#333): the
`POST .../estimates/{id}/cost-lines` and `.../role-assignments` families are gone,
replaced by the cost facet of a revision. The tests that still exercise the
calculation engine (#364) and the reconciliation import/export (#365) are about
those subjects, not about the route a row was born through, so they seed the rows
where they live -- here.

Deliberately not named `test_*.py` (see `_postgres_support.py`'s own docstring
for the same reasoning): pytest would otherwise try to import it as a test
module.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from waterfall.models.resources import CostCategory, CostType, EstimateCostLine, EstimateGridNode
from waterfall.services.estimate_grid import next_estimate_grid_node_uid


def seed_root_grid_node(session: Session, estimate_id: int, kind: str) -> int:
    """Insert one root-level `EstimateGridNode` for `estimate_id` and return its id.

    `kind` is `"cost_line"` or `"labor"`, matching `EstimateGridNode.kind`. Safe
    to call more than once for the same `estimate_id` within one test -- each
    call allocates its own `uid` (via the same `next_estimate_grid_node_uid`
    the production create routes use) and appends after any existing root node.
    """
    existing_root_count = (
        session.query(EstimateGridNode)
        .filter(
            EstimateGridNode.estimate_id == estimate_id,
            EstimateGridNode.parent_uid.is_(None),
        )
        .count()
    )
    node = EstimateGridNode(
        estimate_id=estimate_id,
        uid=next_estimate_grid_node_uid(session, estimate_id),
        parent_uid=None,
        position=existing_root_count + 1,
        kind=kind,
    )
    session.add(node)
    session.flush()
    return node.id


def seed_cost_line(
    session: Session,
    *,
    estimate_id: int,
    cost_category_id: int,
    label: str,
    quantity: str = "1.00",
    unit_cost: str = "0.00",
    task_id: int | None = None,
    cost_code_id: int | None = None,
    planned_date: datetime | None = None,
    supply_status: str | None = None,
) -> EstimateCostLine:
    """Insert one `EstimateCostLine` with its own root grid node, flushed not committed.

    Reproduces what the removed `POST .../cost-lines` route wrote, including the four
    denormalized columns (`cost_type_id`, `cost_type_code`, `accounting_code`,
    `category_code`) and `purchase_cost` -- the reconciliation export reads them back,
    so a row seeded without them is not the row the production code ever saw. The
    default `supply_status` follows the same rule the route applied: `planned` on a
    supply cost type, `None` otherwise.

    Two of those rules outlived the route and are still written in production, by the
    reconciliation import (`api/routes/estimates.py`): `_apply_cost_line_creates`
    computes `purchase_cost = quantity * unit_cost` and defaults `supply_status` to
    `"planned"` on a supply cost type, and `_apply_cost_line_updates` recomputes
    `purchase_cost` the same way. **Keep those two sites and this helper in sync**: if
    either formula ever gains a rounding rule or a coefficient, a helper still applying
    the old one would let the tests of #364/#365 keep passing on rows production can no
    longer produce.
    """
    category = session.query(CostCategory).filter(CostCategory.id == cost_category_id).one()
    cost_type = session.query(CostType).filter(CostType.id == category.cost_type_id).one()
    node_id = seed_root_grid_node(session, estimate_id, "cost_line")
    line = EstimateCostLine(
        estimate_id=estimate_id,
        task_id=task_id,
        cost_type_id=cost_type.id,
        cost_category_id=category.id,
        cost_code_id=cost_code_id,
        cost_type_code=cost_type.code,
        accounting_code=category.accounting_code,
        category_code=category.category_code,
        label=label,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        purchase_cost=Decimal(quantity) * Decimal(unit_cost),
        planned_date=planned_date,
        supply_status=(
            supply_status
            if supply_status is not None
            else ("planned" if cost_type.kind == "supply" else None)
        ),
        node_id=node_id,
    )
    session.add(line)
    session.flush()
    return line
