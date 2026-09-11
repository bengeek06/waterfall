"""One deliberate violation per invariant of ``docs/revision-v0.1-specification.md``.

Acceptance test of E14-02: *every* invariant INV-01..INV-26 must have at least one
test that fails when it is violated on purpose. Each test below reproduces the
"violation canonique" the specification documents for its invariant, and then:

* for an ``état``-scoped invariant, asserts that
  :func:`~waterfall.domain.revision.invariants.check_invariants` names it;
* for an ``opération``-scoped invariant (INV-02, INV-03, INV-07), asserts that the
  operation refuses the forbidden command and leaves the state unchanged, or that
  its post-condition holds.

Where a canonical violation unavoidably breaks a second invariant as well (a
self-predecessor is also a one-node precedence cycle, for instance), the test
asserts membership rather than an exact set, and says so.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from types import ModuleType

import pytest

import waterfall.domain.revision as package
from _revision_domain_support import (
    Bench,
    assert_sound,
    build_bench,
    build_draft,
    build_project,
    cost_facet,
    plan_facet,
    raw_link,
    raw_node,
    violations_of,
)
from waterfall.domain.revision import (
    CalendarSource,
    CostNature,
    CrossRevisionError,
    DuplicateWorkItemError,
    ExternalUidError,
    FacetContractError,
    FacetPlacementError,
    ImmutableRevisionError,
    LinkError,
    Project,
    ProjectRevision,
    RevisionKind,
    RevisionLifecycleError,
    RevisionStatus,
    SupplyStatus,
    TreeCycleError,
    WorkItemKind,
    add_cost_line,
    add_link,
    add_task,
    apply_reimport,
    bearing_work_item_id,
    check_invariants,
    compact_positions,
    copy_revision,
    create_revision,
    create_work_item,
    delete_nodes,
    depth_first,
    facets,
    indent_nodes,
    insert_node,
    move_nodes,
    move_nodes_down,
    move_nodes_up,
    outdent_nodes,
    subtree_ids,
    tree,
    validate_revision,
    violated_invariant_ids,
    work_breakdown,
)
from waterfall.domain.revision.entities import (
    BreakdownEntry,
    BreakdownKind,
    ProjectStatus,
    SkeletonFingerprint,
)
from waterfall.domain.revision.facets import (
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
from waterfall.domain.revision.invariants import (
    OPERATION_SCOPED_INVARIANTS,
    STATE_SCOPED_INVARIANTS,
)
from waterfall.domain.revision.work_breakdown import (
    generate_skeleton,
    regenerate_skeleton,
    save_work_breakdown,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def bench() -> Bench:
    return build_bench()


def test_every_specified_invariant_has_a_declared_scope() -> None:
    """The 26 invariants of the specification are all accounted for, exactly once."""
    declared = set(STATE_SCOPED_INVARIANTS) | OPERATION_SCOPED_INVARIANTS
    assert declared == {f"INV-{number:02d}" for number in range(1, 27)}
    assert len(STATE_SCOPED_INVARIANTS) + len(OPERATION_SCOPED_INVARIANTS) == 26


def test_the_reference_bench_violates_nothing(bench: Bench) -> None:
    assert_sound(bench.project, bench.revision)


# --------------------------------------------------------------------------------------
# INV-01 -- bearing task is the first strict planning ancestor
# --------------------------------------------------------------------------------------


def test_inv_01_bearing_task_resolves_to_the_first_strict_planning_ancestor(
    bench: Bench,
) -> None:
    revision = bench.revision
    assert bearing_work_item_id(revision, bench.labor) == (
        revision.nodes[bench.child_b].work_item_id
    )
    assert bearing_work_item_id(revision, bench.supply) == (
        revision.nodes[bench.root_a].work_item_id
    )
    # Root reached without meeting a planning facet: a global project cost.
    assert bearing_work_item_id(revision, bench.global_cost) is None


def test_inv_01_violated_by_memorising_a_stale_bearing_task(bench: Bench) -> None:
    """Canonical violation: memorise a bearing task that is not the first ancestor."""
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    assert_sound(project, revision)

    line = next(
        frozen
        for frozen in revision.frozen_lines
        if frozen.work_item_id == revision.nodes[bench.labor].work_item_id
    )
    line.bearing_work_item_id = revision.nodes[bench.root_c].work_item_id

    assert "INV-01" in violations_of(project, revision)


# --------------------------------------------------------------------------------------
# INV-02 -- deleting a node deletes its subtree and both facets (opération)
# --------------------------------------------------------------------------------------


def test_inv_02_delete_removes_the_whole_subtree_and_both_facets(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    add_link(revision, node_id=bench.child_b, predecessor_node_id=bench.root_c)
    doomed = subtree_ids(revision, bench.root_a)
    assert set(doomed) == {bench.root_a, bench.child_b, bench.labor, bench.supply}

    report = delete_nodes(project, revision, [bench.root_a])

    assert set(report.removed_node_ids) == set(doomed)
    for node_id in doomed:
        assert node_id not in revision.nodes
        assert node_id not in revision.plan_facets
        assert node_id not in revision.cost_facets
    assert not [
        link
        for link in revision.links
        if link.node_id in doomed or link.predecessor_node_id in doomed
    ]
    # Siblings of the deleted node are renumbered contiguously (INV-05).
    assert [node.position for node in depth_first(revision)] == [1, 2]
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# INV-03 -- a validated or superseded revision is immutable, on both facets (opération)
# --------------------------------------------------------------------------------------


def _write_attempts(bench: Bench) -> list[tuple[str, Callable[[], object]]]:
    """Every write the domain exposes, tree and both facets, plus the re-import.

    Exhaustive on purpose: each of these calls ``require_draft``, but nothing
    would stop a new operation from forgetting to, so the matrix is the guard.
    """
    project, revision = bench.project, bench.revision
    return [
        ("add_task", lambda: add_task(project, revision, name="new")),
        (
            "add_cost_line",
            lambda: add_cost_line(
                project,
                revision,
                nature=CostNature.NON_LABOR,
                label="new",
                cost_type_id=1,
                cost_category_id=10,
                unit_cost=Decimal("1"),
            ),
        ),
        (
            "insert_node",
            lambda: insert_node(
                project,
                revision,
                work_item_id=create_work_item(project, WorkItemKind.TASK).id,
                plan=plan_facet("new"),
            ),
        ),
        ("move_nodes", lambda: move_nodes(project, revision, [bench.child_b])),
        ("move_nodes_up", lambda: move_nodes_up(project, revision, [bench.root_c])),
        ("move_nodes_down", lambda: move_nodes_down(project, revision, [bench.root_a])),
        ("indent_nodes", lambda: indent_nodes(project, revision, [bench.root_c])),
        ("outdent_nodes", lambda: outdent_nodes(project, revision, [bench.child_b])),
        ("delete_nodes", lambda: delete_nodes(project, revision, [bench.child_b])),
        ("compact_positions", lambda: compact_positions(revision)),
        (
            "add_link",
            lambda: add_link(revision, node_id=bench.child_b, predecessor_node_id=bench.root_c),
        ),
        ("apply_reimport", lambda: apply_reimport(project, revision, [])),
        ("rename_task", lambda: rename_task(revision, bench.root_a, "renamed")),
        ("set_task_duration", lambda: set_task_duration(revision, bench.root_a, 999)),
        (
            "set_task_dates",
            lambda: set_task_dates(revision, bench.root_a, start_at=NOW, finish_at=NOW),
        ),
        (
            "set_task_calendar_manually",
            lambda: set_task_calendar_manually(revision, bench.root_a, 99),
        ),
        (
            "clear_task_calendar_override",
            lambda: clear_task_calendar_override(project, revision, bench.child_b),
        ),
        (
            "assign_role",
            lambda: assign_role(project, revision, bench.labor, role_id=2, hours=Decimal("99")),
        ),
        (
            "set_cost_quantity",
            lambda: set_cost_quantity(revision, bench.supply, Decimal("99")),
        ),
        ("set_cost_hours", lambda: set_cost_hours(revision, bench.labor, Decimal("99"))),
        (
            "set_cost_unit_cost",
            lambda: set_cost_unit_cost(revision, bench.supply, Decimal("99")),
        ),
        ("set_cost_label", lambda: set_cost_label(revision, bench.supply, "relabelled")),
        (
            "set_supply_status",
            lambda: set_supply_status(revision, bench.supply, SupplyStatus.ORDERED),
        ),
        (
            "set_cost_planned_date",
            lambda: set_cost_planned_date(revision, bench.supply, date(2027, 1, 1)),
        ),
        ("set_cost_comment", lambda: set_cost_comment(revision, bench.supply, "commented")),
        ("validate_revision", lambda: validate_revision(project, revision, now=NOW)),
        ("generate_skeleton", lambda: generate_skeleton(project, revision)),
        ("regenerate_skeleton", lambda: regenerate_skeleton(project, revision)),
    ]


@pytest.mark.parametrize("status", [RevisionStatus.VALIDATED, RevisionStatus.SUPERSEDED])
def test_inv_03_every_write_is_refused_with_the_same_error(
    bench: Bench, status: RevisionStatus
) -> None:
    """Canonical violation: accept an MO hours edit, or a move "only" touching planning."""
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    revision.status = status
    before = copy.deepcopy(revision)

    for label, attempt in _write_attempts(bench):
        with pytest.raises(ImmutableRevisionError):
            attempt()
        assert revision == before, f"{label} mutated a {status.value} revision"
        assert revision.lock_version == before.lock_version


def test_inv_03_the_write_matrix_covers_every_facet_write() -> None:
    """Guards the matrix itself: a new facet write must be added to it, not forgotten."""
    covered = {label for label, _ in _write_attempts(build_bench())}
    exposed = {
        name
        for name, value in vars(facets).items()
        if not name.startswith("_")
        and callable(value)
        and getattr(value, "__module__", "") == facets.__name__
    }

    assert exposed, "no facet write found: the introspection no longer sees the module"
    assert exposed <= covered, f"facet writes missing from the INV-03 matrix: {exposed - covered}"


#: Public callables of ``tree`` that **never write the revision**, and therefore
#: owe nothing to INV-03. Spelled out one by one on purpose: a new operation is a
#: *write* until this list says otherwise, so forgetting to add it to the matrix
#: above fails the test rather than passing unnoticed.
#:
#: "Never writes the revision" is the exact claim, and it is narrower than "reads
#: the state": ``create_work_item`` does write -- it registers a ``work_item`` and
#: bumps a counter -- but on the **project**, which INV-03 does not freeze. An
#: operation that rewrites so much as a node position belongs in the matrix, not
#: here; ``_renumber_children`` is the reason this comment says so, and the reason
#: it is private (see the test just below).
_TREE_READERS = frozenset(
    {
        "carries_labor",
        "check_external_uid_available",
        "cost_losses_of",
        "create_work_item",
        "describe_cost_losses",
        "links_of",
        # Addressing guard, not a write: it raises on an unknown node and returns
        # the node otherwise, on a validated revision exactly as on a draft --
        # reading a frozen revision is what INV-03 explicitly still allows.
        "require_node",
        "selection_roots",
    }
)

#: Same list for ``work_breakdown``: the lotissement is project data (INV-26), so
#: saving it writes nothing a validated revision freezes, and the three skeleton
#: predicates only read.
_BREAKDOWN_READERS = frozenset(
    {
        "breakdown_changed_since_generation",
        "can_regenerate_skeleton",
        "save_work_breakdown",
        "skeleton_fingerprint_of",
    }
)


def _public_operations(namespace: Mapping[str, object], module_name: str) -> set[str]:
    """Public callables ``module_name`` itself defines, dataclasses excluded."""
    return {
        name
        for name, value in namespace.items()
        if not name.startswith("_")
        and callable(value)
        and not isinstance(value, type)  # the dataclasses the module exports
        and getattr(value, "__module__", "") == module_name
    }


@pytest.mark.parametrize(
    ("module", "readers"),
    [(tree, _TREE_READERS), (work_breakdown, _BREAKDOWN_READERS)],
    ids=["tree", "work_breakdown"],
)
def test_inv_03_the_write_matrix_covers_every_tree_write(
    module: ModuleType, readers: frozenset[str]
) -> None:
    """Same guard as above, on the operation modules: the matrix is the only thing
    that proves a *new* operation did not forget its ``require_draft``."""
    covered = {label for label, _ in _write_attempts(build_bench())}
    exposed = _public_operations(vars(module), module.__name__) - readers

    assert exposed, f"no {module.__name__} write found: the introspection sees nothing"
    assert exposed <= covered, f"writes missing from the INV-03 matrix: {exposed - covered}"


def test_the_write_matrix_guard_fails_on_a_write_blessed_as_a_reader() -> None:
    """The guard above only has value if it *fails* on a write nobody declared.

    Reproduces the exact shape the round-3 review found: a public callable of
    ``tree`` that rewrites node positions, carries no ``require_draft``, and sits
    in the reader whitelist. Whitelisted, it passes unnoticed; take it out of the
    whitelist without giving it a guard and the meta-test names it.
    """

    def renumber_children(revision: ProjectRevision, parent_id: int | None) -> None:
        tree._renumber_children(revision, parent_id)  # pyright: ignore[reportPrivateUsage]

    renumber_children.__module__ = tree.__name__
    namespace = {**vars(tree), "renumber_children": renumber_children}
    covered = {label for label, _ in _write_attempts(build_bench())}

    blessed = _public_operations(namespace, tree.__name__) - (_TREE_READERS | {"renumber_children"})
    unmasked = _public_operations(namespace, tree.__name__) - _TREE_READERS

    assert blessed <= covered, "the whitelisted write is reported anyway: the setup is wrong"
    assert "renumber_children" in unmasked - covered


def test_renumber_children_is_private_because_it_writes_without_a_draft_guard(
    bench: Bench,
) -> None:
    """M-3: it rewrites positions on a *validated* revision and raises nothing.

    That is precisely why it is not on the package surface: ``__all__`` is the
    boundary E14-04 consumes, and a caller reaching this one would mutate a frozen
    revision without INV-03 ever being consulted. Every internal caller runs
    ``require_draft`` first, so nothing is broken -- the hole was the *declared*
    surface, not any live path.
    """
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    revision.nodes[bench.root_c].position = 42

    tree._renumber_children(revision, None)  # pyright: ignore[reportPrivateUsage]

    assert revision.nodes[bench.root_c].position != 42
    assert "renumber_children" not in package.__all__
    assert "renumber_children" not in _TREE_READERS


# --------------------------------------------------------------------------------------
# INV-04 -- a work_item appears at most once per revision
# --------------------------------------------------------------------------------------


def test_inv_04_violated_by_two_nodes_sharing_a_work_item(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    raw_node(
        project,
        revision,
        work_item_id=revision.nodes[bench.root_c].work_item_id,
        parent_id=bench.root_c,
        plan=plan_facet("duplicate"),
    )

    assert violations_of(project, revision) == ["INV-04"]


def test_inv_04_insertion_refuses_a_work_item_already_placed(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    with pytest.raises(DuplicateWorkItemError, match="already occupies node"):
        insert_node(
            project,
            revision,
            work_item_id=revision.nodes[bench.root_c].work_item_id,
            plan=plan_facet("duplicate"),
        )


# --------------------------------------------------------------------------------------
# INV-05 -- sibling positions are contiguous from 1
# --------------------------------------------------------------------------------------


def test_inv_05_violated_by_a_hole_in_the_sibling_positions(bench: Bench) -> None:
    bench.revision.nodes[bench.root_c].position = 7

    assert violations_of(bench.project, bench.revision) == ["INV-05"]


def test_inv_05_violated_by_two_siblings_sharing_a_position(bench: Bench) -> None:
    bench.revision.nodes[bench.root_c].position = bench.revision.nodes[bench.root_a].position

    assert violations_of(bench.project, bench.revision) == ["INV-05"]


# --------------------------------------------------------------------------------------
# INV-06 -- the parent graph is acyclic
# --------------------------------------------------------------------------------------


def test_inv_06_violated_by_a_node_becoming_its_own_ancestor() -> None:
    project = build_project()
    revision = build_draft(project)
    parent = add_task(project, revision, name="parent")
    child = add_task(project, revision, name="child", parent_id=parent.id)
    assert_sound(project, revision)

    revision.nodes[parent.id].parent_id = child.id

    assert violations_of(project, revision) == ["INV-06"]


def test_inv_06_move_under_own_descendant_is_refused(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    before = copy.deepcopy(revision)

    with pytest.raises(TreeCycleError):
        move_nodes(project, revision, [bench.root_a], target_parent_id=bench.child_b)

    assert revision == before


# --------------------------------------------------------------------------------------
# INV-07 -- copying a revision reproduces tree and facets on the same work items
# --------------------------------------------------------------------------------------


def test_inv_07_copy_reproduces_the_tree_on_the_same_work_items(bench: Bench) -> None:
    project, source = bench.project, bench.revision
    add_link(source, node_id=bench.child_b, predecessor_node_id=bench.root_c)
    validate_revision(project, source, now=NOW)
    source_before = copy.deepcopy(source)

    duplicate = copy_revision(project, source, now=NOW)

    assert len(duplicate.nodes) == len(source.nodes)
    assert [node.work_item_id for node in depth_first(duplicate)] == [
        node.work_item_id for node in depth_first(source)
    ]
    assert [
        duplicate.plan_facets[node.id].name
        for node in depth_first(duplicate)
        if node.id in duplicate.plan_facets
    ] == [
        source.plan_facets[node.id].name
        for node in depth_first(source)
        if node.id in source.plan_facets
    ]
    # No node identity is shared, and the links were retranslated onto the copy.
    assert not set(duplicate.nodes) & set(source.nodes)
    assert len(duplicate.links) == len(source.links)
    for link in duplicate.links:
        assert link.node_id in duplicate.nodes
        assert link.predecessor_node_id in duplicate.nodes
    # A draft copy carries no frozen line (INV-24) and leaves its source untouched.
    assert duplicate.frozen_lines == []
    assert source == source_before
    assert_sound(project, duplicate)


# --------------------------------------------------------------------------------------
# INV-08 -- a predecessor designates a node of the same revision
# --------------------------------------------------------------------------------------


def test_inv_08_violated_by_a_link_pointing_outside_the_revision(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    other = create_revision(project)
    foreign = add_task(project, other, name="foreign")

    raw_link(revision, bench.child_b, foreign.id)

    assert violations_of(project, revision) == ["INV-08"]


def test_inv_08_link_creation_refuses_a_foreign_node(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    other = create_revision(project)
    foreign = add_task(project, other, name="foreign")

    with pytest.raises(CrossRevisionError, match="does not belong to revision"):
        add_link(revision, node_id=bench.child_b, predecessor_node_id=foreign.id)


# --------------------------------------------------------------------------------------
# INV-09 -- a node and its parent belong to the same revision
# --------------------------------------------------------------------------------------


def test_inv_09_violated_by_a_parent_outside_the_revision(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    other = create_revision(project)
    foreign = add_task(project, other, name="foreign")

    # The last root sibling, so that detaching it leaves the others contiguous
    # and the checker reports INV-09 alone.
    revision.nodes[bench.global_cost].parent_id = foreign.id

    assert violations_of(project, revision) == ["INV-09"]


# --------------------------------------------------------------------------------------
# INV-10 -- the work_item of a node belongs to the project of the revision
# --------------------------------------------------------------------------------------


def test_inv_10_violated_by_a_work_item_of_another_project(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    other_project = build_project(project_id=2)
    # Distinct id space, so the stranger does not shadow a work item of this project.
    other_project.next_work_item_id = 1000
    stranger = create_work_item(other_project, WorkItemKind.TASK)
    project.work_items[stranger.id] = stranger

    raw_node(
        project,
        revision,
        work_item_id=stranger.id,
        parent_id=bench.root_c,
        plan=plan_facet("stranger"),
    )

    assert violations_of(project, revision) == ["INV-10"]


# --------------------------------------------------------------------------------------
# INV-11 -- a node carries exactly one facet
# --------------------------------------------------------------------------------------


def test_inv_11_violated_by_a_node_without_any_facet(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    work_item = create_work_item(project, WorkItemKind.TASK)
    raw_node(project, revision, work_item_id=work_item.id, parent_id=bench.root_c)

    assert violations_of(project, revision) == ["INV-11"]


def test_inv_11_violated_by_a_node_carrying_both_facets(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    # Hung on a leaf task, so nothing else (INV-14 in particular) is disturbed.
    facet = cost_facet("smuggled onto a task")
    facet.node_id = bench.root_c
    revision.cost_facets[bench.root_c] = facet

    assert violations_of(project, revision) == ["INV-11"]


def test_inv_11_insertion_refuses_a_node_without_or_with_two_facets(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    work_item = create_work_item(project, WorkItemKind.TASK)

    with pytest.raises(FacetContractError):
        insert_node(project, revision, work_item_id=work_item.id)
    with pytest.raises(FacetContractError):
        insert_node(
            project,
            revision,
            work_item_id=work_item.id,
            plan=plan_facet(),
            cost=cost_facet(),
        )


# --------------------------------------------------------------------------------------
# INV-12 -- no orphaned facet
# --------------------------------------------------------------------------------------


def test_inv_12_violated_by_a_facet_left_behind_by_its_node(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    orphan = revision.plan_facets[bench.root_c]
    del revision.nodes[bench.root_c]

    violations = check_invariants(project, revision)

    orphaned = [violation for violation in violations if violation.invariant == "INV-12"]
    assert orphaned, violated_invariant_ids(violations)
    assert f"plan facet references node {orphan.node_id}" in orphaned[0].detail
    assert str(orphaned[0]).startswith("INV-12: ")


# --------------------------------------------------------------------------------------
# INV-13 -- the facet of a node matches the kind of its work_item
# --------------------------------------------------------------------------------------


def test_inv_13_violated_by_a_plan_facet_on_a_cost_work_item(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    work_item = create_work_item(project, WorkItemKind.COST)

    raw_node(
        project,
        revision,
        work_item_id=work_item.id,
        parent_id=bench.root_c,
        plan=plan_facet("cost work item wearing a plan facet"),
    )

    assert violations_of(project, revision) == ["INV-13"]


def test_inv_13_insertion_refuses_a_facet_of_the_wrong_kind(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    work_item = create_work_item(project, WorkItemKind.TASK)

    with pytest.raises(FacetContractError):
        insert_node(project, revision, work_item_id=work_item.id, cost=cost_facet())


# --------------------------------------------------------------------------------------
# INV-14 -- the set of planning nodes is closed upwards
# --------------------------------------------------------------------------------------


def test_inv_14_violated_by_a_task_under_a_cost_line(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    revision.nodes[bench.root_c].parent_id = bench.global_cost
    revision.nodes[bench.root_c].position = 1
    # Keep the root siblings contiguous, so INV-14 is reported on its own.
    revision.nodes[bench.global_cost].position = 2

    assert violations_of(project, revision) == ["INV-14"]


def test_inv_14_indenting_a_task_under_a_cost_line_is_refused(bench: Bench) -> None:
    """The bench's root order is A, C, global cost: move C right after the cost line."""
    project, revision = bench.project, bench.revision
    move_nodes(project, revision, [bench.root_c], target_parent_id=None, position=3)
    before = copy.deepcopy(revision)

    with pytest.raises(FacetPlacementError):
        indent_nodes(project, revision, [bench.root_c])
    assert revision == before

    with pytest.raises(FacetPlacementError):
        move_nodes(project, revision, [bench.root_c], target_parent_id=bench.global_cost)
    assert revision == before


