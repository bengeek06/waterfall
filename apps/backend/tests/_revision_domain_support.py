"""Builders shared by the revision-domain test bench (E14-02).

Deliberately not named ``test_*.py`` (see ``_estimate_grid_support.py`` for the
same reasoning): pytest would otherwise try to import it as a test module.

Two kinds of helper live here:

* sound builders (:func:`build_project`, :func:`build_draft`), which go through
  the domain operations and therefore always produce a valid state;
* raw builders (:func:`raw_node`, :func:`raw_link`), which write straight into
  the dataclasses, bypassing every guard. They exist for one purpose only:
  reproducing the *canonical violation* each invariant of
  ``docs/revision-v0.1-specification.md`` documents, so the checker can be caught
  failing to report it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from waterfall.domain.revision import (
    CalendarSource,
    CostFacet,
    CostNature,
    NodeLink,
    PlanFacet,
    Project,
    ProjectRevision,
    RevisionKind,
    RevisionNode,
    Role,
    add_cost_line,
    add_task,
    check_invariants,
    create_revision,
    violated_invariant_ids,
)

PROJECT_CALENDAR_ID = 1
ROLE_CALENDAR_ID = 2


def build_project(project_id: int = 1) -> Project:
    """A project with a default calendar, two roles and one cost category."""
    return Project(
        id=project_id,
        name=f"Project {project_id}",
        calendar_id=PROJECT_CALENDAR_ID,
        roles={
            1: Role(
                id=1,
                name="Ingénieur",
                calendar_id=ROLE_CALENDAR_ID,
                category_code="MO-ENG",
                accounting_code="641000",
                hourly_rate=Decimal("80.00"),
            ),
            2: Role(
                id=2,
                name="Technicien",
                calendar_id=None,
                category_code="MO-TEC",
                accounting_code="641100",
                hourly_rate=Decimal("55.00"),
            ),
        },
        cost_categories={10: "ACH-STD"},
    )


def build_draft(project: Project, kind: RevisionKind = RevisionKind.INITIAL) -> ProjectRevision:
    """An empty draft revision of ``project``."""
    return create_revision(project, kind=kind)


@dataclass
class Bench:
    """A tiny but complete revision, used by most invariant tests.

    ``root_a`` (task) > ``child_b`` (task) > ``labor`` (MO cost line);
    ``root_a`` > ``supply`` (non-MO cost line); ``root_c`` (task);
    ``global_cost`` (non-MO cost line at the root, no bearing task).
    """

    project: Project
    revision: ProjectRevision
    root_a: int
    child_b: int
    root_c: int
    labor: int
    supply: int
    global_cost: int


def build_bench() -> Bench:
    """Build :class:`Bench` through the domain operations only."""
    project = build_project()
    revision = build_draft(project)
    root_a = add_task(project, revision, name="A", duration_minutes=480)
    child_b = add_task(project, revision, name="B", parent_id=root_a.id, duration_minutes=240)
    labor = add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Étude",
        parent_id=child_b.id,
        role_id=1,
        hours=Decimal("10"),
    )
    supply = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Câblage",
        parent_id=root_a.id,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("120.00"),
        quantity=Decimal("3"),
    )
    root_c = add_task(project, revision, name="C", duration_minutes=120)
    global_cost = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Assurance chantier",
        cost_type_id=2,
        cost_category_id=10,
        unit_cost=Decimal("5000.00"),
    )
    return Bench(
        project=project,
        revision=revision,
        root_a=root_a.id,
        child_b=child_b.id,
        root_c=root_c.id,
        labor=labor.id,
        supply=supply.id,
        global_cost=global_cost.id,
    )


def raw_node(
    project: Project,
    revision: ProjectRevision,
    *,
    work_item_id: int,
    parent_id: int | None = None,
    position: int = 1,
    plan: PlanFacet | None = None,
    cost: CostFacet | None = None,
) -> RevisionNode:
    """Insert a node writing straight into the state, bypassing every guard."""
    node = RevisionNode(
        id=project.next_node_id,
        revision_id=revision.id,
        work_item_id=work_item_id,
        parent_id=parent_id,
        position=position,
    )
    project.next_node_id += 1
    revision.nodes[node.id] = node
    if plan is not None:
        plan.node_id = node.id
        revision.plan_facets[node.id] = plan
    if cost is not None:
        cost.node_id = node.id
        revision.cost_facets[node.id] = cost
    return node


def raw_link(revision: ProjectRevision, node_id: int, predecessor_node_id: int) -> None:
    """Append a precedence link bypassing every guard."""
    revision.links.append(NodeLink(node_id=node_id, predecessor_node_id=predecessor_node_id))


def plan_facet(name: str = "Raw task") -> PlanFacet:
    """A valid planning facet (calendar set, source ``project``)."""
    return PlanFacet(
        node_id=0,
        name=name,
        calendar_id=PROJECT_CALENDAR_ID,
        calendar_source=CalendarSource.PROJECT,
    )


def cost_facet(label: str = "Raw cost") -> CostFacet:
    """A valid non-labour cost facet."""
    return CostFacet(
        node_id=0,
        nature=CostNature.NON_LABOR,
        label=label,
        quantity=Decimal("1"),
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("10.00"),
    )


def violations_of(project: Project, revision: ProjectRevision) -> list[str]:
    """Identifiers of every state-scoped invariant ``revision`` violates."""
    return violated_invariant_ids(check_invariants(project, revision))


def assert_sound(project: Project, revision: ProjectRevision) -> None:
    """Fail with the full detail if any state-scoped invariant is violated."""
    violations = check_invariants(project, revision)
    assert not violations, "; ".join(str(violation) for violation in violations)
