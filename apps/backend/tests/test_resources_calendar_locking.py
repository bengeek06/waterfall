"""PostgreSQL concurrency regressions for resource mutations (issues #50, #51, #59).

This intentionally lives outside test_resources_api.py rather than alongside the
other calendar tests there: everything in that module goes through the HTTP layer
via `TestClient`, which (per tests/conftest.py's session-scoped fixture) is wired
to a single SQLite database for the whole test session. SQLite has no
`SELECT ... FOR UPDATE` semantics -- SQLAlchemy's sqlite dialect silently drops the
clause (see the comment on `_get_calendar_for_update_or_404` in
`waterfall/api/routes/resources.py`) -- so a TestClient-based test could never
observe the row lock this issue is about. Proving the lock works requires a real
PostgreSQL backend with two independent connections/transactions, which in turn
means driving the guarded helper functions directly instead of going through the
FastAPI `Depends(get_db)` request lifecycle, so each side's transaction can be
started, held open, and committed/rolled back independently and on cue.

The PostgreSQL reachability check and ephemeral-database helpers come from the
shared tests/_postgres_support.py module (also used by test_migrations.py)
rather than being duplicated here -- see that module's docstring for why it is
a standalone, non-underscore-prefixed helper module instead of importing
test_migrations.py's private helpers directly. What is *not* reused from
test_migrations.py is its `postgres_database_url` fixture: that fixture
migrates the ephemeral database to head via an `alembic upgrade` subprocess,
which is the right tool for migration tests but is an unnecessary subprocess
round-trip here. This test only needs the application schema, so it builds its
own ephemeral database and populates it directly with `Base.metadata.create_all`,
matching the "normal test session" schema-setup style used by
tests/conftest.py's `reset_database` fixture.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any, cast

import pytest
from fastapi import HTTPException, status
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
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
        # Importing the models package registers every mapped class on Base.metadata,
        # so create_all below produces the full application schema -- consistent with
        # how test_migrations.py's _assert_schema_matches_orm_metadata triggers the
        # same registration (referencing an attribute, not just importing the module,
        # keeps this from being flagged as an unused import).
        from waterfall.models import User

        _ = User.__tablename__
        from waterfall.db.base import Base

        engine = create_engine(database_url, future=True)
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
        yield database_url


def _seed_calendar(session: Session) -> int:
    from waterfall.models.resources import Calendar

    calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=47)
    session.add(calendar)
    session.commit()
    return calendar.id


def _seed_three_calendars_with_a_default(session: Session) -> tuple[int, int, int]:
    """Seeds calendar A (currently `is_default=True`) plus two challengers, B and C,
    both active and not default -- the starting state for the issue #51 two-row
    promotion race below."""
    from waterfall.models.resources import Calendar

    calendar_a = Calendar(code="DEFAULT-A", name="Default A", weeks_per_year=47, is_default=True)
    calendar_b = Calendar(code="CHALLENGER-B", name="Challenger B", weeks_per_year=47)
    calendar_c = Calendar(code="CHALLENGER-C", name="Challenger C", weeks_per_year=47)
    session.add_all([calendar_a, calendar_b, calendar_c])
    session.commit()
    return calendar_a.id, calendar_b.id, calendar_c.id


def _wait_until_backend_blocked_on_lock(
    engine: Engine, backend_pid: int, timeout: float = 5.0
) -> None:
    """Polls pg_stat_activity until `backend_pid` is observed waiting on a lock.

    Used instead of a fixed `time.sleep` so the test deterministically proves the
    second session actually queued behind the first session's held row lock (rather
    than, say, racing ahead and returning before the first session even committed,
    which would make the assertions below vacuous).
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


