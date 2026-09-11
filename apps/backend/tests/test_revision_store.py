"""The adapter between the pure revision domain and its tables (E14-03, issue #329).

The central test is :func:`test_a_domain_operation_survives_a_full_round_trip`:
load a revision from the database, apply operations of the *pure* domain module
to it, write the result back, read it again, and check that the invariant checker
of E14-02 reports nothing. That is the acceptance criterion of the issue, and it
is what proves the two halves agree -- the tree logic never has to know about
SQLAlchemy, and the adapter never has to know about the tree rules.

It runs on PostgreSQL too: the sibling-position uniqueness this exercises is an
immediate constraint on both dialects, but the production one is the one that
matters.
"""

from __future__ import annotations

import signal
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import FrameType

import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session

from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_link,
    insert_revision,
    insert_task,
    postgres_session,
    seed_reference_data,
)
from waterfall.db.session import get_session_factory
from waterfall.domain import revision as domain
from waterfall.models.resources import Calendar
from waterfall.models.revision import (
    ProjectRevision,
    RevisionCostFacet,
    RevisionNode,
    RevisionNodeLink,
    RevisionPlanFacet,
    WorkItem,
)
from waterfall.services.revision_store import (
    LoadedRevision,
    MissingProjectCalendarError,
    RevisionNotFoundError,
    RevisionStoreError,
    load_revision,
    save_revision,
)


def _seed_small_tree(
    session: Session, *, with_a_later_revision: bool = False
) -> tuple[ReferenceData, int]:
    """A parent with two children, a labour line under the first, and one link.

    Written straight into the tables, so that loading it proves the adapter reads
    a tree it did not itself write.

    ``with_a_later_revision`` adds a *second* revision of the same project whose
    nodes and work items are inserted **after** those of the revision returned.
    The next id each sequence will hand out is then well above the highest id the
    loaded revision carries -- which is what makes a test of the id adoption
    discriminating. Without it, "the id the domain allocated for itself" and "the
    id the database allocated" coincide, and every assertion about the
    renumbering holds whether the renumbering happened or not.
    """
    reference = seed_reference_data(session)
    revision = insert_revision(session, reference)
    parent = insert_task(session, reference, revision, name="Parent", external_uid=1, position=1)
    first = insert_task(
        session, reference, revision, name="First", parent_id=parent.id, position=1, external_uid=2
    )
    second = insert_task(
        session, reference, revision, name="Second", parent_id=parent.id, position=2, external_uid=3
    )
    insert_labor_line(session, reference, revision, label="Study", parent_id=first.id, position=1)
    insert_link(session, revision, second, first)
    if with_a_later_revision:
        later = insert_revision(session, reference, version_number=2)
        for index in range(1, 5):
            insert_task(session, reference, later, name=f"Later {index}", position=index)
    session.commit()
    return reference, revision.id


def _task_named(loaded: LoadedRevision, name: str) -> int:
    node_id = next(
        node_id for node_id, facet in loaded.revision.plan_facets.items() if facet.name == name
    )
    return node_id


def _seed_a_later_project(session: Session, *, key: str = "other", tasks: int = 3) -> None:
    """A second project, created *after* the first, carrying tasks of its own.

    `wf_work_item`, `wf_revision_node` and `wf_revision` have one sequence each,
    shared by every project: seeding a second project pushes them above every id
    the first one carries, so the id a domain counter allocates and the id the
    database allocates for the same new object cannot coincide by chance.

    ``key`` keeps the globally unique referential codes apart, so a test that
    needs the sequences pushed further can seed more than one.
    """
    other = seed_reference_data(session, key=key, is_default=False)
    revision = insert_revision(session, other)
    for index in range(1, tasks + 1):
        insert_task(session, other, revision, name=f"Elsewhere {index}", position=index)
    session.commit()


@contextmanager
def _time_limit(seconds: int) -> Generator[None]:
    """Fail, rather than hang, when the block does not terminate.

    The write path walks the *stored* parent chain, which SQL cannot keep acyclic
    (INV-06 is not expressible as a constraint). A regression there does not
    produce a wrong answer, it produces no answer at all -- and a test that hangs
    blocks the suite instead of reporting. The alarm turns that into a failure.
    """

    def _expire(signal_number: int, frame: FrameType | None) -> None:
        raise TimeoutError(f"the block did not terminate within {seconds}s")

    previous = signal.signal(signal.SIGALRM, _expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _node_count(session: Session, revision_id: int) -> int:
    return session.query(RevisionNode).filter(RevisionNode.revision_id == revision_id).count()


def _highest_node_id(session: Session) -> int:
    return session.query(func.max(RevisionNode.id)).scalar() or 0


def _highest_work_item_id(session: Session) -> int:
    return session.query(func.max(WorkItem.id)).scalar() or 0


def _snapshot(session: Session) -> list[str]:
    """Every row of the six revision tables, rendered as comparable strings.

    Compared before and after a refused write: an assertion on counts alone would
    miss a position left in the parking band, which is precisely the residue a
    half-written save leaves behind.
    """
    session.expire_all()
    rows = [
        f"revision {row.id} {row.version_number} {row.kind} {row.status} {row.lock_version}"
        for row in session.query(ProjectRevision)
    ]
    rows += [
        f"item {row.id} {row.project_id} {row.kind} {row.description} {row.external_uid}"
        for row in session.query(WorkItem)
    ]
    rows += [
        f"node {row.id} {row.revision_id} {row.work_item_id} {row.kind} "
        f"{row.parent_id} {row.position}"
        for row in session.query(RevisionNode)
    ]
    rows += [
        f"plan {row.id} {row.node_id} {row.name} {row.calendar_id} {row.calendar_source}"
        for row in session.query(RevisionPlanFacet)
    ]
    rows += [
        f"cost {row.id} {row.node_id} {row.nature} {row.label} {row.hours}"
        for row in session.query(RevisionCostFacet)
    ]
    rows += [
        f"link {row.id} {row.node_id} {row.predecessor_node_id} {row.link_type} "
        f"{row.lag_tenth_minute}"
        for row in session.query(RevisionNodeLink)
    ]
    return sorted(rows)


def test_loads_a_tree_written_straight_into_the_tables() -> None:
    with get_session_factory()() as session:
        reference, revision_id = _seed_small_tree(session)

        loaded = load_revision(session, revision_id)

        assert loaded.project.id == reference.project_id
        assert loaded.revision.id == revision_id
        assert loaded.revision.status is domain.RevisionStatus.DRAFT
        assert len(loaded.revision.nodes) == 4
        assert len(loaded.revision.plan_facets) == 3
        assert len(loaded.revision.cost_facets) == 1
        assert len(loaded.revision.links) == 1
        assert sorted(facet.name for facet in loaded.revision.plan_facets.values()) == [
            "First",
            "Parent",
            "Second",
        ]
        labor = next(iter(loaded.revision.cost_facets.values()))
        assert labor.nature is domain.CostNature.LABOR
        assert labor.role_id == reference.role_id
        assert labor.hours == Decimal("10.00")


def test_a_loaded_tree_violates_no_state_invariant() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)

        loaded = load_revision(session, revision_id)

        assert domain.check_invariants(loaded.project, loaded.revision) == []


