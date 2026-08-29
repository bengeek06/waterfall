"""working calendars

Revision ID: 20260829_0002
Revises: 20260823_0001
Create Date: 2026-08-29 09:00:00.000000

"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260829_0002"
down_revision = "20260823_0001"
branch_labels = None
depends_on = None

STANDARD_CALENDAR_CODE = "STANDARD"
# MS Project DayType: 1=Sunday .. 7=Saturday; 0 hours means non working day.
STANDARD_WEEKDAY_HOURS = {
    1: Decimal("0.00"),
    2: Decimal("7.00"),
    3: Decimal("7.00"),
    4: Decimal("7.00"),
    5: Decimal("7.00"),
    6: Decimal("7.00"),
    7: Decimal("0.00"),
}


def upgrade() -> None:
    op.create_table(
        "wf_calendar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("weeks_per_year", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "weeks_per_year >= 1 AND weeks_per_year <= 53",
            name="ck_wf_calendar_weeks_per_year",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_wf_calendar_code"),
    )
    op.create_table(
        "wf_calendar_weekday",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calendar_id", sa.Integer(), nullable=False),
        sa.Column("day_type", sa.Integer(), nullable=False),
        sa.Column("hours_per_day", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "day_type >= 1 AND day_type <= 7",
            name="ck_wf_calendar_weekday_day_type",
        ),
        sa.CheckConstraint(
            "hours_per_day >= 0 AND hours_per_day <= 24",
            name="ck_wf_calendar_weekday_hours",
        ),
        sa.ForeignKeyConstraint(["calendar_id"], ["wf_calendar.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calendar_id", "day_type", name="uq_wf_calendar_weekday_day"),
    )
    op.create_index(
        "idx_wf_calendar_weekday_calendar", "wf_calendar_weekday", ["calendar_id"], unique=False
    )

    calendar_table = sa.table(
        "wf_calendar",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("weeks_per_year", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    weekday_table = sa.table(
        "wf_calendar_weekday",
        sa.column("calendar_id", sa.Integer),
        sa.column("day_type", sa.Integer),
        sa.column("hours_per_day", sa.Numeric(4, 2)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    now = datetime.now(UTC)
    connection = op.get_bind()
    connection.execute(
        sa.insert(calendar_table).values(
            code=STANDARD_CALENDAR_CODE,
            name="Standard",
            weeks_per_year=47,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    calendar_id = connection.execute(
        sa.select(calendar_table.c.id).where(calendar_table.c.code == STANDARD_CALENDAR_CODE)
    ).scalar_one()
    connection.execute(
        sa.insert(weekday_table).values(
            [
                {
                    "calendar_id": calendar_id,
                    "day_type": day_type,
                    "hours_per_day": hours,
                    "created_at": now,
                    "updated_at": now,
                }
                for day_type, hours in sorted(STANDARD_WEEKDAY_HOURS.items())
            ]
        )
    )

    with op.batch_alter_table("wf_resource_role") as batch_op:
        batch_op.add_column(sa.Column("calendar_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_wf_resource_role_calendar", "wf_calendar", ["calendar_id"], ["id"]
        )
        batch_op.create_index("idx_wf_resource_role_calendar", ["calendar_id"], unique=False)

    role_table = sa.table(
        "wf_resource_role",
        sa.column("calendar_id", sa.Integer),
    )
    connection.execute(sa.update(role_table).values(calendar_id=calendar_id))


def downgrade() -> None:
    with op.batch_alter_table("wf_resource_role") as batch_op:
        batch_op.drop_index("idx_wf_resource_role_calendar")
        batch_op.drop_constraint("fk_wf_resource_role_calendar", type_="foreignkey")
        batch_op.drop_column("calendar_id")

    op.drop_index("idx_wf_calendar_weekday_calendar", table_name="wf_calendar_weekday")
    op.drop_table("wf_calendar_weekday")
    op.drop_table("wf_calendar")
