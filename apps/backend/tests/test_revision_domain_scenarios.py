"""The nine real scenarios the revision model has to survive (E14-02).

Each scenario replays a real sequence of operations and calls the invariant
checker **after every step**, not only at the end. Nothing here relaxes an
invariant to make a scenario pass: a scenario that could only pass by loosening
one would mean the specification is wrong, not the test.

Le planning que le banc exerce est **généré**, pas lu d'un fichier du poste :
``generate_mspdi`` produit un arbre profond, large, avec récapitulatifs, jalons
et liens de précédence, dont le volume et la profondeur sont déclarés ici en
toutes lettres. Un banc d'essai qui ne s'exécuterait que sur une machine
particulière ne prouverait rien -- celui-ci tourne en CI, sur un document que le
test fabrique lui-même.

La lecture du MSPDI reste en dehors du domaine (elle vit dans
``_mspdi_fixture_support``) : le domaine ne connaît pas MS Project, seulement un
``external_uid`` que la couche d'import lui tend.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from _mspdi_fixture_support import MspdiPlanning, generate_mspdi, read_mspdi
from _revision_domain_support import (
    PlanningBench,
    assert_sound,
    build_draft,
    build_planning_bench,
    build_project,
    imported_tasks,
)
from waterfall.domain.revision import (
    BreakdownEntry,
    BreakdownKind,
    CostNature,
    ImmutableRevisionError,
    ImportedTask,
    ProjectRevision,
    ProjectStatus,
    RevisionKind,
    RevisionStatus,
    SupplyStatus,
    WorkBreakdownError,
    add_cost_line,
    add_task,
    apply_reimport,
    bearing_work_item_id,
    can_regenerate_skeleton,
    children_of,
    copy_revision,
    delete_nodes,
    depth_first,
    generate_skeleton,
    indent_nodes,
    move_nodes,
    node_by_work_item,
    plan_reimport,
    reconcile_forecast_to_budget,
    regenerate_skeleton,
    save_work_breakdown,
    subtree_ids,
    validate_revision,
)
from waterfall.domain.revision.facets import rename_task, set_cost_hours
from waterfall.domain.revision.pricing import default_amount
from waterfall.domain.revision.structure import is_milestone_node

#: Le planning de référence du banc. Déclaré ici plutôt que lu d'un fichier : ces
#: trois nombres *sont* ce que les scénarios exercent, et un test peut les
#: assertir au lieu de faire confiance au contenu d'un fichier qu'il n'écrit pas.
#:
#: 300 tâches sur 6 niveaux avec 3 enfants par récapitulatif : assez large pour
#: qu'un récapitulatif ait toujours plusieurs frères sous lui (scénario 4 en
#: indente un derrière un autre), assez profond pour qu'une tâche ait toujours un
#: nœud intermédiaire au-dessus d'elle (scénario 5 le supprime), assez rapide pour
#: que le module entier reste de l'ordre de la seconde. Le test de charge va bien
#: plus haut, c'est son rôle et non celui du banc fonctionnel.
REFERENCE_TASK_COUNT = 300
REFERENCE_DEPTH = 6
REFERENCE_BRANCHING = 3
#: Une feuille sur cinq est un jalon, une sur deux porte un lien de précédence --
#: et ces liens passent par les quatre types MSPDI, avec décalage positif, négatif
#: et nul (voir ``_LINK_TYPE_CYCLE`` dans ``_mspdi_fixture_support``).
REFERENCE_MILESTONE_EVERY = 5
REFERENCE_LINK_EVERY = 2

#: Le volume du test de charge : nettement plus gros et plus profond que le banc
#: fonctionnel, et toujours fabriqué à la volée. 1500 tâches sur 7 niveaux, c'est
#: plus que ce que porte le plus gros planning réel connu du projet, sans qu'un
#: seul octet de celui-ci n'entre dans le dépôt. Repère de coût : moins d'une
#: seconde, construction de l'arbre et vérification complète des invariants
#: comprises.
VOLUME_TASK_COUNT = 1500
VOLUME_DEPTH = 7

REFERENCE_MSPDI = generate_mspdi(
    task_count=REFERENCE_TASK_COUNT,
    depth=REFERENCE_DEPTH,
    branching=REFERENCE_BRANCHING,
    milestone_every=REFERENCE_MILESTONE_EVERY,
    link_every=REFERENCE_LINK_EVERY,
    name="Banc d'essai du modèle de révision",
    guid="BENCH-REVISION-0001",
)

# Always passed in: the domain never reads a clock.
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _tree_depth(revision: ProjectRevision) -> int:
    """Profondeur réelle de l'arbre monté, comptée en remontant les parents."""
    depths: dict[int, int] = {}
    for node in depth_first(revision):
        parent_id = node.parent_id
        depths[node.id] = 1 if parent_id is None else depths[parent_id] + 1
    return max(depths.values(), default=0)


