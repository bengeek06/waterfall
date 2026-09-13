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
from waterfall.domain import revision as domain
from waterfall.models.revision import (
    ProjectRevision,
    ProjectRevisionPointer,
    RevisionCostFacet,
    RevisionFrozenLine,
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


# --------------------------------------------------------------------------------------
# The frozen document and the project's revision pointers (E14-08, issue #334)
# --------------------------------------------------------------------------------------


def _insert_frozen_line(
    session: Session,
    revision: ProjectRevision,
    work_item: WorkItem,
    *,
    year: int | None,
    nature: str = "labor",
    cost_code: str | None = None,
) -> RevisionFrozenLine:
    line = RevisionFrozenLine(
        revision_id=revision.id,
        work_item_id=work_item.id,
        bearing_work_item_id=None,
        label="Etude",
        nature=nature,
        cost_code=cost_code,
        year=year,
        quantity=Decimal("1"),
        hours=Decimal("5"),
        hourly_rate=Decimal("100.0000"),
        inflation_coefficient=Decimal("1.00000000"),
        amount=Decimal("500.00"),
    )
    session.add(line)
    session.flush()
    return line


def _two_frozen_lines_of_one_work_item_in_one_year(session: Session) -> None:
    """The grain of the document: one line per (chiffrage, year), never two."""
    reference = seed_reference_data(session)
    revision = insert_revision(session, reference, status="validated")
    work_item = insert_work_item(session, reference, kind="cost")
    _insert_frozen_line(session, revision, work_item, year=2026)
    # Another year of the same chiffrage is exactly what the grain is for.
    _insert_frozen_line(session, revision, work_item, year=2027)

    with pytest.raises(IntegrityError):
        _insert_frozen_line(session, revision, work_item, year=2026)
    session.rollback()


def test_two_frozen_lines_of_one_work_item_in_one_year_are_rejected() -> None:
    with get_session_factory()() as session:
        _two_frozen_lines_of_one_work_item_in_one_year(session)


def _two_year_less_frozen_lines_of_one_work_item(session: Session) -> None:
    """The year-less row: uniqueness is the **domain's**, and the docstring says so.

    ``uq_wf_revision_frozen_line_year`` covers ``(revision_id, work_item_id, year)``
    and SQL keeps NULLs distinct, so two rows with no year never collide -- the
    database accepts them, as asserted below. What forbids the pair is INV-24 alone,
    which counts ``(work_item_id, year)`` pairs including the null one, plus the fact
    that ``_frozen_lines`` produces exactly one such row per facet.

    Pinned rather than left implicit (#334 review, B3): "the constraint does not cover
    this case" is a claim, and a claim in a docstring about a unique index is exactly
    the kind that quietly becomes false.
    """
    reference = seed_reference_data(session)
    revision = insert_revision(session, reference, status="validated")
    work_item = insert_work_item(session, reference, kind="cost")
    first = _insert_frozen_line(session, revision, work_item, year=None)
    second = _insert_frozen_line(session, revision, work_item, year=None)

    assert first.id != second.id
    session.rollback()


def test_the_database_does_not_hold_the_year_less_frozen_line_unique() -> None:
    with get_session_factory()() as session:
        _two_year_less_frozen_lines_of_one_work_item(session)


def test_postgres_does_not_hold_the_year_less_frozen_line_unique(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _two_year_less_frozen_lines_of_one_work_item(session)


def test_the_domain_is_what_refuses_two_year_less_frozen_lines() -> None:
    """The other half of B3: what the database lets through, INV-24 catches."""
    project = domain.Project(id=1)
    work_item = domain.WorkItem(id=1, project_id=1, kind=domain.WorkItemKind.COST)
    project.work_items[work_item.id] = work_item
    revision = domain.ProjectRevision(
        id=1, project_id=1, version_number=1, status=domain.RevisionStatus.VALIDATED
    )
    node = domain.RevisionNode(id=1, revision_id=1, work_item_id=work_item.id)
    revision.nodes[node.id] = node
    project.roles[1] = domain.Role(id=1, name="Developpeur")
    revision.cost_facets[node.id] = domain.CostFacet(
        node_id=node.id,
        nature=domain.CostNature.LABOR,
        label="Etude",
        role_id=1,
        hours=Decimal("10"),
    )
    revision.frozen_lines = [
        domain.FrozenLine(
            revision_id=1,
            work_item_id=work_item.id,
            bearing_work_item_id=None,
            label="Etude",
            nature=domain.CostNature.LABOR,
            year=None,
        )
        for _ in range(2)
    ]
    project.revisions[revision.id] = revision

    violations = domain.check_invariants(project, revision)

    assert [violation.invariant for violation in violations] == ["INV-24"]


def test_postgres_two_frozen_lines_of_one_work_item_in_one_year_are_rejected(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _two_frozen_lines_of_one_work_item_in_one_year(session)


def _pointer_to_a_revision_of_another_project(session: Session) -> None:
    """A project points at a revision **of its own**, or at nothing.

    What the composite foreign key buys over the single-column
    ``fk_ms_project_reference_estimate`` it replaces, which accepted anybody's
    estimate id as happily as its own.
    """
    mine = seed_reference_data(session, key="mine")
    yours = seed_reference_data(session, key="yours", is_default=False)
    foreign = insert_revision(session, yours, status="validated")

    session.add(
        ProjectRevisionPointer(project_id=mine.project_id, reference_revision_id=foreign.id)
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_a_project_cannot_reference_a_revision_of_another_project() -> None:
    with get_session_factory()() as session:
        _pointer_to_a_revision_of_another_project(session)


def test_postgres_a_project_cannot_reference_a_revision_of_another_project(
    postgres_app_database_url: str,
) -> None:
    with postgres_session(postgres_app_database_url) as session:
        _pointer_to_a_revision_of_another_project(session)


def test_the_revision_pointers_close_no_new_foreign_key_cycle() -> None:
    """The reason the pointers are a table and not two columns on `ms_project`.

    ``sort_tables_and_constraints`` hands back, under a ``None`` table, exactly the
    foreign keys it could not place in creation order -- the ones a cycle forces to
    be added by a deferred ``ALTER``. Three of them exist, all three legacy
    (``ms_project`` -> `wf_planning`/`wf_estimate` -> ``ms_project``), and E14-12
    (#339) removes them. Two pointer *columns* on `ms_project` would have made a
    fourth, since `wf_revision` references `ms_project` in the other direction; one
    table further out, the whole schema sorts in a single topological order.

    Asserted on the exact set rather than on a count, so that removing the legacy
    three in #339 fails here loudly instead of leaving the guard testing nothing.
    """
    from sqlalchemy.sql.ddl import sort_tables_and_constraints

    from waterfall.db.base import Base

    deferred = {
        constraint.name
        for table, constraints in sort_tables_and_constraints(list(Base.metadata.tables.values()))
        if table is None
        for constraint in constraints
    }

    assert deferred == {
        "fk_ms_project_planning_reference",
        "fk_ms_project_displayed_planning",
        "fk_ms_project_reference_estimate",
    }
    assert "wf_project_revision_pointer" in Base.metadata.tables
