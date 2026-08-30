"""Concurrency regression test for issue #50 (calendar deactivation TOCTOU race).

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

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
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
