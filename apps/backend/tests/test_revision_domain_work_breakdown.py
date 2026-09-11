"""Unit coverage of the lotissement and of the skeleton it seeds (INV-26, Règle 4).

``test_revision_domain_scenarios.py`` replays the whole product sequence end to
end; this module pins down each refusal and each edge of the fingerprint rule on
its own, so a regression names the exact rule it broke.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from _revision_domain_support import assert_sound, build_draft, build_project
from waterfall.domain.revision import (
    BreakdownEntry,
    BreakdownKind,
    CalendarSource,
    CostNature,
    FacetContractError,
    ImmutableRevisionError,
    PlanFacet,
    Project,
    ProjectRevision,
    ProjectStatus,
    WorkBreakdownError,
    WorkItemKind,
    add_cost_line,
    add_link,
    add_task,
    breakdown_changed_since_generation,
    can_regenerate_skeleton,
    copy_revision,
    create_work_item,
    delete_nodes,
    depth_first,
    generate_skeleton,
    node_by_work_item,
    regenerate_skeleton,
    save_work_breakdown,
    skeleton_fingerprint_of,
    validate_revision,
)
from waterfall.domain.revision.facets import (
    rename_task,
    set_task_calendar_manually,
    set_task_dates,
    set_task_duration,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _lotissement() -> list[BreakdownEntry]:
    return [
        BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot A"),
        BreakdownEntry(id=2, kind=BreakdownKind.POSTE, name="Poste A.1", parent_id=1),
        BreakdownEntry(id=3, kind=BreakdownKind.LIVRABLE, name="Livrable A.1", parent_id=2),
    ]


def _seeded() -> tuple[Project, ProjectRevision]:
    """A project with a lotissement and a draft carrying the freshly generated skeleton."""
    project = build_project()
    save_work_breakdown(project, _lotissement())
    revision = build_draft(project)
    generate_skeleton(project, revision, now=NOW)
    return project, revision


# --------------------------------------------------------------------------------------
# Saving the lotissement
# --------------------------------------------------------------------------------------


def test_a_lotissement_listing_an_entry_twice_is_refused() -> None:
    project = build_project()

    with pytest.raises(WorkBreakdownError, match="listed twice"):
        save_work_breakdown(
            project,
            [
                BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot A"),
                BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot A bis"),
            ],
        )

    assert project.work_breakdown == ()
    assert project.status is ProjectStatus.CREE


def test_a_lotissement_naming_a_parent_it_defines_later_is_refused() -> None:
    """Same contract as an imported file: the list is already depth-first."""
    project = build_project()

    with pytest.raises(WorkBreakdownError, match="does not define before it"):
        save_work_breakdown(
            project,
            [
                BreakdownEntry(id=2, kind=BreakdownKind.POSTE, name="Poste A.1", parent_id=1),
                BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot A"),
            ],
        )

    assert project.work_breakdown == ()


def test_saving_a_lotissement_twice_replaces_it_wholesale() -> None:
    project = build_project()
    save_work_breakdown(project, _lotissement())

    save_work_breakdown(project, [BreakdownEntry(id=9, kind=BreakdownKind.LOT, name="Lot Z")])

    assert [entry.id for entry in project.work_breakdown] == [9]
    # The status transition happens once and is not undone.
    assert project.status is ProjectStatus.INITIALISE


def test_a_status_beyond_initialise_is_left_alone_by_a_save() -> None:
    project = build_project()
    project.status = ProjectStatus.EN_COURS

    save_work_breakdown(project, _lotissement())

    assert project.status is ProjectStatus.EN_COURS


# --------------------------------------------------------------------------------------
# Generating a skeleton
# --------------------------------------------------------------------------------------


def test_generating_without_a_lotissement_is_refused() -> None:
    project = build_project()
    revision = build_draft(project)

    with pytest.raises(WorkBreakdownError, match="no lotissement"):
        generate_skeleton(project, revision, now=NOW)

    assert revision.nodes == {}
    assert revision.skeleton_fingerprint is None


def test_generating_into_a_revision_that_already_holds_nodes_is_refused() -> None:
    """Overwriting an existing tree is ``regenerate_skeleton``'s decision to take."""
    project = build_project()
    save_work_breakdown(project, _lotissement())
    revision = build_draft(project)
    add_task(project, revision, name="Saisie à la main")
    before = copy.deepcopy(revision)

    with pytest.raises(WorkBreakdownError, match="already carries"):
        generate_skeleton(project, revision, now=NOW)

    assert revision == before


