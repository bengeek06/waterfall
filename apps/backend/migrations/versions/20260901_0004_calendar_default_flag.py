"""calendar default flag

Revision ID: 20260901_0004
Revises: 20260831_0003
Create Date: 2026-09-01 09:00:00.000000

"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260901_0004"
down_revision = "20260831_0003"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_wf_calendar_is_default_true"

logger = logging.getLogger(__name__)


def upgrade() -> None:
    # server_default is required here only to satisfy NOT NULL against existing rows;
    # it is dropped again below once every row has a real value, so the column ends up
    # matching the ORM model (Calendar.is_default has no server_default) and does not
    # trip the schema-drift check in test_migrations.py.
    with op.batch_alter_table("wf_calendar") as batch_op:
        batch_op.add_column(
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # is_default defaults to false for every existing row (including STANDARD) from
    # the column add itself; this backfill is what actually flips STANDARD's row to
    # true, matching the "STANDARD is always the seeded system default" invariant
    # (issue #51) instead of leaving every calendar without a default after upgrade.
    calendar_table = sa.table(
        "wf_calendar",
        sa.column("code", sa.String),
        sa.column("is_default", sa.Boolean),
    )
    connection = op.get_bind()
    result = connection.execute(
        sa.update(calendar_table).where(calendar_table.c.code == "STANDARD").values(is_default=True)
    )
    # A rowcount of 0 means no row with code == 'STANDARD' existed at upgrade time (e.g.
    # it was already renamed or deleted before running this migration). That is not
    # fatal -- resolve_default_calendar_id's role calendar -> is_default calendar ->
    # wall-clock fallback chain still degrades gracefully with no default calendar --
    # but it silently leaves the system without any default, so warn loudly enough for
    # an operator to notice and promote one explicitly (PATCH is_default=true).
    if result.rowcount == 0:
        logger.warning(
            "calendar default flag backfill: no calendar with code == 'STANDARD' was "
            "found, so no calendar was flagged is_default. Promote one explicitly via "
            "PATCH /resources/calendars/{id} with is_default=true."
        )

    with op.batch_alter_table("wf_calendar") as batch_op:
        batch_op.alter_column("is_default", existing_type=sa.Boolean(), server_default=None)

    op.create_index(
        INDEX_NAME,
        "wf_calendar",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="wf_calendar")

    with op.batch_alter_table("wf_calendar") as batch_op:
        batch_op.drop_column("is_default")