def test_inv_14_allows_a_cost_line_under_another_cost_line(bench: Bench) -> None:
    """The "premier ancêtre" wording exists precisely for this case."""
    project, revision = bench.project, bench.revision
    nested = add_cost_line(
        project,
        revision,
        nature=CostNature.NON_LABOR,
        label="Sous-fourniture",
        parent_id=bench.supply,
        cost_type_id=1,
        cost_category_id=10,
        unit_cost=Decimal("7"),
    )

    assert_sound(project, revision)
    assert bearing_work_item_id(revision, nested.id) == revision.nodes[bench.root_a].work_item_id


# --------------------------------------------------------------------------------------
# INV-15 -- a planning facet always carries a calendar
# --------------------------------------------------------------------------------------


def test_inv_15_violated_by_a_task_without_a_calendar(bench: Bench) -> None:
    bench.revision.plan_facets[bench.root_c].calendar_id = None

    assert violations_of(bench.project, bench.revision) == ["INV-15"]


def test_inv_15_violated_by_a_missing_calendar_source(bench: Bench) -> None:
    bench.revision.plan_facets[bench.root_c].calendar_source = None

    assert violations_of(bench.project, bench.revision) == ["INV-15"]


def test_inv_15_a_task_created_unpriced_gets_the_project_calendar(bench: Bench) -> None:
    facet = bench.revision.plan_facets[bench.root_c]
    assert facet.calendar_id == bench.project.calendar_id
    assert facet.calendar_source is CalendarSource.PROJECT


