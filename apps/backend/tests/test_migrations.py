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
                == "20260823_0001"
            )


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
