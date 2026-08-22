from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]


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


def test_planning_lifecycle_migration_backfills_statuses_and_downgrades() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260821_0004")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ms_project "
                    "(id, source_version, save_version_out, name, schedule_from_start, "
                    "start_date, minutes_per_day, minutes_per_week, days_per_month, "
                    "created_at, updated_at) VALUES "
                    "(1, 2016, 16, 'With tasks', true, '2026-01-01 08:00:00', "
                    "480, 2400, 20, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "(2, 2016, 16, 'Without tasks', true, '2026-01-01 08:00:00', "
                    "480, 2400, 20, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ms_task "
                    "(id, project_id, uid, name, is_summary, is_milestone, created_at, updated_at) "
                    "VALUES (1, 1, 1001, 'Task', false, false, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                )
            )

        _run_alembic(database_url, "20260821_0005")

        with engine.connect() as connection:
            projects = connection.execute(
                text(
                    "SELECT id, status, planning_reference_id, displayed_planning_id "
                    "FROM ms_project ORDER BY id"
                )
            ).all()
            assert [tuple(project) for project in projects] == [
                (1, "initialise", 1, 1),
                (2, "cree", 2, 2),
            ]
            assert connection.scalar(text("SELECT COUNT(*) FROM wf_planning")) == 2
            assert connection.scalar(text("SELECT COUNT(*) FROM wf_planning_task_snapshot")) == 1

        _downgrade_alembic(database_url, "20260821_0004")

        with engine.connect() as connection:
            project_columns = {
                column["name"] for column in inspect(connection).get_columns("ms_project")
            }
            assert "status" not in project_columns
            assert connection.scalar(text("SELECT COUNT(*) FROM ms_task")) == 1