def test_inv_15_removing_the_last_mo_assignment_falls_back_to_the_project(
    bench: Bench,
) -> None:
    """Rule 1, case 3: the task stays datable, it does not lose its calendar."""
    project, revision = bench.project, bench.revision
    facet = revision.plan_facets[bench.child_b]
    assert facet.calendar_source is CalendarSource.ROLE

    delete_nodes(project, revision, [bench.labor])

    assert revision.plan_facets[bench.child_b].calendar_id == project.calendar_id
    assert revision.plan_facets[bench.child_b].calendar_source is CalendarSource.PROJECT
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# INV-16 -- a node is never its own predecessor
# --------------------------------------------------------------------------------------


def test_inv_16_violated_by_a_self_link(bench: Bench) -> None:
    """A self link is also a one-node precedence cycle, hence INV-18 alongside."""
    raw_link(bench.revision, bench.child_b, bench.child_b)

    violations = violations_of(bench.project, bench.revision)

    assert "INV-16" in violations
    assert violations == ["INV-16", "INV-18"]


def test_inv_16_link_creation_refuses_a_self_link(bench: Bench) -> None:
    with pytest.raises(LinkError):
        add_link(bench.revision, node_id=bench.root_a, predecessor_node_id=bench.root_a)


# --------------------------------------------------------------------------------------
# INV-17 -- both ends of a precedence link carry a planning facet
# --------------------------------------------------------------------------------------