def test_generating_into_a_validated_revision_raises_the_immutability_error() -> None:
    """Not a lotissement error: INV-03 answers first, and with its own exception."""
    project = build_project()
    save_work_breakdown(project, _lotissement())
    revision = build_draft(project)
    validate_revision(project, revision, now=NOW)

    with pytest.raises(ImmutableRevisionError):
        generate_skeleton(project, revision, now=NOW)


def test_a_generated_skeleton_mirrors_the_lotissement() -> None:
    project, revision = _seeded()

    assert [revision.plan_facets[node.id].name for node in depth_first(revision)] == [
        "Lot A",
        "Poste A.1",
        "Livrable A.1",
    ]
    assert revision.skeleton_fingerprint == skeleton_fingerprint_of(project, revision)
    assert can_regenerate_skeleton(project, revision)
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# The "untouched" marker
# --------------------------------------------------------------------------------------


def test_a_renamed_task_makes_the_skeleton_touched() -> None:
    project, revision = _seeded()
    task = depth_first(revision)[0]

    rename_task(revision, task.id, "Renommée par l'utilisateur")

    assert not can_regenerate_skeleton(project, revision)
    with pytest.raises(WorkBreakdownError, match="untouched skeleton"):
        regenerate_skeleton(project, revision, now=NOW)


def test_chiffrage_hung_under_a_skeleton_task_makes_it_touched() -> None:
    """A cost line counts: it is exactly what a regeneration must never destroy."""
    project, revision = _seeded()
    task = depth_first(revision)[0]

    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Étude",
        parent_id=task.id,
        role_id=1,
        hours=Decimal("10"),
    )

    assert not can_regenerate_skeleton(project, revision)
    assert_sound(project, revision)


def test_a_precedence_link_between_two_skeleton_tasks_makes_it_touched() -> None:
    """A link lives in ``revision.links``, outside the tree: the signature reads it too."""
    project, revision = _seeded()
    first, second = depth_first(revision)[0], depth_first(revision)[1]

    add_link(revision, node_id=second.id, predecessor_node_id=first.id)

    assert not can_regenerate_skeleton(project, revision)
    with pytest.raises(WorkBreakdownError, match="untouched skeleton"):
        regenerate_skeleton(project, revision, now=NOW)
    assert len(revision.links) == 1


def test_a_duration_typed_on_a_skeleton_task_makes_it_touched() -> None:
    """The planner's first move on a fresh skeleton, and it must not be regenerable away."""
    project, revision = _seeded()
    task = depth_first(revision)[0]

    set_task_duration(revision, task.id, 480)

    assert not can_regenerate_skeleton(project, revision)
    with pytest.raises(WorkBreakdownError, match="untouched skeleton"):
        regenerate_skeleton(project, revision, now=NOW)
    assert revision.plan_facets[task.id].duration_minutes == 480


def test_dates_set_on_a_skeleton_task_make_it_touched() -> None:
    project, revision = _seeded()
    task = depth_first(revision)[0]

    set_task_dates(
        revision,
        task.id,
        start_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
        finish_at=datetime(2026, 10, 3, 17, tzinfo=UTC),
    )

    assert not can_regenerate_skeleton(project, revision)


def test_a_calendar_pinned_by_hand_on_a_skeleton_task_makes_it_touched() -> None:
    """``manual`` is the one calendar source the user owns (Rule 1); it is watched."""
    project, revision = _seeded()
    task = depth_first(revision)[0]

    set_task_calendar_manually(revision, task.id, calendar_id=99)

    assert not can_regenerate_skeleton(project, revision)
    with pytest.raises(WorkBreakdownError, match="untouched skeleton"):
        regenerate_skeleton(project, revision, now=NOW)
    assert revision.plan_facets[task.id].calendar_id == 99
    assert revision.plan_facets[task.id].calendar_source is CalendarSource.MANUAL


def test_a_milestone_flag_set_on_a_skeleton_task_makes_it_touched() -> None:
    """Set through the facet itself: no operation exposes it, the fingerprint still sees it."""
    project, revision = _seeded()
    task = depth_first(revision)[0]

    revision.plan_facets[task.id].is_milestone = True

    assert not can_regenerate_skeleton(project, revision)


def _first_plan(revision: ProjectRevision) -> PlanFacet:
    return revision.plan_facets[depth_first(revision)[0].id]


def _no_preparation(revision: ProjectRevision) -> None:
    """Nothing to prepare: the mark lives on a facet the generated skeleton carries."""