def test_loading_seeds_the_domain_counters_above_every_id_it_read() -> None:
    """What makes a freshly created domain object recognisable when writing back."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)

        loaded = load_revision(session, revision_id)

        assert loaded.project.next_node_id > max(loaded.revision.nodes)
        assert loaded.project.next_work_item_id > max(loaded.project.work_items)
        assert loaded.project.next_revision_id > revision_id


def test_loading_carries_the_roles_the_calendar_rule_reads() -> None:
    with get_session_factory()() as session:
        reference, revision_id = _seed_small_tree(session)

        loaded = load_revision(session, revision_id)

        role = loaded.project.roles[reference.role_id]
        assert role.calendar_id == reference.calendar_id
        assert loaded.project.calendar_id == reference.calendar_id


def test_loading_an_unknown_revision_is_refused() -> None:
    with get_session_factory()() as session, pytest.raises(RevisionNotFoundError):
        load_revision(session, 4242)


def test_loading_a_revision_whose_project_is_gone_is_refused() -> None:
    """Defensive: `wf_revision.project_id` is a foreign key, so this is out of
    reach through the API -- and the adapter names it rather than failing later
    on a ``None``."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        row = session.get(ProjectRevision, revision_id)
        assert row is not None

        with session.no_autoflush:
            row.project_id = 4242
            with pytest.raises(RevisionNotFoundError, match="Project 4242"):
                load_revision(session, revision_id)
        session.rollback()


def test_loading_without_an_organisation_default_calendar_is_refused() -> None:
    """A task always carries a calendar (INV-15), so there has to be one to inherit."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        session.query(Calendar).update({Calendar.is_default: False})
        session.commit()

        with pytest.raises(MissingProjectCalendarError):
            load_revision(session, revision_id)


def _round_trip(session: Session) -> None:
    reference, revision_id = _seed_small_tree(session)
    loaded = load_revision(session, revision_id)
    parent_id = _task_named(loaded, "Parent")
    first_id = _task_named(loaded, "First")

    # Four operations of the pure domain, none of which knows a database exists:
    # a reorder (which renumbers a sibling set), an insertion, a cost line, and a
    # cascade delete.
    domain.move_nodes_down(loaded.project, loaded.revision, [first_id])
    added = domain.add_task(loaded.project, loaded.revision, name="Added", parent_id=parent_id)
    domain.add_cost_line(
        loaded.project,
        loaded.revision,
        nature=domain.CostNature.LABOR,
        label="Added labour",
        parent_id=added.id,
        role_id=reference.role_id,
        hours=Decimal("4"),
    )
    domain.delete_nodes(loaded.project, loaded.revision, [_task_named(loaded, "Second")])
    assert domain.check_invariants(loaded.project, loaded.revision) == []

    outcome = save_revision(session, loaded)
    session.commit()

    reloaded = load_revision(session, outcome.revision_id)
    assert domain.check_invariants(reloaded.project, reloaded.revision) == []
    names = sorted(facet.name for facet in reloaded.revision.plan_facets.values())
    assert names == ["Added", "First", "Parent"]
    assert sorted(facet.label for facet in reloaded.revision.cost_facets.values()) == [
        "Added labour",
        "Study",
    ]
    # "Second" carried the only link, and went with its deletion (INV-02).
    assert reloaded.revision.links == []
    # The reorder actually reached the database: "First" was pushed behind the
    # task that followed it, which the delete then renumbered back to slot 1.
    reloaded_parent = _task_named(reloaded, "Parent")
    children = domain.children_of(reloaded.revision, reloaded_parent)
    assert [reloaded.revision.plan_facets[node.id].name for node in children] == ["First", "Added"]
    assert [node.position for node in children] == [1, 2]


def test_a_domain_operation_survives_a_full_round_trip() -> None:
    with get_session_factory()() as session:
        _round_trip(session)


def test_postgres_a_domain_operation_survives_a_full_round_trip(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _round_trip(session)


def _sibling_swap(session: Session) -> None:
    _, revision_id = _seed_small_tree(session)
    loaded = load_revision(session, revision_id)
    first_id = _task_named(loaded, "First")

    domain.move_nodes_down(loaded.project, loaded.revision, [first_id])
    save_revision(session, loaded)
    session.commit()

    reloaded = load_revision(session, revision_id)
    parent_id = _task_named(reloaded, "Parent")
    children = domain.children_of(reloaded.revision, parent_id)
    assert [reloaded.revision.plan_facets[node.id].name for node in children] == ["Second", "First"]
    assert [node.position for node in children] == [1, 2]
    # No position was left in the parking band the swap goes through.
    assert max(node.position for node in reloaded.revision.nodes.values()) < 1_000_000


def test_swapping_two_siblings_does_not_trip_the_position_constraint() -> None:
    """The transient state a naive row-by-row write would produce is refused by
    ``uq_wf_revision_node_sibling_position``: two siblings cannot both sit at
    position 1, not even halfway through a write."""
    with get_session_factory()() as session:
        _sibling_swap(session)


def test_postgres_swapping_two_siblings_does_not_trip_the_position_constraint(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _sibling_swap(session)


def test_swapping_two_root_siblings_does_not_trip_the_root_position_index() -> None:
    """Same, for the root sibling set and its partial unique index."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        insert_task(session, reference, revision, name="Root A", position=1)
        insert_task(session, reference, revision, name="Root B", position=2)
        session.commit()

        loaded = load_revision(session, revision.id)
        domain.move_nodes_down(loaded.project, loaded.revision, [_task_named(loaded, "Root A")])
        save_revision(session, loaded)
        session.commit()

        reloaded = load_revision(session, revision.id)
        roots = domain.children_of(reloaded.revision, None)
        assert [reloaded.revision.plan_facets[node.id].name for node in roots] == [
            "Root B",
            "Root A",
        ]


