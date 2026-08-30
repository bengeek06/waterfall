"""Shared helpers for tests that need a real PostgreSQL backend.

Factored out of test_migrations.py (rather than duplicated) so every test that
needs a throwaway PostgreSQL database against the local docker-postgres-1
service shares exactly one reachability policy and one ephemeral-database
lifecycle: test_migrations.py uses it for migration tests (database migrated to
head via Alembic), test_resources_calendar_locking.py uses it for an
application-level concurrency test (database populated via
Base.metadata.create_all instead). Both need the same "is PostgreSQL up, and if
so give me a disposable database" building block, nothing migration-specific.

Deliberately not named test_*.py: pytest's default collection would otherwise
try to import it as a test module. Its functions are also deliberately *not*
underscore-prefixed (unlike the rest of this test suite's module-local helpers)
because they are meant to be imported across test modules; pyright's strict
`reportPrivateUsage` check flags leading-underscore names used outside their
declaring module, and there is no other module in this codebase that needs to
reach into pytest test helpers, so a shared public-named module is the cleanest
fix at the root rather than suppressing the check at each call site.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Default admin connection for spinning up ephemeral PostgreSQL test databases; matches
# the docker-compose dev service credentials (infra/docker/docker-compose.yml) so tests
# work out of the box against `docker compose up postgres`. Override with
# TEST_POSTGRES_URL to point at a different PostgreSQL instance (e.g. in CI).
DEFAULT_TEST_POSTGRES_URL = "postgresql+psycopg://waterfall:waterfall@localhost:5432/waterfall"


def postgres_admin_url() -> str:
    return os.environ.get("TEST_POSTGRES_URL", DEFAULT_TEST_POSTGRES_URL)


def postgres_reachable(admin_url: str) -> bool:
    url = make_url(admin_url)
    try:
        connection = psycopg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            dbname=url.database,
            connect_timeout=2,
        )
    except psycopg.OperationalError:
        return False
    connection.close()
    return True


@contextmanager
def ephemeral_postgres_database(admin_url: str) -> Generator[str]:
    """Create a throwaway PostgreSQL database on the server addressed by admin_url.

    Yields a connection URL for the new database and drops it on exit, even if the
    caller raises. CREATE/DROP DATABASE cannot run inside a transaction, hence the
    AUTOCOMMIT isolation level on the admin connection.
    """
    database_name = f"test_ephemeral_{uuid.uuid4().hex}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        try:
            yield (
                make_url(admin_url)
                .set(database=database_name)
                .render_as_string(hide_password=False)
            )
        finally:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    finally:
        admin_engine.dispose()
