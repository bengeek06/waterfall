"""Unit coverage of the tree and facet operations of the revision domain (E14-02).

The invariant bench (``test_revision_domain_invariants.py``) proves the model is
sound; this module pins down the behaviour of each operation the EPIC requires the
domain to expose -- insert, move up/down, indent, outdent (up to the root),
cascade delete, contiguous renumbering, bearing-task resolution -- plus Rule 1's
calendar resynchronisation and the facet-level writes.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from _revision_domain_support import (
    ROLE_CALENDAR_ID,
    Bench,
    assert_sound,
    build_bench,
    build_draft,
    build_project,
    plan_facet,
)
from waterfall.domain.revision import (
    CalendarSource,
    CostFacet,
    CostNature,
    FacetPlacementError,
    ImportedTask,
    ImportStructureError,
    NotFoundError,
    PositionError,
    Project,
    ProjectMismatchError,
    RevisionDomainError,
    RevisionKind,
    RevisionLifecycleError,
    RevisionStatus,
    Role,
    SelectionError,
    SupplyStatus,
    TreeCycleError,
    WorkItemKind,
    add_cost_line,
    add_link,
    add_task,
    ancestors_of,
    apply_reimport,
    check_all_invariants,
    check_invariants,
    children_of,
    copy_revision,
    create_revision,
    create_work_item,
    delete_nodes,
    depth_first,
    describe_cost_losses,
    indent_nodes,
    insert_node,
    levels,
    move_nodes,
    move_nodes_down,
    move_nodes_up,
    node_by_work_item,
    outdent_nodes,
    plan_reimport,
    resolve_bearing_task,
    selection_roots,
    subtree_ids,
    unreachable_node_ids,
    validate_revision,
    violated_invariant_ids,
)
from waterfall.domain.revision.facets import (
    FacetContractError,
    assign_role,
    clear_task_calendar_override,
    rename_task,
    set_cost_comment,
    set_cost_hours,
    set_cost_label,
    set_cost_planned_date,
    set_cost_quantity,
    set_cost_unit_cost,
    set_supply_status,
    set_task_calendar_manually,
    set_task_dates,
    set_task_duration,
)
from waterfall.domain.revision.reconciliation import reconcile_forecast_to_budget
from waterfall.domain.revision.tree import links_of

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

#: Calendar of a *second* MO role, distinct from ``ROLE_CALENDAR_ID``. Needed
#: wherever the order of two MO facets has to decide which calendar Rule 1 picks.
SECOND_ROLE_CALENDAR_ID = 33


@pytest.fixture
def bench() -> Bench:
    return build_bench()


def _names(bench: Bench, parent_id: int | None) -> list[str]:
    revision = bench.revision
    return [
        revision.plan_facets[node.id].name
        if node.id in revision.plan_facets
        else revision.cost_facets[node.id].label
        for node in children_of(revision, parent_id)
    ]


# --------------------------------------------------------------------------------------
# Insertion and positions
# --------------------------------------------------------------------------------------


def test_insert_at_an_explicit_position_shifts_the_following_siblings(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    inserted = add_task(project, revision, name="Inserted", position=2)

    assert _names(bench, None) == ["A", "Inserted", "C", "Assurance chantier"]
    assert [node.position for node in children_of(revision, None)] == [1, 2, 3, 4]
    assert revision.nodes[inserted.id].position == 2
    assert_sound(project, revision)


def test_insert_outside_the_sibling_range_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(PositionError):
        add_task(project, revision, name="Too far", position=9)
    with pytest.raises(PositionError):
        add_task(project, revision, name="Too early", position=0)


def test_insert_under_an_unknown_parent_or_work_item_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(NotFoundError):
        add_task(project, revision, name="Orphan", parent_id=9999)
    with pytest.raises(NotFoundError):
        insert_node(project, revision, work_item_id=9999, plan=plan_facet())


def test_insert_of_a_work_item_of_another_project_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    other_project = build_project(project_id=2)
    other_project.next_work_item_id = 500
    stranger = create_work_item(other_project, WorkItemKind.TASK)
    project.work_items[stranger.id] = stranger

    with pytest.raises(ProjectMismatchError):
        insert_node(project, revision, work_item_id=stranger.id, plan=plan_facet())


def test_a_delete_closes_the_hole_it_leaves_in_the_sibling_positions(bench: Bench) -> None:
    """Contiguous renumbering (INV-05) is reachable only through an operation.

    The renumbering helper itself is private: it writes without a ``require_draft``
    of its own, so it is not on the package surface (see
    ``test_renumber_children_is_private_because_it_writes_without_a_draft_guard``).
    """
    project, revision = bench.project, bench.revision
    assert [node.position for node in children_of(revision, None)] == [1, 2, 3]

    delete_nodes(project, revision, [bench.root_a])

    assert [node.position for node in children_of(revision, None)] == [1, 2]
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# Selection normalisation
# --------------------------------------------------------------------------------------


def test_selection_roots_drops_a_node_already_carried_by_its_ancestor(bench: Bench) -> None:
    roots = selection_roots(bench.revision, [bench.child_b, bench.root_a, bench.labor])

    assert [node.id for node in roots] == [bench.root_a]


def test_selection_roots_rejects_an_empty_or_duplicated_selection(bench: Bench) -> None:
    with pytest.raises(SelectionError):
        selection_roots(bench.revision, [])
    with pytest.raises(SelectionError):
        selection_roots(bench.revision, [bench.root_a, bench.root_a])
    with pytest.raises(NotFoundError):
        selection_roots(bench.revision, [4242])


# --------------------------------------------------------------------------------------
# Move up / down / indent / outdent
# --------------------------------------------------------------------------------------


def test_move_up_and_down_shift_a_block_of_siblings(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    assert _names(bench, None) == ["A", "C", "Assurance chantier"]

    move_nodes_down(project, revision, [bench.root_a])
    assert _names(bench, None) == ["C", "A", "Assurance chantier"]
    assert_sound(project, revision)

    move_nodes_up(project, revision, [bench.root_a])
    assert _names(bench, None) == ["A", "C", "Assurance chantier"]
    assert_sound(project, revision)


def test_move_up_or_down_at_the_edge_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(SelectionError):
        move_nodes_up(project, revision, [bench.root_a])
    with pytest.raises(SelectionError):
        move_nodes_down(project, revision, [bench.global_cost])


def test_move_up_of_a_non_contiguous_block_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    extra = add_task(project, revision, name="D")

    with pytest.raises(SelectionError):
        move_nodes_up(project, revision, [bench.root_c, extra.id])


def test_indent_places_the_selection_under_its_preceding_sibling(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    indent_nodes(project, revision, [bench.root_c])

    assert revision.nodes[bench.root_c].parent_id == bench.root_a
    assert _names(bench, None) == ["A", "Assurance chantier"]
    assert_sound(project, revision)


def test_indent_of_a_first_child_or_of_a_split_selection_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(SelectionError):
        indent_nodes(project, revision, [bench.root_a])
    with pytest.raises(SelectionError):
        indent_nodes(project, revision, [bench.root_c, bench.child_b])


def test_outdent_moves_a_node_up_to_the_root_right_after_its_former_parent(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision

    outdent_nodes(project, revision, [bench.child_b])

    assert revision.nodes[bench.child_b].parent_id is None
    assert _names(bench, None) == ["A", "B", "C", "Assurance chantier"]
    assert_sound(project, revision)


def test_outdent_of_a_root_node_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(SelectionError):
        outdent_nodes(project, revision, [bench.root_a])


def test_move_keeps_the_relative_order_of_a_multi_node_selection(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    move_nodes(
        project,
        revision,
        [bench.root_c, bench.root_a],
        target_parent_id=None,
        position=1,
    )

    assert _names(bench, None) == ["A", "C", "Assurance chantier"]
    assert_sound(project, revision)


def test_move_outside_the_target_range_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(PositionError):
        move_nodes(project, revision, [bench.root_c], target_parent_id=None, position=9)


def test_move_under_an_unknown_parent_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(NotFoundError):
        move_nodes(project, revision, [bench.root_c], target_parent_id=4242)


# --------------------------------------------------------------------------------------
# Bearing task, subtree and links
# --------------------------------------------------------------------------------------


def test_resolve_bearing_task_walks_up_through_nested_cost_lines(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    nested = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Sous-ligne",
        parent_id=bench.supply,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("4"),
    )

    bearing = resolve_bearing_task(revision, nested.id)

    assert bearing is not None
    assert bearing.id == bench.root_a
    assert resolve_bearing_task(revision, bench.global_cost) is None


def test_ancestors_and_subtree_helpers(bench: Bench) -> None:
    revision = bench.revision

    assert [node.id for node in ancestors_of(revision, bench.labor)] == [
        bench.child_b,
        bench.root_a,
    ]
    assert set(subtree_ids(revision, bench.root_a)) == {
        bench.root_a,
        bench.child_b,
        bench.labor,
        bench.supply,
    }
    assert subtree_ids(revision, 4242) == []
    assert node_by_work_item(revision, 4242) is None


def test_links_survive_a_move_and_are_listed_per_node(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    add_link(revision, node_id=bench.child_b, predecessor_node_id=bench.root_c, link_type=1)

    move_nodes(project, revision, [bench.child_b], target_parent_id=bench.root_c)

    assert links_of(revision, bench.child_b) == [(bench.root_c, 1, 0)]
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# Delete
# --------------------------------------------------------------------------------------


def test_delete_of_a_selection_mixing_a_parent_and_its_descendant(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    report = delete_nodes(project, revision, [bench.labor, bench.root_a])

    assert set(report.removed_node_ids) == {
        bench.root_a,
        bench.child_b,
        bench.labor,
        bench.supply,
    }
    assert _names(bench, None) == ["C", "Assurance chantier"]
    assert_sound(project, revision)


def test_describe_cost_losses_uses_the_injected_amount_resolver(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    losses = describe_cost_losses(
        project,
        revision,
        [bench.root_a],
        amount_of=lambda _project, _facet: Decimal("42"),
    )

    assert {loss.label for loss in losses} == {"Étude", "Câblage"}
    assert {loss.amount for loss in losses} == {Decimal("42")}
    assert {loss.bearing_task_name for loss in losses} == {"A", "B"}


# --------------------------------------------------------------------------------------
# Rule 1 -- calendar of a task
# --------------------------------------------------------------------------------------


def test_rule_1_assigning_a_role_with_a_calendar_resynchronises_the_task(
    bench: Bench,
) -> None:
    revision = bench.revision

    assert revision.plan_facets[bench.child_b].calendar_id == ROLE_CALENDAR_ID
    assert revision.plan_facets[bench.child_b].calendar_source is CalendarSource.ROLE
    # The role of the only MO line carries no calendar above task C.
    assert revision.plan_facets[bench.root_c].calendar_source is CalendarSource.PROJECT


def test_rule_1_a_manual_calendar_is_never_overwritten(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    set_task_calendar_manually(revision, bench.child_b, 99)

    assign_role(project, revision, bench.labor, role_id=1, hours=Decimal("5"))

    assert revision.plan_facets[bench.child_b].calendar_id == 99
    assert revision.plan_facets[bench.child_b].calendar_source is CalendarSource.MANUAL
    assert_sound(project, revision)


def test_rule_1_clearing_the_manual_choice_restores_the_automatic_value(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision
    set_task_calendar_manually(revision, bench.child_b, 99)

    clear_task_calendar_override(project, revision, bench.child_b)

    assert revision.plan_facets[bench.child_b].calendar_id == ROLE_CALENDAR_ID
    assert revision.plan_facets[bench.child_b].calendar_source is CalendarSource.ROLE


def test_rule_1_switching_to_a_role_without_calendar_falls_back_to_the_project(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision

    assign_role(project, revision, bench.labor, role_id=2, hours=Decimal("8"))

    assert revision.plan_facets[bench.child_b].calendar_id == project.calendar_id
    assert revision.plan_facets[bench.child_b].calendar_source is CalendarSource.PROJECT
    assert_sound(project, revision)


def test_rule_1_moving_an_mo_line_resynchronises_both_ends(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    move_nodes(project, revision, [bench.labor], target_parent_id=bench.root_c)

    assert revision.plan_facets[bench.child_b].calendar_source is CalendarSource.PROJECT
    assert revision.plan_facets[bench.root_c].calendar_id == ROLE_CALENDAR_ID
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# Facet writes
# --------------------------------------------------------------------------------------


def test_facet_writes_apply_and_bump_the_lock_version(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    before = revision.lock_version

    rename_task(revision, bench.root_a, "A renommée")
    set_task_duration(revision, bench.root_a, 960)
    set_task_dates(revision, bench.root_a, start_at=NOW, finish_at=NOW)
    set_cost_label(revision, bench.supply, "Câblage renforcé")
    set_cost_quantity(revision, bench.supply, Decimal("5"))
    set_cost_unit_cost(revision, bench.supply, Decimal("130.00"))
    set_supply_status(revision, bench.supply, SupplyStatus.ORDERED)
    set_cost_hours(revision, bench.labor, Decimal("12"))

    assert revision.plan_facets[bench.root_a].name == "A renommée"
    assert revision.plan_facets[bench.root_a].duration_minutes == 960
    assert revision.plan_facets[bench.root_a].start_at == NOW
    assert revision.cost_facets[bench.supply].label == "Câblage renforcé"
    assert revision.cost_facets[bench.supply].quantity == Decimal("5")
    assert revision.cost_facets[bench.supply].unit_cost == Decimal("130.00")
    assert revision.cost_facets[bench.supply].supply_status is SupplyStatus.ORDERED
    assert revision.cost_facets[bench.labor].hours == Decimal("12")
    assert revision.lock_version == before + 8
    assert_sound(project, revision)


def test_facet_writes_refuse_the_wrong_facet_or_nature(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(NotFoundError):
        rename_task(revision, bench.supply, "not a task")
    with pytest.raises(NotFoundError):
        set_cost_quantity(revision, bench.root_a, Decimal("2"))
    with pytest.raises(FacetContractError):
        set_cost_hours(revision, bench.supply, Decimal("4"))
    with pytest.raises(FacetContractError):
        set_cost_unit_cost(revision, bench.labor, Decimal("4"))
    with pytest.raises(NotFoundError):
        assign_role(project, revision, bench.root_a, role_id=1, hours=Decimal("1"))


# --------------------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------------------


def test_a_superseded_revision_can_still_be_copied_into_a_new_draft(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    second = copy_revision(project, revision, now=NOW)
    validate_revision(project, second, now=NOW)
    assert revision.status is RevisionStatus.SUPERSEDED

    third = copy_revision(project, revision, now=NOW)

    assert third.status is RevisionStatus.DRAFT
    assert third.source_revision_id == revision.id
    assert len(third.nodes) == len(revision.nodes)
    assert_sound(project, third)


def test_an_explicit_version_number_is_honoured_and_an_empty_copy_stays_empty() -> None:
    project = build_project()
    first = create_revision(project, version_number=7)
    duplicate = copy_revision(project, first)

    assert first.version_number == 7
    assert duplicate.version_number == 8
    assert duplicate.nodes == {}
    assert_sound(project, duplicate)


def test_reconciliation_reports_a_line_present_on_one_side_only(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    budget = copy_revision(project, revision, kind=RevisionKind.CONTRACT_REFERENCE)
    validate_revision(project, budget, now=NOW)
    forecast = copy_revision(project, budget, kind=RevisionKind.FORECAST_REMAINING)

    # A line dropped from the forecast, a line that only the forecast carries.
    dropped = next(iter(forecast.cost_facets))
    dropped_work_item = forecast.nodes[dropped].work_item_id
    delete_nodes(project, forecast, [dropped])
    added = add_cost_line(
        project,
        forecast,
        nature=CostNature.NON_LABOR,
        label="Aléa",
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("1000"),
    )

    entries = {
        entry.work_item_id: entry
        for entry in reconcile_forecast_to_budget(project, budget=budget, forecast=forecast)
    }

    assert entries[dropped_work_item].forecast_amount is None
    assert entries[dropped_work_item].variance < 0
    added_work_item = forecast.nodes[added.id].work_item_id
    assert entries[added_work_item].budget_amount is None
    assert entries[added_work_item].variance == Decimal("1000")


def test_a_cost_facet_of_an_unknown_node_is_ignored_by_the_reconciliation() -> None:
    project = build_project()
    budget = build_draft(project)
    forecast = create_revision(project, kind=RevisionKind.FORECAST_REMAINING)
    forecast.cost_facets[999] = CostFacet(
        node_id=999,
        nature=CostNature.NON_LABOR,
        label="orpheline",
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("5"),
    )

    assert reconcile_forecast_to_budget(project, budget=budget, forecast=forecast) == []


def test_levels_group_the_tree_by_depth(bench: Bench) -> None:
    """Roots first, then their children, each level in display order."""
    grouped = [[node.id for node in level] for level in levels(bench.revision)]

    assert grouped == [
        [bench.root_a, bench.root_c, bench.global_cost],
        [bench.child_b, bench.supply],
        [bench.labor],
    ]
    assert unreachable_node_ids(bench.revision) == []


def test_an_empty_revision_has_no_level(bench: Bench) -> None:
    bench.revision.nodes.clear()

    assert levels(bench.revision) == []
    assert unreachable_node_ids(bench.revision) == []


def test_a_node_hanging_from_a_missing_parent_belongs_to_no_level(bench: Bench) -> None:
    """INV-09: no root reaches it, so a level-by-level walk must leave it out."""
    bench.revision.nodes[bench.root_c].parent_id = 4242

    assert bench.root_c not in [node.id for level in levels(bench.revision) for node in level]
    assert unreachable_node_ids(bench.revision) == [bench.root_c]


def test_a_parent_cycle_belongs_to_no_level(bench: Bench) -> None:
    """INV-06: two nodes hanging off each other are reached from nowhere, and the
    walk must still terminate."""
    revision = bench.revision
    revision.nodes[bench.root_a].parent_id = bench.child_b

    # The cycle takes its whole subtree with it: nothing below `root_a` hangs off
    # a root any more either.
    assert unreachable_node_ids(revision) == sorted(
        [bench.root_a, bench.child_b, bench.labor, bench.supply]
    )
    assert [node.id for level in levels(revision) for node in level] == [
        bench.root_c,
        bench.global_cost,
    ]


def test_depth_first_skips_a_node_hanging_from_a_missing_parent(bench: Bench) -> None:
    """The read helpers stay total on a state the checker would reject (INV-09)."""
    revision = bench.revision
    revision.nodes[bench.root_c].parent_id = 4242

    assert bench.root_c not in [node.id for node in depth_first(revision)]
    assert ancestors_of(revision, bench.root_c) == []


# --------------------------------------------------------------------------------------
# Defensive paths of the checker and of the re-import
# --------------------------------------------------------------------------------------


def test_check_all_invariants_walks_every_revision_of_the_project(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    other = create_revision(project)
    add_task(project, other, name="Sound")

    assert check_all_invariants(project) == []

    revision.nodes[bench.root_c].position = 9
    other.plan_facets[next(iter(other.plan_facets))].calendar_id = None

    assert violated_invariant_ids(check_all_invariants(project)) == ["INV-05", "INV-15"]


def test_a_non_labor_line_missing_its_debours_is_reported(bench: Bench) -> None:
    bench.revision.cost_facets[bench.supply].unit_cost = None

    assert violated_invariant_ids(check_invariants(bench.project, bench.revision)) == ["INV-20"]


def test_an_undeclared_attribute_on_a_frozen_line_is_reported(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)

    setattr(revision.frozen_lines[0], "grid_row", 3)  # noqa: B010

    assert violated_invariant_ids(check_invariants(project, revision)) == ["INV-23"]


def test_an_explicit_calendar_at_creation_is_recorded_as_manual(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    node = add_task(project, revision, name="Pinned", calendar_id=77)

    assert revision.plan_facets[node.id].calendar_id == 77
    assert revision.plan_facets[node.id].calendar_source is CalendarSource.MANUAL
    assert_sound(project, revision)


def test_asking_for_a_manual_calendar_without_naming_one_is_refused(bench: Bench) -> None:
    """``manual`` means "the user pinned this calendar": there has to be one.

    Refused rather than silently downgraded to ``project``, like every other
    contradictory input of this module -- a downgrade would hand back a facet the
    caller never asked for, and the next role assignment would overwrite it.
    """
    project, revision = bench.project, bench.revision
    work_items_before = copy.deepcopy(project.work_items)
    counter_before = project.next_work_item_id

    with pytest.raises(FacetContractError):
        add_task(
            project,
            revision,
            name="Manuel sans calendrier",
            calendar_source=CalendarSource.MANUAL,
        )

    assert project.work_items == work_items_before
    # The id counter too: a refusal that burned an id would still have allocated
    # something, and "the refusal allocates nothing" is the whole property here.
    assert project.next_work_item_id == counter_before
    assert_sound(project, revision)

    # What is refused is the *missing* calendar, not the word ``manual``: the same
    # source with a calendar to pin goes through and is stored as given.
    pinned = add_task(
        project,
        revision,
        name="Manuel avec calendrier",
        calendar_id=77,
        calendar_source=CalendarSource.MANUAL,
    )

    assert revision.plan_facets[pinned.id].calendar_id == 77
    assert revision.plan_facets[pinned.id].calendar_source is CalendarSource.MANUAL
    assert_sound(project, revision)


def test_inserting_a_task_under_a_cost_line_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    with pytest.raises(FacetPlacementError):
        add_task(project, revision, name="Under a cost line", parent_id=bench.global_cost)


def test_a_non_positive_version_number_is_refused() -> None:
    project = build_project()

    with pytest.raises(RevisionLifecycleError):
        create_revision(project, version_number=0)


def test_a_reimport_naming_a_parent_defined_after_its_child_is_refused() -> None:
    """The parent *is* in the file: the fault is its order, not its absence.

    MS Project writes a depth-first file, so a child listed before its parent
    signals a malformed source -- a structure error (422 once the transport layer
    maps the domain exceptions), never a "not found" (404).
    """
    project = build_project()
    revision = build_draft(project)

    with pytest.raises(ImportStructureError):
        apply_reimport(
            project,
            revision,
            [
                ImportedTask(external_uid=2, name="Child", parent_external_uid=1),
                ImportedTask(external_uid=1, name="Parent"),
            ],
        )


def test_a_reimport_naming_a_parent_no_one_knows_is_refused_as_not_found() -> None:
    """The other half of the distinction: a parent neither the file nor the revision
    holds is genuinely missing, and stays a :class:`NotFoundError`."""
    project = build_project()
    revision = build_draft(project)

    with pytest.raises(NotFoundError):
        apply_reimport(
            project,
            revision,
            [ImportedTask(external_uid=1, name="Orpheline", parent_external_uid=99)],
        )


def test_a_reimport_on_an_empty_draft_builds_the_whole_tree() -> None:
    project = build_project()
    revision = build_draft(project)

    diff = apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="Parent"),
            ImportedTask(external_uid=2, name="Child", parent_external_uid=1),
        ],
    )

    assert [item.external_uid for item in diff.added] == [1, 2]
    assert diff.removed == () and diff.moved == ()
    assert [revision.plan_facets[node.id].name for node in depth_first(revision)] == [
        "Parent",
        "Child",
    ]
    assert_sound(project, revision)


def test_a_reimport_keeping_a_child_of_a_removed_summary_reparents_it(bench: Bench) -> None:
    """A task still in the file is reparented, not destroyed with its former parent."""
    project = build_project()
    revision = build_draft(project)
    summary = add_task(project, revision, name="Summary", external_uid=1)
    survivor = add_task(project, revision, name="Survivor", parent_id=summary.id, external_uid=2)
    doomed_sibling = add_task(
        project, revision, name="Doomed", parent_id=summary.id, external_uid=3
    )
    kept_line = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Chiffrage conservé",
        parent_id=survivor.id,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("10"),
    )
    lost_line = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Chiffrage perdu",
        parent_id=doomed_sibling.id,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("20"),
    )

    # The file drops the summary and task 3, and keeps task 2 at the root.
    tasks = [ImportedTask(external_uid=2, name="Survivor")]
    diff = plan_reimport(project, revision, tasks)

    # Every vanished task is listed, the summary and the child that went with it.
    assert [item.external_uid for item in diff.removed] == [1, 3]
    # The safeguard announces the line that really disappears, and only that one.
    assert [loss.node_id for loss in diff.cost_losses] == [lost_line.id]

    apply_reimport(project, revision, tasks)
    assert_sound(project, revision)

    assert summary.id not in revision.nodes
    assert doomed_sibling.id not in revision.nodes
    assert lost_line.id not in revision.cost_facets
    # The survivor kept its node, its work item and its cost line.
    assert revision.nodes[survivor.id].parent_id is None
    assert revision.nodes[survivor.id].work_item_id == survivor.work_item_id
    assert revision.cost_facets[kept_line.id].label == "Chiffrage conservé"


# --------------------------------------------------------------------------------------
# Atomicity of a creation: a refused command allocates nothing (INV-25 retry)
# --------------------------------------------------------------------------------------


def _refused_creations(bench: Bench) -> list[tuple[str, Callable[[], object]]]:
    project, revision = bench.project, bench.revision
    return [
        (
            "task at an impossible position",
            lambda: add_task(project, revision, name="Refusée", external_uid=42, position=9),
        ),
        (
            "task under an unknown parent",
            lambda: add_task(project, revision, name="Refusée", parent_id=4242),
        ),
        (
            "task under a cost line",
            lambda: add_task(project, revision, name="Refusée", parent_id=bench.global_cost),
        ),
        (
            "task reusing an external uid",
            lambda: add_task(project, revision, name="Refusée", external_uid=7),
        ),
        (
            "cost line at an impossible position",
            lambda: add_cost_line(
                project,
                revision,
                nature=CostNature.NON_LABOR,
                label="Refusée",
                position=9,
                cost_type_id=1,
                cost_category_id=10,
                unit_cost=Decimal("1"),
            ),
        ),
        (
            "MO line without a role",
            lambda: add_cost_line(
                project,
                revision,
                nature=CostNature.LABOR,
                label="Refusée",
                parent_id=bench.root_c,
                hours=Decimal("2"),
            ),
        ),
        (
            "cost line under an unknown parent",
            lambda: add_cost_line(
                project,
                revision,
                nature=CostNature.NON_LABOR,
                label="Refusée",
                parent_id=4242,
                cost_type_id=1,
                cost_category_id=10,
                unit_cost=Decimal("1"),
            ),
        ),
    ]


def test_a_refused_creation_allocates_no_work_item(bench: Bench) -> None:
    """A refused command leaves the project exactly as it was, counters included."""
    project, revision = bench.project, bench.revision
    project.work_items[revision.nodes[bench.root_a].work_item_id].external_uid = 7
    work_items_before = copy.deepcopy(project.work_items)
    counter_before = project.next_work_item_id
    revision_before = copy.deepcopy(revision)

    for label, attempt in _refused_creations(bench):
        with pytest.raises(RevisionDomainError):
            attempt()
        assert project.work_items == work_items_before, f"{label} allocated a work item"
        assert project.next_work_item_id == counter_before, f"{label} burnt an id"
        assert revision == revision_before, f"{label} mutated the revision"


def test_a_refused_creation_can_be_retried_with_the_same_external_uid(bench: Bench) -> None:
    """The regression: a refused entry used to make correcting that entry impossible."""
    project, revision = bench.project, bench.revision

    with pytest.raises(PositionError):
        add_task(project, revision, name="Saisie", external_uid=42, position=9)

    retried = add_task(project, revision, name="Saisie", external_uid=42, position=2)

    assert project.work_items[retried.work_item_id].external_uid == 42
    assert _names(bench, None) == ["A", "Saisie", "C", "Assurance chantier"]
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# Indent / outdent require a contiguous block of siblings
# --------------------------------------------------------------------------------------


def test_indent_of_a_non_contiguous_sibling_selection_is_refused() -> None:
    """B and D indented together would make D jump over the unselected C."""
    project = build_project()
    revision = build_draft(project)
    nodes = [add_task(project, revision, name=name).id for name in ("A", "B", "C", "D")]
    before = copy.deepcopy(revision)

    with pytest.raises(SelectionError):
        indent_nodes(project, revision, [nodes[1], nodes[3]])

    assert revision == before
    # The contiguous block starting at the same node is accepted.
    indent_nodes(project, revision, [nodes[1], nodes[2]])
    assert [node.id for node in children_of(revision, nodes[0])] == [nodes[1], nodes[2]]
    assert_sound(project, revision)


def test_outdent_of_a_non_contiguous_sibling_selection_is_refused() -> None:
    project = build_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="Parent")
    children = [
        add_task(project, revision, name=name, parent_id=parent.id).id
        for name in ("A", "B", "C", "D")
    ]
    before = copy.deepcopy(revision)

    with pytest.raises(SelectionError):
        outdent_nodes(project, revision, [children[1], children[3]])

    assert revision == before
    # The contiguous half of the very same selection is accepted.
    outdent_nodes(project, revision, [children[2], children[3]])
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# Cost facet attributes the public API has to expose
# --------------------------------------------------------------------------------------


def test_supply_status_is_refused_on_an_mo_line(bench: Bench) -> None:
    """The specification reserves ``supply_status`` to supplies."""
    revision = bench.revision
    before = revision.lock_version

    with pytest.raises(FacetContractError):
        set_supply_status(revision, bench.labor, SupplyStatus.ORDERED)

    assert revision.cost_facets[bench.labor].supply_status is None
    assert revision.lock_version == before


def test_a_planned_date_and_a_comment_are_settable_and_reach_the_frozen_line(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision

    line = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Provision pour aléas",
        cost_type_id=2,
        cost_category_id=10,
        unit_cost=Decimal("1000"),
        planned_date=date(2027, 3, 4),
        comment="à revoir après commande",
    )
    assert revision.cost_facets[line.id].planned_date == date(2027, 3, 4)
    assert revision.cost_facets[line.id].comment == "à revoir après commande"

    set_cost_planned_date(revision, line.id, date(2028, 1, 15))
    set_cost_comment(revision, line.id, "décalée en 2028")
    validate_revision(project, revision, now=NOW)

    frozen = next(item for item in revision.frozen_lines if item.label == "Provision pour aléas")
    assert frozen.year == 2028
    assert revision.cost_facets[line.id].comment == "décalée en 2028"
    assert_sound(project, revision)


def test_a_cost_line_without_a_planned_date_freezes_without_a_year(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    validate_revision(project, revision, now=NOW)

    assert {line.year for line in revision.frozen_lines} == {None}


def test_a_line_without_a_cost_category_freezes_without_a_category_code(bench: Bench) -> None:
    """A null category is a *null* category, never the sentinel key ``0``."""
    project, revision = bench.project, bench.revision
    project.cost_categories[0] = "SENTINELLE"
    # An MO line whose role the project no longer knows: no role category, and no
    # category of its own either (INV-19 forbids one on an MO line).
    del project.roles[1]

    validate_revision(project, revision, now=NOW)

    frozen = next(line for line in revision.frozen_lines if line.label == "Étude")
    assert frozen.category_code is None


# --------------------------------------------------------------------------------------
# Validation is all-or-nothing
# --------------------------------------------------------------------------------------


def _exploding_amount(project: Project, facet: CostFacet) -> Decimal:
    raise ArithmeticError(f"no rate table for {facet.label} of project {project.id}")


def test_a_validation_failing_midway_leaves_the_previous_revision_validated(
    bench: Bench,
) -> None:
    """Superseding before the frozen lines are built would leave the project without one."""
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    second = copy_revision(project, revision, now=NOW)

    with pytest.raises(ArithmeticError):
        validate_revision(project, second, now=NOW, amount_of=_exploding_amount)

    assert revision.status is RevisionStatus.VALIDATED
    assert second.status is RevisionStatus.DRAFT
    assert second.frozen_lines == []
    assert second.lock_version == 0
    assert check_all_invariants(project) == []


def test_a_successful_validation_bumps_the_lock_version_once(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    before = revision.lock_version

    validate_revision(project, revision, now=NOW)

    assert revision.lock_version == before + 1


# --------------------------------------------------------------------------------------
# Re-import: the file is validated as a whole before a single node is touched
# --------------------------------------------------------------------------------------


def test_a_reimport_naming_a_parent_the_file_does_not_list_is_refused() -> None:
    """The named parent is a node this very import removes: applying it would
    reparent the survivor into a doomed subtree and destroy unannounced chiffrage."""
    project = build_project()
    revision = build_draft(project)
    add_task(project, revision, name="OldParent", external_uid=10)
    kid = add_task(project, revision, name="Kid", external_uid=11)
    add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Chiffrage du Kid",
        parent_id=kid.id,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("99"),
    )
    tasks = [ImportedTask(external_uid=11, name="Kid", parent_external_uid=10)]

    with pytest.raises(ImportStructureError):
        plan_reimport(project, revision, tasks)


def test_a_refused_reimport_keeps_the_chiffrage_it_would_have_destroyed() -> None:
    project = build_project()
    revision = build_draft(project)
    add_task(project, revision, name="OldParent", external_uid=10)
    kid = add_task(project, revision, name="Kid", external_uid=11)
    line = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Chiffrage du Kid",
        parent_id=kid.id,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("99"),
    )
    before = copy.deepcopy(revision)

    with pytest.raises(ImportStructureError):
        apply_reimport(
            project,
            revision,
            [ImportedTask(external_uid=11, name="Kid", parent_external_uid=10)],
        )

    assert line.id in revision.cost_facets
    assert revision == before
    assert_sound(project, revision)


def test_a_reimport_whose_parent_chain_closes_a_cycle_is_refused() -> None:
    """Reparenting straight from the file used to build a cycle the checker
    could only report afterwards, with both nodes unreachable for good (INV-06)."""
    project = build_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="A", external_uid=1)
    add_task(project, revision, name="B", parent_id=parent.id, external_uid=2)
    before = copy.deepcopy(revision)

    with pytest.raises(TreeCycleError):
        apply_reimport(
            project,
            revision,
            [
                ImportedTask(external_uid=1, name="A", parent_external_uid=2),
                ImportedTask(external_uid=2, name="B", parent_external_uid=1),
            ],
        )

    assert revision == before
    assert_sound(project, revision)


def test_a_reimport_refused_on_its_second_task_leaves_the_revision_untouched() -> None:
    """The faulty task sits *after* a valid one, so the naive order would already
    have created a node and bumped ``lock_version`` before giving up."""
    project = build_project()
    revision = build_draft(project)
    revision_before = copy.deepcopy(revision)
    work_items_before = copy.deepcopy(project.work_items)

    with pytest.raises(NotFoundError):
        apply_reimport(
            project,
            revision,
            [
                ImportedTask(external_uid=1, name="OK"),
                ImportedTask(external_uid=2, name="Bad", parent_external_uid=99),
            ],
        )

    assert revision == revision_before
    assert revision.nodes == {}
    assert revision.lock_version == 0
    assert project.work_items == work_items_before


def test_a_reimport_reparenting_a_task_resynchronises_the_calendars() -> None:
    """Rule 1: a re-import moves MO assignments across subtrees exactly as a move does."""
    project = build_project()
    revision = build_draft(project)
    first = add_task(project, revision, name="T1", external_uid=1)
    second = add_task(project, revision, name="T2", external_uid=2)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Étude",
        parent_id=first.id,
        role_id=1,
        hours=Decimal("10"),
    )
    assert revision.plan_facets[first.id].calendar_source is CalendarSource.ROLE
    assert revision.plan_facets[second.id].calendar_source is CalendarSource.PROJECT

    apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=2, name="T2"),
            ImportedTask(external_uid=1, name="T1", parent_external_uid=2),
        ],
    )

    assert revision.nodes[first.id].parent_id == second.id
    assert revision.plan_facets[second.id].calendar_source is CalendarSource.ROLE
    assert revision.plan_facets[second.id].calendar_id == ROLE_CALENDAR_ID
    assert_sound(project, revision)


def test_reimporting_the_same_file_into_two_revisions_reuses_the_work_items() -> None:
    """``external_uid`` identifies a work item **per project**, not per revision:
    a second revision importing the same file must land on the same identities,
    or the forecast/budget reconciliation would have nothing left to join on."""
    project = build_project()
    first = build_draft(project)
    second = create_revision(project)
    tasks = [
        ImportedTask(external_uid=1, name="Parent"),
        ImportedTask(external_uid=2, name="Child", parent_external_uid=1),
    ]

    apply_reimport(project, first, tasks)
    apply_reimport(project, second, tasks)

    assert [node.work_item_id for node in depth_first(first)] == [
        node.work_item_id for node in depth_first(second)
    ]
    assert not set(first.nodes) & set(second.nodes)
    assert len([item for item in project.work_items.values() if item.external_uid == 1]) == 1
    assert check_all_invariants(project) == []


def test_a_reimport_reports_a_move_away_from_a_parent_created_in_waterfall() -> None:
    """A local parent has no ``external_uid``: comparing uids read "root" on both
    sides and under-reported a move the apply step really performed."""
    project = build_project()
    revision = build_draft(project)
    local = add_task(project, revision, name="Local (jamais exporté)")
    imported = add_task(project, revision, name="Imported", parent_id=local.id, external_uid=1)
    tasks = [ImportedTask(external_uid=1, name="Imported")]

    diff = plan_reimport(project, revision, tasks)

    assert [item.external_uid for item in diff.moved] == [1]
    assert diff.removed == ()

    applied = apply_reimport(project, revision, tasks)

    assert applied.moved == diff.moved
    assert revision.nodes[imported.id].parent_id is None
    assert local.id in revision.nodes
    assert_sound(project, revision)


def test_a_reimport_reports_a_move_under_a_task_the_same_file_creates() -> None:
    """The expected parent does not exist yet, so the move cannot be missed."""
    project = build_project()
    revision = build_draft(project)
    existing_node = add_task(project, revision, name="Imported", external_uid=1)
    tasks = [
        ImportedTask(external_uid=2, name="NewParent"),
        ImportedTask(external_uid=1, name="Imported", parent_external_uid=2),
    ]

    diff = plan_reimport(project, revision, tasks)

    assert [item.external_uid for item in diff.moved] == [1]
    assert [item.external_uid for item in diff.added] == [2]

    apply_reimport(project, revision, tasks)

    assert revision.nodes[existing_node.id].parent_id is not None
    assert_sound(project, revision)


def test_a_reimport_renumbers_a_parent_the_file_gives_no_child() -> None:
    """The file moves the only task of a parent away and leaves its cost line behind.

    That parent appears in no ``file_children`` entry and is not the parent of any
    removed node either, so only the fallback renumbering keeps its remaining cost
    child contiguous (INV-05).
    """
    project = build_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="Parent", external_uid=1)
    child = add_task(project, revision, name="Child", parent_id=parent.id, external_uid=2)
    kept = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Chiffrage conservé",
        parent_id=parent.id,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("15"),
    )
    other = add_task(project, revision, name="Other", external_uid=3)
    assert revision.nodes[kept.id].position == 2

    diff = apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="Parent"),
            ImportedTask(external_uid=3, name="Other"),
            ImportedTask(external_uid=2, name="Child", parent_external_uid=3),
        ],
    )

    assert [item.external_uid for item in diff.moved] == [2]
    assert diff.removed == () and diff.cost_losses == ()
    assert revision.nodes[child.id].parent_id == other.id
    assert revision.nodes[kept.id].position == 1
    assert_sound(project, revision)


def test_a_reimport_that_reparents_and_deletes_its_mo_line_refreshes_the_former_ancestor() -> None:
    """Rule 1, case 4: the guard is read *before* the deletions, or the former
    ancestor keeps the calendar of a role its subtree no longer carries.

    The file does both at once: it pulls ``branch`` out of ``former`` **and** drops
    the task that bore the MO line. Reading "does this file move chiffrage around"
    after the deletion answers "no" -- the reparented subtree no longer carries MO
    by then -- and ``delete_nodes`` cannot make up for it: it resynchronises from
    the parent of the deleted node upwards, a chain the reparenting has just taken
    ``former`` out of. No state invariant catches the result: INV-15 checks that a
    calendar is present, not that it is fresh.
    """
    project = build_project()
    revision = build_draft(project)
    former = add_task(project, revision, name="Ancien parent", external_uid=1)
    branch = add_task(project, revision, name="Branche", parent_id=former.id, external_uid=2)
    bearer = add_task(project, revision, name="Porteuse", parent_id=branch.id, external_uid=3)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="Étude",
        parent_id=bearer.id,
        role_id=1,
        hours=Decimal("10"),
    )
    for node_id in (former.id, branch.id, bearer.id):
        assert revision.plan_facets[node_id].calendar_source is CalendarSource.ROLE

    apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="Ancien parent"),
            ImportedTask(external_uid=2, name="Branche"),
        ],
    )

    assert revision.plan_facets[former.id].calendar_source is CalendarSource.PROJECT
    assert revision.plan_facets[former.id].calendar_id == project.calendar_id
    assert revision.plan_facets[branch.id].calendar_source is CalendarSource.PROJECT
    assert revision.plan_facets[branch.id].calendar_id == project.calendar_id
    assert_sound(project, revision)


def test_a_reimport_pushes_a_task_created_in_waterfall_after_the_imported_ones() -> None:
    """Rule 3 a: a local task is never removed nor promoted, but it does end up
    after the imported siblings -- the file carries no position for it, exactly as
    it carries none for a cost line."""
    project = build_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="Parent", external_uid=1)
    local = add_task(project, revision, name="Locale", parent_id=parent.id)
    imported = add_task(project, revision, name="Importée", parent_id=parent.id, external_uid=2)
    assert [revision.nodes[node].position for node in (local.id, imported.id)] == [1, 2]

    diff = apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="Parent"),
            ImportedTask(external_uid=2, name="Importée", parent_external_uid=1),
        ],
    )

    assert diff.removed == () and diff.cost_losses == ()
    assert revision.nodes[imported.id].position == 1
    assert revision.nodes[local.id].position == 2
    assert revision.nodes[local.id].parent_id == parent.id
    assert_sound(project, revision)


def _two_calendar_project() -> Project:
    """A project with two MO roles carrying **different** calendars.

    The standard bench gives role 1 a calendar and role 2 none, so the order of
    two MO facets almost never decides anything. It has to here: Rule 1 resolves
    on the *first* MO facet in depth-first order, so two competing calendars are
    what makes reordering observable.
    """
    project = build_project()
    project.roles[3] = Role(
        id=3,
        name="Chef de projet",
        calendar_id=SECOND_ROLE_CALENDAR_ID,
        category_code="MO-CDP",
        accounting_code="641200",
        hourly_rate=Decimal("95.00"),
    )
    return project


def test_a_reimport_that_changes_nothing_still_refreshes_the_calendars() -> None:
    """Rule 1 resolves on an *order*, and a re-import reorders even when it changes
    nothing at all.

    The file here is strictly identical to the tree: ``added``, ``moved`` and
    ``removed`` are all empty. But the re-import still puts the file's tasks before
    the cost lines of the same parent, so ``C`` overtakes the MO line hanging
    directly under ``P`` -- and the first MO facet in depth-first order of ``P``'s
    subtree becomes the one under ``C``, carrying another calendar. The *set* of
    assignments did not change by one element; the answer Rule 1 gives did.

    No state invariant catches the stale result: INV-15 checks that a calendar is
    present, never that it is fresh. And the user changed nothing -- they merely
    re-imported their file.
    """
    project = _two_calendar_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="P", external_uid=1)
    direct = add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="MO directe",
        parent_id=parent.id,
        role_id=1,
        hours=Decimal("10"),
    )
    child = add_task(project, revision, name="C", parent_id=parent.id, external_uid=2)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="MO de l'enfant",
        parent_id=child.id,
        role_id=3,
        hours=Decimal("5"),
    )
    assert revision.plan_facets[parent.id].calendar_id == ROLE_CALENDAR_ID

    diff = apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="P"),
            ImportedTask(external_uid=2, name="C", parent_external_uid=1),
        ],
    )

    assert (diff.added, diff.moved, diff.removed) == ((), (), ())
    assert (revision.nodes[child.id].position, revision.nodes[direct.id].position) == (1, 2)
    assert revision.plan_facets[parent.id].calendar_id == SECOND_ROLE_CALENDAR_ID
    assert revision.plan_facets[parent.id].calendar_source is CalendarSource.ROLE
    assert_sound(project, revision)


def test_a_reimport_pushing_a_local_mo_bearing_task_back_refreshes_the_calendars() -> None:
    """Same defect, on the shape Rule 3 a froze: a **local** task bearing MO is
    pushed behind the imported sibling, which is exactly what invalidates Rule 1's
    answer for their common parent.

    Nothing is reparented here either -- only the rank of two siblings changes.
    """
    project = _two_calendar_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="P", external_uid=1)
    local = add_task(project, revision, name="Locale", parent_id=parent.id)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="MO locale",
        parent_id=local.id,
        role_id=1,
        hours=Decimal("10"),
    )
    imported = add_task(project, revision, name="Importée", parent_id=parent.id, external_uid=2)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="MO importée",
        parent_id=imported.id,
        role_id=3,
        hours=Decimal("5"),
    )
    assert revision.plan_facets[parent.id].calendar_id == ROLE_CALENDAR_ID

    apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="P"),
            ImportedTask(external_uid=2, name="Importée", parent_external_uid=1),
        ],
    )

    assert (revision.nodes[imported.id].position, revision.nodes[local.id].position) == (1, 2)
    assert revision.plan_facets[parent.id].calendar_id == SECOND_ROLE_CALENDAR_ID
    assert revision.plan_facets[parent.id].calendar_source is CalendarSource.ROLE
    assert_sound(project, revision)


def test_a_reimport_leaves_a_manually_pinned_calendar_alone() -> None:
    """The terminal recomputation is unguarded, not indiscriminate: ``manual`` wins.

    Stated here because the guard that used to spare the whole walk is gone, so the
    only thing left protecting a user's explicit choice is the precedence rule
    itself (``manual`` > ``role`` > ``project``).
    """
    project = _two_calendar_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="P", external_uid=1)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="MO directe",
        parent_id=parent.id,
        role_id=1,
        hours=Decimal("10"),
    )
    child = add_task(project, revision, name="C", parent_id=parent.id, external_uid=2)
    add_cost_line(
        project,
        revision,
        nature=CostNature.LABOR,
        label="MO de l'enfant",
        parent_id=child.id,
        role_id=3,
        hours=Decimal("5"),
    )
    set_task_calendar_manually(revision, parent.id, 404)

    apply_reimport(
        project,
        revision,
        [
            ImportedTask(external_uid=1, name="P"),
            ImportedTask(external_uid=2, name="C", parent_external_uid=1),
        ],
    )

    assert revision.plan_facets[parent.id].calendar_id == 404
    assert revision.plan_facets[parent.id].calendar_source is CalendarSource.MANUAL
    assert_sound(project, revision)