@pytest.fixture(scope="module")
def reference_planning() -> MspdiPlanning:
    """Le document généré, lu une fois pour tout le module."""
    return read_mspdi(REFERENCE_MSPDI)


@pytest.fixture(scope="module")
def shared_planning(reference_planning: MspdiPlanning) -> PlanningBench:
    return build_planning_bench(reference_planning)


@pytest.fixture
def planning(shared_planning: PlanningBench) -> PlanningBench:
    """A private copy of the imported planning, so a scenario can mutate it freely."""
    return copy.deepcopy(shared_planning)


@dataclass
class Estimate:
    """The planning bench plus a small estimate built on top of it."""

    bench: PlanningBench
    task_x: int
    task_y: int
    task_z: int
    labor_x: int
    supply_x: int
    labor_y: int
    global_cost: int


def _leaf_task_ids(bench: PlanningBench) -> list[int]:
    """Leaf tasks that hang under a parent and can bear a cost line, depth-first.

    Root-level leaves are excluded so that a scenario always has an intermediate
    node above the task it works on (scenario 5 deletes exactly that node).

    Milestones are excluded too, and for a rule rather than for convenience: a
    jalon carries no child at all, cost line included (INV-27). Le planning de
    référence en est truffé (une feuille sur cinq), donc ce filtre est ce qui
    garde les scénarios sur le modèle au lieu de les faire dépendre de la case où
    le générateur a posé un jalon.

    Asked through ``is_milestone_node`` and not by indexing ``plan_facets``:
    ``depth_first`` walks *every* node, cost facets included, so the index would
    be total only as long as this stays called before the first ``add_cost_line``
    -- a positional safety that a second call, or a moved one, would turn into a
    ``KeyError``.
    """
    revision = bench.revision
    return [
        node.id
        for node in depth_first(revision)
        if node.parent_id is not None
        and not children_of(revision, node.id)
        and not is_milestone_node(revision, node.id)
    ]


def _build_estimate(bench: PlanningBench) -> Estimate:
    """Scenario 2: non-MO lines under tasks, MO lines with role and hours, one root line."""
    project, revision = bench.project, bench.revision
    leaves = _leaf_task_ids(bench)
    task_x, task_y, task_z = leaves[0], leaves[1], leaves[40]

    labor_x = add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Étude de faisabilité",
        parent_id=task_x,
        role_id=1,
        hours=Decimal("120"),
    )
    supply_x = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Baie 19 pouces",
        parent_id=task_x,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("2400.00"),
        quantity=Decimal("2"),
        supply_status=SupplyStatus.PLANNED,
        cost_code_id=77,
    )
    labor_y = add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Intégration",
        parent_id=task_y,
        role_id=2,
        hours=Decimal("64"),
    )
    global_cost = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Assurance projet",
        cost_type_id=2,
        cost_category_id=10,
        unit_cost=Decimal("18000.00"),
    )
    return Estimate(
        bench=bench,
        task_x=task_x,
        task_y=task_y,
        task_z=task_z,
        labor_x=labor_x.id,
        supply_x=supply_x.id,
        labor_y=labor_y.id,
        global_cost=global_cost.id,
    )