def test_inv_17_violated_by_a_link_on_a_cost_line(bench: Bench) -> None:
    raw_link(bench.revision, bench.supply, bench.root_c)

    assert violations_of(bench.project, bench.revision) == ["INV-17"]


def test_inv_17_link_creation_refuses_a_cost_node(bench: Bench) -> None:
    with pytest.raises(LinkError):
        add_link(bench.revision, node_id=bench.supply, predecessor_node_id=bench.root_c)


# --------------------------------------------------------------------------------------
# INV-18 -- the precedence graph is acyclic
# --------------------------------------------------------------------------------------


def test_inv_18_violated_by_two_mutual_predecessors(bench: Bench) -> None:
    raw_link(bench.revision, bench.child_b, bench.root_c)
    raw_link(bench.revision, bench.root_c, bench.child_b)

    assert violations_of(bench.project, bench.revision) == ["INV-18"]


def test_inv_18_link_creation_refuses_to_close_a_cycle(bench: Bench) -> None:
    revision = bench.revision
    add_link(revision, node_id=bench.child_b, predecessor_node_id=bench.root_c)

    with pytest.raises(LinkError):
        add_link(revision, node_id=bench.root_c, predecessor_node_id=bench.child_b)


# --------------------------------------------------------------------------------------
# INV-19 / INV-20 -- labour and non-labour attribute sets
# --------------------------------------------------------------------------------------


