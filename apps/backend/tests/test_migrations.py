from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from _postgres_support import (
    ephemeral_postgres_database,
    postgres_admin_url,
    postgres_reachable,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


@contextmanager
def _disposable_engine(database_url: str) -> Generator[Engine]:
    # Dispose the engine so its pooled sqlite connections are closed here instead of
    # being reclaimed later by the GC (which would raise a ResourceWarning).
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _run_alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _downgrade_alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def postgres_database_url() -> Generator[str]:
    admin_url = postgres_admin_url()
    if not postgres_reachable(admin_url):
        pytest.skip(
            "PostgreSQL is not reachable at "
            f"{make_url(admin_url).render_as_string(hide_password=True)}; set "
            "TEST_POSTGRES_URL or start the docker-compose postgres service to run "
            "this test."
        )
    with ephemeral_postgres_database(admin_url) as database_url:
        yield database_url


def test_migration_upgrade_creates_expected_schema() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            assert {
                "ms_project",
                "ms_task",
                "wf_planning",
                "wf_planning_task_snapshot",
                "wf_estimate",
                "wf_estimate_task_row",
            }.issubset(table_names)

            project_columns = {column["name"] for column in inspector.get_columns("ms_project")}
            assert {"status", "planning_reference_id", "displayed_planning_id"}.issubset(
                project_columns
            )

            planning_columns = {column["name"] for column in inspector.get_columns("wf_planning")}
            assert "structure_draft_json" in planning_columns

            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "code" not in role_columns

            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260831_0003"
            )


def test_migration_creates_calendar_tables_and_seeds_standard_calendar() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            assert {"wf_calendar", "wf_calendar_weekday"}.issubset(set(inspector.get_table_names()))

            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "calendar_id" in role_columns

            calendar_row = connection.execute(
                text("SELECT id, name, weeks_per_year FROM wf_calendar WHERE code = 'STANDARD'")
            ).one()
            weekdays = connection.execute(
                text(
                    "SELECT day_type, hours_per_day FROM wf_calendar_weekday "
                    "WHERE calendar_id = :calendar_id ORDER BY day_type"
                ),
                {"calendar_id": calendar_row[0]},
            ).all()

            assert calendar_row[1] == "Standard"
            assert calendar_row[2] == 47
            assert [row[0] for row in weekdays] == [1, 2, 3, 4, 5, 6, 7]
            assert [float(row[1]) for row in weekdays] == [0.0, 7.0, 7.0, 7.0, 7.0, 7.0, 0.0]


def test_migration_backfills_existing_roles_with_standard_calendar() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260823_0001")

        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO wf_cost_type "
                    "(id, code, name, kind, is_active, created_at, updated_at) "
                    "VALUES (1, 'MO', 'Main d''oeuvre', 'labor', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_cost_category (id, cost_type_id, accounting_code, name, "
                    "is_active, created_at, updated_at) VALUES (1, 1, 'DEV', 'Developpement', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_resource_node (id, code, name, is_active, "
                    "created_at, updated_at) VALUES (1, 'IT', 'Informatique', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_resource_role (id, node_id, cost_category_id, code, name, "
                    "is_active, created_at, updated_at) VALUES "
                    "(1, 1, 1, 'DEV-SW', 'Developpeur', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            standard_id = connection.scalar(
                text("SELECT id FROM wf_calendar WHERE code = 'STANDARD'")
            )
            assert (
                connection.scalar(text("SELECT calendar_id FROM wf_resource_role WHERE id = 1"))
                == standard_id
            )


def test_calendar_migration_is_reversible() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")
        _downgrade_alembic(database_url, "20260823_0001")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            assert "wf_calendar" not in table_names
            assert "wf_calendar_weekday" not in table_names
            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "calendar_id" not in role_columns
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260823_0001"
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            assert "wf_calendar" in inspector.get_table_names()
            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "calendar_id" in role_columns


