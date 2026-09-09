from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import Engine, String, create_engine, inspect, text
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


def _run_alembic(database_url: str, revision: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
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


def _seed_estimate_line(database_url: str, role_code: str, role_name: str | None = None) -> None:
    """Seed a minimal but FK-complete `wf_estimate_line` row on a database already
    migrated to head, via the ORM.

    `role_name` defaults to `role_code` to mirror how
    `waterfall.services.estimate_calculation._generate_labor_lines` derives
    `EstimateLine.role_code` from `ResourceRole.name` in production. Kept as a separate
    module-scoped helper (rather than inlined per test) because both the SQLite downgrade
    guard tests and the PostgreSQL empirical test below need the exact same FK chain:
    CostType -> CostCategory -> ResourceNode -> ResourceRole, MsProject -> Estimate ->
    EstimateLine.
    """
    from sqlalchemy.orm import Session

    from waterfall.models.ms_core import MsProject
    from waterfall.models.resources import (
        CostCategory,
        CostType,
        Estimate,
        EstimateLine,
        ResourceNode,
        ResourceRole,
    )

    with _disposable_engine(database_url) as engine, Session(engine) as session:
        cost_type = CostType(code="MO", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()

        cost_category = CostCategory(
            cost_type_id=cost_type.id, accounting_code="DEV", name="Developpement"
        )
        session.add(cost_category)
        session.flush()

        node = ResourceNode(code="IT", name="Informatique")
        session.add(node)
        session.flush()

        role = ResourceRole(
            node_id=node.id, cost_category_id=cost_category.id, name=role_name or role_code
        )
        session.add(role)
        session.flush()

        project = MsProject(
            source_version=2016,
            name="Projet Test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add(project)
        session.flush()

        estimate = Estimate(
            project_id=project.id, version_number=1, kind="initial", currency_code="EUR"
        )
        session.add(estimate)
        session.flush()

        line = EstimateLine(
            estimate_id=estimate.id,
            role_id=role.id,
            task_name="Tache",
            role_code=role_code,
            role_name=role.name,
            accounting_code=cost_category.accounting_code,
            year=2026,
            quantity=Decimal("1"),
            hours=Decimal("10"),
            hourly_rate=Decimal("50"),
            inflation_coefficient=Decimal("1"),
            budget_cost=Decimal("500"),
        )
        session.add(line)
        session.commit()


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

            project_column_details = {
                column["name"]: column for column in inspector.get_columns("ms_project")
            }
            project_columns = set(project_column_details)
            assert {"status", "planning_reference_id", "displayed_planning_id"}.issubset(
                project_columns
            )
            external_uid_type = project_column_details["external_uid"]["type"]
            assert isinstance(external_uid_type, String)
            assert external_uid_type.length == 36

            planning_columns = {column["name"] for column in inspector.get_columns("wf_planning")}
            assert "structure_draft_json" in planning_columns
            assert "revision" in planning_columns

            role_columns = {column["name"] for column in inspector.get_columns("wf_resource_role")}
            assert "code" not in role_columns

            task_columns = {column["name"] for column in inspector.get_columns("ms_task")}
            assert "id_display" not in task_columns
            snapshot_columns = {
                column["name"] for column in inspector.get_columns("wf_planning_task_snapshot")
            }
            assert "id_display" not in snapshot_columns
            task_index_names = {index["name"] for index in inspector.get_indexes("ms_task")}
            assert "idx_ms_task_project_id_display" not in task_index_names

            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0010"
            )


def test_task_id_display_removal_migration_upgrade_with_existing_data() -> None:
    """E9-01 (#146): the migration must apply cleanly on a database that already has
    ms_task/wf_planning_task_snapshot rows carrying non-null id_display values, and
    must drop both the column and its supporting index."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260906_0007")

        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ms_project (id, source_version, save_version_out, name, "
                    "schedule_from_start, start_date, minutes_per_day, minutes_per_week, "
                    "days_per_month, status, created_at, updated_at) VALUES (1, 2016, 16, "
                    "'Project', 1, '2026-01-01', 480, 2400, 20, 'cree', "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ms_task (id, project_id, uid, id_display, name, is_summary, "
                    "is_milestone, created_at, updated_at) VALUES (1, 1, 1, 42, 'Task', 0, 0, "
                    "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_planning (id, project_id, version_number, status, revision, "
                    "created_at) VALUES (1, 1, 1, 'draft', 0, '2026-01-01 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_planning_task_snapshot (id, planning_id, uid, id_display, "
                    "name, is_summary, is_milestone) VALUES (1, 1, 1, 7, 'Snapshot', 0, 0)"
                )
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            task_columns = {column["name"] for column in inspector.get_columns("ms_task")}
            assert "id_display" not in task_columns
            snapshot_columns = {
                column["name"] for column in inspector.get_columns("wf_planning_task_snapshot")
            }
            assert "id_display" not in snapshot_columns
            task_index_names = {index["name"] for index in inspector.get_indexes("ms_task")}
            assert "idx_ms_task_project_id_display" not in task_index_names

            assert connection.scalar(text("SELECT uid FROM ms_task")) == 1
            assert connection.scalar(text("SELECT uid FROM wf_planning_task_snapshot")) == 1


def test_task_id_display_removal_migration_is_reversible() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")
        _downgrade_alembic(database_url, "20260906_0007")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            task_columns = {column["name"] for column in inspector.get_columns("ms_task")}
            assert "id_display" in task_columns
            snapshot_columns = {
                column["name"] for column in inspector.get_columns("wf_planning_task_snapshot")
            }
            assert "id_display" in snapshot_columns
            task_index_names = {index["name"] for index in inspector.get_indexes("ms_task")}
            assert "idx_ms_task_project_id_display" in task_index_names
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260906_0007"
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            task_columns = {column["name"] for column in inspector.get_columns("ms_task")}
            assert "id_display" not in task_columns


def test_postgres_task_id_display_removal_migration_upgrade_and_downgrade(
    postgres_database_url: str,
) -> None:
    """PostgreSQL variant of the id_display removal round trip (#146/E9-01)."""
    _run_alembic(postgres_database_url, "20260906_0007")

    with _disposable_engine(postgres_database_url) as engine, engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (email, hashed_password, is_active, is_admin, "
                "token_version, failed_login_attempts, created_at, updated_at) VALUES "
                "('e9-01-migration@example.com', 'x', true, true, 0, 0, now(), now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ms_project (owner_id, source_version, save_version_out, name, "
                "schedule_from_start, start_date, minutes_per_day, minutes_per_week, "
                "days_per_month, status, created_at, updated_at) VALUES ("
                "(SELECT id FROM users WHERE email = 'e9-01-migration@example.com'), "
                "2016, 16, 'Project', true, now(), 480, 2400, 20, 'cree', now(), now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ms_task (project_id, uid, id_display, name, is_summary, "
                "is_milestone, created_at, updated_at) VALUES "
                "((SELECT id FROM ms_project LIMIT 1), 1, 42, 'Task', false, false, "
                "now(), now())"
            )
        )

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        inspector = inspect(connection)
        task_columns = {column["name"] for column in inspector.get_columns("ms_task")}
        assert "id_display" not in task_columns
        task_index_names = {index["name"] for index in inspector.get_indexes("ms_task")}
        assert "idx_ms_task_project_id_display" not in task_index_names
        assert connection.scalar(text("SELECT uid FROM ms_task")) == 1

    _downgrade_alembic(postgres_database_url, "20260906_0007")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        inspector = inspect(connection)
        task_columns = {column["name"] for column in inspector.get_columns("ms_task")}
        assert "id_display" in task_columns
        task_index_names = {index["name"] for index in inspector.get_indexes("ms_task")}
        assert "idx_ms_task_project_id_display" in task_index_names


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


def test_calendar_default_flag_migration_backfills_standard_and_enforces_uniqueness() -> None:
    """Issue #51: the 20260901_0004 migration adds wf_calendar.is_default, backfills
    the seeded STANDARD calendar's row to True, and creates a partial unique index
    enforcing at most one True row system-wide."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            calendar_columns = {
                column["name"] for column in inspect(connection).get_columns("wf_calendar")
            }
            assert "is_default" in calendar_columns

            row = connection.execute(
                text("SELECT code, is_default FROM wf_calendar WHERE code = 'STANDARD'")
            ).one()
            assert row[1] == 1

            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0010"
            )

        # STANDARD is already backfilled to is_default=1 above, so a second row
        # inserted with is_default=1 must be rejected by the partial unique index
        # immediately -- no need to promote a second row first.
        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            with pytest.raises(Exception, match="UNIQUE constraint failed"):
                connection.execute(
                    text(
                        "INSERT INTO wf_calendar (code, name, weeks_per_year, is_active, "
                        "is_default, created_at, updated_at) VALUES ('OTHER', 'Other', 47, 1, "
                        "1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                    )
                )
            connection.rollback()


def test_calendar_default_flag_migration_is_reversible() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")
        _downgrade_alembic(database_url, "20260831_0003")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            calendar_columns = {
                column["name"] for column in inspect(connection).get_columns("wf_calendar")
            }
            assert "is_default" not in calendar_columns
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260831_0003"
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            calendar_columns = {
                column["name"] for column in inspect(connection).get_columns("wf_calendar")
            }
            assert "is_default" in calendar_columns
            assert (
                connection.scalar(
                    text("SELECT is_default FROM wf_calendar WHERE code = 'STANDARD'")
                )
                == 1
            )


def test_calendar_default_flag_migration_does_not_backfill_inactive_standard() -> None:
    """Follow-up to issue #51: if a deployment already deactivated the STANDARD
    calendar before running the 20260901_0004 migration (the exact deactivation bug
    issue #51 exists to repair), the backfill must NOT flag that inactive row
    is_default=true. update_calendar's promotion logic requires the target to be
    active, and resolve_default_calendar_id only considers active rows, so an
    inactive is_default row is a state the API would never produce -- and would
    silently degrade the system to the wall-clock fallback with no active default and
    no operator-visible signal (see the migration's own comment for why a warning,
    not an auto-reactivation, is the intervention here)."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260831_0003")

        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(text("UPDATE wf_calendar SET is_active = 0 WHERE code = 'STANDARD'"))

        result = _run_alembic(database_url, "head")
        assert "STANDARD" in result.stderr
        assert "inactive" in result.stderr

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            standard_row = connection.execute(
                text("SELECT is_active, is_default FROM wf_calendar WHERE code = 'STANDARD'")
            ).one()
            assert standard_row[0] == 0
            assert standard_row[1] == 0

            any_default_count = connection.scalar(
                text("SELECT COUNT(*) FROM wf_calendar WHERE is_default = 1")
            )
            assert any_default_count == 0


def test_calendar_default_flag_migration_warns_when_standard_renamed() -> None:
    """Follow-up to issue #51: if a deployment renames (or deletes) the STANDARD
    calendar's code before ever running the 20260901_0004 migration -- the literal
    rename/delete deployment scenario the issue describes -- the backfill's UPDATE
    matches zero rows and there is no row with code == 'STANDARD' to inspect at all.
    That must still emit the "no calendar with code == 'STANDARD' was found" warning
    (distinct from the inactive-row warning covered above) so an operator notices the
    system ended up with no default calendar, rather than failing silently."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260831_0003")

        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text("UPDATE wf_calendar SET code = 'RENAMED' WHERE code = 'STANDARD'")
            )

        result = _run_alembic(database_url, "head")
        assert "no calendar with code == 'STANDARD' was found" in result.stderr

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            any_default_count = connection.scalar(
                text("SELECT COUNT(*) FROM wf_calendar WHERE is_default = 1")
            )
            assert any_default_count == 0


def test_postgres_calendar_default_flag_migration_upgrade_and_downgrade(
    postgres_database_url: str,
) -> None:
    """PostgreSQL variant of the calendar default-flag migration round trip, covering
    the partial-index syntax difference (postgresql_where vs sqlite_where) and the
    server_default drop-after-backfill step on a real PostgreSQL dialect."""
    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        calendar_columns = {
            column["name"] for column in inspect(connection).get_columns("wf_calendar")
        }
        assert "is_default" in calendar_columns

        row = connection.execute(
            text("SELECT code, is_default FROM wf_calendar WHERE code = 'STANDARD'")
        ).one()
        assert row[1] is True

    # STANDARD is already backfilled to is_default=true above, so a second row
    # inserted with is_default=true must be rejected by the partial unique index
    # immediately -- no need to promote a second row first.
    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        with pytest.raises(Exception, match="uq_wf_calendar_is_default_true"):
            connection.execute(
                text(
                    "INSERT INTO wf_calendar (code, name, weeks_per_year, is_active, "
                    "is_default, created_at, updated_at) VALUES ('OTHER', 'Other', 47, true, "
                    "true, now(), now())"
                )
            )
        connection.rollback()

    _downgrade_alembic(postgres_database_url, "20260831_0003")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        calendar_columns = {
            column["name"] for column in inspect(connection).get_columns("wf_calendar")
        }
        assert "is_default" not in calendar_columns

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        calendar_columns = {
            column["name"] for column in inspect(connection).get_columns("wf_calendar")
        }
        assert "is_default" in calendar_columns


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


def test_resource_role_code_removal_downgrade_rejects_long_role_code() -> None:
    """Regression guard for the truncation risk flagged on #46's downgrade path: since
    role_code is now derived from ResourceRole.name (up to 255 chars) instead of the
    removed ResourceRole.code (64 chars), an existing wf_estimate_line row can hold a
    role_code longer than 64 characters. Downgrading must refuse rather than silently
    truncate it."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")

        _seed_estimate_line(database_url, role_code="R" * 100)

        # Target the resource-role-code-removal revision explicitly (rather than "-1")
        # so this test stays correct regardless of how many migrations now sit above it
        # in the chain (see 20260901_0004, added after this migration for issue #51).
        # alembic applies each intermediate downgrade step individually, so 20260901_0004's
        # own downgrade (unrelated to role_code) still succeeds before 20260831_0003's
        # downgrade raises -- the version lands one step short of the original target, at
        # 20260831_0003, not back at head.
        with pytest.raises(subprocess.CalledProcessError):
            _downgrade_alembic(database_url, "20260829_0002")

        # The rejected downgrade must not have applied the role_code-losing step: schema
        # and data below it untouched.
        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260831_0003"
            )
            assert connection.scalar(text("SELECT role_code FROM wf_estimate_line")) == "R" * 100


