"""PostgreSQL concurrency regression test for issue #18 (planning revision conflict).

Mirrors the pattern in test_projects_task_reference_locking.py and
test_resources_calendar_locking.py (see those modules' docstrings for the full
rationale): proving this fix requires a real PostgreSQL backend with two
independent connections/transactions, since SQLite silently drops
`SELECT ... FOR UPDATE`, so the normal SQLite-backed TestClient test session
could never observe the row lock this issue is about.

Two clients starting from the same `revision` must not both succeed: the first
commit wins and increments `revision`; the second, still holding the *same*
stale `expected_revision`, must be rejected with a structured
`PLANNING_REVISION_CONFLICT` once it is unblocked -- never a silent double
mutation.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, text
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
        # Same registration trick as test_resources_calendar_locking.py: importing
        # the models package registers every mapped class on Base.metadata, so
        # create_all below produces the full application schema.
        from waterfall.models import User

        _ = User.__tablename__
        from waterfall.db.base import Base

        engine = create_engine(database_url, future=True)
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
        yield database_url


def _wait_until_backend_blocked_on_lock(
    engine: Engine, backend_pid: int, timeout: float = 5.0
) -> None:
    """Polls pg_stat_activity until `backend_pid` is observed waiting on a lock."""
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


def _seed_draft_planning_with_two_root_tasks(session: Session) -> tuple[int, int, int]:
    from waterfall.models.ms_core import MsProject
    from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
    from waterfall.models.user import User

    owner = User(
        email=f"planning-revision-{uuid4().hex[:8]}@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(owner)
    session.flush()

    project = MsProject(
        owner_id=owner.id,
        source_version=2016,
        save_version_out=16,
        name="Planning Revision Locking Test",
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

    planning = WfPlanning(project_id=project.id, version_number=1, status="draft", revision=0)
    session.add(planning)
    session.flush()

    session.add_all(
        [
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=1,
                name="First",
                position=1,
                outline_number="1",
                outline_level=1,
            ),
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=2,
                name="Second",
                position=2,
                outline_number="2",
                outline_level=1,
            ),
        ]
    )
    session.commit()

    return owner.id, project.id, planning.id


def test_move_revision_conflict_serializes_and_rejects_the_loser(
    postgres_app_database_url: str,
) -> None:
    from waterfall.api.routes.plannings import move_planning_tasks_route
    from waterfall.api.routes.project_access import (
        get_mutable_draft_planning_with_locks,
        raise_on_planning_revision_conflict,
    )
    from waterfall.models.user import User
    from waterfall.schemas.projects import PlanningTaskMove
    from waterfall.services import move_planning_tasks

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            owner_id, project_id, planning_id = _seed_draft_planning_with_two_root_tasks(
                seed_session
            )

        session_a = session_factory()
        session_b = session_factory()
        try:
            # Session A: replicate move_planning_tasks_route's own locking/mutation
            # sequence up to (but not including) the commit, so the test can hold
            # the planning row lock open while session B's concurrent move, still
            # targeting the same stale revision 0, piles up behind it.
            _, planning_a = get_mutable_draft_planning_with_locks(
                session_a, project_id, planning_id, owner_id
            )
            raise_on_planning_revision_conflict(project_id, planning_a, 0)
            move_planning_tasks(
                session_a,
                planning_a,
                PlanningTaskMove(
                    task_uids=[2], target_parent_uid=None, position=1, expected_revision=0
                ),
            )
            planning_a.revision += 1
            session_a.add(planning_a)
            session_a.flush()

            # Capture session B's backend pid *before* starting the thread that
            # will block it -- a Session/connection cannot safely be driven from
            # two threads at once, so this quick roundtrip must happen first.
            backend_pid_b = session_b.execute(text("SELECT pg_backend_pid()")).scalar()
            assert backend_pid_b is not None

            results: dict[str, Any] = {}

            def _run_session_b() -> None:
                try:
                    results["detail"] = move_planning_tasks_route(
                        project_id,
                        planning_id,
                        PlanningTaskMove(
                            task_uids=[1], target_parent_uid=None, position=1, expected_revision=0
                        ),
                        db=session_b,
                        current_user=User(id=owner_id),
                    )
                except HTTPException as exc:
                    results["error"] = exc

            thread = threading.Thread(target=_run_session_b)
            thread.start()
            try:
                _wait_until_backend_blocked_on_lock(engine, backend_pid_b)

                # Session A completes its move, releasing the lock and leaving
                # the planning at revision 1.
                session_a.commit()

                thread.join(timeout=5)
                assert not thread.is_alive(), (
                    "session B's move never returned -- looks like a deadlock/hang"
                )
            finally:
                session_b.rollback()

            assert "detail" not in results, "the stale request must not have succeeded"
            error = results["error"]
            assert error.status_code == 409
            assert error.detail == {
                "code": "PLANNING_REVISION_CONFLICT",
                "project_id": project_id,
                "planning_id": planning_id,
                "expected_revision": 0,
                "current_revision": 1,
            }
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine.dispose()

    # The winner's move (task 2 to position 1) must be the only mutation applied.
    with session_factory() as verify_session:
        from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot

        planning = verify_session.get(WfPlanning, planning_id)
        assert planning is not None
        assert planning.revision == 1
        task_two = (
            verify_session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
            .filter(WfPlanningTaskSnapshot.uid == 2)
            .one()
        )
        assert task_two.position == 1
