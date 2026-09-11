"""Row builders shared by the revision-schema tests (E14-03, issue #329).

Deliberately not named ``test_*.py`` (same reasoning as ``_postgres_support.py``):
pytest would otherwise collect it as a test module. Its functions are public-named
for the same reason too -- they are imported across test modules, and pyright's
strict ``reportPrivateUsage`` flags an underscore-prefixed name used outside the
module that declares it.

Everything here writes *straight* into the tables, bypassing the domain
completely: the point of the constraint tests is to prove the database itself
refuses a state, not that the domain never builds one.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from waterfall.models.ms_core import MsProject
from waterfall.models.resources import (
    Calendar,
    CostCategory,
    CostType,
    ResourceNode,
    ResourceRole,
)
from waterfall.models.revision import (
    ProjectRevision,
    RevisionCostFacet,
    RevisionNode,
    RevisionNodeLink,
    RevisionPlanFacet,
    WorkItem,
)


@contextmanager
def postgres_session(database_url: str) -> Generator[Session]:
    """One session on ``database_url``, on an engine of its own, disposed on exit.

    Shared by both revision test modules: the tables of this schema are proven on
    PostgreSQL as well as on the SQLite database the suite runs on, and a single
    lifecycle keeps the two from drifting apart.
    """
    engine = create_engine(database_url, future=True)
    try:
        with sessionmaker(bind=engine, autoflush=False)() as session:
            yield session
    finally:
        engine.dispose()


@dataclass(frozen=True)
class ReferenceData:
    """Ids of the rows every revision row hangs off: a project and the referential."""

    project_id: int
    calendar_id: int
    role_id: int
    cost_type_id: int
    cost_category_id: int


def seed_reference_data(
    session: Session, *, key: str = "main", is_default: bool = True
) -> ReferenceData:
    """A project, a calendar, a cost type/category and a role, flushed.

    ``key`` keeps the globally unique codes apart when a test seeds more than one
    project; ``is_default`` must then be left False on all but the first, at most
    one calendar system-wide being flagged as the default (`uq_wf_calendar_is_default_true`).
    """
    calendar = Calendar(
        code=f"CAL-{key}", name="Standard", weeks_per_year=47, is_active=True, is_default=is_default
    )
    session.add(calendar)
    cost_type = CostType(code=f"MO-{key}", name="Main d'oeuvre", kind="labor")
    session.add(cost_type)
    session.flush()
    category = CostCategory(
        cost_type_id=cost_type.id, accounting_code=f"DEV-{key}", name="Developpement"
    )
    node = ResourceNode(code=f"IT-{key}", name="Informatique")
    session.add(category)
    session.add(node)
    session.flush()
    role = ResourceRole(
        node_id=node.id,
        cost_category_id=category.id,
        calendar_id=calendar.id,
        name="Developpeur",
    )
    project = MsProject(
        source_version=2016,
        save_version_out=16,
        name=f"Revision schema test {key}",
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
    )
    session.add(role)
    session.add(project)
    session.flush()
    return ReferenceData(
        project_id=project.id,
        calendar_id=calendar.id,
        role_id=role.id,
        cost_type_id=cost_type.id,
        cost_category_id=category.id,
    )


def insert_revision(
    session: Session,
    reference: ReferenceData,
    *,
    version_number: int = 1,
    kind: str = "initial",
    status: str = "draft",
) -> ProjectRevision:
    revision = ProjectRevision(
        project_id=reference.project_id,
        version_number=version_number,
        kind=kind,
        status=status,
        currency_code="EUR",
    )
    session.add(revision)
    session.flush()
    return revision


def insert_work_item(
    session: Session,
    reference: ReferenceData,
    *,
    kind: str = "task",
    external_uid: int | None = None,
    description: str | None = None,
) -> WorkItem:
    work_item = WorkItem(
        project_id=reference.project_id,
        kind=kind,
        external_uid=external_uid,
        description=description,
    )
    session.add(work_item)
    session.flush()
    return work_item


def insert_node(
    session: Session,
    revision: ProjectRevision,
    work_item: WorkItem,
    *,
    parent_id: int | None = None,
    position: int = 1,
) -> RevisionNode:
    node = RevisionNode(
        revision_id=revision.id,
        work_item_id=work_item.id,
        kind=work_item.kind,
        parent_id=parent_id,
        position=position,
    )
    session.add(node)
    session.flush()
    return node


def insert_task(
    session: Session,
    reference: ReferenceData,
    revision: ProjectRevision,
    *,
    name: str = "Task",
    parent_id: int | None = None,
    position: int = 1,
    external_uid: int | None = None,
) -> RevisionNode:
    """A task work item, its node and its planning facet, in one call."""
    work_item = insert_work_item(session, reference, kind="task", external_uid=external_uid)
    node = insert_node(session, revision, work_item, parent_id=parent_id, position=position)
    session.add(
        RevisionPlanFacet(
            node_id=node.id,
            node_kind="task",
            name=name,
            calendar_id=reference.calendar_id,
            calendar_source="project",
        )
    )
    session.flush()
    return node


def insert_labor_line(
    session: Session,
    reference: ReferenceData,
    revision: ProjectRevision,
    *,
    label: str = "Labor",
    parent_id: int | None = None,
    position: int = 1,
    hours: Decimal = Decimal("10"),
) -> RevisionNode:
    work_item = insert_work_item(session, reference, kind="cost")
    node = insert_node(session, revision, work_item, parent_id=parent_id, position=position)
    session.add(
        RevisionCostFacet(
            node_id=node.id,
            node_kind="cost",
            nature="labor",
            label=label,
            quantity=Decimal("1"),
            role_id=reference.role_id,
            hours=hours,
        )
    )
    session.flush()
    return node


def insert_link(
    session: Session,
    revision: ProjectRevision,
    node: RevisionNode,
    predecessor: RevisionNode,
    *,
    link_type: int = 1,
) -> RevisionNodeLink:
    link = RevisionNodeLink(
        revision_id=revision.id,
        node_id=node.id,
        predecessor_node_id=predecessor.id,
        link_type=link_type,
    )
    session.add(link)
    session.flush()
    return link