def _seed_inactive_role_with_calendar(session: Session, calendar_id: int) -> int:
    """Seeds an *inactive* role that still carries a (currently active) calendar_id.

    Mirrors the state a role reaches before the reactivation scenario in issue
    PR #60's follow-up: a role can be deactivated while its calendar is still
    active, and later the calendar can be deactivated independently (allowed,
    since no active role references it at that point).
    """
    from waterfall.models.resources import CostCategory, CostType, ResourceNode, ResourceRole

    cost_type = CostType(code="MO-LOCK", name="Main d'oeuvre", kind="labor")
    session.add(cost_type)
    session.flush()
    category = CostCategory(
        cost_type_id=cost_type.id,
        accounting_code="MO-CAT-LOCK",
        name="Developpement",
    )
    session.add(category)
    node = ResourceNode(code="IT-LOCK", name="Informatique")
    session.add(node)
    session.flush()
    role = ResourceRole(
        node_id=node.id,
        cost_category_id=category.id,
        calendar_id=calendar_id,
        name="Developpeur",
        is_active=False,
    )
    session.add(role)
    session.commit()
    return role.id


def test_calendar_lock_blocks_concurrent_active_role_assignment(
    postgres_app_database_url: str,
) -> None:
    """Reproduces the race from issue #50 and shows the FOR UPDATE lock closes it.

    Session A simulates the start of the deactivation path (update_calendar /
    delete_calendar): it locks calendar C via `_get_calendar_for_update_or_404`
    and does *not* commit yet, exactly as the route does before running
    `_ensure_calendar_not_assigned_to_active_role` and writing `is_active`.

    Session B then simulates the role-assignment path (create_role / update_role):
    it calls `_get_active_calendar_or_400` on the same calendar, with a short
    `lock_timeout` set so the test observes the contention deterministically and
    quickly instead of depending on real-time thread scheduling.

    Before this fix, `_get_active_calendar_or_400` ran a plain, unlocked SELECT.
    Under READ COMMITTED (PostgreSQL's default), that SELECT would have seen
    calendar C's still-committed `is_active = True` and returned immediately,
    letting session B's role write and session A's deactivation write both
    succeed -- the exact inconsistency this issue is about. The fact that
    session B's *locked* SELECT below instead blocks and times out is direct
    evidence that `_get_active_calendar_or_400` now takes the same row lock as
    the deactivation path and is queued behind it.
    """
    # This white-box test intentionally reaches into resources.py's module-private
    # guard helpers rather than reimplementing their queries here, so the test stays
    # tied to the actual production locking behaviour instead of a parallel
    # description of it that could silently drift.
    from waterfall.api.routes.resources import (
        _get_active_calendar_or_400,  # pyright: ignore[reportPrivateUsage]
        _get_calendar_for_update_or_404,  # pyright: ignore[reportPrivateUsage]
    )

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            calendar_id = _seed_calendar(seed_session)

        session_a = session_factory()
        session_b = session_factory()
        try:
            # Session A: start of the deactivation path -- locks the row, no commit yet.
            locked_calendar = _get_calendar_for_update_or_404(session_a, calendar_id)
            assert locked_calendar.is_active is True

            # Session B: role-assignment path, contending for the same row lock.
            session_b.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                _get_active_calendar_or_400(session_b, calendar_id)
            session_b.rollback()

            # Releasing A's lock lets the same call on B succeed immediately, confirming
            # the earlier failure was specifically caused by A's still-held row lock.
            session_a.commit()

            reassigned = _get_active_calendar_or_400(session_b, calendar_id)
            assert reassigned.is_active is True
            session_b.commit()
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine.dispose()


