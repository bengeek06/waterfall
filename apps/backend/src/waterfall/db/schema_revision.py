from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


class DatabaseSchemaRevisionError(RuntimeError):
    def __init__(self, current_revision: str | None, expected_revision: str) -> None:
        self.current_revision = current_revision
        self.expected_revision = expected_revision
        current_label = current_revision or "none"
        super().__init__(
            "Database schema revision is not current: "
            f"current={current_label}, expected={expected_revision}. "
            "Run `make migrate-up` before starting the API."
        )


def get_expected_schema_revision() -> str:
    backend_dir = Path(__file__).resolve().parents[3]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    head_revision = ScriptDirectory.from_config(alembic_config).get_current_head()
    if head_revision is None:
        raise RuntimeError("Alembic head revision could not be resolved.")
    return head_revision


def assert_database_schema_current(engine: Engine) -> None:
    expected_revision = get_expected_schema_revision()
    with engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        current_revision = migration_context.get_current_revision()

    if current_revision != expected_revision:
        raise DatabaseSchemaRevisionError(current_revision, expected_revision)