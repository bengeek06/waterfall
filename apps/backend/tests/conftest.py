import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")


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
        # Delete rows (children before parents) instead of dropping and recreating the
        # schema: DDL churn on every one of ~280 tests was the dominant cost of the
        # suite (~1.3s/test just in fixture setup). SQLite reassigns a table's
        # INTEGER PRIMARY KEY rowid starting at 1 once it is empty (these models don't
        # use the AUTOINCREMENT keyword), so this is behaviorally equivalent to a full
        # recreate for anything the test suite asserts on.
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
        # Commit before re-enabling the pragma: the deletes above autobegan this
        # connection's SQLAlchemy transaction, and the pragma is a no-op while one is
        # still open (see the comment above).
        connection.commit()
        if is_sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


@pytest.fixture(autouse=True)
def reset_login_rate_limiter() -> None:
    from waterfall.api.routes.auth import login_rate_limiter

    login_rate_limiter.clear()
