from collections.abc import Generator
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from waterfall.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    if engine.url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