def test_inv_19_violated_by_a_debours_on_an_mo_line(bench: Bench) -> None:
    bench.revision.cost_facets[bench.labor].unit_cost = Decimal("10")

    assert violations_of(bench.project, bench.revision) == ["INV-19"]


def test_inv_19_violated_by_an_mo_line_without_a_role(bench: Bench) -> None:
    bench.revision.cost_facets[bench.labor].role_id = None

    assert violations_of(bench.project, bench.revision) == ["INV-19"]


def test_inv_19_violated_by_a_supply_status_on_an_mo_line(bench: Bench) -> None:
    """``supply_status`` follows up an order: an MO line has a role and hours, never one."""
    bench.revision.cost_facets[bench.labor].supply_status = SupplyStatus.ORDERED

    assert violations_of(bench.project, bench.revision) == ["INV-19"]


def test_inv_19_creation_refuses_an_mo_line_without_a_role(bench: Bench) -> None:
    with pytest.raises(FacetContractError):
        add_cost_line(
            bench.project,
            bench.revision,
            nature=CostNature.LABOR,
            label="MO sans rôle",
            parent_id=bench.root_c,
            hours=Decimal("2"),
        )


def test_inv_19_creation_refuses_an_mo_line_carrying_a_supply_status(bench: Bench) -> None:
    """The refusal :func:`set_supply_status` already carried, applied at creation too.

    Stated on the invariant rather than on the route, so every present and future
    write of a cost facet inherits it through ``check_cost_facet_shape``.
    """
    with pytest.raises(FacetContractError):
        add_cost_line(
            bench.project,
            bench.revision,
            nature=CostNature.LABOR,
            label="MO commandée",
            parent_id=bench.root_c,
            role_id=1,
            hours=Decimal("2"),
            supply_status=SupplyStatus.ORDERED,
        )