def _hang_a_link(revision: ProjectRevision) -> None:
    """A link to carry the three link marks; its own presence is watched too."""
    nodes = depth_first(revision)
    add_link(revision, node_id=nodes[1].id, predecessor_node_id=nodes[0].id)


def _type_a_charge(revision: ProjectRevision) -> None:
    _first_plan(revision).work_minutes = 960


def _type_a_progress(revision: ProjectRevision) -> None:
    _first_plan(revision).percent_complete = 40


def _switch_to_manual_scheduling(revision: ProjectRevision) -> None:
    _first_plan(revision).is_manual = True


def _change_the_duration_format(revision: ProjectRevision) -> None:
    _first_plan(revision).duration_format = 7


def _change_the_link_type(revision: ProjectRevision) -> None:
    revision.links[0].link_type = 3


def _add_a_lag(revision: ProjectRevision) -> None:
    revision.links[0].lag_tenth_minute = 4800


def _change_the_lag_format(revision: ProjectRevision) -> None:
    revision.links[0].lag_format = 7


@pytest.mark.parametrize(
    ("mark", "prepare", "touch_it"),
    [
        ("work_minutes", _no_preparation, _type_a_charge),
        ("percent_complete", _no_preparation, _type_a_progress),
        ("is_manual", _no_preparation, _switch_to_manual_scheduling),
        ("duration_format", _no_preparation, _change_the_duration_format),
        ("link_type", _hang_a_link, _change_the_link_type),
        ("lag_tenth_minute", _hang_a_link, _add_a_lag),
        ("lag_format", _hang_a_link, _change_the_lag_format),
    ],
)
def test_every_watched_mark_makes_the_skeleton_touched_on_its_own(
    mark: str,
    prepare: Callable[[ProjectRevision], None],
    touch_it: Callable[[ProjectRevision], None],
) -> None:
    """One row per mark the signature watches but no scenario above changes alone.

    Branch coverage does not protect these: they sit in a tuple built
    unconditionally, so dropping one would keep the coverage at 100 % and break no
    assertion. What is asserted here is the *property* -- "this field is watched"
    -- so removing it from the signature turns a row red.

    The link marks need a link to hang on, and adding one is itself a touch: the
    fingerprint is therefore re-stamped on the prepared state, so that the only
    difference the assertion can see is the mark under test.
    """
    project, revision = _seeded()
    prepare(revision)
    revision.skeleton_fingerprint = skeleton_fingerprint_of(project, revision)
    assert can_regenerate_skeleton(project, revision), mark

    touch_it(revision)

    assert not can_regenerate_skeleton(project, revision), mark
    with pytest.raises(WorkBreakdownError, match="untouched skeleton"):
        regenerate_skeleton(project, revision, now=NOW)


def test_a_deleted_task_makes_the_skeleton_touched() -> None:
    project, revision = _seeded()
    task = depth_first(revision)[0]

    delete_nodes(project, revision, [task.id])

    assert not can_regenerate_skeleton(project, revision)


def test_a_revision_that_never_carried_a_skeleton_is_not_regenerable() -> None:
    project = build_project()
    save_work_breakdown(project, _lotissement())
    revision = build_draft(project)
    add_task(project, revision, name="Feuille blanche")

    assert revision.skeleton_fingerprint is None
    assert not can_regenerate_skeleton(project, revision)


def test_an_emptied_lotissement_makes_the_skeleton_unregenerable() -> None:
    project, revision = _seeded()
    assert can_regenerate_skeleton(project, revision)

    save_work_breakdown(project, [])

    assert not can_regenerate_skeleton(project, revision)


def test_a_copy_of_an_untouched_skeleton_is_still_untouched() -> None:
    """The fingerprint is computed on shape and labels, never on node ids (INV-07)."""
    project, revision = _seeded()

    duplicate = copy_revision(project, revision, now=NOW)

    assert not set(duplicate.nodes) & set(revision.nodes)
    assert duplicate.skeleton_fingerprint == revision.skeleton_fingerprint
    assert can_regenerate_skeleton(project, duplicate)


