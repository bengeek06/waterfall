"""PostgreSQL concurrency test of the revision API's optimistic lock (#18, then #331).

Mirrors the pattern in test_projects_task_reference_locking.py and
test_resources_calendar_locking.py (see those modules' docstrings for the full
rationale): proving this requires a real PostgreSQL backend with two independent
connections/transactions, since SQLite silently drops `SELECT ... FOR UPDATE`, so
the normal SQLite-backed TestClient test session could never observe the row lock
this is about.

Two clients starting from the same `lock_version` must not both succeed: the first
commit wins and bumps the counter; the second, still holding the *same* stale
`expected_lock_version`, must be rejected with a structured
`REVISION_LOCK_CONFLICT` once it is unblocked -- never a silent double mutation.

Originally written against `wf_planning.revision` and the planning-snapshot move
endpoint (#18); E14-05 (#331) moved it onto `wf_revision.lock_version` and the
revision tree, which is the single counter that replaces it. Its service-level
counterpart lives in test_revision_tree.py; what this one adds is the *response*:
the 409 body a client actually resynchronises from.
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


def _seed_draft_revision_with_two_root_tasks(session: Session) -> tuple[int, int, int, int, int]:
    """``(owner, project, revision, first node, second node)``, written straight into the tables."""
    from waterfall.models.ms_core import MsProject
    from waterfall.models.resources import Calendar
    from waterfall.models.revision import ProjectRevision, RevisionNode, RevisionPlanFacet, WorkItem
    from waterfall.models.user import User

    owner = User(
        email=f"revision-lock-{uuid4().hex[:8]}@example.com",
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
        name="Revision Locking Test",
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

    return owner.id, project.id, revision.id, node_ids[0], node_ids[1]


def test_move_lock_conflict_serializes_and_rejects_the_loser(
    postgres_app_database_url: str,
) -> None:
    from waterfall.api.routes.revisions import move_revision_nodes
    from waterfall.models.user import User
    from waterfall.schemas.revisions import RevisionNodeMove
    from waterfall.services import revision_tree

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            owner_id, project_id, revision_id, first_node, second_node = (
                _seed_draft_revision_with_two_root_tasks(seed_session)
            )

        session_a = session_factory()
        session_b = session_factory()
        try:
            # Session A: run the move service up to (but not including) the commit,
            # so the test holds the revision row lock open while session B's
            # concurrent move, still targeting the same stale lock_version 0, piles
            # up behind it.
            revision_tree.move_nodes(
                session_a,
                revision_id,
                [second_node],
                expected_lock_version=0,
                target_parent_id=None,
                position=1,
            )
            session_a.flush()

            # Capture session B's backend pid *before* starting the thread that
            # will block it -- a Session/connection cannot safely be driven from
            # two threads at once, so this quick roundtrip must happen first.
            backend_pid_b = session_b.execute(text("SELECT pg_backend_pid()")).scalar()
            assert backend_pid_b is not None

            results: dict[str, Any] = {}

            def _run_session_b() -> None:
                try:
                    results["detail"] = move_revision_nodes(
                        project_id,
                        revision_id,
                        RevisionNodeMove(
                            node_ids=[first_node],
                            mode="to_parent",
                            target_parent_id=None,
                            position=1,
                            expected_lock_version=0,
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
                # the revision at lock_version 1.
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
                "code": "REVISION_LOCK_CONFLICT",
                "revision_id": revision_id,
                "expected_lock_version": 0,
                "current_lock_version": 1,
            }
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine.dispose()

    # The winner's move (the second node to position 1) must be the only mutation applied.
    with sessionmaker(bind=create_engine(postgres_app_database_url, future=True))() as verify:
        from waterfall.models.revision import ProjectRevision, RevisionNode

        revision = verify.get(ProjectRevision, revision_id)
        assert revision is not None
        assert revision.lock_version == 1
        moved = verify.get(RevisionNode, second_node)
        assert moved is not None
        assert moved.position == 1
