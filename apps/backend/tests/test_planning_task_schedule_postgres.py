"""PostgreSQL-only regression test for the naive/aware datetime bug fixed in
E3-03's PR review (finding #1): editing a draft planning task's schedule
raised ``TypeError: can't compare offset-naive and offset-aware datetimes``
on real PostgreSQL whenever the edited task had a summary ancestor with at
least one other (untouched) sibling.

This lives outside test_planning_task_schedule.py, which drives everything
through ``TestClient`` -- wired by tests/conftest.py to a single SQLite
database for the whole test session (see test_resources_calendar_locking.py's
module docstring for the same reasoning). SQLite's default ``DateTime`` type
does not preserve ``tzinfo`` across a round trip, so every value it returns is
already naive -- the exact mismatch this bug depends on (a freshly reloaded
sibling task, timezone-aware on PostgreSQL, compared against the just-edited
task's already-naive value) can never be observed through SQLite. Proving the
fix requires a real PostgreSQL backend, so this test builds its own ephemeral
database and drives ``update_planning_task_schedule`` directly, following the
same pattern as test_resources_calendar_locking.py (see that module's
docstring for why the shared tests/_postgres_support.py helpers exist as a
standalone module).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from _postgres_support import (
    ephemeral_postgres_database,
    postgres_admin_url,
    postgres_reachable,
)


@pytest.fixture
def postgres_app_database_url() -> Generator[str]:
    admin_url = postgres_admin_url()
    if not postgres_reachable(admin_url):
        pytest.skip(
            "PostgreSQL is not reachable; set TEST_POSTGRES_URL or start the "
            "docker-compose postgres service to run this test."
        )
    with ephemeral_postgres_database(admin_url) as database_url:
        from waterfall.db.base import Base
        from waterfall.models import User

        _ = User.__tablename__

        engine = create_engine(database_url, future=True)
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
        yield database_url


def _seed_planning_with_summary_sibling(session: Session) -> tuple[int, int]:
    """Seed a project/planning with a summary parent (uid=1) whose children are
    uid=2 (the task edited by the test) and uid=3 (an untouched sibling with
    fixed dates already committed) -- exactly the shape needed to exercise the
    bug: ``_recalculate_ancestor_summaries`` must compare uid=2's freshly
    edited (naive, from the request payload) dates against uid=3's dates,
    freshly reloaded from PostgreSQL (timezone-aware) in the very same
    request.
    """
    from waterfall.models.ms_core import MsProject
    from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot

    project = MsProject(
        source_version=2016,
        save_version_out=16,
        name="E3-03 PostgreSQL naive/aware regression",
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
        currency_code="EUR",
    )
    session.add(project)
    session.flush()

    planning = WfPlanning(project_id=project.id, version_number=1, status="draft")
    session.add(planning)
    session.flush()

    session.add_all(
        [
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=1,
                name="Parent",
                position=1,
                is_summary=True,
                is_milestone=False,
            ),
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=2,
                name="Leaf (edited)",
                parent_uid=1,
                position=1,
                is_summary=False,
                is_milestone=False,
            ),
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=3,
                name="Leaf sibling (untouched)",
                parent_uid=1,
                position=2,
                start_at=datetime(2026, 1, 6, 8, 0),
                finish_at=datetime(2026, 1, 8, 8, 0),
                duration_minutes=2880,
                is_summary=False,
                is_milestone=False,
            ),
        ]
    )
    session.commit()
    return planning.id, project.id


def test_schedule_update_with_summary_sibling_does_not_raise_on_postgresql(
    postgres_app_database_url: str,
) -> None:
    """Reproduces the E3-03 PR review finding #1 and shows the fix closes it.

    Before the fix, this raised ``TypeError: can't compare offset-naive and
    offset-aware datetimes`` from ``_recalculate_summary_fields``'s
    ``min(start_dates)``/``max(finish_dates)``, because uid=3 (reloaded from
    PostgreSQL at the top of ``update_planning_task_schedule``) came back
    timezone-aware while uid=2's just-written ``start_at``/``finish_at``
    (normalized to naive by ``PlanningTaskScheduleUpdate._drop_tzinfo``)
    stayed naive.
    """
    from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
    from waterfall.schemas.projects import PlanningTaskScheduleUpdate
    from waterfall.services.planning_tree import update_planning_task_schedule

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            planning_id, _project_id = _seed_planning_with_summary_sibling(seed_session)

        with session_factory() as session:
            planning = session.get(WfPlanning, planning_id)
            assert planning is not None

            payload = PlanningTaskScheduleUpdate(
                is_manual=True,
                start_at=datetime(2026, 1, 9, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 11, 8, 0, tzinfo=UTC),
                duration_minutes=500,
                expected_revision=0,
            )

            # This must not raise TypeError on PostgreSQL.
            task = update_planning_task_schedule(session, planning, task_uid=2, payload=payload)
            session.commit()

            assert task.start_at is not None
            assert task.finish_at is not None

            parent = (
                session.query(WfPlanningTaskSnapshot)
                .filter_by(planning_id=planning_id, uid=1)
                .one()
            )
            # min(sibling's 2026-01-06 08:00, edited leaf's 2026-01-09 08:00)
            assert parent.start_at is not None and parent.start_at.replace(tzinfo=None) == datetime(
                2026, 1, 6, 8, 0
            )
            # max(sibling's 2026-01-08 08:00, edited leaf's 2026-01-11 08:00)
            assert parent.finish_at is not None and parent.finish_at.replace(
                tzinfo=None
            ) == datetime(2026, 1, 11, 8, 0)
    finally:
        engine.dispose()
