"""The single tree service on the revision node (E14-04, issue #330).

Every acceptance criterion of the issue is pinned down here, and three of them
deliberately look at the **database** rather than at the state in memory: a
cascade delete that leaves an orphan facet behind is exactly the shape of #267,
and an in-memory assertion would not have caught it.

The concurrency criterion runs on PostgreSQL only -- SQLAlchemy's SQLite dialect
drops ``SELECT ... FOR UPDATE`` silently, so the SQLite session could never
observe the row lock the optimistic guard rests on. Same pattern, and the same
reasoning, as ``test_planning_revision_locking.py``.
"""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_revision,
    insert_task,
    seed_reference_data,
)
from waterfall.db.session import get_session_factory
from waterfall.domain import revision as domain
from waterfall.models.revision import (
    ProjectRevision,
    RevisionCostFacet,
    RevisionNode,
    RevisionPlanFacet,
    WorkItem,
)
from waterfall.services import revision_tree
from waterfall.services.revision_store import (
    RevisionNotFoundError,
    RevisionStoreError,
    load_revision,
    save_revision,
)
from waterfall.services.revision_tree import RevisionLockConflictError


@dataclass(frozen=True)
class Tree:
    """The seeded tree, by database id.

    ``alpha`` (task) > ``design`` (task) > {``study`` (MO), ``sub`` (task) >
    ``wiring`` (MO)}; ``alpha`` > ``build`` (task); ``beta`` (task) at the root.
    """

    reference: ReferenceData
    revision_id: int
    alpha: int
    design: int
    study: int
    sub: int
    wiring: int
    build: int
    beta: int


def _seed_tree(session: Session, *, status: str = "draft") -> Tree:
    """Write the tree straight into the tables, bypassing the service entirely."""
    reference = seed_reference_data(session)
    revision = insert_revision(session, reference, status=status)
    alpha = insert_task(session, reference, revision, name="Alpha", position=1, external_uid=1)
    design = insert_task(
        session, reference, revision, name="Design", parent_id=alpha.id, position=1, external_uid=2
    )
    study = insert_labor_line(
        session, reference, revision, label="Study", parent_id=design.id, position=1
    )
    sub = insert_task(
        session, reference, revision, name="Sub", parent_id=design.id, position=2, external_uid=3
    )
    wiring = insert_labor_line(
        session,
        reference,
        revision,
        label="Wiring",
        parent_id=sub.id,
        position=1,
        hours=Decimal("7"),
    )
    build = insert_task(
        session, reference, revision, name="Build", parent_id=alpha.id, position=2, external_uid=4
    )
    beta = insert_task(session, reference, revision, name="Beta", position=2, external_uid=5)
    session.commit()
    return Tree(
        reference=reference,
        revision_id=revision.id,
        alpha=alpha.id,
        design=design.id,
        study=study.id,
        sub=sub.id,
        wiring=wiring.id,
        build=build.id,
        beta=beta.id,
    )


def _stored_tree(session: Session, revision_id: int) -> list[tuple[int, int | None, int, str]]:
    """``(node id, parent id, position, kind)`` of every stored node, read back from the base."""
    session.expire_all()
    return sorted(
        (row.id, row.parent_id, row.position, row.kind)
        for row in session.query(RevisionNode).filter(RevisionNode.revision_id == revision_id)
    )


def _stored_cost_facet(session: Session, node_id: int) -> tuple[Any, ...]:
    """Every business column of a stored cost facet, so "unchanged" means unchanged."""
    session.expire_all()
    row = session.query(RevisionCostFacet).filter(RevisionCostFacet.node_id == node_id).one()
    return (
        row.nature,
        row.label,
        row.quantity,
        row.role_id,
        row.hours,
        row.cost_type_id,
        row.cost_category_id,
        row.unit_cost,
        row.supply_status,
        row.planned_date,
        row.cost_code_id,
        row.comment,
    )


def _orphan_facet_node_ids(session: Session) -> list[int]:
    """Node ids named by a stored facet no stored node carries -- #267, asked of the database."""
    session.expire_all()
    nodes = {row.id for row in session.query(RevisionNode)}
    plans = {row.node_id for row in session.query(RevisionPlanFacet)}
    costs = {row.node_id for row in session.query(RevisionCostFacet)}
    return sorted((plans | costs) - nodes)


def _lock_version(session: Session, revision_id: int) -> int:
    session.expire_all()
    row = session.get(ProjectRevision, revision_id)
    assert row is not None
    return row.lock_version


def _children_of(session: Session, revision_id: int, parent_id: int | None) -> list[int]:
    session.expire_all()
    return [
        row.id
        for row in session.query(RevisionNode)
        .filter(RevisionNode.revision_id == revision_id, RevisionNode.parent_id == parent_id)
        .order_by(RevisionNode.position)
    ]


# --------------------------------------------------------------------------------------
# Insertion
# --------------------------------------------------------------------------------------


