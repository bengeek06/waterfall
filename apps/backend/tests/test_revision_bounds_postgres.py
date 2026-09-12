"""Why the numeric bounds of `schemas/revisions.py` are load-bearing (E14-05, #331).

The review of #331 found ``duration_format`` and ``lag_format`` accepted without an
upper bound while landing in ``SmallInteger`` columns, and no ``CheckConstraint``
covering them. The consequence is invisible on the default test backend: SQLite
gives ``SMALLINT`` the same unbounded INTEGER affinity as everything else, so a
request carrying 100 000 succeeds there and the bug is only reachable in production.

This module pins the two facts that make the schema bound the *only* guard, against
a real PostgreSQL database:

1. an out-of-range value reaches the column and PostgreSQL refuses it;
2. the refusal is a :class:`sqlalchemy.exc.DataError`, which is **not** an
   :class:`sqlalchemy.exc.IntegrityError` -- so no entry of the translation table of
   :mod:`waterfall.api.revision_errors` matches it, and it crosses
   ``revision_operation`` on its way to a 500;
3. it *is* inside ``RevisionFailure`` all the same, so that 500 leaves with the
   ``FOR UPDATE`` row lock released (#331 review, B3: the rollback scope is wider
   than the translation scope, and ``DataError`` used to be the one exception to it).

Together they say: remove the bound from either field and production answers 500.
The 422 the API now returns instead is pinned on SQLite, in
``test_revision_planning_api.test_a_numeric_field_its_column_cannot_hold_is_refused_before_the_flush``;
what *this* module proves is that the 422 is not merely stylistic.

``postgres_app_database_url``, taken as a parameter below, is the shared fixture of
``tests/_postgres_support.py``, made visible through ``tests/conftest.py`` rather
than imported here by name -- importing a ``@pytest.fixture`` callable into a module
that also uses it is what pyright reports as an unused import (same convention as
``test_planning_clone_postgres.py``). It skips the test when PostgreSQL is not
reachable, which is the only way this module is ever silent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

#: Well inside a PostgreSQL ``INTEGER``, well outside a ``SMALLINT``.
_OUT_OF_RANGE_SMALLINT = 100_000


def _seed_task_node(session: Session) -> tuple[int, int]:
    """``(first node id, second node id)`` of a draft revision, straight into the tables."""
    from waterfall.models.ms_core import MsProject
    from waterfall.models.resources import Calendar
    from waterfall.models.revision import ProjectRevision, RevisionNode, RevisionPlanFacet, WorkItem
    from waterfall.models.user import User

    owner = User(
        email=f"revision-bounds-{uuid4().hex[:8]}@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    calendar = Calendar(
        code=f"CAL-{uuid4().hex[:8]}",
        name="Standard",
        weeks_per_year=47,
        is_active=True,
        is_default=True,
    )
    session.add_all([owner, calendar])
    session.flush()

    project = MsProject(
        owner_id=owner.id,
        source_version=2016,
        save_version_out=16,
        name="Revision Bounds Test",
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        finish_date=datetime(2026, 12, 31, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
        currency_code="EUR",
    )
    session.add(project)
    session.flush()

    revision = ProjectRevision(
        project_id=project.id, version_number=1, status="draft", lock_version=0
    )
    session.add(revision)
    session.flush()

    node_ids: list[int] = []
    for position, name in ((1, "First"), (2, "Second")):
        work_item = WorkItem(project_id=project.id, kind="task")
        session.add(work_item)
        session.flush()
        node = RevisionNode(
            revision_id=revision.id,
            work_item_id=work_item.id,
            kind="task",
            parent_id=None,
            position=position,
        )
        session.add(node)
        session.flush()
        session.add(
            RevisionPlanFacet(
                node_id=node.id,
                node_kind="task",
                name=name,
                calendar_id=calendar.id,
                calendar_source="project",
            )
        )
        node_ids.append(node.id)
    session.commit()
    return node_ids[0], node_ids[1]


def test_an_out_of_range_smallint_is_a_data_error_the_conflict_translation_would_miss(
    postgres_app_database_url: str,
) -> None:
    from waterfall.api.revision_errors import RevisionFailure
    from waterfall.models.revision import RevisionNodeLink, RevisionPlanFacet

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            first_node, second_node = _seed_task_node(seed_session)

        # 1. `duration_format`, on the planning facet.
        with session_factory() as session:
            facet = (
                session.query(RevisionPlanFacet)
                .filter(RevisionPlanFacet.node_id == first_node)
                .one()
            )
            facet.duration_format = _OUT_OF_RANGE_SMALLINT
            with pytest.raises(DataError) as duration_failure:
                session.flush()
            session.rollback()

        # 2. `lag_format`, on the precedence link.
        with session_factory() as session:
            session.add(
                RevisionNodeLink(
                    node_id=second_node,
                    predecessor_node_id=first_node,
                    link_type=1,
                    lag_tenth_minute=0,
                    lag_format=_OUT_OF_RANGE_SMALLINT,
                )
            )
            with pytest.raises(DataError) as lag_failure:
                session.flush()
            session.rollback()
    finally:
        engine.dispose()

    for failure in (duration_failure, lag_failure):
        # The whole point: SQLAlchemy classifies this as a DataError, a sibling of
        # IntegrityError and not a subclass of it, so the 409 entry of the
        # translation table cannot match it.
        assert not isinstance(failure.value, IntegrityError)
        # It *is* in the rollback scope, though: `RevisionFailure` lists `DataError`
        # explicitly, so a missed bound comes back as a 500 -- untranslated, which is
        # what an unreachable state deserves -- without stranding the row lock the
        # write took. Translating it is what would be wrong; rolling back is not.
        assert isinstance(failure.value, RevisionFailure)