def test_regenerating_picks_up_a_lotissement_edited_since_the_generation() -> None:
    """The ``breakdown_digest`` half of the fingerprint never forbids anything."""
    project, revision = _seeded()
    stale_fingerprint = revision.skeleton_fingerprint
    assert stale_fingerprint is not None

    save_work_breakdown(
        project, [*_lotissement(), BreakdownEntry(id=4, kind=BreakdownKind.LOT, name="Lot B")]
    )
    assert (
        skeleton_fingerprint_of(project, revision).breakdown_digest
        != stale_fingerprint.breakdown_digest
    )
    assert breakdown_changed_since_generation(project, revision)
    assert can_regenerate_skeleton(project, revision)

    regenerate_skeleton(project, revision, now=NOW)

    assert [revision.plan_facets[node.id].name for node in depth_first(revision)][-1] == "Lot B"
    assert revision.skeleton_fingerprint == skeleton_fingerprint_of(project, revision)
    assert not breakdown_changed_since_generation(project, revision)
    assert_sound(project, revision)


def test_a_revision_without_a_skeleton_never_reports_a_stale_lotissement() -> None:
    project = build_project()
    save_work_breakdown(project, _lotissement())
    revision = build_draft(project)

    assert not breakdown_changed_since_generation(project, revision)


# --------------------------------------------------------------------------------------
# The identity of a regenerated task
# --------------------------------------------------------------------------------------


def _work_item_by_entry(project: Project, revision: ProjectRevision) -> dict[int, int]:
    """``lotissement entry id -> work_item id``, as the tree of ``revision`` carries it."""
    owners: dict[int, int] = {}
    for node in revision.nodes.values():
        entry_id = project.work_items[node.work_item_id].breakdown_entry_id
        assert entry_id is not None, "a generated task hangs on no lotissement entry"
        owners[entry_id] = node.work_item_id
    return owners


def test_a_regenerated_task_keeps_the_work_item_of_its_lotissement_entry() -> None:
    """Regenerating replaces nodes, never identities: the entry owns the ``work_item``."""
    project, revision = _seeded()
    before = _work_item_by_entry(project, revision)
    assert sorted(before) == [1, 2, 3]
    nodes_before = set(revision.nodes)

    regenerate_skeleton(project, revision, now=NOW)

    assert _work_item_by_entry(project, revision) == before
    assert not set(revision.nodes) & nodes_before
    assert_sound(project, revision)


def test_generating_the_same_lotissement_into_a_second_revision_reuses_the_work_items() -> None:
    """The hook is the identity of the *project*, exactly as ``external_uid`` is."""
    project, first = _seeded()
    second = build_draft(project)

    generate_skeleton(project, second, now=NOW)

    assert {node.work_item_id for node in second.nodes.values()} == {
        node.work_item_id for node in first.nodes.values()
    }
    assert not set(second.nodes) & set(first.nodes)
    assert_sound(project, second)


def test_an_undone_touch_makes_the_skeleton_regenerable_without_losing_an_identity() -> None:
    """The finding of round 5: "untouched" compares a state, not a history.

    Hanging a cost line and removing it again makes the regeneration available on
    a tree whose identities a **validated** revision already froze. Since the
    regeneration keeps them, its frozen lines still join onto the forecast.
    """
    project, revision = _seeded()
    bearing = depth_first(revision)[0]
    line = add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Étude",
        parent_id=bearing.id,
        role_id=1,
        hours=Decimal("10"),
    )
    validate_revision(project, revision, now=NOW)
    bearing_work_item = revision.frozen_lines[0].bearing_work_item_id
    assert bearing_work_item is not None

    successor = copy_revision(project, revision, now=NOW)
    assert not can_regenerate_skeleton(project, successor)
    doomed = next(
        node.id for node in successor.nodes.values() if node.work_item_id == line.work_item_id
    )
    delete_nodes(project, successor, [doomed])
    assert can_regenerate_skeleton(project, successor)

    regenerate_skeleton(project, successor, now=NOW)

    assert node_by_work_item(successor, bearing_work_item) is not None
    assert_sound(project, successor)


# --------------------------------------------------------------------------------------
# The lotissement hook of a work item, and what a refused generation leaves behind
# --------------------------------------------------------------------------------------


def _cost_work_item_hooked_onto(project: Project, entry_id: int) -> int:
    """A ``cost`` work item carrying ``breakdown_entry_id``, written by hand.

    The creation surface refuses to build one (that guard has its own tests just
    below), so the only way to reach the state is to write the field directly --
    which is exactly what a persistence layer, a fixture or a future migration
    could do. The generation must refuse it *without writing anything*.
    """
    elsewhere = build_draft(project)
    line = add_cost_line(
        project,
        elsewhere,
        nature=CostNature.LABOR,
        label="Étude",
        role_id=1,
        hours=Decimal("10"),
    )
    project.work_items[line.work_item_id].breakdown_entry_id = entry_id
    return line.work_item_id