def test_role_reactivation_lock_blocks_on_concurrent_calendar_deactivation(
    postgres_app_database_url: str,
) -> None:
    """Extends the issue #50 regression to the reactivation gap found in PR #60 review.

    Before that fix, `update_role` only validated/locked `calendar_id` when it was
    explicitly present in the PATCH payload. A role could sit inactive while still
    referencing a calendar that later gets deactivated (allowed, since no *active*
    role references it at that point), then be reactivated via `{"is_active": true}`
    alone -- never revalidating or locking that calendar, and so never contending
    with a concurrent deactivation of it at all.

    This test drives the real `update_role` route function directly (not just the
    guard helper, as in the test above) to prove the reactivation path now takes
    the same `SELECT ... FOR UPDATE` lock on the role's *effective* (unchanged)
    calendar_id, and is queued behind a concurrent deactivation exactly like an
    explicit `calendar_id` change would be.
    """
    from waterfall.api.routes.resources import (
        _get_calendar_for_update_or_404,  # pyright: ignore[reportPrivateUsage]
        update_role,
    )
    from waterfall.models.user import User
    from waterfall.schemas.resources import ResourceRoleUpdate

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            calendar_id = _seed_calendar(seed_session)
            role_id = _seed_inactive_role_with_calendar(seed_session, calendar_id)

        session_a = session_factory()
        session_b = session_factory()
        try:
            # Session A: start of the deactivation path -- locks the row, no commit yet.
            locked_calendar = _get_calendar_for_update_or_404(session_a, calendar_id)
            assert locked_calendar.is_active is True

            # Session B: reactivate the role via `is_active` alone -- calendar_id is
            # not part of this payload, so only the effective-calendar check added by
            # the fix makes this contend for the same row lock as session A.
            session_b.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                update_role(
                    role_id,
                    ResourceRoleUpdate(is_active=True),
                    db=session_b,
                    _=cast(User, None),
                )
            session_b.rollback()

            # Session A abandons the deactivation attempt without writing
            # is_active=False, simply releasing its lock so session B can proceed.
            session_a.rollback()

            reactivated = update_role(
                role_id,
                ResourceRoleUpdate(is_active=True),
                db=session_b,
                _=cast(User, None),
            )
            assert reactivated.is_active is True
            session_b.commit()
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine.dispose()