def test_adding_a_task_writes_the_node_its_facet_and_bumps_the_lock_version() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        inserted = revision_tree.add_task(
            session,
            tree.revision_id,
            expected_lock_version=0,
            name="Commissioning",
            parent_id=tree.alpha,
            position=1,
        )
        session.commit()

        assert inserted.lock_version == 1
        assert _lock_version(session, tree.revision_id) == 1
        row = session.get(RevisionNode, inserted.node_id)
        assert row is not None
        assert (row.parent_id, row.position, row.kind) == (tree.alpha, 1, "task")
        facet = (
            session.query(RevisionPlanFacet)
            .filter(RevisionPlanFacet.node_id == inserted.node_id)
            .one()
        )
        assert facet.name == "Commissioning"
        assert facet.calendar_id == tree.reference.calendar_id
        item = session.get(WorkItem, inserted.work_item_id)
        assert item is not None and item.kind == "task"
        # The sibling it was inserted before was pushed down, contiguously.
        assert _children_of(session, tree.revision_id, tree.alpha) == [
            inserted.node_id,
            tree.design,
            tree.build,
        ]


def test_adding_a_cost_line_at_the_root_is_a_global_cost_without_a_bearing_task() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        inserted = revision_tree.add_cost_line(
            session,
            tree.revision_id,
            expected_lock_version=0,
            nature=domain.CostNature.NON_LABOR,
            label="Site insurance",
            cost_type_id=tree.reference.cost_type_id,
            cost_category_id=tree.reference.cost_category_id,
            unit_cost=Decimal("5000.00"),
        )
        session.commit()

        row = session.get(RevisionNode, inserted.node_id)
        assert row is not None
        assert (row.parent_id, row.kind) == (None, "cost")
        assert (
            revision_tree.resolve_bearing_task(session, tree.revision_id, inserted.node_id) is None
        )


def test_a_labour_line_without_its_hours_is_refused_by_the_domain() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        with pytest.raises(domain.FacetContractError):
            revision_tree.add_cost_line(
                session,
                tree.revision_id,
                expected_lock_version=0,
                nature=domain.CostNature.LABOR,
                label="Unpriced",
                parent_id=tree.build,
                role_id=tree.reference.role_id,
            )
        session.rollback()

        assert _lock_version(session, tree.revision_id) == 0


# --------------------------------------------------------------------------------------
# Acceptance 1: a cost line moved under another task changes its bearing task
# --------------------------------------------------------------------------------------


def test_moving_a_cost_node_changes_its_bearing_task_and_leaves_its_facet_untouched() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        before = _stored_cost_facet(session, tree.study)
        bearing = revision_tree.resolve_bearing_task(session, tree.revision_id, tree.study)
        assert bearing is not None and bearing.node_id == tree.design

        write = revision_tree.move_nodes(
            session,
            tree.revision_id,
            [tree.study],
            expected_lock_version=0,
            target_parent_id=tree.build,
        )
        session.commit()

        assert write.lock_version == 1
        moved = revision_tree.resolve_bearing_task(session, tree.revision_id, tree.study)
        assert moved is not None
        assert (moved.node_id, moved.name) == (tree.build, "Build")
        # The cost facet itself never moved: only the node did, and the bearing
        # task is resolved from the tree rather than stored (INV-01).
        assert _stored_cost_facet(session, tree.study) == before
        assert _children_of(session, tree.revision_id, tree.build) == [tree.study]
        # And the sibling set it left closed the hole behind it (INV-05).
        assert _children_of(session, tree.revision_id, tree.design) == [tree.sub]
        row = session.get(RevisionNode, tree.sub)
        assert row is not None and row.position == 1


# --------------------------------------------------------------------------------------
# Acceptance 2: a task moved carries its whole subtree, cost facets included
# --------------------------------------------------------------------------------------


def test_moving_a_task_carries_its_whole_subtree_in_the_same_relative_order() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        study_before = _stored_cost_facet(session, tree.study)
        wiring_before = _stored_cost_facet(session, tree.wiring)

        revision_tree.move_nodes(
            session,
            tree.revision_id,
            [tree.design],
            expected_lock_version=0,
            target_parent_id=tree.beta,
        )
        session.commit()

        assert _children_of(session, tree.revision_id, tree.beta) == [tree.design]
        # Same children, same relative order, cost facet first as it was.
        assert _children_of(session, tree.revision_id, tree.design) == [tree.study, tree.sub]
        assert _children_of(session, tree.revision_id, tree.sub) == [tree.wiring]
        assert _stored_cost_facet(session, tree.study) == study_before
        assert _stored_cost_facet(session, tree.wiring) == wiring_before
        # The subtree really left its former parent, which renumbered.
        assert _children_of(session, tree.revision_id, tree.alpha) == [tree.build]
        row = session.get(RevisionNode, tree.build)
        assert row is not None and row.position == 1