@pytest.fixture(scope="module")
def shared_estimate(shared_planning: PlanningBench) -> Estimate:
    return _build_estimate(copy.deepcopy(shared_planning))


@pytest.fixture
def estimate(shared_estimate: Estimate) -> Estimate:
    return copy.deepcopy(shared_estimate)


# --------------------------------------------------------------------------------------
# Scenario 1 -- import a deep, varied planning as a tree of nodes
# --------------------------------------------------------------------------------------


def test_scenario_1_a_deep_planning_imports_as_a_tree_of_nodes(
    reference_planning: MspdiPlanning,
    planning: PlanningBench,
) -> None:
    """Le document entier devient un arbre, dans son ordre et à sa profondeur.

    Les nombres asservis ne sont pas des constantes magiques mais les paramètres
    déclarés du générateur : si le banc cessait d'exercer la profondeur ou la
    variété qu'il annonce, c'est ici que cela se verrait.
    """
    tasks = reference_planning.tasks
    project, revision = planning.project, planning.revision

    assert len(tasks) == REFERENCE_TASK_COUNT
    assert len(revision.nodes) == REFERENCE_TASK_COUNT
    assert len(revision.plan_facets) == REFERENCE_TASK_COUNT
    assert not revision.cost_facets

    # L'arbre monté a bien la profondeur du fichier, et elle est réellement > 2 :
    # sans cela les scénarios 4 et 5 n'auraient pas de nœud intermédiaire à saisir.
    assert reference_planning.max_outline_level() == REFERENCE_DEPTH
    assert _tree_depth(revision) == REFERENCE_DEPTH
    # Et il est varié : des récapitulatifs, des feuilles, des jalons, et des liens
    # qui ne sont pas tous des fin-à-début à décalage nul.
    assert len(reference_planning.leaf_uids()) < REFERENCE_TASK_COUNT
    assert len(reference_planning.milestone_uids()) > 1
    assert len({link.link_type for link in reference_planning.links}) == 4
    assert any(link.lag_tenth_minute < 0 for link in reference_planning.links)
    assert any(link.lag_tenth_minute > 0 for link in reference_planning.links)
    # Les uids du fichier sont épars et non triés, comme MS Project les écrit : le
    # nœud est retrouvé par son ``external_uid`` et jamais par le rang de sa ligne.
    uids = [task.uid for task in tasks]
    assert uids != sorted(uids)
    assert max(uids) > REFERENCE_TASK_COUNT

    # Depth-first display order is exactly the order of the source file.
    ordered = depth_first(revision)
    assert [revision.plan_facets[node.id].name for node in ordered] == [task.name for task in tasks]
    assert [node.id for node in ordered] == [planning.node_by_uid[task.uid] for task in tasks]

    # Every precedence link of the file is a node -> node link of this revision.
    assert len(revision.links) == len(reference_planning.links) > 1
    assert_sound(project, revision)