def test_adding_a_task_inserts_a_work_item_and_maps_the_domain_ids() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        added = domain.add_task(loaded.project, loaded.revision, name="Added", description="Notes")

        outcome = save_revision(session, loaded)
        session.commit()

        assert outcome.node_ids[added.id] > 0
        row = session.get(RevisionNode, outcome.node_ids[added.id])
        assert row is not None
        assert row.kind == "task"
        assert row.revision_id == revision_id
        work_item = session.get(WorkItem, row.work_item_id)
        assert work_item is not None
        assert work_item.description == "Notes"
        assert work_item.external_uid is None
        assert session.query(WorkItem).count() == 5


def test_deleting_a_node_clears_its_subtree_and_both_facets_from_the_tables() -> None:
    """INV-02, all the way down to the rows."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)

        domain.delete_nodes(loaded.project, loaded.revision, [_task_named(loaded, "Parent")])
        save_revision(session, loaded)
        session.commit()

        assert session.query(RevisionNode).count() == 0
        assert session.query(RevisionPlanFacet).count() == 0
        assert session.query(RevisionCostFacet).count() == 0
        assert session.query(RevisionNodeLink).count() == 0
        # The work items survive: they are the identity of an element of work
        # across the versions, and this revision is not the only one that may
        # ever carry them.
        assert session.query(WorkItem).count() == 4


def test_a_copy_of_a_revision_is_written_next_to_its_source() -> None:
    """INV-07 through the adapter: same tree, new nodes, same work items."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        copy = domain.copy_revision(loaded.project, loaded.revision)

        outcome = save_revision(session, loaded, copy)
        session.commit()

        assert outcome.revision_id != revision_id
        assert session.query(ProjectRevision).count() == 2
        assert session.query(WorkItem).count() == 4
        source_items = {
            node.work_item_id
            for node in session.query(RevisionNode).filter(RevisionNode.revision_id == revision_id)
        }
        copied_items = {
            node.work_item_id
            for node in session.query(RevisionNode).filter(
                RevisionNode.revision_id == outcome.revision_id
            )
        }
        assert copied_items == source_items

        reloaded = load_revision(session, outcome.revision_id)
        assert domain.check_invariants(reloaded.project, reloaded.revision) == []
        assert len(reloaded.revision.nodes) == 4
        assert len(reloaded.revision.links) == 1


def test_a_stub_revision_of_the_project_cannot_be_written_back() -> None:
    """The other revisions of the project are loaded without their tree; writing
    one back would read that emptiness as a cascade delete."""
    with get_session_factory()() as session:
        reference, revision_id = _seed_small_tree(session)
        other = insert_revision(session, reference, version_number=2)
        insert_task(session, reference, other, name="Elsewhere")
        session.commit()

        loaded = load_revision(session, revision_id)
        stub = loaded.project.revisions[other.id]
        assert stub.nodes == {}

        with pytest.raises(RevisionStoreError, match="stub"):
            save_revision(session, loaded, stub)

        session.rollback()
        assert session.query(RevisionNode).filter(RevisionNode.revision_id == other.id).count() == 1


def test_saving_twice_without_a_change_leaves_the_rows_alone() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)

        first = save_revision(session, loaded)
        session.commit()
        second = save_revision(session, loaded)
        session.commit()

        assert first.node_ids == second.node_ids
        assert session.query(RevisionNode).count() == 4
        assert session.query(RevisionPlanFacet).count() == 3
        assert session.query(RevisionCostFacet).count() == 1
        assert session.query(RevisionNodeLink).count() == 1


