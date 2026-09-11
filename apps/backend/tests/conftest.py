import os
import sys
from pathlib import Path

import pytest

# Registers the fixtures of _postgres_support/_redis_support/_object_storage_support
# globally, so test modules can request them by parameter name without importing them --
# importing a @pytest.fixture-decorated callable by name into a module that also takes it
# as a test parameter trips ruff's F811 ("redefinition of unused import"), which doesn't
# recognize that pattern as pytest's normal cross-module fixture sharing.
pytest_plugins = ["_postgres_support", "_redis_support", "_object_storage_support"]

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")
# Same default as Settings.redis_url: the in-process limiter, so the suite runs on a
# checkout with no Redis. Without it the fail-closed login path would 503 in every test
# that authenticates, not just the auth ones. TEST_REDIS_URL points the whole app (not
# just _redis_support's reachability checks) at a real Redis; CI sets it so the Redis
# backend itself stays covered.
os.environ.setdefault("REDIS_URL", os.environ.get("TEST_REDIS_URL", "memory://"))
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
# The GARAGE_* object storage settings are defaulted by _object_storage_support (the
# plugin listed above), next to the moto backend that has to agree with them -- not here,
# because importing that module from this one would disable pytest's assertion rewriting
# for it. Plugins are imported before any test runs, hence before Settings is first read.


@pytest.fixture(autouse=True, scope="session")
def prepare_test_environment():
    from waterfall.core.config import get_settings
    from waterfall.db.base import Base
    from waterfall.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    # Schema is dropped and recreated once for the whole session -- not per test, as
    # before -- so switching branches or pulling in a model change still gets a schema
    # that actually matches the current models. test.db is a real, gitignored file that
    # survives between separate local pytest invocations; create_all() alone only adds
    # tables that don't exist yet, it never migrates an existing table for a column or
    # constraint change, so a stale file could otherwise silently run tests against an
    # outdated schema. reset_database (below) then just empties rows between tests.
    engine = get_engine()
    is_sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        if is_sqlite:
            # See reset_database's comment on this cycle and the pragma/transaction gotcha.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(bind=connection)
        connection.commit()
        if is_sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
    Base.metadata.create_all(bind=engine)

    yield

    # Close pooled sqlite connections so the GC does not emit a ResourceWarning.
    get_engine().dispose()


@pytest.fixture(autouse=True)
def reset_database() -> None:
    from waterfall.db.base import Base
    from waterfall.db.session import get_engine

    engine = get_engine()
    is_sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        if is_sqlite:
            # The ms_project <-> wf_planning <-> wf_estimate FK cycle is closed via
            # use_alter=True on the model constraints (see models/ms_core.py), which
            # is enough for SQLAlchemy to resolve table creation/drop order without
            # an SAWarning. SQLite itself still inlines FK constraints in CREATE TABLE
            # regardless of use_alter (it has no ALTER TABLE ADD CONSTRAINT support),
            # so leftover rows from a previous test can still trip FK enforcement
            # while tables involved in the cycle are emptied one at a time; disabling
            # the pragma for the delete keeps that ordering-independent. Issued outside
            # any transaction: SQLite silently no-ops a foreign_keys pragma change made
            # mid-transaction, and (unlike the DDL this fixture used to run) a plain
            # DELETE starts a real one, so toggling it back on would otherwise never
            # actually take effect once this fixture is done.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            # Delete rows (children before parents) instead of dropping and recreating
            # the schema: DDL churn on every one of ~280 tests was the dominant cost of
            # the suite (~1.3s/test just in fixture setup). SQLite reassigns a table's
            # INTEGER PRIMARY KEY rowid starting at 1 once it is empty (these models
            # don't use the AUTOINCREMENT keyword), so this is behaviorally equivalent
            # to a full recreate for anything the test suite asserts on.
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
            # Commit before re-enabling the pragma: the deletes above autobegan this
            # connection's SQLAlchemy transaction, and the pragma is a no-op while one
            # is still open (see the comment above).
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        else:
            # On PostgreSQL, unlike SQLite, the ms_project <-> wf_planning <->
            # wf_estimate cycle's FK constraints stay immediate (checked per-statement)
            # regardless of use_alter -- that flag only affects DDL ordering. No
            # `reversed(sorted_tables)` order can satisfy a DELETE across both
            # directions of a real cycle, so this would intermittently fail once a
            # test populates rows across it. TRUNCATE ... CASCADE lets Postgres itself
            # resolve the cycle instead of relying on a fixed statement order.
            table_names = ", ".join(
                connection.dialect.identifier_preparer.format_table(table)
                for table in Base.metadata.sorted_tables
            )
            connection.exec_driver_sql(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
            connection.commit()


@pytest.fixture(autouse=True)
def reset_readiness_probe_state() -> None:
    """Drop the readiness probe's memoised result and its private engine (E13-03).

    `check_dependencies()` caches for a few seconds so that a burst of anonymous
    /health/ready calls cannot spawn three threads each; tests run far faster than that
    window and simulate outages in-process, so without this a test would assert on the
    previous test's answer. The probe engine is cached the same way as `get_engine()` and
    is dropped for the same reason: a test repointing DATABASE_URL must not inherit an
    engine built from the value before it.
    """
    from waterfall.api.routes.health import reset_dependency_cache, reset_probe_engine

    reset_dependency_cache()
    reset_probe_engine()


@pytest.fixture(autouse=True)
def reset_login_rate_limiter() -> None:
    # Runs before every test in the suite -- most of which have nothing to do with auth --
    # so it must never fail: on the default memory:// backend it empties an in-process
    # dict, and on Redis it swallows connection errors rather than failing closed like
    # allow() (see _RedisRateLimitBackend.clear()).
    from waterfall.api.routes.auth import login_rate_limiter

    login_rate_limiter.clear()