def test_indent_outdent_and_the_sibling_shifts_reach_the_database() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        revision_tree.indent_nodes(session, tree.revision_id, [tree.build], expected_lock_version=0)
        session.commit()
        assert _children_of(session, tree.revision_id, tree.design) == [
            tree.study,
            tree.sub,
            tree.build,
        ]

        revision_tree.move_nodes_up(
            session, tree.revision_id, [tree.build], expected_lock_version=1
        )
        session.commit()
        assert _children_of(session, tree.revision_id, tree.design) == [
            tree.study,
            tree.build,
            tree.sub,
        ]

        revision_tree.move_nodes_down(
            session, tree.revision_id, [tree.build], expected_lock_version=2
        )
        session.commit()
        assert _children_of(session, tree.revision_id, tree.design) == [
            tree.study,
            tree.sub,
            tree.build,
        ]

        revision_tree.outdent_nodes(
            session, tree.revision_id, [tree.build], expected_lock_version=3
        )
        session.commit()
        assert _children_of(session, tree.revision_id, tree.alpha) == [tree.design, tree.build]


def test_outdenting_up_to_the_root_lands_right_after_the_former_parent() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        revision_tree.outdent_nodes(
            session, tree.revision_id, [tree.design], expected_lock_version=0
        )
        session.commit()

        assert _children_of(session, tree.revision_id, None) == [tree.alpha, tree.design, tree.beta]


def test_moving_a_selection_to_the_root_is_accepted() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        revision_tree.move_nodes(
            session,
            tree.revision_id,
            [tree.sub, tree.build],
            expected_lock_version=0,
            target_parent_id=None,
            position=1,
        )
        session.commit()

        assert _children_of(session, tree.revision_id, None) == [
            tree.sub,
            tree.build,
            tree.alpha,
            tree.beta,
        ]
        # The MO line under the moved task came along.
        assert _children_of(session, tree.revision_id, tree.sub) == [tree.wiring]


# --------------------------------------------------------------------------------------
# Acceptance 3: a cascade delete leaves no orphan facet in the database
# --------------------------------------------------------------------------------------


def test_deleting_an_intermediate_node_leaves_no_orphan_facet_in_the_database() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        deleted = revision_tree.delete_nodes(
            session, tree.revision_id, [tree.design], expected_lock_version=0
        )
        session.commit()

        assert set(deleted.removed_node_ids) == {tree.design, tree.study, tree.sub, tree.wiring}
        assert sorted(loss.label for loss in deleted.cost_losses) == ["Study", "Wiring"]
        # Asked of the database, not of the state in memory: this is #267.
        assert _orphan_facet_node_ids(session) == []
        assert _stored_tree(session, tree.revision_id) == [
            (tree.alpha, None, 1, "task"),
            (tree.build, tree.alpha, 1, "task"),
            (tree.beta, None, 2, "task"),
        ]
        for node_id in (tree.design, tree.sub):
            assert (
                session.query(RevisionPlanFacet)
                .filter(RevisionPlanFacet.node_id == node_id)
                .count()
                == 0
            )
        for node_id in (tree.study, tree.wiring):
            assert (
                session.query(RevisionCostFacet)
                .filter(RevisionCostFacet.node_id == node_id)
                .count()
                == 0
            )
        # The work items survive: they are the identity of an element of work
        # across the revisions of the project, not of one of its nodes.
        assert session.query(WorkItem).count() == 7


def test_a_cascade_delete_names_the_chiffrage_it_takes_away() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        deleted = revision_tree.delete_nodes(
            session, tree.revision_id, [tree.sub], expected_lock_version=0
        )
        session.commit()

        assert [(loss.label, loss.bearing_task_name) for loss in deleted.cost_losses] == [
            ("Wiring", "Sub")
        ]
        assert deleted.lock_version == 1


# --------------------------------------------------------------------------------------
# Acceptance 4: a move under one's own descendant is refused, and changes nothing
# --------------------------------------------------------------------------------------


def test_moving_a_node_under_its_own_descendant_is_refused_without_touching_the_tree() -> None:
    """Nothing is written, and "nothing" is asked of a **second** session.

    Read back through the same session after a ``rollback()``, the assertion would
    hold whatever the service had flushed -- the rollback undoes a partial write
    just as thoroughly as it undoes none at all. A second session sees only what
    was committed, so it tells "the refusal never flushed" from "the refusal
    flushed and the test cleaned up after it".
    """
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        before = _stored_tree(session, tree.revision_id)

        with pytest.raises(domain.TreeCycleError):
            revision_tree.move_nodes(
                session,
                tree.revision_id,
                [tree.design],
                expected_lock_version=0,
                target_parent_id=tree.sub,
            )

        with get_session_factory()() as onlooker:
            assert _stored_tree(onlooker, tree.revision_id) == before
            assert _lock_version(onlooker, tree.revision_id) == 0
        session.rollback()

        assert _stored_tree(session, tree.revision_id) == before
        assert _lock_version(session, tree.revision_id) == 0