def test_saving_twice_after_an_insertion_does_not_duplicate_it() -> None:
    """The state stays usable after a write: the domain ids it allocated itself
    are renumbered onto the ones the database gave those rows, so a second save
    recognises them instead of inserting them again.

    Seeded with a later revision *and* a later project on purpose, so that the
    domain counters and the database sequences do not line up on either table:
    the node ids and the work item ids the domain allocates here are already
    taken, and every assertion below therefore fails if the adoption is skipped
    instead of holding by coincidence.
    """
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session, with_a_later_revision=True)
        _seed_a_later_project(session)
        loaded = load_revision(session, revision_id)
        added = domain.add_task(loaded.project, loaded.revision, name="Added")
        allocated_node_id = added.id
        allocated_work_item_id = added.work_item_id
        # The fixture discriminates: the ids the domain just allocated are already
        # in use in the tables, so the database cannot hand back the same ones.
        assert allocated_node_id <= _highest_node_id(session)
        assert allocated_work_item_id <= _highest_work_item_id(session)

        first = save_revision(session, loaded)
        session.commit()
        database_id = first.node_ids[allocated_node_id]
        assert database_id != allocated_node_id
        assert added.id == database_id, "the node adopted the id the database gave its row"
        assert added.work_item_id == first.work_item_ids[allocated_work_item_id]
        assert added.work_item_id != allocated_work_item_id

        domain.rename_task(loaded.revision, added.id, "Renamed after the first save")
        second = save_revision(session, loaded)
        session.commit()

        assert second.node_ids[database_id] == database_id
        assert _node_count(session, revision_id) == 5
        # Four work items of the loaded revision, four of the later one, three of
        # the later project, and the one just added.
        assert session.query(WorkItem).count() == 12
        reloaded = load_revision(session, revision_id)
        assert domain.check_invariants(reloaded.project, reloaded.revision) == []
        assert reloaded.revision.plan_facets[database_id].name == "Renamed after the first save"
        # The later revision, which shares the project's work items, is untouched.
        assert session.query(RevisionNode).count() == 12


def test_a_facet_edit_reaches_the_database() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        node_id = _task_named(loaded, "First")

        before = loaded.revision.lock_version
        domain.rename_task(loaded.revision, node_id, "Renamed")
        domain.set_task_duration(loaded.revision, node_id, 480)
        domain.set_task_calendar_manually(loaded.revision, node_id, loaded.project.calendar_id)
        save_revision(session, loaded)
        session.commit()

        reloaded = load_revision(session, revision_id)
        facet = reloaded.revision.plan_facets[node_id]
        assert facet.name == "Renamed"
        assert facet.duration_minutes == 480
        assert facet.calendar_source is domain.CalendarSource.MANUAL
        assert reloaded.revision.lock_version == before + 3


def test_an_edit_of_a_work_item_description_reaches_the_database() -> None:
    """The `work_item` half of a write: a description edit is an update, not an insert."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        work_item_id = loaded.revision.nodes[_task_named(loaded, "First")].work_item_id
        before = session.get(WorkItem, work_item_id)
        assert before is not None
        stamped_at = before.updated_at

        loaded.project.work_items[work_item_id].description = "Revised scope"
        save_revision(session, loaded)
        session.commit()

        row = session.get(WorkItem, work_item_id)
        assert row is not None
        assert row.description == "Revised scope"
        assert row.updated_at > stamped_at
        assert session.query(WorkItem).count() == 4


# --------------------------------------------------------------------------------------
# Identity adoption across the revisions of one project
# --------------------------------------------------------------------------------------


def _copy_then_source(session: Session) -> None:
    """Save a copy of a revision, then its source, when both gained a work item.

    The work items are project-wide: the copy is what *writes* the one the source
    introduced, so the source is left designating a domain id the database gave a
    different number to. It has to be renumbered as well, or saving it next
    designates a work item of nobody.

    The second project exists to make that visible: created after the first, it
    pushes the `wf_work_item` sequence above the ids of the first project, so the
    id the domain allocated and the id the database allocates cannot coincide.
    """
    reference, revision_id = _seed_small_tree(session)
    _seed_a_later_project(session)
    assert _highest_work_item_id(session) > max(
        work_item.id
        for work_item in session.query(WorkItem).filter(WorkItem.project_id == reference.project_id)
    )

    loaded = load_revision(session, revision_id)
    domain.add_task(
        loaded.project, loaded.revision, name="Added", parent_id=_task_named(loaded, "Parent")
    )
    copy = domain.copy_revision(loaded.project, loaded.revision)

    copied = save_revision(session, loaded, copy)
    session.commit()
    saved = save_revision(session, loaded)
    session.commit()

    for identifier in (saved.revision_id, copied.revision_id):
        reloaded = load_revision(session, identifier)
        assert domain.check_invariants(reloaded.project, reloaded.revision) == []
        assert sorted(facet.name for facet in reloaded.revision.plan_facets.values()) == [
            "Added",
            "First",
            "Parent",
            "Second",
        ]
    # Both revisions designate the very same work items: that is what a copy is.
    assert _node_count(session, saved.revision_id) == _node_count(session, copied.revision_id)
    source_items = {
        node.work_item_id
        for node in session.query(RevisionNode).filter(
            RevisionNode.revision_id == saved.revision_id
        )
    }
    copied_items = {
        node.work_item_id
        for node in session.query(RevisionNode).filter(
            RevisionNode.revision_id == copied.revision_id
        )
    }
    assert source_items == copied_items


def test_saving_a_copy_leaves_its_source_saveable() -> None:
    with get_session_factory()() as session:
        _copy_then_source(session)


def test_postgres_saving_a_copy_leaves_its_source_saveable(
    postgres_app_database_url: str,
) -> None:
    """Proven on PostgreSQL: a shared sequence is what desynchronises the ids."""
    with postgres_session(postgres_app_database_url) as session:
        _copy_then_source(session)


def _copy_of_a_copy(session: Session) -> None:
    """Write a copy, then the copy *of* that copy, and follow the provenance pointer.

    ``source_revision_id`` is the one reference no constraint protects:
    `fk_wf_revision_source` only asks that some revision carry the number, so a
    pointer left on the id the domain had allocated lands -- silently, without an
    error of any kind -- on a revision of another project.

    Two further projects are seeded for exactly that reason: `wf_revision` has one
    sequence for every project, so their revisions push it past the ids the domain
    allocated for itself. The id the first copy gives up is then a real revision of
    somebody else, which is what makes the assertions below discriminating.
    """
    _, revision_id = _seed_small_tree(session)
    _seed_a_later_project(session, key="second", tasks=1)
    _seed_a_later_project(session, key="third", tasks=1)

    loaded = load_revision(session, revision_id)
    first = domain.copy_revision(loaded.project, loaded.revision)
    second = domain.copy_revision(loaded.project, first)
    allocated_id = first.id
    assert second.source_revision_id == allocated_id

    saved_first = save_revision(session, loaded, first)
    session.commit()
    assert saved_first.revision_id != allocated_id
    squatter = session.get(ProjectRevision, allocated_id)
    assert squatter is not None, "the fixture discriminates: that id is a stored revision"
    assert squatter.project_id != loaded.project.id, "...and it belongs to another project"

    assert second.source_revision_id == saved_first.revision_id
    saved_second = save_revision(session, loaded, second)
    session.commit()

    row = session.get(ProjectRevision, saved_second.revision_id)
    assert row is not None
    assert row.source_revision_id == saved_first.revision_id
    source_row = session.get(ProjectRevision, row.source_revision_id)
    assert source_row is not None
    assert source_row.project_id == row.project_id, "a revision descends from one of its own"
    reloaded = load_revision(session, saved_second.revision_id)
    assert domain.check_invariants(reloaded.project, reloaded.revision) == []
    assert len(reloaded.revision.nodes) == 4


def test_a_copy_of_a_copy_points_at_the_revision_its_source_became() -> None:
    with get_session_factory()() as session:
        _copy_of_a_copy(session)


def test_postgres_a_copy_of_a_copy_points_at_the_revision_its_source_became(
    postgres_app_database_url: str,
) -> None:
    """On PostgreSQL too: the shared sequence is what makes the shift visible."""
    with postgres_session(postgres_app_database_url) as session:
        _copy_of_a_copy(session)


def test_a_copy_whose_source_was_never_written_is_refused() -> None:
    """The belt to the renumbering's braces: no constraint would catch this one."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        first = domain.copy_revision(loaded.project, loaded.revision)
        second = domain.copy_revision(loaded.project, first)

        with pytest.raises(RevisionStoreError, match="write the source revision first"):
            save_revision(session, loaded, second)
        session.rollback()

        assert session.query(ProjectRevision).count() == 1


