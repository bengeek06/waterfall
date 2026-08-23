from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
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


def test_planning_lifecycle_migration_backfills_statuses_and_downgrades() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260821_0004")

        with _disposable_engine(database_url) as engine:
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
                        "(id, project_id, uid, name, is_summary, is_milestone, created_at, "
                        "updated_at) "
                        "VALUES (1, 1, 1001, 'Task', false, false, CURRENT_TIMESTAMP, "
                        "CURRENT_TIMESTAMP)"
                    )
                )

            _run_alembic(database_url, "20260821_0005")

            with engine.connect() as connection:
                projects = connection.execute(
                    text(
                        "SELECT p.id, p.status, w.validated_at, p.planning_reference_id, "
                        "p.displayed_planning_id FROM ms_project p "
                        "LEFT JOIN wf_planning w ON w.id = p.displayed_planning_id "
                        "ORDER BY p.id"
                    )
                ).all()
                assert projects[0][0:2] == (1, "initialise")
                assert projects[0][2] is not None
                assert projects[0][3:] == (1, 1)
                assert (
                    connection.execute(
                        text("SELECT status FROM wf_planning WHERE project_id = 1")
                    ).scalar_one()
                    == "validated"
                )
                assert projects[1][0:2] == (2, "cree")
                assert projects[1][2:] == (None, None, None)
                assert (
                    connection.execute(
                        text("SELECT status FROM wf_planning WHERE project_id = 2")
                    ).scalar_one()
                    == "draft"
                )
                assert connection.scalar(text("SELECT COUNT(*) FROM wf_planning")) == 2
                assert (
                    connection.scalar(text("SELECT COUNT(*) FROM wf_planning_task_snapshot")) == 1
                )

            _downgrade_alembic(database_url, "20260821_0004")

            with engine.connect() as connection:
                project_columns = {
                    column["name"] for column in inspect(connection).get_columns("ms_project")
                }
                assert "status" not in project_columns
                assert connection.scalar(text("SELECT COUNT(*) FROM ms_task")) == 1


def test_estimate_task_snapshot_downgrade_refuses_unrestorable_null_task_ids() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260822_0009")

        with _disposable_engine(database_url) as engine:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(email, hashed_password, is_active, is_admin, token_version, "
                        "failed_login_attempts, created_at, updated_at) VALUES "
                        "('migration@example.com', 'hash', true, false, 0, 0, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO ms_project "
                        "(owner_id, source_version, save_version_out, name, schedule_from_start, "
                        "start_date, minutes_per_day, minutes_per_week, days_per_month, "
                        "created_at, updated_at) VALUES (1, 2016, 16, 'Migration', true, "
                        "'2026-01-01 08:00:00', 480, 2400, 20, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO wf_estimate (project_id, version_number, kind, status, "
                        "currency_code, created_at) VALUES "
                        "(1, 1, 'initial', 'draft', 'EUR', CURRENT_TIMESTAMP)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO wf_estimate_task_row "
                        "(estimate_id, task_id, position, task_name, is_milestone) VALUES "
                        "(1, NULL, 1, 'Snapshot task', false)"
                    )
                )

            with pytest.raises(subprocess.CalledProcessError):
                _downgrade_alembic(database_url, "20260822_0008")

            with engine.connect() as connection:
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20260822_0009"
                )
                connection.commit()