def test_indenting_a_task_under_a_cost_line_is_refused() -> None:
    """INV-14: the planning layer is upward-closed -- a task never hangs under a cost."""
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        before = _stored_tree(session, tree.revision_id)

        with pytest.raises(domain.FacetPlacementError):
            revision_tree.indent_nodes(
                session, tree.revision_id, [tree.sub], expected_lock_version=0
            )
        session.rollback()

        assert _stored_tree(session, tree.revision_id) == before


# --------------------------------------------------------------------------------------
# Acceptance 5: two writes from the same lock version
# --------------------------------------------------------------------------------------


def test_a_stale_lock_version_is_refused_and_nothing_is_written() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        revision_tree.add_task(
            session, tree.revision_id, expected_lock_version=0, name="First", parent_id=tree.beta
        )
        session.commit()
        before = _stored_tree(session, tree.revision_id)

        with pytest.raises(RevisionLockConflictError) as caught:
            revision_tree.add_task(
                session,
                tree.revision_id,
                expected_lock_version=0,
                name="Second",
                parent_id=tree.beta,
            )
        session.rollback()

        assert caught.value.expected_lock_version == 0
        assert caught.value.current_lock_version == 1
        assert caught.value.revision_id == tree.revision_id
        assert _stored_tree(session, tree.revision_id) == before
        assert _lock_version(session, tree.revision_id) == 1


def _wait_until_backend_blocked_on_lock(
    engine: Engine, backend_pid: int, timeout: float = 5.0
) -> None:
    """Poll pg_stat_activity until ``backend_pid`` is observed waiting on a lock.

    A fixed sleep would make the assertions vacuous: the point is to prove the
    loser *queued behind* the winner's row lock, not merely that it lost a race
    it might have run before the winner even started.
    """
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            row = probe.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": backend_pid},
            ).first()
            if row is not None and row[0] == "Lock":
                return
            time.sleep(0.02)
    pytest.fail(f"Backend pid {backend_pid} never entered a lock wait within {timeout}s")


def test_postgres_two_concurrent_writes_from_the_same_lock_version_serialize(
    postgres_app_database_url: str,
) -> None:
    """The loser is refused, the winner is applied -- and the loser really waited.

    Session A takes the revision's row lock and writes, without committing.
    Session B, still holding the *same* ``expected_lock_version``, blocks on that
    lock inside :func:`revision_tree._claim_revision`; once A commits, B re-reads
    the row PostgreSQL now shows it, sees the bumped counter and refuses. The
    dangerous outcome -- two writes both succeeding from the same version -- is
    exactly what the row lock plus the counter comparison rules out.
    """
    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            tree = _seed_tree(seed_session)

        session_a = session_factory()
        session_b = session_factory()
        try:
            revision_tree.add_task(
                session_a,
                tree.revision_id,
                expected_lock_version=0,
                name="Winner",
                parent_id=tree.beta,
            )

            # Session B's backend pid, captured before the thread starts: a
            # session cannot safely be driven from two threads at once.
            backend_pid_b = session_b.execute(text("SELECT pg_backend_pid()")).scalar()
            assert backend_pid_b is not None

            results: dict[str, Any] = {}

            def _run_session_b() -> None:
                try:
                    results["written"] = revision_tree.add_task(
                        session_b,
                        tree.revision_id,
                        expected_lock_version=0,
                        name="Loser",
                        parent_id=tree.beta,
                    )
                except RevisionLockConflictError as exc:
                    results["conflict"] = exc

            thread = threading.Thread(target=_run_session_b)
            thread.start()
            try:
                _wait_until_backend_blocked_on_lock(engine, backend_pid_b)
                session_a.commit()
                thread.join(timeout=10)
                assert not thread.is_alive(), "session B never returned -- looks like a deadlock"
            finally:
                session_b.rollback()

            assert "written" not in results, "the stale write must not have been applied"
            conflict = results["conflict"]
            assert conflict.expected_lock_version == 0
            assert conflict.current_lock_version == 1
        finally:
            session_a.close()
            session_b.close()

        with session_factory() as verify_session:
            assert _lock_version(verify_session, tree.revision_id) == 1
            names = sorted(
                facet.name
                for facet in verify_session.query(RevisionPlanFacet)
                .join(RevisionNode, RevisionNode.id == RevisionPlanFacet.node_id)
                .filter(RevisionNode.parent_id == tree.beta)
            )
            assert names == ["Winner"]
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Acceptance 6: a validated revision refuses every write, on either facet
# --------------------------------------------------------------------------------------