def test_a_stored_revision_whose_source_belongs_to_another_project_is_refused() -> None:
    """The other condition the same check covers -- and the other half of its message.

    `fk_wf_revision_source` only asks that *some* revision carry the number, so a
    stored row whose provenance designates a revision of another project is a state
    the schema allows; it is written straight into the table here, nothing in this
    adapter being able to produce it (the renumbering of ``_adopt_database_ids`` is
    what keeps the pointer inside the project).

    Such a revision is not "a source that has not been written yet", and writing
    anything first will not make it saveable: the refusal has to say so, or the
    caller of a future write path that let this through would follow an instruction
    that cannot work.
    """
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        other = seed_reference_data(session, key="other", is_default=False)
        elsewhere = insert_revision(session, other)
        revision_row = session.get(ProjectRevision, revision_id)
        assert revision_row is not None
        revision_row.source_revision_id = elsewhere.id
        session.commit()

        loaded = load_revision(session, revision_id)
        assert loaded.revision.source_revision_id == elsewhere.id

        with pytest.raises(RevisionStoreError, match="another project"):
            save_revision(session, loaded)
        session.rollback()


def test_a_copy_stays_saveable_after_its_first_write() -> None:
    """A copy is not a one-shot object: it is written, edited, and written again.

    What the second save pins down is the renumbering: the copy has adopted the id
    the database gave it, so writing it again must *update* that revision rather
    than insert a second one carrying the whole tree afresh.

    It says nothing about ``LoadedRevision.is_stub`` comparing by identity rather
    than by id. The two answer alike under the invariants of the adapter -- the ids
    of ``project.revisions`` are unique and no entry is ever evicted from it -- so
    no test of this module tells them apart, and the identity test is a defensive
    margin rather than a covered guarantee (see :class:`LoadedRevision`).
    """
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        copy = domain.copy_revision(loaded.project, loaded.revision)

        first = save_revision(session, loaded, copy)
        session.commit()
        node_id = next(
            node_id for node_id, facet in copy.plan_facets.items() if facet.name == "First"
        )
        domain.rename_task(copy, node_id, "Renamed in the copy")
        second = save_revision(session, loaded, copy)
        session.commit()

        assert second.revision_id == first.revision_id
        assert session.query(ProjectRevision).count() == 2
        assert _node_count(session, first.revision_id) == 4
        reloaded = load_revision(session, first.revision_id)
        assert domain.check_invariants(reloaded.project, reloaded.revision) == []
        assert sorted(facet.name for facet in reloaded.revision.plan_facets.values()) == [
            "Parent",
            "Renamed in the copy",
            "Second",
        ]


