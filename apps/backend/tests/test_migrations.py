from __future__ import annotations

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
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
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

            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260903_0006"
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
                == "20260903_0006"
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
    from waterfall.db.base import Base
    from waterfall.models import User

    _ = User.__tablename__
    with _disposable_engine(database_url) as engine:
        Base.metadata.create_all(engine)


def _assert_create_all_schema_can_be_stamped_by_migrate_up(database_url: str) -> None:
    from waterfall.db.base import Base

    _create_orm_schema_without_alembic_version(database_url)
    _run_alembic(database_url, "head")
    _run_alembic(database_url, "head")

    with _disposable_engine(database_url) as engine, engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260903_0006"
        migration_context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(migration_context, Base.metadata) == []


def test_create_all_schema_can_be_stamped_by_migrate_up() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "create_all.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        _assert_create_all_schema_can_be_stamped_by_migrate_up(database_url)


def test_postgres_create_all_schema_can_be_stamped_by_migrate_up(
    postgres_database_url: str,
) -> None:
    _assert_create_all_schema_can_be_stamped_by_migrate_up(postgres_database_url)


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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260903_0006"


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
