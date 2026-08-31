import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsTask


def test_stale_test_db_schema_is_rebuilt_at_session_start(tmp_path: Path) -> None:
    """A leftover test.db from a previous run/branch, with a schema older than the
    current models, must not silently persist into a new pytest session.

    prepare_test_environment drops and recreates the schema once per session instead
    of only calling create_all(): create_all() never migrates an existing table for an
    added/changed column, so without the drop a stale file would make tests run against
    the wrong schema instead of failing loudly or self-correcting.
    """
    # ms_task is the table test_sqlite_enforces_foreign_keys actually inserts into;
    # stub it with only its primary key so the target test's insert -- which sets every
    # other column -- fails loudly with "no such column" if the schema were left stale.
    stale_db = tmp_path / "stale.db"
    connection = sqlite3.connect(stale_db)
    connection.execute("CREATE TABLE ms_task (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    backend_dir = Path(__file__).resolve().parents[1]
    target = "tests/test_db_session.py::test_sqlite_enforces_foreign_keys"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-cov", target],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{stale_db}"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_sqlite_enforces_foreign_keys() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        session.add(
            MsTask(
                project_id=999999,
                uid=1,
                id_display=1,
                name="Orphan task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
                finish_at=datetime(2026, 1, 1, tzinfo=UTC),
                duration_minutes=None,
                duration_format=None,
                work_minutes=None,
                percent_complete=0,
                is_summary=False,
                is_milestone=False,
                calendar_uid=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