def test_writing_one_copy_leaves_the_other_in_the_project() -> None:
    """Two copies live in memory; writing one must not evict the other.

    The one written adopts the id the database allocated -- and that number is the
    one the domain had already handed to its sibling, the sequence having caught
    up. Keyed naively, the sibling would disappear from the project, and saving it
    afterwards would write over the row its id has come to designate.
    """
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        one = domain.copy_revision(loaded.project, loaded.revision)
        two = domain.copy_revision(loaded.project, loaded.revision)
        allocated_id = one.id

        written = save_revision(session, loaded, two)
        session.commit()
        assert written.revision_id == allocated_id, "the collision this test is about"

        assert loaded.project.revisions[allocated_id] is two
        assert any(sibling is one for sibling in loaded.project.revisions.values())
        assert one.id != allocated_id
        assert one.id not in {row.id for row in session.query(ProjectRevision)}

        written_one = save_revision(session, loaded, one)
        session.commit()

        assert written_one.revision_id != written.revision_id
        assert session.query(ProjectRevision).count() == 3
        for identifier in (written.revision_id, written_one.revision_id):
            reloaded = load_revision(session, identifier)
            assert domain.check_invariants(reloaded.project, reloaded.revision) == []
            assert len(reloaded.revision.nodes) == 4
            assert reloaded.revision.source_revision_id == revision_id


# --------------------------------------------------------------------------------------
# Refusals, all decided before the first write
# --------------------------------------------------------------------------------------


def _refused_write_leaves_the_tables_untouched(session: Session) -> None:
    """A refused save writes nothing, even if the caller commits afterwards.

    The state below is one a naive write would get a long way through: a reorder
    (which parks positions in the collision-free band) and a cascade delete (which
    drops rows), followed by a refusal. Were the refusal raised halfway through,
    committing would persist the parked positions -- leaving the revision in
    breach of INV-05 for good, and the band unusable by any later save.
    """
    _, revision_id = _seed_small_tree(session)
    loaded = load_revision(session, revision_id)
    before = _snapshot(session)

    domain.move_nodes_down(loaded.project, loaded.revision, [_task_named(loaded, "First")])
    domain.delete_nodes(loaded.project, loaded.revision, [_task_named(loaded, "Second")])
    loaded.revision.plan_facets[4242] = domain.PlanFacet(
        node_id=4242,
        name="Facet of a node that does not exist",
        calendar_id=loaded.project.calendar_id,
        calendar_source=domain.CalendarSource.PROJECT,
    )

    with pytest.raises(RevisionStoreError, match="INV-12"):
        save_revision(session, loaded)
    session.commit()

    assert _snapshot(session) == before


def test_a_refused_save_writes_nothing_at_all() -> None:
    with get_session_factory()() as session:
        _refused_write_leaves_the_tables_untouched(session)


def test_postgres_a_refused_save_writes_nothing_at_all(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _refused_write_leaves_the_tables_untouched(session)


def test_a_stored_position_inside_the_parking_band_is_refused() -> None:
    """The precondition the band rests on, checked rather than assumed."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        insert_task(session, reference, revision, name="Parked", position=1_000_001)
        insert_task(session, reference, revision, name="Sound", position=1)
        session.commit()

        loaded = load_revision(session, revision.id)
        loaded.revision.nodes[_task_named(loaded, "Parked")].position = 2

        with pytest.raises(RevisionStoreError, match="1000000 band"):
            save_revision(session, loaded)


def test_a_position_to_be_written_inside_the_parking_band_is_refused() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        loaded.revision.nodes[_task_named(loaded, "Parent")].position = 1_000_001

        with pytest.raises(RevisionStoreError, match="1000000 band"):
            save_revision(session, loaded)


def test_a_revision_carrying_frozen_lines_is_refused() -> None:
    """`wf_revision_frozen_line` belongs to the validation of a revision, E14-08."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        domain.validate_revision(
            loaded.project, loaded.revision, now=datetime(2026, 6, 1, tzinfo=UTC)
        )
        assert loaded.revision.frozen_lines

        with pytest.raises(RevisionStoreError, match="#334"):
            save_revision(session, loaded)
        session.commit()

        assert load_revision(session, revision_id).revision.status is domain.RevisionStatus.DRAFT


def test_a_revision_the_database_holds_as_validated_is_never_overwritten() -> None:
    """INV-03: a validated revision is edited by copying it, never in place."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference, status="validated")
        insert_task(session, reference, revision, name="Frozen")
        session.commit()
        loaded = load_revision(session, revision.id)

        with pytest.raises(RevisionStoreError, match="validated"):
            save_revision(session, loaded)


def test_a_node_no_root_reaches_is_refused() -> None:
    """INV-06/INV-09: a level-by-level write would silently skip it."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        loaded.revision.nodes[_task_named(loaded, "Second")].parent_id = 4242

        with pytest.raises(RevisionStoreError, match="no root reaches"):
            save_revision(session, loaded)


def test_a_link_naming_a_node_the_revision_no_longer_holds_is_refused() -> None:
    """INV-08, as a named refusal rather than a bare KeyError."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        loaded.revision.links.append(
            domain.NodeLink(node_id=_task_named(loaded, "First"), predecessor_node_id=4242)
        )

        with pytest.raises(RevisionStoreError, match="INV-08"):
            save_revision(session, loaded)


def test_a_node_carrying_no_facet_is_refused() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        del loaded.revision.plan_facets[_task_named(loaded, "Second")]

        with pytest.raises(RevisionStoreError, match="no facet at all"):
            save_revision(session, loaded)


def test_a_node_carrying_both_facets_is_refused() -> None:
    """INV-11: the half the database cannot see, named instead of silently picked."""
    with get_session_factory()() as session:
        reference, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        node_id = _task_named(loaded, "Second")
        loaded.revision.cost_facets[node_id] = domain.CostFacet(
            node_id=node_id,
            nature=domain.CostNature.LABOR,
            label="A cost facet on a task node",
            role_id=reference.role_id,
            hours=Decimal("2"),
        )

        with pytest.raises(RevisionStoreError, match="both a planning and a cost facet"):
            save_revision(session, loaded)


def test_a_facet_that_contradicts_its_work_item_is_refused() -> None:
    """INV-13: the work item is the authority on the kind, not the facet carried."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        cost_node_id = next(iter(loaded.revision.cost_facets))
        del loaded.revision.cost_facets[cost_node_id]
        loaded.revision.plan_facets[cost_node_id] = domain.PlanFacet(
            node_id=cost_node_id,
            name="A planning facet on a cost work item",
            calendar_id=loaded.project.calendar_id,
            calendar_source=domain.CalendarSource.PROJECT,
        )

        with pytest.raises(RevisionStoreError, match="INV-13"):
            save_revision(session, loaded)


