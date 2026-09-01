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
    #
    # The backfill is deliberately scoped to `is_active = true`: an inactive STANDARD
    # row means some deployment already hit issue #51's deactivation bug before this
    # migration ran. Flagging an inactive row is_default=true would create a state the
    # API's promotion logic (update_calendar) would never allow going forward -- it
    # requires the target to be active -- and resolve_default_calendar_id only
    # considers active rows, so an inactive is_default row is worse than no default at
    # all (it looks "handled" in the data but is invisible to every runtime code path).
    # We deliberately do NOT auto-reactivate the row here either: silently flipping
    # is_active back on would override a state an admin explicitly set, which is a
    # surprising side effect for a schema migration to make. A loud warning is the
    # right level of intervention -- it leaves the decision (reactivate STANDARD, or
    # promote a different active calendar) to an operator.
    calendar_table = sa.table(
        "wf_calendar",
        sa.column("code", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_default", sa.Boolean),
    )
    connection = op.get_bind()
    result = connection.execute(
        sa.update(calendar_table)
        .where(calendar_table.c.code == "STANDARD")
        .where(calendar_table.c.is_active.is_(True))
        .values(is_default=True)
    )
    # A rowcount of 0 means either no row with code == 'STANDARD' existed at upgrade
    # time (e.g. it was already renamed or deleted before running this migration), or
    # it existed but was inactive. Neither is fatal -- resolve_default_calendar_id's
    # role calendar -> is_default calendar -> wall-clock fallback chain still degrades
    # gracefully with no default calendar -- but both silently leave the system
    # without any default, so warn loudly enough for an operator to notice and act.
    if result.rowcount == 0:
        standard_is_active = connection.execute(
            sa.select(calendar_table.c.is_active).where(calendar_table.c.code == "STANDARD")
        ).scalar_one_or_none()
        if standard_is_active is None:
            logger.warning(
                "calendar default flag backfill: no calendar with code == 'STANDARD' was "
                "found, so no calendar was flagged is_default. Promote one explicitly via "
                "PATCH /resources/calendars/{id} with is_default=true."
            )
        else:
            logger.warning(
                "calendar default flag backfill: the 'STANDARD' calendar exists but is "
                "inactive (is_active = false), so no calendar was flagged is_default. "
                "Either reactivate it or promote a different active calendar explicitly "
                "via PATCH /resources/calendars/{id} with is_default=true."
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
