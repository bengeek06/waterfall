"""Builders shared by the revision-domain test bench (E14-02).

Deliberately not named ``test_*.py`` (see ``_estimate_grid_support.py`` for the
same reasoning): pytest would otherwise try to import it as a test module.

Three kinds of helper live here:

* sound builders (:func:`build_project`, :func:`build_draft`), which go through
  the domain operations and therefore always produce a valid state;
* raw builders (:func:`raw_node`, :func:`raw_link`), which write straight into
  the dataclasses, bypassing every guard. They exist for one purpose only:
  reproducing the *canonical violation* each invariant of
  ``docs/revision-v0.1-specification.md`` documents, so the checker can be caught
  failing to report it;
* le banc de planning (:func:`build_planning_bench`), qui monte un fichier MSPDI
  -- une fixture versionnée ou un volume généré, au choix de l'appelant -- dans
  une révision brouillon. C'est par lui que passe tout test ayant besoin d'un
  arbre profond et varié plutôt que du minuscule :func:`build_bench`. Les
  fichiers eux-mêmes vivent dans ``_mspdi_fixture_support``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from _mspdi_fixture_support import MspdiPlanning
from waterfall.domain.revision import (
    CalendarSource,
    CostFacet,
    CostNature,
    ImportedTask,
    NodeLink,
    PlanFacet,
    Project,
    ProjectRevision,
    RevisionKind,
    RevisionNode,
    Role,
    add_cost_line,
    add_link,
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


@dataclass
class PlanningBench:
    """Un projet dont la révision brouillon porte un planning MSPDI importé.

    C'est le banc de départ de tout test de domaine qui a besoin d'un arbre plus
    riche que :func:`build_bench` : plusieurs niveaux, des récapitulatifs, des
    jalons et des liens de précédence. La fixture ou le volume est choisi par
    l'appelant, ce module ne fait que le transformer en révision ::

        from _mspdi_fixture_support import HIERARCHY_MSPDI, read_mspdi_fixture
        from _revision_domain_support import build_planning_bench

        bench = build_planning_bench(read_mspdi_fixture(HIERARCHY_MSPDI))

    ``node_by_uid`` est la seule table de correspondance dont un test a besoin
    pour désigner une tâche par l'uid du fichier plutôt que par un id de nœud
    attribué à la volée.
    """

    project: Project
    revision: ProjectRevision
    node_by_uid: dict[int, int]
    planning: MspdiPlanning


def imported_tasks(planning: MspdiPlanning) -> list[ImportedTask]:
    """Traduire un planning lu en entrées de réimport, dans l'ordre du fichier."""
    return [
        ImportedTask(
            external_uid=task.uid,
            name=task.name,
            parent_external_uid=task.parent_uid,
            duration_minutes=task.duration_minutes,
            is_milestone=task.is_milestone,
            percent_complete=task.percent_complete,
        )
        for task in planning.tasks
    ]


def build_planning_bench(
    planning: MspdiPlanning, *, project: Project | None = None
) -> PlanningBench:
    """Monter ``planning`` dans une révision brouillon, en passant par les opérations.

    Rien n'est écrit en direct dans les dataclasses : chaque tâche passe par
    :func:`add_task` et chaque lien par :func:`add_link`, donc le banc obtenu est
    valide par construction et un banc qui ne se monterait pas serait déjà la
    preuve d'un défaut.
    """
    project = build_project() if project is None else project
    revision = build_draft(project)
    node_by_uid: dict[int, int] = {}
    for task in imported_tasks(planning):
        parent_id = (
            None if task.parent_external_uid is None else node_by_uid[task.parent_external_uid]
        )
        node = add_task(
            project,
            revision,
            name=task.name,
            parent_id=parent_id,
            external_uid=task.external_uid,
            duration_minutes=task.duration_minutes,
            is_milestone=task.is_milestone,
        )
        node_by_uid[task.external_uid] = node.id
    for link in planning.links:
        add_link(
            revision,
            node_id=node_by_uid[link.uid],
            predecessor_node_id=node_by_uid[link.predecessor_uid],
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
    return PlanningBench(
        project=project, revision=revision, node_by_uid=node_by_uid, planning=planning
    )
