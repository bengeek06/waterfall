from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import Engine, create_engine, inspect, text

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

            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260829_0002"
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
        _downgrade_alembic(database_url, "-1")

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