def test_scenario_1_the_tree_holds_a_larger_and_deeper_planning() -> None:
    """La charge et la profondeur, sur un document bien plus gros que le banc.

    C'est ce qui remplace l'ancien scénario « importer le vrai fichier client de
    542 tâches » : la propriété qui avait de la valeur n'était pas que *ce*
    fichier-là passe, mais que l'arbre tienne le volume et la profondeur. Le
    document est fabriqué ici, donc rien de gros n'entre dans le dépôt et la CI
    l'exécute comme le poste.

    Toutes les opérations d'arbre sont rejouées à cette échelle -- et l'invariant
    complet est vérifié après chacune, pas seulement à la fin.
    """
    planning = read_mspdi(
        generate_mspdi(
            task_count=VOLUME_TASK_COUNT,
            depth=VOLUME_DEPTH,
            branching=3,
            milestone_every=7,
            link_every=4,
            name="Planning de charge",
            guid="BENCH-REVISION-VOLUME-01",
        )
    )
    bench = build_planning_bench(planning)
    project, revision = bench.project, bench.revision

    assert len(revision.nodes) == VOLUME_TASK_COUNT
    assert len(revision.plan_facets) == VOLUME_TASK_COUNT
    assert _tree_depth(revision) == VOLUME_DEPTH
    assert len(revision.links) == len(planning.links) > 1
    # Le parcours préfixe visite tout l'arbre, sans dépendre de la pile d'appels.
    assert len(depth_first(revision)) == VOLUME_TASK_COUNT
    assert_sound(project, revision)

    # Déplacer une branche entière depuis la profondeur maximale vers la racine.
    deepest = next(
        node.id
        for node in depth_first(revision)
        if node.parent_id is not None and children_of(revision, node.id)
    )
    moved = subtree_ids(revision, deepest)
    move_nodes(project, revision, [deepest], target_parent_id=None)
    assert_sound(project, revision)
    assert revision.nodes[deepest].parent_id is None
    assert set(subtree_ids(revision, deepest)) == set(moved)

    # Puis supprimer un sous-arbre profond : tout part, et rien d'autre.
    doomed = set(subtree_ids(revision, deepest))
    assert len(doomed) > 1
    report = delete_nodes(project, revision, [deepest])
    assert_sound(project, revision)
    assert set(report.removed_node_ids) == doomed
    assert len(revision.nodes) == VOLUME_TASK_COUNT - len(doomed)
    assert not doomed & set(revision.nodes)


# --------------------------------------------------------------------------------------
# Scenario 2 -- build an estimate on that tree
# --------------------------------------------------------------------------------------


def test_scenario_2_estimate_lines_hang_on_the_same_tree(estimate: Estimate) -> None:
    project, revision = estimate.bench.project, estimate.bench.revision

    assert len(revision.nodes) == REFERENCE_TASK_COUNT + 4
    assert len(revision.cost_facets) == 4
    # A non-MO line and an MO line under a task, resolving to it as bearing task.
    assert bearing_work_item_id(revision, estimate.labor_x) == (
        revision.nodes[estimate.task_x].work_item_id
    )
    assert bearing_work_item_id(revision, estimate.supply_x) == (
        revision.nodes[estimate.task_x].work_item_id
    )
    # A cost line at the root: a global project cost with no bearing task.
    assert revision.nodes[estimate.global_cost].parent_id is None
    assert bearing_work_item_id(revision, estimate.global_cost) is None
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# Scenario 3 -- move a cost line under another task
# --------------------------------------------------------------------------------------


def test_scenario_3_moving_a_cost_line_changes_only_its_bearing_task(
    estimate: Estimate,
) -> None:
    project, revision = estimate.bench.project, estimate.bench.revision
    facet_before = copy.deepcopy(revision.cost_facets[estimate.supply_x])
    amount_before = default_amount(project, revision.cost_facets[estimate.supply_x])
    assert bearing_work_item_id(revision, estimate.supply_x) == (
        revision.nodes[estimate.task_x].work_item_id
    )

    move_nodes(project, revision, [estimate.supply_x], target_parent_id=estimate.task_z)
    assert_sound(project, revision)

    assert bearing_work_item_id(revision, estimate.supply_x) == (
        revision.nodes[estimate.task_z].work_item_id
    )
    facet_after = revision.cost_facets[estimate.supply_x]
    assert facet_after == facet_before
    assert default_amount(project, facet_after) == amount_before
    assert revision.nodes[estimate.supply_x].parent_id == estimate.task_z


def test_scenario_3_moving_an_mo_line_keeps_its_role_and_hours(estimate: Estimate) -> None:
    project, revision = estimate.bench.project, estimate.bench.revision
    before = copy.deepcopy(revision.cost_facets[estimate.labor_x])

    move_nodes(project, revision, [estimate.labor_x], target_parent_id=estimate.task_y)
    assert_sound(project, revision)

    after = revision.cost_facets[estimate.labor_x]
    assert (after.role_id, after.hours, after.quantity) == (
        before.role_id,
        before.hours,
        before.quantity,
    )
    assert bearing_work_item_id(revision, estimate.labor_x) == (
        revision.nodes[estimate.task_y].work_item_id
    )


