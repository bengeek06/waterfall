from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, ForeignKeyConstraint, create_engine, inspect, text
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


def _alembic_revision_exists(connection: Connection) -> bool:
    if not inspect(connection).has_table("alembic_version"):
        return False
    version_count = connection.scalar(text("SELECT COUNT(*) FROM alembic_version"))
    return bool(version_count)


def _all_application_tables_exist(connection: Connection) -> bool:
    existing_tables = set(inspect(connection).get_table_names())
    return set(Base.metadata.tables).issubset(existing_tables)


def _has_application_tables(connection: Connection) -> bool:
    existing_tables = set(inspect(connection).get_table_names())
    return bool(set(Base.metadata.tables) & existing_tables)


def _only_missing_planning_revision(connection: Connection) -> bool:
    diffs = _metadata_diffs(connection)
    return (
        len(diffs) == 1
        and diffs[0][0] == "add_column"
        and diffs[0][2] == "wf_planning"
        and diffs[0][3].name == "revision"
    )


def _metadata_diffs(connection: Connection) -> list[Any]:
    migration_context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    diffs = compare_metadata(migration_context, Base.metadata)
    return [diff for diff in diffs if not _is_sqlite_use_alter_fk_diff(connection, diff)]


def _is_sqlite_use_alter_fk_diff(connection: Connection, diff: Any) -> bool:
    if connection.dialect.name != "sqlite" or not isinstance(diff, tuple) or diff[0] != "add_fk":
        return False
    constraint = cast(ForeignKeyConstraint, diff[1])
    return constraint.use_alter is True and _sqlite_foreign_key_exists(connection, constraint)


def _sqlite_foreign_key_exists(connection: Connection, constraint: ForeignKeyConstraint) -> bool:
    table_name = constraint.table.name
    quoted_table_name = connection.dialect.identifier_preparer.quote(table_name)
    rows = connection.exec_driver_sql(f"PRAGMA foreign_key_list({quoted_table_name})").mappings()
    expected_columns = [column.name for column in constraint.columns]
    expected_referred_table = constraint.elements[0].column.table.name
    expected_referred_columns = [element.column.name for element in constraint.elements]
    grouped_rows: dict[int, list[Any]] = {}
    for row in rows:
        grouped_rows.setdefault(row["id"], []).append(row)

    for group in grouped_rows.values():
        ordered_group = sorted(group, key=lambda row: row["seq"])
        if [row["from"] for row in ordered_group] != expected_columns:
            continue
        if ordered_group[0]["table"] != expected_referred_table:
            continue
        if [row["to"] for row in ordered_group] == expected_referred_columns:
            return True
    return False


def _schema_matches_head(connection: Connection) -> bool:
    return _metadata_diffs(connection) == []


def _ensure_standard_calendar(connection: Connection) -> tuple[int, bool]:
    now = datetime.now(UTC)
    standard = connection.execute(
        text("SELECT id, is_active FROM wf_calendar WHERE code = :code"),
        {"code": STANDARD_CALENDAR_CODE},
    ).one_or_none()
    if standard is None:
        connection.execute(
            text(
                "INSERT INTO wf_calendar "
                "(code, name, weeks_per_year, is_active, is_default, created_at, updated_at) "
                "VALUES (:code, 'Standard', 47, true, false, :now, :now)"
            ),
            {"code": STANDARD_CALENDAR_CODE, "now": now},
        )
        standard = connection.execute(
            text("SELECT id, is_active FROM wf_calendar WHERE code = :code"),
            {"code": STANDARD_CALENDAR_CODE},
        ).one_or_none()
    if standard is None:
        raise RuntimeError("Could not create or resolve the STANDARD calendar.")
    return int(standard[0]), bool(standard[1])


def _repair_calendar_invariants(connection: Connection) -> None:
    standard_id, standard_is_active = _ensure_standard_calendar(connection)
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

    if standard_is_active:
        connection.execute(
            text(
                "UPDATE wf_resource_role SET calendar_id = :calendar_id WHERE calendar_id IS NULL"
            ),
            {"calendar_id": standard_id},
        )


def _stamp_revision(connection: Connection, revision: str) -> None:
    if not inspect(connection).has_table("alembic_version"):
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
    with engine.begin() as connection:
        if _alembic_revision_exists(connection) or not _has_application_tables(connection):
            return None

        if not _all_application_tables_exist(connection):
            raise RuntimeError(
                "Unversioned legacy database schema is incomplete and cannot be "
                "recovered automatically. Restore a backup or stamp the known "
                "matching Alembic revision manually before running `alembic upgrade head`."
            )

        expected_head = _expected_head_revision()
        if expected_head != HEAD_REVISION:
            raise RuntimeError(
                f"Update prepare_alembic_dev_schema.py for Alembic head {expected_head}."
            )

        if _schema_matches_head(connection):
            _repair_calendar_invariants(connection)
            _stamp_revision(connection, HEAD_REVISION)
            return HEAD_REVISION

        if _only_missing_planning_revision(connection):
            _repair_calendar_invariants(connection)
            _stamp_revision(connection, REVISION_BEFORE_PLANNING_REVISION)
            return REVISION_BEFORE_PLANNING_REVISION

        raise RuntimeError(
            "Unversioned legacy database schema has unsupported structural drift and "
            "cannot be recovered automatically. Restore a backup or stamp the known "
            "matching Alembic revision manually before running `alembic upgrade head`."
        )

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
