from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import Connection

from waterfall.core.config import get_settings
from waterfall.db.base import Base
from waterfall.db.schema_revision import get_alembic_config_path
from waterfall.models import User

HEAD_REVISION = "20260903_0006"
REVISION_BEFORE_PLANNING_REVISION = "20260901_0005"
STANDARD_CALENDAR_CODE = "STANDARD"
STANDARD_WEEKDAY_HOURS = {
    1: Decimal("0.00"),
    2: Decimal("7.00"),
    3: Decimal("7.00"),
    4: Decimal("7.00"),
    5: Decimal("7.00"),
    6: Decimal("7.00"),
    7: Decimal("0.00"),
}


def _expected_head_revision() -> str:
    alembic_config = Config(str(get_alembic_config_path()))
    head_revision = ScriptDirectory.from_config(alembic_config).get_current_head()
    if head_revision is None:
        raise RuntimeError("Alembic head revision could not be resolved.")
    return head_revision


def _alembic_version_exists(connection: Connection) -> bool:
    return inspect(connection).has_table("alembic_version")


def _all_application_tables_exist(connection: Connection) -> bool:
    existing_tables = set(inspect(connection).get_table_names())
    return set(Base.metadata.tables).issubset(existing_tables)


def _only_missing_planning_revision(connection: Connection) -> bool:
    migration_context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    diffs = compare_metadata(migration_context, Base.metadata)
    return (
        len(diffs) == 1
        and diffs[0][0] == "add_column"
        and diffs[0][2] == "wf_planning"
        and diffs[0][3].name == "revision"
    )


def _schema_matches_head(connection: Connection) -> bool:
    migration_context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    return compare_metadata(migration_context, Base.metadata) == []


def _ensure_standard_calendar(connection: Connection) -> int:
    now = datetime.now(UTC)
    standard_id = connection.scalar(
        text("SELECT id FROM wf_calendar WHERE code = :code"),
        {"code": STANDARD_CALENDAR_CODE},
    )
    if standard_id is None:
        connection.execute(
            text(
                "INSERT INTO wf_calendar "
                "(code, name, weeks_per_year, is_active, is_default, created_at, updated_at) "
                "VALUES (:code, 'Standard', 47, true, false, :now, :now)"
            ),
            {"code": STANDARD_CALENDAR_CODE, "now": now},
        )
        standard_id = connection.scalar(
            text("SELECT id FROM wf_calendar WHERE code = :code"),
            {"code": STANDARD_CALENDAR_CODE},
        )
    if standard_id is None:
        raise RuntimeError("Could not create or resolve the STANDARD calendar.")
    return int(standard_id)


def _repair_calendar_invariants(connection: Connection) -> None:
    standard_id = _ensure_standard_calendar(connection)
    now = datetime.now(UTC)
    for day_type, hours in STANDARD_WEEKDAY_HOURS.items():
        existing_id = connection.scalar(
            text(
                "SELECT id FROM wf_calendar_weekday "
                "WHERE calendar_id = :calendar_id AND day_type = :day_type"
            ),
            {"calendar_id": standard_id, "day_type": day_type},
        )
        if existing_id is None:
            connection.execute(
                text(
                    "INSERT INTO wf_calendar_weekday "
                    "(calendar_id, day_type, hours_per_day, created_at, updated_at) "
                    "VALUES (:calendar_id, :day_type, :hours_per_day, :now, :now)"
                ),
                {
                    "calendar_id": standard_id,
                    "day_type": day_type,
                    "hours_per_day": str(hours),
                    "now": now,
                },
            )

    default_count = connection.scalar(
        text("SELECT COUNT(*) FROM wf_calendar WHERE is_default = true")
    )
    if default_count == 0:
        connection.execute(
            text(
                "UPDATE wf_calendar SET is_default = true "
                "WHERE id = :calendar_id AND is_active = true"
            ),
            {"calendar_id": standard_id},
        )

    connection.execute(
        text("UPDATE wf_resource_role SET calendar_id = :calendar_id WHERE calendar_id IS NULL"),
        {"calendar_id": standard_id},
    )


def _stamp_revision(connection: Connection, revision: str) -> None:
    connection.execute(
        text(
            "CREATE TABLE alembic_version ("
            "version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
    )
    connection.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
        {"revision": revision},
    )


def prepare_legacy_create_all_schema(engine: Engine) -> str | None:
    _ = User.__tablename__
    expected_head = _expected_head_revision()
    if expected_head != HEAD_REVISION:
        raise RuntimeError(
            f"Update prepare_alembic_dev_schema.py for Alembic head {expected_head}."
        )

    with engine.begin() as connection:
        if _alembic_version_exists(connection) or not _all_application_tables_exist(connection):
            return None

        if _schema_matches_head(connection):
            _repair_calendar_invariants(connection)
            _stamp_revision(connection, HEAD_REVISION)
            return HEAD_REVISION

        if _only_missing_planning_revision(connection):
            _repair_calendar_invariants(connection)
            _stamp_revision(connection, REVISION_BEFORE_PLANNING_REVISION)
            return REVISION_BEFORE_PLANNING_REVISION

    return None


def main() -> None:
    engine = create_engine(get_settings().database_url)
    try:
        revision = prepare_legacy_create_all_schema(engine)
    finally:
        engine.dispose()
    if revision is not None:
        print(f"Stamped legacy create_all schema at Alembic revision {revision}.")


if __name__ == "__main__":
    main()