# --------------------------------------------------------------------------------------
# Scenario 4 -- move and indent a task, its cost lines follow
# --------------------------------------------------------------------------------------


def test_scenario_4_moving_and_indenting_a_task_carries_its_cost_lines(
    estimate: Estimate,
) -> None:
    project, revision = estimate.bench.project, estimate.bench.revision
    task = estimate.task_x
    plan_before = copy.deepcopy(revision.plan_facets[task])
    links_before = sorted(
        (link.node_id, link.predecessor_node_id, link.link_type)
        for link in revision.links
        if task in (link.node_id, link.predecessor_node_id)
    )
    costs_before = {
        node_id: copy.deepcopy(revision.cost_facets[node_id])
        for node_id in subtree_ids(revision, task)
        if node_id in revision.cost_facets
    }
    assert costs_before

    # Move it under the summary task holding task_z, as its last child...
    target_parent = revision.nodes[estimate.task_z].parent_id
    assert target_parent is not None
    move_nodes(project, revision, [task], target_parent_id=target_parent)
    assert_sound(project, revision)
    siblings = children_of(revision, target_parent)
    assert len(siblings) > 1 and siblings[-1].id == task
    preceding_sibling = siblings[-2].id

    # ... then indent it one level, under that preceding sibling.
    indent_nodes(project, revision, [task])
    assert_sound(project, revision)
    assert revision.nodes[task].parent_id == preceding_sibling

    assert revision.plan_facets[task] == plan_before
    assert (
        sorted(
            (link.node_id, link.predecessor_node_id, link.link_type)
            for link in revision.links
            if task in (link.node_id, link.predecessor_node_id)
        )
        == links_before
    )
    for node_id, facet in costs_before.items():
        assert node_id in subtree_ids(revision, task)
        assert revision.cost_facets[node_id] == facet


# --------------------------------------------------------------------------------------
# Scenario 5 -- delete an intermediate node
# --------------------------------------------------------------------------------------


def test_scenario_5_deleting_an_intermediate_node_removes_the_whole_subtree(
    estimate: Estimate,
) -> None:
    project, revision = estimate.bench.project, estimate.bench.revision
    intermediate = revision.nodes[estimate.task_x].parent_id
    assert intermediate is not None
    doomed = subtree_ids(revision, intermediate)
    assert len(doomed) > 1
    doomed_costs = {node_id for node_id in doomed if node_id in revision.cost_facets}
    assert doomed_costs
    kept = len(revision.nodes) - len(doomed)

    report = delete_nodes(project, revision, [intermediate])
    assert_sound(project, revision)

    assert len(revision.nodes) == kept
    assert set(report.removed_node_ids) == set(doomed)
    for node_id in doomed:
        assert node_id not in revision.nodes
        assert node_id not in revision.plan_facets
        assert node_id not in revision.cost_facets
        assert not [
            link for link in revision.links if node_id in (link.node_id, link.predecessor_node_id)
        ]
    # The safeguard named every cost line the deletion took away.
    assert {loss.node_id for loss in report.cost_losses} == doomed_costs
    assert {estimate.labor_x, estimate.supply_x} <= doomed_costs


# --------------------------------------------------------------------------------------
# Scenario 6 -- a new revision from a validated one, edited without touching the source
# --------------------------------------------------------------------------------------


def test_scenario_6_editing_a_copy_never_touches_the_validated_source(
    estimate: Estimate,
) -> None:
    project, source = estimate.bench.project, estimate.bench.revision
    validate_revision(project, source, now=NOW)
    assert_sound(project, source)
    assert source.status is RevisionStatus.VALIDATED
    source_snapshot = copy.deepcopy(source)

    draft = copy_revision(project, source, now=NOW)
    assert_sound(project, draft)
    assert draft.status is RevisionStatus.DRAFT
    assert draft.source_revision_id == source.id

    # Free edits on the draft: rename, move, delete, add, re-price.
    first_task = next(node for node in depth_first(draft) if node.id in draft.plan_facets)
    rename_task(draft, first_task.id, "Renommée dans le brouillon")
    assert_sound(project, draft)

    mo_line = next(
        node_id for node_id, facet in draft.cost_facets.items() if facet.nature is CostNature.LABOR
    )
    set_cost_hours(draft, mo_line, Decimal("999"))
    assert_sound(project, draft)

    add_cost_line(
        project,
        draft,
        nature=CostNature.NON_LABOR,
        label="Ligne ajoutée au brouillon",
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("10.00"),
    )
    assert_sound(project, draft)

    delete_nodes(project, draft, [first_task.id])
    assert_sound(project, draft)

    # The source is bit-for-bit what it was before the copy was even created.
    assert source == source_snapshot


