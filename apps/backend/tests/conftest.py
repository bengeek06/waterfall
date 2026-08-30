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
    from waterfall.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    yield

    # Close pooled sqlite connections so the GC does not emit a ResourceWarning.
    get_engine().dispose()


@pytest.fixture(autouse=True)
def reset_database() -> None:
    from waterfall.db.base import Base
    from waterfall.db.session import get_engine

    engine = get_engine()
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            # The ms_project <-> wf_planning <-> wf_estimate FK cycle is closed via
            # use_alter=True on the model constraints (see models/ms_core.py), which
            # is enough for SQLAlchemy to resolve table creation/drop order without
            # an SAWarning. SQLite itself still inlines FK constraints in CREATE TABLE
            # regardless of use_alter (it has no ALTER TABLE ADD CONSTRAINT support),
            # so leftover rows from a previous test can still trip FK enforcement
            # while tables involved in the cycle are dropped one at a time; disabling
            # the pragma for the drop keeps that ordering-independent.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(bind=connection)
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def reset_login_rate_limiter() -> None:
    from waterfall.api.routes.auth import login_rate_limiter

    login_rate_limiter.clear()