def test_a_generation_refused_halfway_writes_no_node_and_allocates_no_identity() -> None:
    """A refusal on the *second* entry must leave neither a partial tree nor a leak.

    Resolving the hooks as the tree is built would create the first task, refuse
    on the second, and jam the revision for good: ``generate_skeleton`` then
    refuses a non-empty tree, ``regenerate_skeleton`` refuses a tree carrying no
    fingerprint, and no invariant reports the state -- only a manual
    ``delete_nodes`` would get out of it.
    """
    project = build_project()
    save_work_breakdown(project, _lotissement())
    hooked = _cost_work_item_hooked_onto(project, 2)
    revision = build_draft(project)
    identities, counter = set(project.work_items), project.next_work_item_id

    with pytest.raises(FacetContractError, match="cannot carry a task facet"):
        generate_skeleton(project, revision, now=NOW)

    assert revision.nodes == {}
    assert revision.skeleton_fingerprint is None
    assert set(project.work_items) == identities
    assert project.next_work_item_id == counter

    project.work_items[hooked].breakdown_entry_id = None
    generate_skeleton(project, revision, now=NOW)

    assert len(revision.nodes) == 3
    assert can_regenerate_skeleton(project, revision)
    assert_sound(project, revision)


def test_a_regeneration_refused_by_a_hook_leaves_the_tree_it_would_have_replaced() -> None:
    """The refusal is raised before the deletion, not between it and the rewrite."""
    project, revision = _seeded()
    save_work_breakdown(
        project, [*_lotissement(), BreakdownEntry(id=4, kind=BreakdownKind.LOT, name="Lot B")]
    )
    hooked = _cost_work_item_hooked_onto(project, 4)
    before, counter = copy.deepcopy(revision), project.next_work_item_id

    with pytest.raises(FacetContractError, match="cannot carry a task facet"):
        regenerate_skeleton(project, revision, now=NOW)

    assert revision == before
    assert project.next_work_item_id == counter

    project.work_items[hooked].breakdown_entry_id = None
    regenerate_skeleton(project, revision, now=NOW)

    assert [revision.plan_facets[node.id].name for node in depth_first(revision)][-1] == "Lot B"
    assert_sound(project, revision)


def test_creating_a_cost_work_item_hooked_onto_a_lotissement_entry_is_refused() -> None:
    """The hook belongs to a task: a cost line is never generated from a lot.

    A creation guard, not an invariant: Règle 4 is provisoire, so the checker is
    left out of it (see the ``breakdown_entry_id`` row of the attribute table).
    """
    project = build_project()

    with pytest.raises(WorkBreakdownError, match="never generated from a lotissement entry"):
        create_work_item(project, WorkItemKind.COST, breakdown_entry_id=1)

    assert project.work_items == {}
    assert project.next_work_item_id == 1


def test_hooking_two_work_items_onto_the_same_lotissement_entry_is_refused() -> None:
    """The hook is an identity: a second one could never be resolved from the entry.

    Not the benign orphan of an entry dropped from the lotissement -- the
    generation resolves an entry to a single work item, so the second would be
    unreachable from the moment it is created.
    """
    project = build_project()
    first = create_work_item(project, WorkItemKind.TASK, breakdown_entry_id=1)

    with pytest.raises(WorkBreakdownError, match="already hooked onto work_item"):
        create_work_item(project, WorkItemKind.TASK, breakdown_entry_id=1)

    assert list(project.work_items) == [first.id]
    assert create_work_item(project, WorkItemKind.TASK, breakdown_entry_id=2).id != first.id


# --------------------------------------------------------------------------------------
# What the fingerprint is allowed to carry
# --------------------------------------------------------------------------------------


def test_the_fingerprint_carries_digests_only_never_the_content_it_condenses() -> None:
    """INV-26: an empreinte, not a copy -- a validated revision must freeze nothing.

    Both halves: the lotissement half would freeze the lot labels, and the tree
    half, which spells the task names out to compare them, would freeze the very
    same labels one copy further down.
    """
    project = build_project()
    save_work_breakdown(
        project, [BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot secret client X")]
    )
    revision = build_draft(project)
    generate_skeleton(project, revision, now=NOW)
    fingerprint = revision.skeleton_fingerprint
    assert fingerprint is not None

    for half in (fingerprint.breakdown_digest, fingerprint.tree_digest):
        assert "Lot secret client X" not in half
        assert "lot" not in half
        assert len(half) == 64
    assert_sound(project, revision)