# --------------------------------------------------------------------------------------
# Scenario 7 -- re-import a modified planning into a draft (Rule 3)
# --------------------------------------------------------------------------------------


def _modified_planning(
    tasks: list[ImportedTask], *, removed_uid: int, moved_uid: int, new_parent_uid: int
) -> tuple[list[ImportedTask], int]:
    """A file with one task added, one moved and one removed."""
    added_uid = max(task.external_uid for task in tasks) + 1
    modified = [
        replacement
        for task in tasks
        if task.external_uid != removed_uid
        for replacement in [
            ImportedTask(
                external_uid=task.external_uid,
                name=task.name,
                parent_external_uid=(
                    new_parent_uid if task.external_uid == moved_uid else task.parent_external_uid
                ),
                duration_minutes=task.duration_minutes,
                is_milestone=task.is_milestone,
                percent_complete=task.percent_complete,
            )
        ]
    ]
    modified.append(
        ImportedTask(
            external_uid=added_uid,
            name="Tâche ajoutée par le réimport",
            parent_external_uid=new_parent_uid,
        )
    )
    return modified, added_uid


def test_scenario_7_reimport_applies_added_moved_and_removed_tasks(
    reference_planning: MspdiPlanning,
    estimate: Estimate,
) -> None:
    tasks = imported_tasks(reference_planning)
    project, revision = estimate.bench.project, estimate.bench.revision
    uid_of = {node_id: uid for uid, node_id in estimate.bench.node_by_uid.items()}

    removed_uid = uid_of[estimate.task_x]  # the task bearing two cost lines
    moved_uid = uid_of[estimate.task_y]
    # Not a milestone: a jalon carries no child (INV-27), so re-importing the moved
    # task under one would be refused. The reference planning holds plenty of them,
    # so this is a real filter and not a formality.
    new_parent_uid = next(
        task.external_uid
        for task in tasks
        if task.external_uid not in {removed_uid, moved_uid} and not task.is_milestone
    )
    modified, added_uid = _modified_planning(
        tasks, removed_uid=removed_uid, moved_uid=moved_uid, new_parent_uid=new_parent_uid
    )

    # Safeguard first: the diff names every cost-bearing node the confirmation destroys.
    diff = plan_reimport(project, revision, modified)
    assert [item.external_uid for item in diff.removed] == [removed_uid]
    assert [item.external_uid for item in diff.added] == [added_uid]
    assert moved_uid in [item.external_uid for item in diff.moved]
    assert {loss.node_id for loss in diff.cost_losses} == {
        estimate.labor_x,
        estimate.supply_x,
    }
    labels = {loss.label: loss for loss in diff.cost_losses}
    assert labels["Étude de faisabilité"].nature is CostNature.LABOR
    assert labels["Étude de faisabilité"].amount == Decimal("120") * Decimal("80.00")
    assert labels["Baie 19 pouces"].nature is CostNature.NON_LABOR
    assert labels["Baie 19 pouces"].amount == Decimal("2") * Decimal("2400.00")
    assert labels["Baie 19 pouces"].bearing_task_name == revision.plan_facets[estimate.task_x].name
    # Nothing was applied yet.
    assert estimate.task_x in revision.nodes

    applied = apply_reimport(project, revision, modified)
    assert_sound(project, revision)

    assert applied.removed == diff.removed
    # Rule 3: the vanished task, its cost facet and its whole subtree are gone.
    assert estimate.task_x not in revision.nodes
    assert estimate.labor_x not in revision.cost_facets
    assert estimate.supply_x not in revision.cost_facets
    # The moved task now hangs under its new parent, the added one exists.
    moved_node_id = estimate.bench.node_by_uid[moved_uid]
    assert revision.nodes[moved_node_id].parent_id == estimate.bench.node_by_uid[new_parent_uid]
    added_work_item = next(
        item for item in project.work_items.values() if item.external_uid == added_uid
    )
    assert any(node.work_item_id == added_work_item.id for node in revision.nodes.values())
    # The MO line of the moved task followed it and kept its assignment.
    assert estimate.labor_y in revision.cost_facets
    assert bearing_work_item_id(revision, estimate.labor_y) == (
        revision.nodes[moved_node_id].work_item_id
    )
    # The global cost line, absent from any file, is untouched.
    assert estimate.global_cost in revision.cost_facets


