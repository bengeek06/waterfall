"""What the revision schema refuses, invariant by invariant (E14-03, issue #329).

Each test names the invariant of ``docs/revision-v0.1-specification.md`` the
constraint translates, and reproduces that invariant's *canonical violation* --
the same ones the pure-domain checker is caught on in
``test_revision_domain_invariants.py``, here pushed one layer down to prove the
database refuses them even when nothing goes through the domain.

Two acceptance criteria of the issue are also proven on PostgreSQL, not only on
the SQLite database the suite runs on: two nodes of one revision sharing a work
item, and a precedence link across two revisions. The second one is a composite
foreign key, and foreign keys are the part of a schema SQLite is least
representative on.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_link,
    insert_node,
    insert_revision,
    insert_task,
    insert_work_item,
    postgres_session,
    seed_reference_data,
)
from waterfall.db.session import get_session_factory
from waterfall.models.revision import (
    RevisionCostFacet,
    RevisionNode,
    RevisionPlanFacet,
    WorkItem,
)


def _duplicate_work_item_in_one_revision(session: Session) -> None:
    """INV-04: the projection node -> work_item is injective within a revision."""
    reference = seed_reference_data(session)
    revision = insert_revision(session, reference)
    work_item = insert_work_item(session, reference)
    insert_node(session, revision, work_item, position=1)

    with pytest.raises(IntegrityError):
        insert_node(session, revision, work_item, position=2)
    session.rollback()


def _predecessor_from_another_revision(session: Session) -> None:
    """INV-08: a predecessor designates a node of the same revision."""
    reference = seed_reference_data(session)
    first = insert_revision(session, reference, version_number=1)
    second = insert_revision(session, reference, version_number=2)
    node = insert_task(session, reference, first, name="Successor")
    foreign = insert_task(session, reference, second, name="Predecessor elsewhere")

    with pytest.raises(IntegrityError):
        insert_link(session, first, node, foreign)
    session.rollback()


def test_two_nodes_of_one_revision_cannot_share_a_work_item() -> None:
    with get_session_factory()() as session:
        _duplicate_work_item_in_one_revision(session)


def test_postgres_two_nodes_of_one_revision_cannot_share_a_work_item(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _duplicate_work_item_in_one_revision(session)


def test_a_predecessor_of_another_revision_is_rejected() -> None:
    with get_session_factory()() as session:
        _predecessor_from_another_revision(session)


def test_postgres_a_predecessor_of_another_revision_is_rejected(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _predecessor_from_another_revision(session)


def test_two_children_of_one_parent_cannot_share_a_position() -> None:
    """INV-05, for a non-root sibling set."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        parent = insert_task(session, reference, revision, name="Parent")
        insert_task(session, reference, revision, name="First", parent_id=parent.id, position=1)

        with pytest.raises(IntegrityError):
            insert_task(session, reference, revision, name="Clash", parent_id=parent.id, position=1)
        session.rollback()


def test_two_root_siblings_cannot_share_a_position() -> None:
    """INV-05 for the root sibling set, which a plain UNIQUE cannot see.

    ``uq_wf_revision_node_sibling_position`` compares NULL parents, and SQL
    treats NULL = NULL as unknown, so it lets every root pair through: the hole
    is closed by the partial unique index on (revision_id, position) restricted
    to ``parent_id IS NULL``. Without it this insert would succeed.
    """
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        insert_task(session, reference, revision, name="First root", position=1)

        with pytest.raises(IntegrityError):
            insert_task(session, reference, revision, name="Second root", position=1)
        session.rollback()


def test_two_roots_of_two_revisions_may_share_a_position() -> None:
    """The counterpart: the root position index is scoped to one revision."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        first = insert_revision(session, reference, version_number=1)
        second = insert_revision(session, reference, version_number=2)
        insert_task(session, reference, first, name="Root of the first", position=1)
        insert_task(session, reference, second, name="Root of the second", position=1)

        assert session.query(RevisionNode).filter(RevisionNode.position == 1).count() == 2


def test_a_position_is_strictly_positive() -> None:
    """INV-05: sibling positions start at 1."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        work_item = insert_work_item(session, reference)

        with pytest.raises(IntegrityError):
            insert_node(session, revision, work_item, position=0)
        session.rollback()