def test_concurrent_default_promotions_serialize_to_one_default_and_a_409(
    postgres_app_database_url: str,
) -> None:
    """Extends the issue #50 locking regressions to issue #51's two-row promotion.

    `update_calendar`'s `is_default` promotion path locks *two* rows in one
    transaction: the target calendar (via `_get_calendar_for_update_or_404`) and
    whichever calendar currently holds `is_default=True` (via a second, explicit
    `with_for_update()` query). This test proves that when two promotions race for
    that same "current default" row, PostgreSQL serializes them correctly -- the
    second transaction genuinely blocks (no deadlock/hang) and, once unblocked,
    either succeeds cleanly or is rejected with a 409, never a 500 and never a
    silent double-default.

    Session A begins promoting calendar B to default: it locks B, then locks A (the
    seeded, currently-default calendar) via the same "previous_default" query
    `update_calendar` runs, and holds both locks open without committing yet.

    Session B then runs the *real* `update_calendar` route function, on its own
    thread (a genuine second connection is required here, not just a second
    sequential call on the same connection, since it must actually block on a row
    session A is holding open), promoting a third calendar C to default. Its
    "previous_default" query matches A and queues behind session A's lock on that
    row.

    Once the test confirms (via `pg_stat_activity`, not a fixed sleep) that session
    B is genuinely queued on the lock, session A commits, demoting A and promoting
    B. PostgreSQL's `EvalPlanQual` re-checks A's row for session B's still-pending
    query against its now-committed state (`is_default=False`) and excludes it --
    but the rest of session B's scan already ran against its original snapshot
    (predating session A's commit), so it does *not* pick up B as the new
    "previous_default" either. Session B's query therefore returns no
    previous-default row to demote, so it proceeds straight to setting
    `calendar_c.is_default = True` and committing -- at which point the partial
    unique index (`uq_wf_calendar_is_default_true`) rejects the second `True` row
    (B is already committed as the default) with an `IntegrityError`, which
    `_commit` converts to the expected 409. This is the exact "loser gets a 409, not
    a deadlock or silent no-op" behavior this test is pinned to.
    """
    from waterfall.api.routes.resources import (
        _get_calendar_for_update_or_404,  # pyright: ignore[reportPrivateUsage]
        update_calendar,
    )
    from waterfall.models.resources import Calendar
    from waterfall.models.user import User
    from waterfall.schemas.resources import CalendarUpdate

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            calendar_a_id, calendar_b_id, calendar_c_id = _seed_three_calendars_with_a_default(
                seed_session
            )

        session_a = session_factory()
        session_b = session_factory()
        try:
            # Session A: begin promoting B -- replicate update_calendar's own
            # locking sequence for the "is_default" branch up to (but not
            # including) the commit, so the test can hold the previous-default row
            # lock open while session B's concurrent promotion piles up behind it.
            locked_b = _get_calendar_for_update_or_404(session_a, calendar_b_id)
            previous_default = (
                session_a.query(Calendar)
                .filter(Calendar.is_default.is_(True))
                .filter(Calendar.id != calendar_b_id)
                .with_for_update()
                .first()
            )
            assert previous_default is not None
            assert previous_default.id == calendar_a_id
            previous_default.is_default = False
            locked_b.is_default = True
            session_a.flush()

            # Capture session B's backend pid *before* starting the thread that
            # will block it -- a Session/connection cannot safely be driven from
            # two threads at once, so this quick roundtrip must happen first.
            backend_pid_b = session_b.execute(text("SELECT pg_backend_pid()")).scalar()
            assert backend_pid_b is not None

            results: dict[str, Any] = {}

            def _run_session_b() -> None:
                try:
                    results["read"] = update_calendar(
                        calendar_c_id,
                        CalendarUpdate(is_default=True),
                        db=session_b,
                        _=cast(User, None),
                    )
                except HTTPException as exc:
                    results["error"] = exc

            thread = threading.Thread(target=_run_session_b)
            thread.start()
            try:
                _wait_until_backend_blocked_on_lock(engine, backend_pid_b)

                # Session A completes its promotion of B, releasing the lock
                # session B is queued on.
                session_a.commit()

                thread.join(timeout=5)
                assert not thread.is_alive(), (
                    "session B's promotion never returned -- looks like a deadlock/hang"
                )
            finally:
                thread.join(timeout=5)

            assert "error" in results, (
                f"expected session B's promotion to be rejected with a 409, got: {results}"
            )
            error = cast(HTTPException, results["error"])
            assert error.status_code == status.HTTP_409_CONFLICT
            session_b.rollback()
        finally:
            session_a.close()
            session_b.close()

        # Exactly one calendar ends up flagged is_default -- session A's winner (B)
        # -- and session B's rejected promotion of C never took effect.
        with session_factory() as verify_session:
            defaults = verify_session.query(Calendar).filter(Calendar.is_default.is_(True)).all()
            assert [calendar.id for calendar in defaults] == [calendar_b_id]

            calendar_c = verify_session.get(Calendar, calendar_c_id)
            assert calendar_c is not None
            assert calendar_c.is_default is False
    finally:
        engine.dispose()