# --------------------------------------------------------------------------------------
# Scenario 8 -- entering a "reste à engager" on a post-order revision
# --------------------------------------------------------------------------------------


def test_scenario_8_remaining_forecast_reconciles_by_work_item_identity(
    estimate: Estimate,
) -> None:
    project, draft = estimate.bench.project, estimate.bench.revision

    budget = copy_revision(project, draft, kind=RevisionKind.CONTRACT_REFERENCE)
    assert_sound(project, budget)
    validate_revision(project, budget, now=NOW)
    assert_sound(project, budget)

    # After the order: the RAE is the very same cost facet, on a revision of kind
    # forecast_remaining. No extra attribute, no schema change.
    forecast = copy_revision(project, budget, kind=RevisionKind.FORECAST_REMAINING)
    assert_sound(project, forecast)
    assert forecast.kind is RevisionKind.FORECAST_REMAINING

    mo_work_item = budget.nodes[
        next(
            node_id
            for node_id, facet in budget.cost_facets.items()
            if facet.nature is CostNature.LABOR and facet.hours == Decimal("120")
        )
    ].work_item_id
    forecast_node = next(
        node_id for node_id, node in forecast.nodes.items() if node.work_item_id == mo_work_item
    )
    set_cost_hours(forecast, forecast_node, Decimal("30"))
    assert_sound(project, forecast)

    entries = {
        entry.work_item_id: entry
        for entry in reconcile_forecast_to_budget(project, budget=budget, forecast=forecast)
    }
    entry = entries[mo_work_item]
    assert entry.budget_amount == Decimal("120") * Decimal("80.00")
    assert entry.forecast_amount == Decimal("30") * Decimal("80.00")
    assert entry.variance == Decimal("-7200.00")

    # The join is by work_item identity alone: the two revisions share no node id,
    # and a frozen line carries no pointer to any mutable structure.
    assert not set(budget.nodes) & set(forecast.nodes)
    for line in budget.frozen_lines:
        assert not [name for name in vars(line) if "node" in name or "facet" in name]
    assert all(entry.work_item_id in project.work_items for entry in entries.values())


# --------------------------------------------------------------------------------------
# Scenario 9 -- the lotissement lives outside the revision (INV-26, Règle 4)
# --------------------------------------------------------------------------------------


def _lotissement_v1() -> list[BreakdownEntry]:
    """Two lots, one bearing a poste and a livrable."""
    return [
        BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot A — Études"),
        BreakdownEntry(
            id=2, kind=BreakdownKind.POSTE, name="Poste A.1 — Avant-projet", parent_id=1
        ),
        BreakdownEntry(
            id=3, kind=BreakdownKind.LIVRABLE, name="Livrable A.1 — Dossier", parent_id=2
        ),
        BreakdownEntry(id=4, kind=BreakdownKind.LOT, name="Lot B — Réalisation"),
    ]


def _names_in_order(revision: ProjectRevision) -> list[str]:
    return [revision.plan_facets[node.id].name for node in depth_first(revision)]