def test_inv_20_violated_by_hours_on_a_supply_line(bench: Bench) -> None:
    bench.revision.cost_facets[bench.supply].hours = Decimal("3")

    assert violations_of(bench.project, bench.revision) == ["INV-20"]


def test_inv_20_creation_refuses_a_supply_line_with_hours(bench: Bench) -> None:
    with pytest.raises(FacetContractError):
        add_cost_line(
            bench.project,
            bench.revision,
            nature=CostNature.NON_LABOR,
            label="Fourniture avec heures",
            parent_id=bench.root_c,
            cost_type_id=1,
            cost_category_id=10,
            unit_cost=Decimal("5"),
            hours=Decimal("3"),
        )


# --------------------------------------------------------------------------------------
# INV-21 -- version numbers are unique per project and positive
# --------------------------------------------------------------------------------------


def test_inv_21_violated_by_two_revisions_sharing_a_version_number(bench: Bench) -> None:
    project = bench.project
    variant = create_revision(project)
    variant.version_number = bench.revision.version_number

    assert "INV-21" in violations_of(project, variant)


def test_inv_21_violated_by_a_non_positive_version_number(bench: Bench) -> None:
    bench.revision.version_number = 0

    assert "INV-21" in violations_of(bench.project, bench.revision)


def test_inv_21_creation_refuses_a_reused_version_number(bench: Bench) -> None:
    with pytest.raises(RevisionLifecycleError, match="already used by revision"):
        create_revision(bench.project, version_number=bench.revision.version_number)


# --------------------------------------------------------------------------------------
# INV-22 -- at most one validated revision per (project, kind)
# --------------------------------------------------------------------------------------