def test_resource_role_code_removal_downgrade_succeeds_with_short_role_code() -> None:
    """Nominal counterpart to the rejection test above: a role_code within the old
    64-character limit must still downgrade successfully, with the value preserved."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "head")

        _seed_estimate_line(database_url, role_code="R" * 50)

        # Target the resource-role-code-removal revision explicitly (rather than "-1"),
        # same reasoning as the rejection test above.
        _downgrade_alembic(database_url, "20260829_0002")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260829_0002"
            )
            assert connection.scalar(text("SELECT role_code FROM wf_estimate_line")) == "R" * 50


def test_project_external_uid_migration_downgrade_preserves_short_value() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite+pysqlite:///{Path(temporary_directory) / 'migration.db'}"
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ms_project (external_uid, source_version, save_version_out, "
                    "name, schedule_from_start, start_date, minutes_per_day, minutes_per_week, "
                    "days_per_month, created_at, updated_at, status) VALUES (:external_uid, "
                    "2016, 16, 'Downgrade', 1, '2026-01-01', 480, 2400, 20, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'cree')"
                ),
                {"external_uid": "G" * 16},
            )

        _downgrade_alembic(database_url, "20260901_0004")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert connection.scalar(text("SELECT external_uid FROM ms_project")) == "G" * 16
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260901_0004"
            )


def test_project_external_uid_migration_downgrade_rejects_long_value() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_url = f"sqlite+pysqlite:///{Path(temporary_directory) / 'migration.db'}"
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ms_project (external_uid, source_version, save_version_out, "
                    "name, schedule_from_start, start_date, minutes_per_day, minutes_per_week, "
                    "days_per_month, created_at, updated_at, status) VALUES (:external_uid, "
                    "2016, 16, 'Downgrade', 1, '2026-01-01', 480, 2400, 20, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'cree')"
                ),
                {"external_uid": "G" * 17},
            )

        with pytest.raises(subprocess.CalledProcessError):
            _downgrade_alembic(database_url, "20260901_0004")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert connection.scalar(text("SELECT external_uid FROM ms_project")) == "G" * 17
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260901_0005"
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


def _create_orm_schema_without_alembic_version(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from waterfall.db.base import Base; "
            "from waterfall.db.session import get_engine; "
            "from waterfall.models import User; "
            "_ = User.__tablename__; "
            "Base.metadata.create_all(get_engine())",
        ],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_prepare_legacy_schema(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "waterfall.scripts.prepare_alembic_dev_schema"],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_prepare_legacy_schema_unchecked(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "waterfall.scripts.prepare_alembic_dev_schema"],
        cwd=BACKEND_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_alembic_current(database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _assert_create_all_schema_can_be_stamped_by_migrate_up(database_url: str) -> None:
    from waterfall.db.base import Base
    from waterfall.scripts.prepare_alembic_dev_schema import (
        STANDARD_WEEKDAY_HOURS,
        _metadata_diffs,  # pyright: ignore[reportPrivateUsage]
    )

    _create_orm_schema_without_alembic_version(database_url)
    _run_prepare_legacy_schema(database_url)
    _run_alembic(database_url, "head")
    _run_alembic(database_url, "head")

    with _disposable_engine(database_url) as engine, engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260909_0010"
        standard = connection.execute(
            text("SELECT id, is_active, is_default FROM wf_calendar WHERE code = 'STANDARD'")
        ).one()
        assert standard[1] == 1
        assert standard[2] == 1
        weekdays = connection.execute(
            text(
                "SELECT day_type, hours_per_day FROM wf_calendar_weekday "
                "WHERE calendar_id = :calendar_id ORDER BY day_type"
            ),
            {"calendar_id": standard[0]},
        ).all()
        assert [row[0] for row in weekdays] == list(STANDARD_WEEKDAY_HOURS)
        assert [float(row[1]) for row in weekdays] == [
            float(hours) for hours in STANDARD_WEEKDAY_HOURS.values()
        ]
        _ = Base.metadata
        assert _metadata_diffs(connection) == []


def test_alembic_current_does_not_stamp_create_all_schema() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "create_all.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _create_orm_schema_without_alembic_version(database_url)
        _run_alembic_current(database_url)

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert not inspect(connection).has_table("alembic_version")


def test_legacy_prepare_returns_early_for_empty_database_when_head_constant_lags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from waterfall.scripts import prepare_alembic_dev_schema as prepare_module

    monkeypatch.setattr(prepare_module, "HEAD_REVISION", "future-head")

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "empty.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        with _disposable_engine(database_url) as engine:
            assert prepare_module.prepare_legacy_create_all_schema(engine) is None


def test_legacy_prepare_rejects_incomplete_unversioned_schema() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "partial_legacy.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260823_0001")
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))

        result = _run_prepare_legacy_schema_unchecked(database_url)

        assert result.returncode != 0
        assert "Unversioned legacy database schema is incomplete" in result.stderr


def test_legacy_prepare_rejects_complete_unsupported_schema_drift() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "unsupported_drift.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _create_orm_schema_without_alembic_version(database_url)
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(text("ALTER TABLE wf_planning DROP COLUMN note"))

        result = _run_prepare_legacy_schema_unchecked(database_url)

        assert result.returncode != 0
        assert "unsupported structural drift" in result.stderr


def test_legacy_prepare_rejects_missing_sqlite_use_alter_foreign_key() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "missing_fk.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _create_orm_schema_without_alembic_version(database_url)
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            create_sql = connection.scalar(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ms_project'")
            )
            assert isinstance(create_sql, str)
            without_reference_estimate_fk = "\n".join(
                line
                for line in create_sql.splitlines()
                if "fk_ms_project_reference_estimate" not in line
            )
            connection.execute(text("ALTER TABLE ms_project RENAME TO ms_project_old"))
            connection.execute(text(without_reference_estimate_fk))
            connection.execute(text("DROP TABLE ms_project_old"))

        result = _run_prepare_legacy_schema_unchecked(database_url)

        assert result.returncode != 0
        assert "unsupported structural drift" in result.stderr


def test_legacy_prepare_reuses_empty_alembic_version_table() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "empty_version.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _create_orm_schema_without_alembic_version(database_url)
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE alembic_version ("
                    "version_num VARCHAR(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                    ")"
                )
            )

        _run_prepare_legacy_schema(database_url)
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0010"
            )


def test_create_all_schema_before_planning_revision_is_repaired_then_migrated() -> None:
    """Simulates an unversioned legacy database whose schema matches head except for
    the one gap `_only_missing_planning_revision` specifically recognizes and
    repairs: a missing `wf_planning.revision` column (added by migration
    20260903_0006). Recovery now applies that column directly and stamps straight to
    `HEAD_REVISION` (see `_add_missing_planning_revision_column`) rather than
    stamping to an intermediate revision and replaying every migration since --
    `Base.metadata.create_all` always builds *today's* full schema, so replaying a
    later, purely additive migration (e.g. #116's pagination indexes) against it
    would fail trying to recreate objects that already exist.
    """
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "create_all_before_revision.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _create_orm_schema_without_alembic_version(database_url)
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(text("ALTER TABLE wf_planning DROP COLUMN revision"))

        _run_prepare_legacy_schema(database_url)
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0010"
            )
            planning_columns = {
                column["name"] for column in inspect(connection).get_columns("wf_planning")
            }
            assert "revision" in planning_columns
            assert (
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM wf_calendar "
                        "WHERE code = 'STANDARD' AND is_default = true"
                    )
                )
                == 1
            )


def test_create_all_recovery_does_not_assign_roles_to_inactive_standard_calendar() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "inactive_standard.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _create_orm_schema_without_alembic_version(database_url)
        with _disposable_engine(database_url) as engine, engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO wf_calendar "
                    "(id, code, name, weeks_per_year, is_active, is_default, "
                    "created_at, updated_at) "
                    "VALUES (1, 'STANDARD', 'Standard', 47, false, false, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_cost_type "
                    "(id, code, name, kind, is_active, created_at, updated_at) "
                    "VALUES (1, 'MO', 'Main d''oeuvre', 'labor', true, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_cost_category "
                    "(id, cost_type_id, accounting_code, name, is_active, created_at, updated_at) "
                    "VALUES (1, 1, 'DEV', 'Developpement', true, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_resource_node "
                    "(id, code, name, is_active, created_at, updated_at) "
                    "VALUES (1, 'IT', 'Informatique', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO wf_resource_role "
                    "(id, node_id, cost_category_id, name, is_active, created_at, updated_at) "
                    "VALUES (1, 1, 1, 'Developpeur', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        _run_prepare_legacy_schema(database_url)

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            standard = connection.execute(
                text("SELECT id, is_default FROM wf_calendar WHERE code = 'STANDARD'")
            ).one()
            assert standard[1] == 0
            assert (
                connection.scalar(text("SELECT calendar_id FROM wf_resource_role WHERE id = 1"))
                is None
            )


def test_create_all_schema_can_be_stamped_by_migrate_up() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "create_all.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _assert_create_all_schema_can_be_stamped_by_migrate_up(database_url)


def test_postgres_create_all_schema_can_be_stamped_by_migrate_up(
    postgres_database_url: str,
) -> None:
    _assert_create_all_schema_can_be_stamped_by_migrate_up(postgres_database_url)


def test_schema_revision_check_rejects_database_behind_head() -> None:
    from waterfall.db.schema_revision import (
        DatabaseSchemaRevisionError,
        assert_database_schema_current,
    )

    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "behind-head.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _run_alembic(database_url, "20260901_0005")

        with (
            _disposable_engine(database_url) as engine,
            pytest.raises(DatabaseSchemaRevisionError) as error,
        ):
            assert_database_schema_current(engine)

    assert error.value.current_revision == "20260901_0005"
    assert error.value.expected_revision == "20260909_0010"
    assert "Run `make migrate-up`" in str(error.value)


def test_api_startup_rejects_database_behind_head(monkeypatch: pytest.MonkeyPatch) -> None:
    from waterfall import main as main_module
    from waterfall.core.config import get_settings
    from waterfall.db.schema_revision import DatabaseSchemaRevisionError

    startup_error = DatabaseSchemaRevisionError("20260901_0005", "20260903_0006")

    def reject_schema_revision(_engine: object) -> None:
        raise startup_error

    async def run_lifespan() -> None:
        async with main_module.lifespan(FastAPI()):
            pass

    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    monkeypatch.setattr(main_module, "assert_database_schema_current", reject_schema_revision)

    with pytest.raises(DatabaseSchemaRevisionError, match="Run `make migrate-up`"):
        asyncio.run(run_lifespan())

    get_settings.cache_clear()


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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260909_0010"


def test_postgres_project_external_uid_accepts_canonical_guid(
    postgres_database_url: str,
) -> None:
    """PostgreSQL enforces VARCHAR lengths that SQLite ignores."""
    _run_alembic(postgres_database_url, "head")
    external_uid = "12345678-1234-1234-1234-123456789abc"

    with _disposable_engine(postgres_database_url) as engine, engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ms_project (external_uid, source_version, save_version_out, name, "
                "schedule_from_start, start_date, finish_date, minutes_per_day, "
                "minutes_per_week, days_per_month, created_at, updated_at, status) VALUES "
                "(:external_uid, 2016, 16, 'GUID import', true, '2026-01-01', '2026-12-31', "
                "480, 2400, 20, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'cree')"
            ),
            {"external_uid": external_uid},
        )

        assert connection.scalar(text("SELECT external_uid FROM ms_project")) == external_uid


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


def test_postgres_estimate_line_role_code_accepts_long_role_name(
    postgres_database_url: str,
) -> None:
    """Empirical regression test for #46's original bug: validating an estimate whose
    role name exceeds 64 characters used to raise an uncaught DataError, because
    wf_estimate_line.role_code was String(64) while it is derived from
    ResourceRole.name (String(255)) in
    waterfall.services.estimate_calculation._generate_labor_lines.

    SQLite does not enforce VARCHAR length, so only a real PostgreSQL run can prove the
    widened column (String(255), see the 20260831_0003 migration) actually accepts and
    stores a long role name without truncation or error."""
    _run_alembic(postgres_database_url, "head")

    long_role_name = "R" * 200  # well past the pre-fix 64-char limit, within the new 255
    assert len(long_role_name) == 200

    # Must not raise psycopg.errors.DataError / sqlalchemy.exc.DataError.
    _seed_estimate_line(postgres_database_url, role_code=long_role_name, role_name=long_role_name)

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        stored_role_code = connection.scalar(text("SELECT role_code FROM wf_estimate_line"))
        assert stored_role_code == long_role_name
        assert len(stored_role_code) == 200


def _seed_project_at_revision(
    database_url: str, revision: str, *, name: str, code: str | None
) -> int:
    """Seed a minimal `ms_project` row via the ORM on a database already migrated to
    `revision`, and return its id. Used to seed a project *before* the
    20260909_0009 migration runs, so its backfill logic has a pre-existing row to
    act on."""
    from sqlalchemy.orm import Session

    from waterfall.models.ms_core import MsProject

    _run_alembic(database_url, revision)
    with _disposable_engine(database_url) as engine, Session(engine) as session:
        project = MsProject(
            source_version=2016,
            save_version_out=16,
            name=name,
            code=code,
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add(project)
        session.commit()
        return project.id


def test_project_cost_code_migration_backfills_root_from_code_and_prj_fallback() -> None:
    """Issue #62 (E6-01): the 20260909_0009 migration creates wf_project_cost_code and
    backfills a root cost code for every pre-existing project, using project.code when
    set or the deterministic PRJ-{id} fallback when it is NULL."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        project_with_code_id = _seed_project_at_revision(
            database_url, "20260908_0008", name="Projet Avec Code", code="PRJ-042"
        )
        project_without_code_id = _seed_project_at_revision(
            database_url, "20260908_0008", name="Projet Sans Code", code=None
        )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
            assert "wf_project_cost_code" in table_names

            with_code_row = connection.execute(
                text(
                    "SELECT parent_id, code, name FROM wf_project_cost_code WHERE project_id = :id"
                ),
                {"id": project_with_code_id},
            ).one()
            assert with_code_row[0] is None
            assert with_code_row[1] == "PRJ-042"
            assert with_code_row[2] == "Projet Avec Code"

            without_code_row = connection.execute(
                text(
                    "SELECT parent_id, code, name FROM wf_project_cost_code WHERE project_id = :id"
                ),
                {"id": project_without_code_id},
            ).one()
            assert without_code_row[0] is None
            assert without_code_row[1] == f"PRJ-{project_without_code_id}"

            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0010"
            )


