"""Rule 1 of the specification: where a task's calendar comes from.

The calendar is an attribute of the planning facet, initialised to the project
calendar when the node is created and refreshed from a role on assignment. It is
never derived at read time from the roles -- an unpriced task must stay datable
(INV-15).

Precedence ``manual`` > ``role`` > ``project``: only a facet whose
``calendar_source`` is ``project`` or ``role`` may be rewritten automatically.
The resynchronisation takes the calendar of the role of the first MO facet, in
depth-first order of the task's subtree, whose role carries a calendar; failing
that it falls back to the project calendar with source ``project``.
"""

from __future__ import annotations

from waterfall.domain.revision.entities import (
    CalendarSource,
    CostNature,
    Project,
    ProjectRevision,
)
from waterfall.domain.revision.structure import ancestors_of, depth_first, is_plan_node


def resynchronize_task_calendar(
    project: Project, revision: ProjectRevision, task_node_id: int
) -> None:
    """Reapply Rule 1 to one task node. A ``manual`` calendar is left untouched."""
    facet = revision.plan_facets.get(task_node_id)
    if facet is None or facet.calendar_source is CalendarSource.MANUAL:
        return

    for node in depth_first(revision, task_node_id):
        cost = revision.cost_facets.get(node.id)
        if cost is None or cost.nature is not CostNature.LABOR or cost.role_id is None:
            continue
        role = project.roles.get(cost.role_id)
        if role is not None and role.calendar_id is not None:
            facet.calendar_id = role.calendar_id
            facet.calendar_source = CalendarSource.ROLE
            return

    facet.calendar_id = project.calendar_id
    facet.calendar_source = CalendarSource.PROJECT


def resynchronize_from_node(project: Project, revision: ProjectRevision, node_id: int) -> None:
    """Reapply Rule 1 to every task whose subtree contains ``node_id``.

    Called after any change to the set of MO assignments carried by a subtree:
    an assignment added, modified or removed, and also a node moved -- a move
    changes the subtree of both the old and the new ancestors.
    """
    if is_plan_node(revision, node_id):
        resynchronize_task_calendar(project, revision, node_id)
    for ancestor in ancestors_of(revision, node_id):
        if is_plan_node(revision, ancestor.id):
            resynchronize_task_calendar(project, revision, ancestor.id)