def test_scenario_9_the_lotissement_survives_a_validated_revision() -> None:
    """Product decision: the lotissement is project data, not revision data.

    The whole sequence, with the invariant checker run after **every** step:
    save the lotissement, generate a skeleton in a draft, validate that draft,
    **edit the lotissement anyway**, regenerate on an untouched tree, then touch
    the tree and watch the regeneration be refused.

    The one tension worth naming: INV-03 makes a validated revision immutable, so
    a regeneration -- which writes -- can only ever target a **draft**. That is not
    a contradiction with the decision, it is the decision working: the lotissement
    edit is accepted precisely *because* it is not part of the validated revision,
    and the regeneration goes to a draft copy of it. No invariant is relaxed
    anywhere in this test.
    """
    project = build_project()
    assert project.status is ProjectStatus.CREE

    # 1. The lotissement is saved at project level. Only this moves cree -> initialise.
    save_work_breakdown(project, _lotissement_v1())
    assert project.status is ProjectStatus.INITIALISE
    assert [entry.name for entry in project.work_breakdown][0] == "Lot A — Études"

    # 2. A skeleton is generated into a draft: one of three ways to start a planning.
    draft = build_draft(project)
    assert_sound(project, draft)
    entry_to_node = generate_skeleton(project, draft, now=NOW)
    assert_sound(project, draft)
    assert _names_in_order(draft) == [entry.name for entry in project.work_breakdown]
    assert draft.nodes[entry_to_node[2]].parent_id == entry_to_node[1]
    assert draft.nodes[entry_to_node[3]].parent_id == entry_to_node[2]
    # Skeleton tasks were never in a file, so they carry no external_uid (Rule 3 a).
    assert all(
        project.work_items[node.work_item_id].external_uid is None for node in draft.nodes.values()
    )

    # 3. The draft is validated. It is now immutable (INV-03).
    validate_revision(project, draft, now=NOW)
    assert_sound(project, draft)
    assert draft.status is RevisionStatus.VALIDATED
    frozen = copy.deepcopy(draft)

    # 4. The lotissement is edited anyway -- accepted, and propagating nothing.
    save_work_breakdown(
        project,
        [
            *_lotissement_v1(),
            BreakdownEntry(
                id=5, kind=BreakdownKind.POSTE, name="Poste B.1 — Chantier", parent_id=4
            ),
        ],
    )
    assert_sound(project, draft)
    assert [entry.id for entry in project.work_breakdown] == [1, 2, 3, 4, 5]
    # Not one node, facet, link or lock_version of the validated revision moved.
    assert draft == frozen
    # And regenerating *into* it is refused by immutability, not worked around.
    with pytest.raises(ImmutableRevisionError):
        regenerate_skeleton(project, draft, now=NOW)
    assert draft == frozen
    assert not can_regenerate_skeleton(project, draft)

    # 5. Regeneration therefore targets a draft copy, whose tree is untouched.
    successor = copy_revision(project, draft, now=NOW)
    assert_sound(project, successor)
    assert can_regenerate_skeleton(project, successor)
    regenerate_skeleton(project, successor, now=NOW)
    assert_sound(project, successor)
    assert _names_in_order(successor) == [entry.name for entry in project.work_breakdown]
    assert "Poste B.1 — Chantier" in _names_in_order(successor)
    # Identity continuity across the regeneration: the rebuilt tasks are new nodes
    # but the **same** work items, the ones the validated revision froze. A
    # reallocation would leave its frozen lines -- and the reconciliation that
    # joins on ``work_item_id`` and on nothing else -- with nothing to join on.
    assert not set(successor.nodes) & set(draft.nodes)
    for frozen_node in draft.nodes.values():
        assert node_by_work_item(successor, frozen_node.work_item_id) is not None

    # 6. The tree is touched: the regeneration is refused, and changes nothing.
    add_task(project, successor, name="Tâche saisie à la main")
    assert_sound(project, successor)
    assert not can_regenerate_skeleton(project, successor)
    touched = copy.deepcopy(successor)

    with pytest.raises(WorkBreakdownError, match="untouched skeleton"):
        regenerate_skeleton(project, successor, now=NOW)

    assert successor == touched
    assert_sound(project, successor)