def test_a_node_designating_a_work_item_of_no_loaded_project_is_refused() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        loaded.revision.nodes[_task_named(loaded, "Second")].work_item_id = 4242

        with pytest.raises(RevisionStoreError, match="belongs to no loaded project"):
            save_revision(session, loaded)


def test_changing_the_kind_of_a_stored_work_item_is_refused() -> None:
    """INV-13 as a named refusal, not as a foreign key breaking somewhere else.

    The state below is internally consistent -- the work item changes nature and
    its facet follows -- so nothing earlier in the validation pass objects. What
    the write would do is update `wf_work_item.kind`, which
    `fk_wf_revision_node_work_item` ties to the denormalised kind of the nodes of
    **every** revision carrying that item: rows this write never looked at, and an
    ``IntegrityError`` that leaves the session unusable.
    """
    with get_session_factory()() as session:
        reference, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        node_id = _task_named(loaded, "Second")
        work_item_id = loaded.revision.nodes[node_id].work_item_id
        loaded.project.work_items[work_item_id].kind = domain.WorkItemKind.COST
        del loaded.revision.plan_facets[node_id]
        loaded.revision.cost_facets[node_id] = domain.CostFacet(
            node_id=node_id,
            nature=domain.CostNature.LABOR,
            label="No longer a task",
            role_id=reference.role_id,
            hours=Decimal("2"),
        )

        with pytest.raises(RevisionStoreError, match="stored as task"):
            save_revision(session, loaded)
        session.rollback()

        row = session.get(WorkItem, work_item_id)
        assert row is not None
        assert row.kind == "task"


def test_deleting_a_stored_node_that_is_its_own_parent_terminates() -> None:
    """A stored parent cycle makes the delete ordering walk loop, not fail.

    INV-06 is not expressible in SQL: ``fk_wf_revision_node_parent`` accepts a row
    that is its own parent, so such a row is reachable by a manual repair or by a
    future faulty write path. Deleting it orders the deletes by stored depth, and
    an unguarded walk up that chain never comes back -- pinning a worker instead
    of raising. The domain reports the row as unreachable (INV-06), and dropping
    it is exactly what a caller would do to repair the tree.
    """
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        insert_task(session, reference, revision, name="Keep", position=1)
        looping = insert_task(session, reference, revision, name="Its own parent", position=2)
        looping.parent_id = looping.id
        session.commit()

        loaded = load_revision(session, revision.id)
        assert domain.unreachable_node_ids(loaded.revision) == [looping.id]
        del loaded.revision.nodes[looping.id]
        del loaded.revision.plan_facets[looping.id]

        with _time_limit(30):
            save_revision(session, loaded)
        session.commit()

        assert _node_count(session, revision.id) == 1
        reloaded = load_revision(session, revision.id)
        assert domain.check_invariants(reloaded.project, reloaded.revision) == []