def test_inv_22_violated_by_a_second_validated_revision_of_the_same_kind(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    second = copy_revision(project, revision, now=NOW)
    second.status = RevisionStatus.VALIDATED

    assert "INV-22" in violations_of(project, second)


def test_inv_22_validation_supersedes_the_previous_revision_of_the_same_kind(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision
    other_kind = create_revision(project, kind=RevisionKind.CONTRACT_REFERENCE)
    validate_revision(project, other_kind, now=NOW)
    validate_revision(project, revision, now=NOW)

    second = copy_revision(project, revision, now=NOW)
    validate_revision(project, second, now=NOW)

    assert revision.status is RevisionStatus.SUPERSEDED
    assert second.status is RevisionStatus.VALIDATED
    # A validated revision of another kind is untouched.
    assert other_kind.status is RevisionStatus.VALIDATED
    assert not violations_of(project, second)


# --------------------------------------------------------------------------------------
# INV-23 -- a frozen line references no mutable structure
# --------------------------------------------------------------------------------------


def test_inv_23_violated_by_keeping_the_source_node_id_on_a_frozen_line(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)

    setattr(revision.frozen_lines[0], "source_node_id", bench.labor)  # noqa: B010

    assert violations_of(project, revision) == ["INV-23"]


def test_inv_23_frozen_lines_only_carry_identities_labels_and_amounts(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)

    for line in revision.frozen_lines:
        assert not [name for name in vars(line) if "node" in name or "facet" in name]
        assert line.work_item_id in project.work_items


# --------------------------------------------------------------------------------------
# INV-24 -- frozen lines exist only for a validated or superseded revision
# --------------------------------------------------------------------------------------


def test_inv_24_violated_by_frozen_lines_on_a_draft(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    duplicate = copy_revision(project, revision, now=NOW)
    duplicate.frozen_lines = list(revision.frozen_lines)

    assert "INV-24" in violations_of(project, duplicate)


def test_inv_24_violated_by_a_validated_revision_missing_a_frozen_line(
    bench: Bench,
) -> None:
    project, revision = bench.project, bench.revision
    validate_revision(project, revision, now=NOW)
    revision.frozen_lines.pop()

    assert "INV-24" in violations_of(project, revision)


def test_inv_24_validation_produces_one_frozen_line_per_cost_facet(bench: Bench) -> None:
    project, revision = bench.project, bench.revision

    validate_revision(project, revision, now=NOW)

    assert len(revision.frozen_lines) == len(revision.cost_facets) == 3
    assert revision.validated_at == NOW
    assert_sound(project, revision)


# --------------------------------------------------------------------------------------
# INV-25 -- external_uid is null on a cost work item, unique per project otherwise
# --------------------------------------------------------------------------------------


def test_inv_25_violated_by_two_work_items_sharing_an_external_uid(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    project.work_items[revision.nodes[bench.root_a].work_item_id].external_uid = 42
    project.work_items[revision.nodes[bench.root_c].work_item_id].external_uid = 42

    assert violations_of(project, revision) == ["INV-25"]


def test_inv_25_violated_by_an_external_uid_on_a_cost_work_item(bench: Bench) -> None:
    project, revision = bench.project, bench.revision
    project.work_items[revision.nodes[bench.supply].work_item_id].external_uid = 7

    assert violations_of(project, revision) == ["INV-25"]


def test_inv_25_creation_refuses_a_duplicate_or_cost_external_uid(bench: Bench) -> None:
    project = bench.project
    create_work_item(project, WorkItemKind.TASK, external_uid=99)

    with pytest.raises(ExternalUidError):
        create_work_item(project, WorkItemKind.TASK, external_uid=99)
    with pytest.raises(ExternalUidError):
        create_work_item(project, WorkItemKind.COST, external_uid=100)


# --------------------------------------------------------------------------------------
# INV-26 -- the lotissement is project data, which a validated revision never freezes
# --------------------------------------------------------------------------------------


def _lotissement() -> list[BreakdownEntry]:
    return [
        BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="Lot 1"),
        BreakdownEntry(id=2, kind=BreakdownKind.POSTE, name="Poste 1.1", parent_id=1),
    ]


def test_inv_26_violated_by_carrying_the_lotissement_on_the_revision(bench: Bench) -> None:
    """Canonical violation: copy the lotissement onto the revision at generation time.

    That is exactly what would make a validated revision freeze it, and it is the
    shape the product decision refuses.
    """
    project, revision = bench.project, bench.revision
    save_work_breakdown(project, _lotissement())
    assert_sound(project, revision)

    setattr(revision, "work_breakdown", project.work_breakdown)  # noqa: B010

    assert violations_of(project, revision) == ["INV-26"]


def _as_single(entries: list[BreakdownEntry]) -> object:
    return entries[0]


def _as_list(entries: list[BreakdownEntry]) -> object:
    return list(entries)


def _as_tuple(entries: list[BreakdownEntry]) -> object:
    return tuple(entries)


def _as_dict(entries: list[BreakdownEntry]) -> object:
    return {entry.id: entry for entry in entries}


def _as_rows(entries: list[BreakdownEntry]) -> object:
    """Field by field, the shape the fingerprint used to be built from."""
    return [(entry.id, entry.parent_id, entry.kind.value, entry.name) for entry in entries]


def _as_repr_string(entries: list[BreakdownEntry]) -> object:
    """The very smuggling round 5 found: the lotissement serialised into a string."""
    return repr(_as_rows(entries))


def _as_json_string(entries: list[BreakdownEntry]) -> object:
    return json.dumps([asdict(entry) for entry in entries], default=str)


def _as_dicts(entries: list[BreakdownEntry]) -> object:
    return [asdict(entry) for entry in entries]


def _as_fingerprint_holding_the_content(entries: list[BreakdownEntry]) -> object:
    """A fingerprint whose ``breakdown`` half is the content instead of a digest."""
    return SkeletonFingerprint(breakdown_digest=repr(_as_rows(entries)), tree_digest="")


@pytest.mark.parametrize(
    ("label", "carried"),
    [
        ("a single entry", _as_single),
        ("a list", _as_list),
        ("a tuple", _as_tuple),
        ("a dict keyed by entry id", _as_dict),
        ("a row per entry", _as_rows),
        ("a repr string", _as_repr_string),
        ("a json string", _as_json_string),
        ("a list of asdict mappings", _as_dicts),
        ("a fingerprint carrying the content", _as_fingerprint_holding_the_content),
    ],
)
def test_inv_26_is_reported_however_the_lotissement_is_carried(
    bench: Bench,
    label: str,
    carried: Callable[[list[BreakdownEntry]], object],
) -> None:
    """The shape of the smuggling does not matter -- only that the revision holds it."""
    project, revision = bench.project, bench.revision
    save_work_breakdown(project, _lotissement())

    setattr(revision, "lotissement", carried(list(project.work_breakdown)))  # noqa: B010

    assert violations_of(project, revision) == ["INV-26"], label


def _as_csv(entries: list[BreakdownEntry]) -> object:
    return "\n".join(f"{entry.id},{entry.kind.value},{entry.name}" for entry in entries)


def _as_markdown_table(entries: list[BreakdownEntry]) -> object:
    return "\n".join(f"| {entry.id} | {entry.kind.value} | {entry.name} |" for entry in entries)


def _as_a_human_sentence(entries: list[BreakdownEntry]) -> object:
    return " ; ".join(f"{entry.name} — {entry.kind.value} (lot #{entry.id})" for entry in entries)


@pytest.mark.parametrize(
    ("label", "carried"),
    [
        ("a CSV rendering", _as_csv),
        ("a markdown table row", _as_markdown_table),
        ("a human sentence", _as_a_human_sentence),
    ],
)
def test_inv_26_says_where_its_string_heuristic_stops(
    bench: Bench,
    label: str,
    carried: Callable[[list[BreakdownEntry]], object],
) -> None:
    """The string shape is **best effort**, and its boundary is written down here.

    The three structural shapes -- entry, ``id``/``kind``/``name`` mapping,
    field-by-field row -- are decided on the shape of the object and are
    guaranteed. The fourth, a serialised string, is recognised by a heuristic:
    a serialisation *quotes* the names, the legitimate copy of a lot label onto a
    generated task does not. Every rendering below carries the whole lotissement
    verbatim without quoting it, and goes unreported.

    Asserting the misses rather than leaving them undiscovered is the point: a
    green INV-26 reads as "no entry, mapping or row, and no obvious
    serialisation", never as "nothing of the lotissement is in there". Widening
    the heuristic would only move this boundary, not remove it.
    """
    project, revision = bench.project, bench.revision
    save_work_breakdown(project, _lotissement())

    setattr(revision, "lotissement", carried(list(project.work_breakdown)))  # noqa: B010

    assert violations_of(project, revision) == [], label


def test_inv_26_walks_as_deep_as_it_says_and_no_deeper(bench: Bench) -> None:
    """The bound of the smuggling walk is stated by a test rather than discovered.

    Four levels is what it takes to reach a string field of a dataclass held in a
    collection -- where a serialised lotissement would hide. One level further the
    check gives up, and says so here instead of leaving a reader to assume it
    never does.
    """
    project, revision = bench.project, bench.revision
    save_work_breakdown(project, _lotissement())
    smuggled = _as_fingerprint_holding_the_content(list(project.work_breakdown))

    setattr(revision, "reachable", {"a": [smuggled]})  # noqa: B010
    assert violations_of(project, revision) == ["INV-26"]

    delattr(revision, "reachable")
    setattr(revision, "too_deep", [{"a": [smuggled]}])  # noqa: B010
    assert violations_of(project, revision) == []


def test_inv_26_is_not_reported_on_an_unrelated_extra_attribute(bench: Bench) -> None:
    """The check names the lotissement, not any attribute a revision happens to carry."""
    project, revision = bench.project, bench.revision
    save_work_breakdown(project, _lotissement())

    setattr(revision, "scratch", ["not a breakdown entry", 42, None])  # noqa: B010

    assert violations_of(project, revision) == []


def test_inv_26_is_not_reported_on_a_skeleton_generated_from_awkward_lot_names() -> None:
    """The legitimate copy of a lot name onto a generated task is not smuggling.

    Names chosen to defeat a naive "the revision mentions the name, the kind and
    the id" check: each one already contains its own kind and its own id. What
    tells a serialisation apart is that it *quotes* the name, and a task label
    never does.
    """
    project = build_project()
    save_work_breakdown(
        project,
        [
            BreakdownEntry(id=1, kind=BreakdownKind.LOT, name="lot 1 - étude"),
            BreakdownEntry(id=2, kind=BreakdownKind.POSTE, name="poste 2 - essais", parent_id=1),
        ],
    )
    revision = build_draft(project)

    generate_skeleton(project, revision, now=NOW)

    assert violations_of(project, revision) == []


def test_inv_26_a_validated_revision_does_not_freeze_the_lotissement(bench: Bench) -> None:
    """The lotissement stays editable while the revision refuses every write."""
    project, revision = bench.project, bench.revision
    save_work_breakdown(project, _lotissement())
    validate_revision(project, revision, now=NOW)
    frozen = copy.deepcopy(revision)

    extended = [*_lotissement(), BreakdownEntry(id=3, kind=BreakdownKind.LIVRABLE, name="Livrable")]
    save_work_breakdown(project, extended)

    assert [entry.id for entry in project.work_breakdown] == [1, 2, 3]
    assert revision == frozen
    assert_sound(project, revision)


def test_inv_26_saving_the_lotissement_is_the_only_trigger_of_the_initialise_status() -> None:
    project = build_project()
    assert project.status is ProjectStatus.CREE

    revision = build_draft(project)
    add_task(project, revision, name="Créée à la main")
    assert project.status is ProjectStatus.CREE

    save_work_breakdown(project, _lotissement())

    assert project.status is ProjectStatus.INITIALISE


# --------------------------------------------------------------------------------------
# Edge cases the specification declares allowed
# --------------------------------------------------------------------------------------


def test_a_cost_line_at_the_root_is_allowed_and_has_no_bearing_task(bench: Bench) -> None:
    assert bearing_work_item_id(bench.revision, bench.global_cost) is None
    assert_sound(bench.project, bench.revision)


def test_a_task_without_any_cost_facet_is_allowed() -> None:
    project = build_project()
    revision = build_draft(project)
    task = add_task(project, revision, name="Unpriced")

    assert revision.plan_facets[task.id].calendar_id == project.calendar_id
    assert_sound(project, revision)


def test_check_invariants_reports_nothing_on_an_empty_revision() -> None:
    project = build_project()
    revision = build_draft(project)

    assert check_invariants(project, revision) == []


def test_facets_of_a_copy_are_independent_objects(bench: Bench) -> None:
    project: Project = bench.project
    source: ProjectRevision = bench.revision
    duplicate = copy_revision(project, source, now=NOW)

    node = next(iter(duplicate.plan_facets))
    duplicate.plan_facets[node].name = "renamed in the copy"

    assert {facet.name for facet in source.plan_facets.values()} == {"A", "B", "C"}
