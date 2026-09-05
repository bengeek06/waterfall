from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy import inspect as inspect_database
from sqlalchemy.engine import Connection

from waterfall.core.config import get_settings
from waterfall.db.base import Base
from waterfall.models import User

config = context.config
settings = get_settings()

config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_ = User
target_metadata = Base.metadata


def _stamp_existing_head_schema(connection: Connection) -> None:
    inspector = inspect_database(connection)
    if inspector.has_table("alembic_version"):
        connection.rollback()
        return

    application_tables = set(target_metadata.tables)
    existing_tables = set(inspector.get_table_names())
    if not application_tables.issubset(existing_tables):
        connection.rollback()
        return

    migration_context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    if compare_metadata(migration_context, target_metadata) != []:
        connection.rollback()
        return

    head_revision = ScriptDirectory.from_config(config).get_current_head()
    if head_revision is None:
        connection.rollback()
        return

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
        {"revision": head_revision},
    )
    connection.commit()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _stamp_existing_head_schema(connection)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
