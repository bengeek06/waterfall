"""Facet edits: the attribute-level writes of a revision.

Deliberately expressed as explicit, typed operations rather than a generic
"patch these fields" helper, so that each one can enforce its own contract --
the labour/non-labour attribute sets (INV-19, INV-20), the always-present
calendar (INV-15), and above all the immutability of a validated revision
(INV-03), which applies to *both* facets with the same error.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from waterfall.domain.revision.calendar_rule import (
    resynchronize_from_node,
    resynchronize_task_calendar,
)
from waterfall.domain.revision.entities import (
    CalendarSource,
    CostFacet,
    CostNature,
    PlanFacet,
    Project,
    ProjectRevision,
    SupplyStatus,
)
from waterfall.domain.revision.errors import FacetContractError, NotFoundError
from waterfall.domain.revision.guards import require_draft, touch
from waterfall.domain.revision.invariants import check_cost_facet_shape


def _plan_facet(revision: ProjectRevision, node_id: int) -> PlanFacet:
    facet = revision.plan_facets.get(node_id)
    if facet is None:
        raise NotFoundError(f"Node {node_id} carries no planning facet in revision {revision.id}")
    return facet


def _cost_facet(revision: ProjectRevision, node_id: int) -> CostFacet:
    facet = revision.cost_facets.get(node_id)
    if facet is None:
        raise NotFoundError(f"Node {node_id} carries no cost facet in revision {revision.id}")
    return facet


def _reject_invalid_cost_facet(node_id: int, facet: CostFacet) -> None:
    violations = check_cost_facet_shape(node_id, facet)
    if violations:
        raise FacetContractError("; ".join(str(violation) for violation in violations))


def rename_task(revision: ProjectRevision, node_id: int, name: str) -> None:
    """Rename a task inside this revision only -- the ``work_item`` carries no label."""
    require_draft(revision)
    _plan_facet(revision, node_id).name = name
    touch(revision)


def set_task_duration(
    revision: ProjectRevision, node_id: int, duration_minutes: int | None
) -> None:
    """Set a task's duration. Dates are the scheduling engine's business, not the tree's."""
    require_draft(revision)
    _plan_facet(revision, node_id).duration_minutes = duration_minutes
    touch(revision)


def set_task_dates(
    revision: ProjectRevision,
    node_id: int,
    *,
    start_at: datetime | None,
    finish_at: datetime | None,
) -> None:
    """Store a task's start/finish as given (no recalculation happens in this module)."""
    require_draft(revision)
    facet = _plan_facet(revision, node_id)
    facet.start_at = start_at
    facet.finish_at = finish_at
    touch(revision)


def set_task_calendar_manually(revision: ProjectRevision, node_id: int, calendar_id: int) -> None:
    """Pin a task's calendar explicitly: ``calendar_source`` becomes ``manual`` (Rule 1)."""
    require_draft(revision)
    facet = _plan_facet(revision, node_id)
    facet.calendar_id = calendar_id
    facet.calendar_source = CalendarSource.MANUAL
    touch(revision)


def clear_task_calendar_override(project: Project, revision: ProjectRevision, node_id: int) -> None:
    """Drop an explicit calendar choice and fall back to the automatic behaviour (Rule 1)."""
    require_draft(revision)
    facet = _plan_facet(revision, node_id)
    facet.calendar_source = CalendarSource.PROJECT
    resynchronize_task_calendar(project, revision, node_id)
    touch(revision)


def assign_role(
    project: Project,
    revision: ProjectRevision,
    node_id: int,
    *,
    role_id: int,
    hours: Decimal,
) -> None:
    """Set the role and hours of an MO cost line, then reapply Rule 1 to its ancestors."""
    require_draft(revision)
    facet = _cost_facet(revision, node_id)
    candidate = replace(facet, role_id=role_id, hours=hours)
    _reject_invalid_cost_facet(node_id, candidate)
    facet.role_id = role_id
    facet.hours = hours
    resynchronize_from_node(project, revision, node_id)
    touch(revision)


def set_cost_quantity(revision: ProjectRevision, node_id: int, quantity: Decimal) -> None:
    """Set the multiplier of a cost line, on either nature."""
    require_draft(revision)
    _cost_facet(revision, node_id).quantity = quantity
    touch(revision)


def set_cost_hours(revision: ProjectRevision, node_id: int, hours: Decimal) -> None:
    """Set the hours of an MO cost line -- the very write a RAE entry performs."""
    require_draft(revision)
    facet = _cost_facet(revision, node_id)
    candidate = replace(facet, hours=hours)
    _reject_invalid_cost_facet(node_id, candidate)
    facet.hours = hours
    touch(revision)


def set_cost_unit_cost(revision: ProjectRevision, node_id: int, unit_cost: Decimal) -> None:
    """Set the unit débours of a non-MO cost line."""
    require_draft(revision)
    facet = _cost_facet(revision, node_id)
    candidate = replace(facet, unit_cost=unit_cost)
    _reject_invalid_cost_facet(node_id, candidate)
    facet.unit_cost = unit_cost
    touch(revision)


def set_cost_label(revision: ProjectRevision, node_id: int, label: str) -> None:
    """Relabel a cost line inside this revision only."""
    require_draft(revision)
    _cost_facet(revision, node_id).label = label
    touch(revision)


def set_supply_status(revision: ProjectRevision, node_id: int, supply_status: SupplyStatus) -> None:
    """Advance the supply follow-up status of a non-MO cost line.

    The specification reserves ``supply_status`` to supplies: an MO line has a
    role and hours, never an order to follow up.
    """
    require_draft(revision)
    facet = _cost_facet(revision, node_id)
    if facet.nature is not CostNature.NON_LABOR:
        raise FacetContractError(
            f"Cost facet of node {node_id} is of nature {facet.nature.value}: supply_status "
            "belongs to a non-labor line only"
        )
    facet.supply_status = supply_status
    touch(revision)


def set_cost_planned_date(
    revision: ProjectRevision, node_id: int, planned_date: date | None
) -> None:
    """Set the forecast cash-out date of a cost line.

    Independent of the bearing task's dates, and the sole source of the ``year``
    a frozen line carries once the revision is validated.
    """
    require_draft(revision)
    _cost_facet(revision, node_id).planned_date = planned_date
    touch(revision)


def set_cost_comment(revision: ProjectRevision, node_id: int, comment: str | None) -> None:
    """Set the free-text comment of a cost line, inside this revision only."""
    require_draft(revision)
    _cost_facet(revision, node_id).comment = comment
    touch(revision)