def test_resource_role_code_removal_migration_is_reversible() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "code" not in role_columns

        # Seed two roles (past the point "code" was dropped) so the downgrade below is
        # exercised against a table with more than one row: a static server_default for
        # the resurrected "code" column would give every row the same value and blow up
        # the unique constraint the downgrade re-creates.
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO wf_cost_type "
                    "(id, code, name, kind, is_active, created_at, updated_at) "
                    "VALUES (1, 'MO', 'Main d''oeuvre', 'labor', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_cost_category (id, cost_type_id, accounting_code, name, "
                    "is_active, created_at, updated_at) VALUES (1, 1, 'DEV', 'Developpement', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_resource_node (id, code, name, is_active, "
                    "created_at, updated_at) VALUES (1, 'IT', 'Informatique', 1, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_resource_role "
                    "(id, node_id, cost_category_id, name, is_active, created_at, updated_at) "
                    "VALUES "
                    "(1, 1, 1, 'Developpeur', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00'), "
                    "(2, 1, 1, 'Architecte', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )

        _downgrade_alembic(database_url, "20260829_0002")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "code" in role_columns
            unique_constraints = inspector.get_unique_constraints("wf_resource_role")
            assert any(constraint["column_names"] == ["code"] for constraint in unique_constraints)
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260829_0002"
            )

            codes = connection.execute(
                text("SELECT id, code FROM wf_resource_role ORDER BY id")
            ).all()
            assert [row[0] for row in codes] == [1, 2]
            role_codes = [row[1] for row in codes]
            assert all(role_codes), "downgraded roles must keep a non-empty code"
            assert len(set(role_codes)) == len(role_codes), "downgraded role codes must be unique"

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "code" not in role_columns


def test_migration_downgrade_drops_all_tables() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")
        _downgrade_alembic(database_url, "base")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            assert "ms_project" not in table_names
            assert "wf_planning" not in table_names

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert "ms_project" in inspect(connection).get_table_names()


def _assert_schema_matches_orm_metadata(database_url: str) -> None:
    """Diff a post-`upgrade head` schema against Base.metadata via alembic's comparator.

    A non-empty diff means a model changed without a matching migration (or vice versa).
    `compare_server_default` is enabled explicitly (alongside the already-default
    `compare_type`) so a future `server_default` added to a model without a matching
    migration default is also caught.
    """
    # Importing the models package registers every mapped class on Base.metadata;
    # nothing else in this test module triggers that import chain.
    from waterfall.models import User

    _ = User.__tablename__
    from waterfall.db.base import Base

    _run_alembic(database_url, "head")

    with _disposable_engine(database_url) as engine, engine.connect() as connection:
        migration_context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        diffs = compare_metadata(migration_context, Base.metadata)

    assert diffs == [], f"Schema drift between migrations and ORM models: {diffs!r}"


def test_migration_schema_matches_orm_metadata() -> None:
    """SQLite variant: fast, but notoriously unreliable for compare_type on some types
    (Boolean, Numeric, timezone-aware DateTime). Kept as a quick complement to the
    PostgreSQL variant below, which is the production-representative check."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _assert_schema_matches_orm_metadata(database_url)


def test_postgres_migration_schema_matches_orm_metadata(postgres_database_url: str) -> None:
    """PostgreSQL variant: the production-representative schema-drift guard for #45."""
    _assert_schema_matches_orm_metadata(postgres_database_url)


def test_postgres_migration_upgrade_head_succeeds(postgres_database_url: str) -> None:
    # Regression test for the original bug: ms_project's FKs to wf_planning/wf_estimate
    # were emitted before those tables existed. SQLite tolerates forward references at
    # CREATE TABLE time, PostgreSQL does not, so only a real PostgreSQL run catches a
    # future migration reintroducing this ordering mistake.
    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        assert {
            "ms_project",
            "ms_task",
            "wf_planning",
            "wf_planning_task_snapshot",
            "wf_estimate",
            "wf_estimate_task_row",
        }.issubset(table_names)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260831_0003"


def test_postgres_migration_is_reversible(postgres_database_url: str) -> None:
    _run_alembic(postgres_database_url, "head")
    _downgrade_alembic(postgres_database_url, "base")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        assert "ms_project" not in table_names
        assert "wf_planning" not in table_names
        assert "wf_estimate" not in table_names

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        assert "ms_project" in table_names
        assert "wf_planning" in table_names
        assert "wf_estimate" in table_names