def test_concurrent_first_calendar_creations_serialize_to_one_default(
    postgres_app_database_url: str,
) -> None:
    """Issue #110 review follow-up: the bootstrap "first calendar in an empty
    database becomes the default" promotion must not be decided by a read-then-write
    `count() == 0` check, which is a TOCTOU race under concurrent creation -- two
    requests can both observe an empty table before either commits. The fix
    (`_promote_as_default_if_unclaimed`) instead runs a conditional `UPDATE ...
    WHERE NOT EXISTS (...)` after the insert, inside its own SAVEPOINT so a losing
    transaction's unique-index violation can be swallowed without discarding the
    calendar row itself.

    Session A replicates `create_calendar`'s own sequence up to (but not including)
    its commit: insert calendar A, flush, then call the real
    `_promote_as_default_if_unclaimed` helper, which writes `is_default=True` but
    leaves it uncommitted since session A does not commit yet.

    Session B then runs the *real* `create_calendar` route function on its own
    thread. Session A's uncommitted write is invisible to session B's own `NOT
    EXISTS` check under READ COMMITTED, so session B also attempts to promote its
    own calendar (B) to default. PostgreSQL detects the emerging conflict between
    the two uncommitted `is_default=True` writes on the partial unique index and
    blocks session B's `UPDATE` until session A resolves the ambiguity.

    Once session A commits (calendar A wins the race and keeps `is_default=True`),
    session B's blocked `UPDATE` resumes, discovers the now-committed conflict, and
    that violation is caught by the promotion's own SAVEPOINT: calendar B is still
    created successfully (a normal `CalendarRead`, not an `HTTPException`), just
    not as the default. Exactly one calendar ends up flagged `is_default` -- proof
    that the conditional UPDATE, not a pre-computed flag, is what decided the
    outcome, and that losing the race is not surfaced as an error."""
    from waterfall.api.routes.resources import (
        _promote_as_default_if_unclaimed,  # pyright: ignore[reportPrivateUsage]
        create_calendar,
    )
    from waterfall.models.resources import Calendar
    from waterfall.models.user import User
    from waterfall.schemas.resources import CalendarCreate

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        session_a = session_factory()
        session_b = session_factory()
        try:
            # Session A: the early half of create_calendar's own sequence, held
            # open (no commit) so its is_default=True write stays uncommitted.
            calendar_a = Calendar(code="RACE-A", name="Race A", weeks_per_year=47)
            session_a.add(calendar_a)
            session_a.flush()
            _promote_as_default_if_unclaimed(session_a, calendar_a)
            assert calendar_a.is_default is True

            # Capture session B's backend pid *before* starting the thread that
            # will block it -- a Session/connection cannot safely be driven from
            # two threads at once, so this quick roundtrip must happen first.
            backend_pid_b = session_b.execute(text("SELECT pg_backend_pid()")).scalar()
            assert backend_pid_b is not None

            results: dict[str, Any] = {}

            def _run_session_b() -> None:
                results["response"] = create_calendar(
                    CalendarCreate(code="RACE-B", name="Race B", weeks_per_year=47),
                    db=session_b,
                    _=cast(User, None),
                )

            thread = threading.Thread(target=_run_session_b)
            thread.start()
            try:
                _wait_until_backend_blocked_on_lock(engine, backend_pid_b)

                # Session A completes, releasing the lock session B is queued on.
                session_a.commit()

                thread.join(timeout=5)
                assert not thread.is_alive(), (
                    "session B's create_calendar never returned -- looks like a deadlock/hang"
                )
            finally:
                thread.join(timeout=5)

            assert "response" in results, (
                f"expected session B's create_calendar to return a CalendarRead, got: {results}"
            )
            assert results["response"].is_default is False
        finally:
            session_a.close()
            session_b.close()

        # Exactly one calendar ends up flagged is_default -- session A's winner.
        with session_factory() as verify_session:
            defaults = verify_session.query(Calendar).filter(Calendar.is_default.is_(True)).all()
            assert [calendar.code for calendar in defaults] == ["RACE-A"]
    finally:
        engine.dispose()


def test_resource_update_response_ignores_write_committed_after_its_transaction(
    postgres_app_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #59: the response must describe this request's committed mutation."""
    from waterfall.api.routes.resources import update_node
    from waterfall.models.resources import ResourceNode
    from waterfall.models.user import User
    from waterfall.schemas.resources import ResourceNodeUpdate

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            node = ResourceNode(code="SNAPSHOT", name="Before")
            seed_session.add(node)
            seed_session.commit()
            node_id = node.id

        session_a = session_factory()
        original_commit = session_a.commit

        def commit_then_concurrent_update() -> None:
            original_commit()
            with session_factory() as session_b:
                concurrent_node = session_b.get(ResourceNode, node_id)
                assert concurrent_node is not None
                concurrent_node.name = "Concurrent write"
                session_b.commit()

        monkeypatch.setattr(session_a, "commit", commit_then_concurrent_update)
        try:
            response = update_node(
                node_id,
                ResourceNodeUpdate(name="Request A"),
                db=session_a,
                _=cast(User, None),
            )
        finally:
            session_a.close()

        assert response.name == "Request A"
        with session_factory() as verify_session:
            persisted_node = verify_session.get(ResourceNode, node_id)
            assert persisted_node is not None
            assert persisted_node.name == "Concurrent write"
    finally:
        engine.dispose()