def test_a_planning_facet_without_a_calendar_is_refused() -> None:
    """INV-15: a task is always schedulable, so it always carries a calendar."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        loaded.revision.plan_facets[_task_named(loaded, "First")].calendar_id = None

        with pytest.raises(RevisionStoreError, match="INV-15"):
            save_revision(session, loaded)


# --------------------------------------------------------------------------------------
# Precedence links
# --------------------------------------------------------------------------------------


def test_an_unrelated_edit_leaves_the_precedence_links_in_place() -> None:
    """Links are diffed on their triple, not deleted and rewritten on every save."""
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        before = {
            (row.node_id, row.predecessor_node_id): row.id
            for row in session.query(RevisionNodeLink)
        }

        domain.rename_task(loaded.revision, _task_named(loaded, "First"), "Renamed")
        save_revision(session, loaded)
        session.commit()

        after = {
            (row.node_id, row.predecessor_node_id): row.id
            for row in session.query(RevisionNodeLink)
        }
        assert after == before


def test_an_added_link_is_inserted_and_a_dropped_one_deleted() -> None:
    with get_session_factory()() as session:
        _, revision_id = _seed_small_tree(session)
        loaded = load_revision(session, revision_id)
        domain.add_link(
            loaded.revision,
            node_id=_task_named(loaded, "Second"),
            predecessor_node_id=_task_named(loaded, "First"),
            link_type=0,
        )

        save_revision(session, loaded)
        session.commit()
        assert session.query(RevisionNodeLink).count() == 2

        loaded.revision.links = []
        save_revision(session, loaded)
        session.commit()

        assert session.query(RevisionNodeLink).count() == 0


def _links_by_triple(session: Session, revision_id: int) -> dict[tuple[int, int, int], int]:
    return {
        (row.node_id, row.predecessor_node_id, row.link_type): row.id
        for row in session.query(RevisionNodeLink).filter(
            RevisionNodeLink.revision_id == revision_id
        )
    }


def _highest_link_id(session: Session) -> int:
    return session.query(func.max(RevisionNodeLink.id)).scalar() or 0


def _seed_a_link_in_a_later_revision(session: Session, reference: ReferenceData) -> int:
    """A link of another revision, inserted last and never touched by the saves below.

    It is what makes the row-id comparisons of :func:`_link_diff` independent of the
    order the fixture inserted the links under test in. SQLite allocates a rowid as
    ``max(rowid) + 1`` over the rows the table still *holds*: delete every link of
    the revision under test and reinsert it, and the freed ids come straight back --
    handed out in ``sorted(triple)`` order, which is the order ``_save_links``
    reinserts in. A fixture that happened to insert its links in that same order
    would then compare equal to itself, and these assertions would hold just as well
    for the wholesale rewrite they exist to catch.

    One surviving row of higher id removes that coincidence: whatever order the
    reinsertion goes in, it lands above the ids compared. PostgreSQL needs no such
    help, its sequence never reusing an id -- which is why the variant that runs
    there is the real guarantee and this the SQLite stand-in.

    Returns the id of the seeded link, which every save below must leave alone: it
    belongs to another revision, and the diff only ever touches its own.
    """
    later = insert_revision(session, reference, version_number=2)
    predecessor = insert_task(session, reference, later, name="Elsewhere A", position=1)
    node = insert_task(session, reference, later, name="Elsewhere B", position=2)
    return insert_link(session, later, node, predecessor, link_type=1).id


def _link_diff(session: Session) -> None:
    """The diff, on the link that actually changed -- the case the two tests above miss.

    One asserts links survive an unrelated edit, the other that an added link is
    inserted and a dropped one deleted; neither says what happens to a link whose
    *attributes* change. A lag is an update of the stored row, identity and all,
    while the link type is part of that identity and can only be a replacement.
    Both are asserted on the row ids, which is what a regression to "delete every
    link and rewrite them" would shuffle.

    The two links are edited through the entities directly: the domain exposes
    ``add_link`` and nothing to retune one, and what is under test here is the
    adapter's diff, not a tree operation.

    The second link is written straight into the table, like the first, so that
    the row ids compared below are the ones the *fixture* allocated. Captured
    after a save instead, they would already be whatever the write path made of
    them -- and a write path that rewrites every link on every save would compare
    equal to itself.
    """
    reference, revision_id = _seed_small_tree(session)
    revision_row = session.get(ProjectRevision, revision_id)
    assert revision_row is not None
    named = {
        facet.name: session.get(RevisionNode, facet.node_id)
        for facet in session.query(RevisionPlanFacet)
        .join(RevisionNode, RevisionNode.id == RevisionPlanFacet.node_id)
        .filter(RevisionNode.revision_id == revision_id)
    }
    first_node, parent_node = named["First"], named["Parent"]
    assert first_node is not None and parent_node is not None
    insert_link(session, revision_row, first_node, parent_node, link_type=2)
    elsewhere = _seed_a_link_in_a_later_revision(session, reference)
    session.commit()
    before = _links_by_triple(session, revision_id)
    assert len(before) == 2
    assert elsewhere == _highest_link_id(session)
    assert max(before.values()) < elsewhere, (
        "precondition: a link row of higher id outlives every save below, so reinserting "
        "these two cannot land back on their own ids and the comparisons stay discriminating "
        "whatever order the fixture inserted them in (see _seed_a_link_in_a_later_revision)"
    )

    loaded = load_revision(session, revision_id)

    edited = next(link for link in loaded.revision.links if link.link_type == 1)
    edited.lag_tenth_minute = 4800
    edited.lag_format = 7
    save_revision(session, loaded)
    session.commit()

    assert _links_by_triple(session, revision_id) == before, "a lag is an update, not a new row"
    row = session.get(RevisionNodeLink, before[(edited.node_id, edited.predecessor_node_id, 1)])
    assert row is not None
    assert (row.lag_tenth_minute, row.lag_format) == (4800, 7)

    untouched = next(link for link in loaded.revision.links if link.link_type == 2)
    untouched_key = (untouched.node_id, untouched.predecessor_node_id, 2)
    edited.link_type = 3
    save_revision(session, loaded)
    session.commit()

    after = _links_by_triple(session, revision_id)
    assert set(after) == {untouched_key, (edited.node_id, edited.predecessor_node_id, 3)}
    assert after[untouched_key] == before[untouched_key], "its neighbour kept its row"

    loaded.revision.links.append(
        domain.NodeLink(
            node_id=edited.node_id,
            predecessor_node_id=edited.predecessor_node_id,
            link_type=3,
            lag_tenth_minute=60,
        )
    )
    save_revision(session, loaded)
    session.commit()

    # Counted on the rows, not on the triples the dict above would collapse.
    stored_links = (
        session.query(RevisionNodeLink).filter(RevisionNodeLink.revision_id == revision_id).count()
    )
    assert stored_links == 2, "a duplicate triple collapses"
    assert session.get(RevisionNodeLink, elsewhere) is not None, "another revision, untouched"


def test_an_edited_link_is_updated_in_place_and_a_retyped_one_replaced() -> None:
    with get_session_factory()() as session:
        _link_diff(session)


def test_postgres_an_edited_link_is_updated_in_place_and_a_retyped_one_replaced(
    postgres_app_database_url: str,
) -> None:
    """The same, where the row ids prove it on their own.

    A PostgreSQL sequence never hands a freed id back, so a write path that deleted
    every link and rewrote it lands on new ids here no matter what -- independently
    of the insertion order the SQLite variant has to be shielded from.
    """
    with postgres_session(postgres_app_database_url) as session:
        _link_diff(session)