def _write_attempts(
    session: Session, tree: Tree, *, expected_lock_version: int = 0
) -> list[tuple[str, Callable[[], object]]]:
    """Every write this service exposes, one call each -- all eight of them.

    Exhaustive on purpose, exactly like the domain's own INV-03 matrix: each of
    these goes through ``_claim_revision``, but nothing would stop the route work
    of #331/#332/#333 from adding one that forgets to -- or that calls
    ``load_revision`` *before* locking, which reads a tree the lock does not
    cover. Either would pass every behavioural test in this file while quietly
    bypassing the single optimistic lock of the EPIC on that one route.

    Three guards ride on this list, and a new operation has to satisfy all three:
    it is *covered* by the matrix, its signature *takes* an
    ``expected_lock_version``, and it *claims before it reads*.

    ``create_revision_from`` is absent by design, and named as an exception below:
    it is the one write that must *not* require a draft (INV-07, copying is how a
    validated revision is edited).
    """
    return [
        (
            "add_task",
            lambda: revision_tree.add_task(
                session,
                tree.revision_id,
                expected_lock_version=expected_lock_version,
                name="Planning side",
                parent_id=tree.beta,
            ),
        ),
        (
            "add_cost_line",
            lambda: revision_tree.add_cost_line(
                session,
                tree.revision_id,
                expected_lock_version=expected_lock_version,
                nature=domain.CostNature.LABOR,
                label="Cost side",
                parent_id=tree.build,
                role_id=tree.reference.role_id,
                hours=Decimal("3"),
            ),
        ),
        (
            "move_nodes",
            lambda: revision_tree.move_nodes(
                session,
                tree.revision_id,
                [tree.study],
                expected_lock_version=expected_lock_version,
                target_parent_id=tree.build,
            ),
        ),
        (
            "move_nodes_up",
            lambda: revision_tree.move_nodes_up(
                session,
                tree.revision_id,
                [tree.beta],
                expected_lock_version=expected_lock_version,
            ),
        ),
        (
            "move_nodes_down",
            lambda: revision_tree.move_nodes_down(
                session,
                tree.revision_id,
                [tree.alpha],
                expected_lock_version=expected_lock_version,
            ),
        ),
        (
            "indent_nodes",
            lambda: revision_tree.indent_nodes(
                session,
                tree.revision_id,
                [tree.build],
                expected_lock_version=expected_lock_version,
            ),
        ),
        (
            "outdent_nodes",
            lambda: revision_tree.outdent_nodes(
                session,
                tree.revision_id,
                [tree.study],
                expected_lock_version=expected_lock_version,
            ),
        ),
        (
            "delete_nodes",
            lambda: revision_tree.delete_nodes(
                session,
                tree.revision_id,
                [tree.study],
                expected_lock_version=expected_lock_version,
            ),
        ),
        (
            "compact_positions",
            lambda: revision_tree.compact_positions(
                session, tree.revision_id, expected_lock_version=expected_lock_version
            ),
        ),
    ]


#: Public callables of ``revision_tree`` that write nothing, and therefore owe
#: nothing to the lock or to INV-03. Spelled out one by one, as in the domain's
#: ``_TREE_READERS``: a new operation is a *write* until this list says otherwise,
#: so forgetting to add it to the matrix fails rather than passes unnoticed.
_SERVICE_READERS = frozenset({"resolve_bearing_task"})

#: The single documented exception to "every write refuses a non-draft revision".
#: It still takes -- and still enforces -- ``expected_lock_version``, so it is
#: exempt from the INV-03 guard only, never from the lock one.
_IMMUTABILITY_EXCEPTIONS = frozenset({"create_revision_from"})


def _public_operations(namespace: Mapping[str, object], module_name: str) -> set[str]:
    """Public callables ``module_name`` itself defines, dataclasses and errors excluded."""
    return {
        name
        for name, value in namespace.items()
        if not name.startswith("_")
        and callable(value)
        and not isinstance(value, type)  # the result dataclasses and the error classes
        and getattr(value, "__module__", "") == module_name
    }


@pytest.mark.parametrize("status", ["validated", "superseded"])
def test_every_write_on_a_frozen_revision_is_refused_on_both_facets(status: str) -> None:
    """INV-03, on both frozen statuses: the service guard reads the *stored* status,
    which is ``!= 'draft'``, so ``superseded`` is refused exactly as ``validated``."""
    with get_session_factory()() as session:
        tree = _seed_tree(session, status=status)
        before = _stored_tree(session, tree.revision_id)

        for label, attempt in _write_attempts(session, tree):
            with pytest.raises(domain.ImmutableRevisionError):
                attempt()
            session.rollback()
            assert _stored_tree(session, tree.revision_id) == before, f"{label} wrote the tree"

        # INV-03 to the letter: the state is rigorously identical, lock_version included.
        assert _stored_tree(session, tree.revision_id) == before
        assert _lock_version(session, tree.revision_id) == 0


def test_the_write_matrix_covers_every_service_write() -> None:
    """Guards the matrix itself: a new write must be added to it, not forgotten.

    The service counterpart of the domain's
    ``test_inv_03_the_write_matrix_covers_every_tree_write``, and it exists for the
    same reason: the matrix above is the only thing that proves a *new* operation
    did not skip ``_claim_revision``.
    """
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        covered = {label for label, _ in _write_attempts(session, tree)}

    exposed = (
        _public_operations(vars(revision_tree), revision_tree.__name__)
        - _SERVICE_READERS
        - _IMMUTABILITY_EXCEPTIONS
    )

    assert exposed, "no service write found: the introspection no longer sees the module"
    assert exposed <= covered, f"writes missing from the service write matrix: {exposed - covered}"


