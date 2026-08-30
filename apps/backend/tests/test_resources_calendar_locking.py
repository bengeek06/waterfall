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
from typing import cast

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
        code="DEV-LOCK",
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