def test_a_labor_cost_facet_refuses_a_disbursement() -> None:
    """INV-19: a labour line carries a role and hours, and no unit cost."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        work_item = insert_work_item(session, reference, kind="cost")
        node = insert_node(session, revision, work_item)

        session.add(
            RevisionCostFacet(
                node_id=node.id,
                node_kind="cost",
                nature="labor",
                label="Labour with a disbursement",
                quantity=Decimal("1"),
                role_id=reference.role_id,
                hours=Decimal("8"),
                unit_cost=Decimal("100"),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_a_labor_cost_facet_refuses_a_supply_status() -> None:
    """INV-19: a labour line has no order to follow up."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        work_item = insert_work_item(session, reference, kind="cost")
        node = insert_node(session, revision, work_item)

        session.add(
            RevisionCostFacet(
                node_id=node.id,
                node_kind="cost",
                nature="labor",
                label="Ordered labour",
                quantity=Decimal("1"),
                role_id=reference.role_id,
                hours=Decimal("8"),
                supply_status="ordered",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_a_non_labor_cost_facet_refuses_hours() -> None:
    """INV-20: a supply line carries a category and a disbursement, never hours."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        work_item = insert_work_item(session, reference, kind="cost")
        node = insert_node(session, revision, work_item)

        session.add(
            RevisionCostFacet(
                node_id=node.id,
                node_kind="cost",
                nature="non_labor",
                label="Supply with hours",
                quantity=Decimal("1"),
                cost_type_id=reference.cost_type_id,
                cost_category_id=reference.cost_category_id,
                unit_cost=Decimal("100"),
                hours=Decimal("8"),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_a_non_labor_cost_facet_accepts_a_supply_status() -> None:
    """The counterpart of the two refusals above: a sound supply line goes in."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        work_item = insert_work_item(session, reference, kind="cost")
        node = insert_node(session, revision, work_item)

        session.add(
            RevisionCostFacet(
                node_id=node.id,
                node_kind="cost",
                nature="non_labor",
                label="Ordered supply",
                quantity=Decimal("2"),
                cost_type_id=reference.cost_type_id,
                cost_category_id=reference.cost_category_id,
                unit_cost=Decimal("100"),
                supply_status="ordered",
            )
        )
        session.flush()

        assert session.query(RevisionCostFacet).count() == 1


def test_a_cost_work_item_refuses_an_external_uid() -> None:
    """INV-25: the MS Project uid is null on a cost item."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)

        with pytest.raises(IntegrityError):
            insert_work_item(session, reference, kind="cost", external_uid=12)
        session.rollback()


def test_an_external_uid_is_unique_within_a_project_but_may_repeat_as_null() -> None:
    """INV-25: unique per project when set, freely repeated when absent."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        insert_work_item(session, reference, external_uid=7)
        insert_work_item(session, reference, external_uid=None)
        insert_work_item(session, reference, external_uid=None)

        assert session.query(WorkItem).count() == 3

        with pytest.raises(IntegrityError):
            insert_work_item(session, reference, external_uid=7)
        session.rollback()


def test_the_same_external_uid_may_be_used_by_two_projects() -> None:
    """INV-25 is scoped to the project: two files may both number a task 7."""
    with get_session_factory()() as session:
        first = seed_reference_data(session, key="first")
        second = seed_reference_data(session, key="second", is_default=False)
        insert_work_item(session, first, external_uid=7)
        insert_work_item(session, second, external_uid=7)

        assert session.query(WorkItem).count() == 2


def test_at_most_one_validated_revision_per_project_and_kind() -> None:
    """INV-22: validating a second one of the same kind supersedes the first."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        insert_revision(session, reference, version_number=1, status="validated")
        insert_revision(session, reference, version_number=2, status="superseded")
        insert_revision(
            session, reference, version_number=3, kind="forecast_remaining", status="validated"
        )

        with pytest.raises(IntegrityError):
            insert_revision(session, reference, version_number=4, status="validated")
        session.rollback()


def test_a_node_kind_must_match_the_kind_of_its_work_item() -> None:
    """INV-13, first half, through the composite foreign key on (work_item_id, kind)."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        work_item = insert_work_item(session, reference, kind="cost")

        session.add(
            RevisionNode(
                revision_id=revision.id,
                work_item_id=work_item.id,
                kind="task",
                position=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_a_cost_facet_cannot_hang_on_a_task_node() -> None:
    """INV-13, second half -- and the "never both" half of INV-11 with it."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        task = insert_task(session, reference, revision, name="A task")

        session.add(
            RevisionCostFacet(
                node_id=task.id,
                node_kind="cost",
                nature="non_labor",
                label="Cost on a task node",
                quantity=Decimal("1"),
                cost_type_id=reference.cost_type_id,
                cost_category_id=reference.cost_category_id,
                unit_cost=Decimal("10"),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_a_node_and_its_parent_belong_to_the_same_revision() -> None:
    """INV-09, through the composite foreign key on (revision_id, parent_id)."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        first = insert_revision(session, reference, version_number=1)
        second = insert_revision(session, reference, version_number=2)
        foreign_parent = insert_task(session, reference, second, name="Parent elsewhere")
        work_item = insert_work_item(session, reference)

        with pytest.raises(IntegrityError):
            insert_node(session, first, work_item, parent_id=foreign_parent.id)
        session.rollback()


def test_a_node_is_never_its_own_predecessor() -> None:
    """INV-16, the degenerate one-node cycle of INV-18."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        node = insert_task(session, reference, revision, name="Self linked")

        with pytest.raises(IntegrityError):
            insert_link(session, revision, node, node)
        session.rollback()


def _precedence_link_on_a_cost_node(session: Session) -> None:
    """INV-17: both ends of a precedence link carry a planning facet."""
    reference = seed_reference_data(session)
    revision = insert_revision(session, reference)
    task = insert_task(session, reference, revision, name="A task")
    cost = insert_labor_line(session, reference, revision, label="Study", position=2)

    with pytest.raises(IntegrityError):
        insert_link(session, revision, cost, task)
    session.rollback()


def test_a_precedence_link_cannot_hang_on_a_cost_node() -> None:
    with get_session_factory()() as session:
        _precedence_link_on_a_cost_node(session)


def test_postgres_a_precedence_link_cannot_hang_on_a_cost_node(
    postgres_app_database_url: str,
) -> None:
    """Proven on PostgreSQL too: it rests on a composite foreign key, the part of
    a schema SQLite is least representative on."""
    with postgres_session(postgres_app_database_url) as session:
        _precedence_link_on_a_cost_node(session)


def test_a_precedence_link_cannot_name_a_cost_node_as_its_predecessor() -> None:
    """INV-17 on the other end, which a single-sided constraint would let through."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        task = insert_task(session, reference, revision, name="A task")
        cost = insert_labor_line(session, reference, revision, label="Study", position=2)

        with pytest.raises(IntegrityError):
            insert_link(session, revision, task, cost)
        session.rollback()


def test_a_sound_revision_tree_is_accepted_whole() -> None:
    """The nominal counterpart of every refusal above, on one small tree."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)
        revision = insert_revision(session, reference)
        parent = insert_task(session, reference, revision, name="Parent", external_uid=1)
        child = insert_task(
            session, reference, revision, name="Child", parent_id=parent.id, position=1
        )
        sibling = insert_task(
            session, reference, revision, name="Sibling", parent_id=parent.id, position=2
        )
        insert_labor_line(session, reference, revision, parent_id=child.id, label="Study")
        insert_link(session, revision, sibling, child)
        session.commit()

        assert session.query(RevisionNode).count() == 4
        assert session.query(RevisionPlanFacet).count() == 3
        assert session.query(RevisionCostFacet).count() == 1


def test_the_reference_seed_builds_a_usable_project() -> None:
    """Guards the shared builder itself: a silently broken seed would hide failures."""
    with get_session_factory()() as session:
        reference = seed_reference_data(session)

        assert isinstance(reference, ReferenceData)
        assert reference.project_id > 0
        assert reference.calendar_id > 0
        assert reference.role_id > 0