def test_every_service_write_takes_an_expected_lock_version() -> None:
    """The other half of the guard: the matrix proves the *refusal*, this proves the
    *signature*. A write that simply has no ``expected_lock_version`` to hand could
    never be claimed under the single optimistic lock, whatever it does inside."""
    writes = _public_operations(vars(revision_tree), revision_tree.__name__) - _SERVICE_READERS

    assert writes, "no service write found: the introspection no longer sees the module"
    for name in sorted(writes):
        parameter = inspect.signature(getattr(revision_tree, name)).parameters.get(
            "expected_lock_version"
        )
        assert parameter is not None, f"{name} takes no expected_lock_version"
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{name} takes expected_lock_version positionally: it must be keyword-only, so a "
            "caller can never pass it by accident in the place of a node id"
        )


def test_every_service_write_claims_the_revision_before_it_reads_the_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The third guard, and the one behaviour alone cannot show.

    An operation that loaded the revision and *then* took the lock would pass
    every other test here: it would refuse a frozen revision, refuse a stale
    counter, and write the right tree. What it would not do is write the tree the
    lock covers -- a concurrent writer committing between the read and the lock
    would be read past, silently. The order is the guarantee (see
    ``_claim_revision``), so the order is what is asserted, on every write of the
    matrix at once.
    """
    calls: list[str] = []
    real_claim = revision_tree._claim_revision  # pyright: ignore[reportPrivateUsage]
    real_load = revision_tree.load_revision

    def claiming(*args: Any, **kwargs: Any) -> Any:
        calls.append("claim")
        return real_claim(*args, **kwargs)

    def loading(*args: Any, **kwargs: Any) -> Any:
        calls.append("load")
        return real_load(*args, **kwargs)

    monkeypatch.setattr(revision_tree, "_claim_revision", claiming)
    monkeypatch.setattr(revision_tree, "load_revision", loading)

    with get_session_factory()() as session:
        tree = _seed_tree(session)
        for label, attempt in _write_attempts(session, tree):
            calls.clear()
            attempt()
            assert calls == ["claim", "load"], f"{label} read the tree outside the lock: {calls}"
            # Each attempt starts from the seeded tree again, so every one of them
            # runs against the same state and the same lock version.
            session.rollback()


def test_the_write_matrix_guards_fail_on_a_write_that_forgot_the_lock() -> None:
    """Both guards above only have value if they *fail* on a write nobody declared.

    Same shape as the domain's ``test_the_write_matrix_guard_fails_on_a_write_
    blessed_as_a_reader``: a public callable of ``revision_tree`` that mutates a
    revision, takes no ``expected_lock_version``, and is in neither whitelist --
    precisely what #331 or #333 would add by accident. Reproduced here rather than
    waited for.
    """

    def rename_task(db: Session, revision_id: int, node_id: int, name: str) -> None:
        """The plausible omission: loads, mutates, saves, never claims."""
        loaded = load_revision(db, revision_id)
        loaded.revision.plan_facets[node_id].name = name
        save_revision(db, loaded)

    rename_task.__module__ = revision_tree.__name__
    namespace = {**vars(revision_tree), "rename_task": rename_task}
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        covered = {label for label, _ in _write_attempts(session, tree)}

    declared = _public_operations(namespace, revision_tree.__name__) - (
        _SERVICE_READERS | _IMMUTABILITY_EXCEPTIONS | {"rename_task"}
    )
    unmasked = _public_operations(namespace, revision_tree.__name__) - (
        _SERVICE_READERS | _IMMUTABILITY_EXCEPTIONS
    )

    assert declared <= covered, "a declared write is reported anyway: the setup is wrong"
    # The coverage guard names it...
    assert "rename_task" in unmasked - covered
    # ... and so does the signature guard, independently.
    assert "expected_lock_version" not in inspect.signature(rename_task).parameters


def test_a_validated_revision_is_refused_again_by_the_store_under_the_service_guard() -> None:
    """The two guards combine rather than contradict each other.

    The service refuses on the *stored* status before reading anything; the
    domain's ``require_draft`` refuses the same operation on the state it loaded;
    and the store refuses to overwrite a revision the database holds as validated
    even when the state in hand claims to be a draft. Each one alone would leave
    a hole: this checks the last of the three, which is the one no caller can
    reach through the service at all.
    """
    with get_session_factory()() as session:
        tree = _seed_tree(session, status="validated")

        with pytest.raises(domain.ImmutableRevisionError):
            revision_tree.move_nodes(
                session,
                tree.revision_id,
                [tree.study],
                expected_lock_version=0,
                target_parent_id=tree.build,
            )
        session.rollback()

        loaded = load_revision(session, tree.revision_id)
        loaded.revision.status = domain.RevisionStatus.DRAFT
        domain.move_nodes(
            loaded.project, loaded.revision, [tree.study], target_parent_id=tree.build
        )
        with pytest.raises(RevisionStoreError, match="no longer accepts a write"):
            save_revision(session, loaded)
        session.rollback()

        assert _lock_version(session, tree.revision_id) == 0


# --------------------------------------------------------------------------------------
# Compaction, bearing task, copy
# --------------------------------------------------------------------------------------


def test_compaction_closes_a_hole_written_straight_into_the_tables() -> None:
    """The repair path: positions the service did not write can be non-contiguous."""
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        row = session.get(RevisionNode, tree.build)
        assert row is not None
        row.position = 9
        session.commit()

        compacted = revision_tree.compact_positions(
            session, tree.revision_id, expected_lock_version=0
        )
        session.commit()

        assert compacted.moved_node_ids == (tree.build,)
        assert compacted.lock_version == 1
        moved = session.get(RevisionNode, tree.build)
        assert moved is not None and moved.position == 2


def test_compacting_a_contiguous_tree_moves_nothing_but_still_counts_as_a_write() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        compacted = revision_tree.compact_positions(
            session, tree.revision_id, expected_lock_version=0
        )
        session.commit()

        assert compacted.moved_node_ids == ()
        assert _lock_version(session, tree.revision_id) == 1


def test_compaction_cannot_repair_a_position_parked_in_the_store_band() -> None:
    """The limit the docstring claims, pinned down: the repair has a blind spot.

    A position at or above the store's parking band is the residue of an
    interrupted write -- the very accident that leaves a sibling set needing a
    repair -- and the store refuses to write back a revision holding one. A
    support engineer reaching for this function after such an interruption gets a
    refusal, not a repair, and has to bring the row back under the band with a
    direct ``UPDATE`` first.
    """
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        row = session.get(RevisionNode, tree.build)
        assert row is not None
        row.position = 1_000_002
        session.commit()

        with pytest.raises(RevisionStoreError, match="band this adapter parks a moved node in"):
            revision_tree.compact_positions(session, tree.revision_id, expected_lock_version=0)
        session.rollback()

        # Refused, and nothing touched -- the counter included.
        unrepaired = session.get(RevisionNode, tree.build)
        assert unrepaired is not None and unrepaired.position == 1_000_002
        assert _lock_version(session, tree.revision_id) == 0

        # And the documented way out: put the row back under the band by hand,
        # then the repair runs.
        unrepaired.position = 9
        session.commit()
        compacted = revision_tree.compact_positions(
            session, tree.revision_id, expected_lock_version=0
        )
        session.commit()
        assert compacted.moved_node_ids == (tree.build,)


def test_compaction_cannot_repair_an_orphan_node_either() -> None:
    """The second blind spot of the same docstring: INV-09.

    A node no root reaches is renumbered in memory among its fellow orphans, but
    ``_check_reachable`` refuses to write the revision back. Reattaching (or
    deleting) the orphans comes first; compaction cannot.

    Written as a parent cycle rather than a dangling ``parent_id`` because
    ``fk_wf_revision_node_parent`` forbids the latter outright: the unreachable
    node the store has to refuse is, in the database, a cycle -- the other half of
    the same check.
    """
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        session.execute(
            text("UPDATE wf_revision_node SET parent_id = :parent, position = 1 WHERE id = :node"),
            {"parent": tree.build, "node": tree.design},
        )
        session.execute(
            text("UPDATE wf_revision_node SET parent_id = :parent, position = 9 WHERE id = :node"),
            {"parent": tree.design, "node": tree.build},
        )
        session.commit()

        with pytest.raises(RevisionStoreError, match="no root reaches"):
            revision_tree.compact_positions(session, tree.revision_id, expected_lock_version=0)
        session.rollback()

        assert _lock_version(session, tree.revision_id) == 0


def test_resolving_the_bearing_task_of_an_unknown_node_is_refused() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        with pytest.raises(domain.NotFoundError):
            revision_tree.resolve_bearing_task(session, tree.revision_id, 4242)


def test_a_bearing_task_is_the_nearest_ancestor_carrying_a_plan_facet() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        bearing = revision_tree.resolve_bearing_task(session, tree.revision_id, tree.wiring)

        assert bearing is not None
        assert (bearing.node_id, bearing.name) == (tree.sub, "Sub")


def test_creating_a_revision_from_a_validated_one_reproduces_the_tree_and_its_work_items() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session, status="validated")

        created = revision_tree.create_revision_from(
            session, tree.revision_id, expected_lock_version=0, note="Rework"
        )
        session.commit()

        assert created.source_revision_id == tree.revision_id
        assert created.version_number == 2
        assert created.lock_version == 0
        copy = load_revision(session, created.revision_id)
        assert copy.revision.status is domain.RevisionStatus.DRAFT
        assert copy.revision.source_revision_id == tree.revision_id
        assert domain.check_invariants(copy.project, copy.revision) == []
        # Same shape, no node identity shared, and each node designates the very
        # same work item as its counterpart in the source (INV-07).
        source = load_revision(session, tree.revision_id)
        assert set(copy.revision.nodes) & set(source.revision.nodes) == set()
        assert sorted(node.work_item_id for node in copy.revision.nodes.values()) == sorted(
            node.work_item_id for node in source.revision.nodes.values()
        )
        assert sorted(facet.label for facet in copy.revision.cost_facets.values()) == [
            "Study",
            "Wiring",
        ]
        # Copying reads the source and writes a new revision: the source's own
        # counter and status are left exactly where they were.
        assert _lock_version(session, tree.revision_id) == 0
        row = session.get(ProjectRevision, tree.revision_id)
        assert row is not None and row.status == "validated"


def test_the_copy_is_editable_while_the_source_still_refuses_every_write() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session, status="validated")
        created = revision_tree.create_revision_from(
            session, tree.revision_id, expected_lock_version=0
        )
        session.commit()

        copy = load_revision(session, created.revision_id)
        copied_study = next(
            node_id
            for node_id, facet in copy.revision.cost_facets.items()
            if facet.label == "Study"
        )
        copied_build = next(
            node_id for node_id, facet in copy.revision.plan_facets.items() if facet.name == "Build"
        )

        revision_tree.move_nodes(
            session,
            created.revision_id,
            [copied_study],
            expected_lock_version=0,
            target_parent_id=copied_build,
        )
        session.commit()

        bearing = revision_tree.resolve_bearing_task(session, created.revision_id, copied_study)
        assert bearing is not None and bearing.node_id == copied_build
        # The source is untouched by an edit on its copy: no node identity is
        # shared between the two, so the same cost line still hangs where it did.
        source_bearing = revision_tree.resolve_bearing_task(session, tree.revision_id, tree.study)
        assert source_bearing is not None
        assert (source_bearing.node_id, source_bearing.name) == (tree.design, "Design")


def test_creating_a_revision_twice_from_the_same_version_produces_two_copies() -> None:
    """A known limit, pinned down as known rather than left to be discovered (#352).

    Copying leaves the source's ``lock_version`` alone -- it must, INV-03 forbids
    writing a validated revision -- so ``expected_lock_version`` cannot tell a
    replay from a first attempt: a double-clicked button sends the same value
    twice, and both calls pass. The service cannot close this; the route can, with
    an idempotency key or a project-level lock, which is what #352 tracks.

    The day that lands, this test is the one that must change, and its failure is
    the notification.
    """
    with get_session_factory()() as session:
        tree = _seed_tree(session, status="validated")

        first = revision_tree.create_revision_from(
            session, tree.revision_id, expected_lock_version=0
        )
        session.commit()
        second = revision_tree.create_revision_from(
            session, tree.revision_id, expected_lock_version=0
        )
        session.commit()

        assert first.revision_id != second.revision_id
        assert (first.version_number, second.version_number) == (2, 3)
        assert session.query(ProjectRevision).count() == 3
        # The source never moved, which is exactly why the second call passed.
        assert _lock_version(session, tree.revision_id) == 0
        # Two copies of the same tree, node for node.
        left = load_revision(session, first.revision_id)
        right = load_revision(session, second.revision_id)
        assert sorted(node.work_item_id for node in left.revision.nodes.values()) == sorted(
            node.work_item_id for node in right.revision.nodes.values()
        )


def test_copying_a_source_that_moved_on_is_refused() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)
        revision_tree.add_task(
            session, tree.revision_id, expected_lock_version=0, name="Late", parent_id=tree.beta
        )
        session.commit()

        with pytest.raises(RevisionLockConflictError):
            revision_tree.create_revision_from(session, tree.revision_id, expected_lock_version=0)
        session.rollback()

        assert session.query(ProjectRevision).count() == 1


# --------------------------------------------------------------------------------------
# Addressing errors
# --------------------------------------------------------------------------------------


def test_writing_on_an_unknown_revision_is_refused_before_anything_is_read() -> None:
    with get_session_factory()() as session:
        _seed_tree(session)

        with pytest.raises(RevisionNotFoundError):
            revision_tree.add_task(session, 4242, expected_lock_version=0, name="Nowhere")
        with pytest.raises(RevisionNotFoundError):
            revision_tree.create_revision_from(session, 4242, expected_lock_version=0)


def test_an_empty_or_unknown_selection_is_refused() -> None:
    with get_session_factory()() as session:
        tree = _seed_tree(session)

        with pytest.raises(domain.SelectionError):
            revision_tree.move_nodes(session, tree.revision_id, [], expected_lock_version=0)
        session.rollback()
        with pytest.raises(domain.NotFoundError):
            revision_tree.delete_nodes(session, tree.revision_id, [4242], expected_lock_version=0)
        session.rollback()

        assert _lock_version(session, tree.revision_id) == 0