def test_project_cost_code_migration_enforces_one_root_per_project() -> None:
    """The partial unique index (project_id, WHERE parent_id IS NULL) must reject a
    second root row for a project that already has one -- including the backfilled
    root inserted by this same migration."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        project_id = _seed_project_at_revision(
            database_url, "20260908_0008", name="Projet Unique Root", code="PRJ-ROOT"
        )
        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            with pytest.raises(Exception, match="UNIQUE constraint failed"):
                connection.execute(
                    text(
                        "INSERT INTO wf_project_cost_code (project_id, parent_id, code, name, "
                        "is_active, created_at, updated_at) VALUES (:project_id, NULL, "
                        "'DUP-ROOT', 'Second racine', 1, '2026-01-01 00:00:00', "
                        "'2026-01-01 00:00:00')"
                    ),
                    {"project_id": project_id},
                )
            connection.rollback()


def test_project_cost_code_migration_is_reversible() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _seed_project_at_revision(
            database_url, "20260908_0008", name="Projet Reversible", code="PRJ-REV"
        )
        _run_alembic(database_url, "head")
        _downgrade_alembic(database_url, "20260908_0008")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
            assert "wf_project_cost_code" not in table_names
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260908_0008"
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
            assert "wf_project_cost_code" in table_names
            # Re-upgrading after a downgrade-then-upgrade round trip re-runs the
            # backfill against the still-existing project row, so it must not be
            # duplicated or lost.
            row_count = connection.scalar(text("SELECT COUNT(*) FROM wf_project_cost_code"))
            assert row_count == 1


def test_postgres_project_cost_code_migration_backfill_and_downgrade(
    postgres_database_url: str,
) -> None:
    """PostgreSQL variant of the project cost code migration round trip, covering the
    partial-index syntax difference (postgresql_where vs sqlite_where) on a real
    PostgreSQL dialect."""
    project_with_code_id = _seed_project_at_revision(
        postgres_database_url, "20260908_0008", name="Projet PG Avec Code", code="PRJ-PG-1"
    )
    project_without_code_id = _seed_project_at_revision(
        postgres_database_url, "20260908_0008", name="Projet PG Sans Code", code=None
    )

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        with_code_row = connection.execute(
            text("SELECT parent_id, code FROM wf_project_cost_code WHERE project_id = :id"),
            {"id": project_with_code_id},
        ).one()
        assert with_code_row[0] is None
        assert with_code_row[1] == "PRJ-PG-1"

        without_code_row = connection.execute(
            text("SELECT parent_id, code FROM wf_project_cost_code WHERE project_id = :id"),
            {"id": project_without_code_id},
        ).one()
        assert without_code_row[1] == f"PRJ-{project_without_code_id}"

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        with pytest.raises(Exception, match="uq_wf_project_cost_code_single_root"):
            connection.execute(
                text(
                    "INSERT INTO wf_project_cost_code (project_id, parent_id, code, name, "
                    "is_active, created_at, updated_at) VALUES (:project_id, NULL, "
                    "'DUP-ROOT-PG', 'Second racine', true, now(), now())"
                ),
                {"project_id": project_with_code_id},
            )
        connection.rollback()

    _downgrade_alembic(postgres_database_url, "20260908_0008")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        assert "wf_project_cost_code" not in table_names

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        table_names = set(inspect(connection).get_table_names())
        assert "wf_project_cost_code" in table_names


def _seed_project_root_and_cost_lines_at_revision(
    database_url: str, revision: str, *, project_name: str
) -> dict[str, int]:
    """Seed a project with its root cost code, plus one pre-existing
    `wf_task_role_assignment` row, one `wf_estimate_cost_line` row, and one
    `wf_estimate_line` row -- so the 20260909_0010 migration's backfill (or
    deliberate non-backfill, for `wf_estimate_line`) has real pre-existing rows to
    act on. Returns the ids needed to assert on after upgrading to head.

    The three rows about to gain `cost_code_id` in 20260909_0010 are inserted via
    plain `sa.table()` Core proxies scoped to the columns that exist at `revision`
    (deliberately excluding `cost_code_id`) rather than via the current ORM models,
    which already declare that column and would otherwise emit an INSERT referencing
    a column this pre-migration schema does not have yet -- the same technique
    `_seed_estimate_line` and the 20260909_0009 migration itself use elsewhere in
    this file for schema-shape-sensitive seeding.
    """
    from sqlalchemy.orm import Session

    from waterfall.models.ms_core import MsProject, MsTask
    from waterfall.models.resources import (
        CostCategory,
        CostType,
        Estimate,
        ProjectCostCode,
        ResourceNode,
        ResourceRole,
    )

    _run_alembic(database_url, revision)
    with _disposable_engine(database_url) as engine, Session(engine) as session:
        project = MsProject(
            source_version=2016,
            save_version_out=16,
            name=project_name,
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add(project)
        session.flush()

        # The root cost code is normally auto-created by POST /projects (or backfilled
        # by 20260909_0009 for rows that predate it) -- neither applies to a project
        # inserted directly at an already-migrated revision, so it is seeded here too.
        root = ProjectCostCode(
            project_id=project.id, parent_id=None, code=f"PRJ-{project.id}", name=project_name
        )
        session.add(root)
        session.flush()

        cost_type = CostType(code="MO", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()
        cost_category = CostCategory(
            cost_type_id=cost_type.id, accounting_code="DEV", name="Developpement"
        )
        session.add(cost_category)
        session.flush()
        node = ResourceNode(code="IT", name="Informatique")
        session.add(node)
        session.flush()
        role = ResourceRole(node_id=node.id, cost_category_id=cost_category.id, name="Dev")
        session.add(role)
        session.flush()

        task = MsTask(project_id=project.id, uid=1, name="Task")
        session.add(task)
        session.flush()

        estimate = Estimate(
            project_id=project.id, version_number=1, kind="initial", currency_code="EUR"
        )
        session.add(estimate)
        session.flush()

        session.commit()
        project_id = project.id
        root_id = root.id
        cost_type_id = cost_type.id
        cost_category_id = cost_category.id
        role_id = role.id
        task_id = task.id
        estimate_id = estimate.id

    now = datetime.now(UTC)
    task_role_assignment_table = sa.table(
        "wf_task_role_assignment",
        sa.column("id", sa.Integer),
        sa.column("task_id", sa.Integer),
        sa.column("role_id", sa.Integer),
        sa.column("quantity", sa.Numeric(10, 2)),
        sa.column("hours", sa.Numeric(14, 2)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    estimate_cost_line_table = sa.table(
        "wf_estimate_cost_line",
        sa.column("id", sa.Integer),
        sa.column("estimate_id", sa.Integer),
        sa.column("cost_type_id", sa.Integer),
        sa.column("cost_category_id", sa.Integer),
        sa.column("cost_type_code", sa.String),
        sa.column("accounting_code", sa.String),
        sa.column("label", sa.String),
        sa.column("quantity", sa.Numeric(14, 2)),
        sa.column("unit_cost", sa.Numeric(16, 2)),
        sa.column("purchase_cost", sa.Numeric(16, 2)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    estimate_line_table = sa.table(
        "wf_estimate_line",
        sa.column("id", sa.Integer),
        sa.column("estimate_id", sa.Integer),
        sa.column("role_id", sa.Integer),
        sa.column("task_name", sa.String),
        sa.column("role_code", sa.String),
        sa.column("role_name", sa.String),
        sa.column("accounting_code", sa.String),
        sa.column("year", sa.Integer),
        sa.column("quantity", sa.Numeric(10, 2)),
        sa.column("hours", sa.Numeric(14, 2)),
        sa.column("hourly_rate", sa.Numeric(14, 4)),
        sa.column("inflation_coefficient", sa.Numeric(12, 8)),
        sa.column("budget_cost", sa.Numeric(16, 2)),
    )

    with _disposable_engine(database_url) as engine, engine.begin() as connection:
        assignment_id = connection.execute(
            sa.insert(task_role_assignment_table)
            .values(
                task_id=task_id,
                role_id=role_id,
                quantity=Decimal("1"),
                hours=Decimal("1"),
                created_at=now,
                updated_at=now,
            )
            .returning(task_role_assignment_table.c.id)
        ).scalar_one()
        cost_line_id = connection.execute(
            sa.insert(estimate_cost_line_table)
            .values(
                estimate_id=estimate_id,
                cost_type_id=cost_type_id,
                cost_category_id=cost_category_id,
                cost_type_code="MO",
                accounting_code="DEV",
                label="Ligne",
                quantity=Decimal("1"),
                unit_cost=Decimal("1"),
                purchase_cost=Decimal("1"),
                created_at=now,
                updated_at=now,
            )
            .returning(estimate_cost_line_table.c.id)
        ).scalar_one()
        estimate_line_id = connection.execute(
            sa.insert(estimate_line_table)
            .values(
                estimate_id=estimate_id,
                role_id=role_id,
                task_name="Task",
                role_code="Dev",
                role_name="Dev",
                accounting_code="DEV",
                year=2026,
                quantity=Decimal("1"),
                hours=Decimal("1"),
                hourly_rate=Decimal("1"),
                inflation_coefficient=Decimal("1"),
                budget_cost=Decimal("1"),
            )
            .returning(estimate_line_table.c.id)
        ).scalar_one()

    return {
        "root_cost_code_id": root_id,
        "assignment_id": assignment_id,
        "cost_line_id": cost_line_id,
        "estimate_line_id": estimate_line_id,
        "project_id": project_id,
    }


def test_cost_line_cost_code_migration_backfills_lines_but_not_estimate_line() -> None:
    """Issue #63 (E6-02): the 20260909_0010 migration backfills `cost_code_id` on
    pre-existing `wf_task_role_assignment`/`wf_estimate_cost_line` rows to their
    project's active root cost code, and deliberately leaves the frozen
    `wf_estimate_line` snapshot untouched (NULL) -- see the migration's own docstring
    for why it cannot be reconstructed after the fact."""
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        ids = _seed_project_root_and_cost_lines_at_revision(
            database_url, "20260909_0009", project_name="Projet Backfill Lignes"
        )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT cost_code_id FROM wf_task_role_assignment WHERE id = :id"),
                    {"id": ids["assignment_id"]},
                )
                == ids["root_cost_code_id"]
            )
            assert (
                connection.scalar(
                    text("SELECT cost_code_id FROM wf_estimate_cost_line WHERE id = :id"),
                    {"id": ids["cost_line_id"]},
                )
                == ids["root_cost_code_id"]
            )
            assert (
                connection.scalar(
                    text("SELECT cost_code_id FROM wf_estimate_line WHERE id = :id"),
                    {"id": ids["estimate_line_id"]},
                )
                is None
            )


def test_cost_line_cost_code_migration_is_reversible() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _seed_project_root_and_cost_lines_at_revision(
            database_url, "20260909_0009", project_name="Projet Reversible Lignes"
        )
        _run_alembic(database_url, "head")
        _downgrade_alembic(database_url, "20260909_0009")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            for table_name in (
                "wf_task_role_assignment",
                "wf_estimate_cost_line",
                "wf_estimate_line",
            ):
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                assert "cost_code_id" not in columns
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260909_0009"
            )

        _run_alembic(database_url, "head")

        with _disposable_engine(database_url) as engine, engine.connect() as connection:
            inspector = inspect(connection)
            for table_name in (
                "wf_task_role_assignment",
                "wf_estimate_cost_line",
                "wf_estimate_line",
            ):
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                assert "cost_code_id" in columns


def test_postgres_cost_line_cost_code_migration_backfill_and_downgrade(
    postgres_database_url: str,
) -> None:
    """PostgreSQL variant of the cost-line cost-code migration round trip."""
    ids = _seed_project_root_and_cost_lines_at_revision(
        postgres_database_url, "20260909_0009", project_name="Projet PG Backfill Lignes"
    )

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT cost_code_id FROM wf_task_role_assignment WHERE id = :id"),
                {"id": ids["assignment_id"]},
            )
            == ids["root_cost_code_id"]
        )
        assert (
            connection.scalar(
                text("SELECT cost_code_id FROM wf_estimate_cost_line WHERE id = :id"),
                {"id": ids["cost_line_id"]},
            )
            == ids["root_cost_code_id"]
        )
        assert (
            connection.scalar(
                text("SELECT cost_code_id FROM wf_estimate_line WHERE id = :id"),
                {"id": ids["estimate_line_id"]},
            )
            is None
        )

    _downgrade_alembic(postgres_database_url, "20260909_0009")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        inspector = inspect(connection)
        for table_name in ("wf_task_role_assignment", "wf_estimate_cost_line", "wf_estimate_line"):
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert "cost_code_id" not in columns

    _run_alembic(postgres_database_url, "head")

    with _disposable_engine(postgres_database_url) as engine, engine.connect() as connection:
        inspector = inspect(connection)
        for table_name in ("wf_task_role_assignment", "wf_estimate_cost_line", "wf_estimate_line"):
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert "cost_code_id" in columns
