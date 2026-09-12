"""The organisation's default calendar, seeded for the tests that import a planning.

Deliberately not named ``test_*.py`` (same reasoning as ``_postgres_support.py``):
pytest would otherwise collect it as a test module.

Why an import now needs one
---------------------------

Règle 1 makes the calendar a **stored attribute** of every planning facet,
initialised to the project's -- which, until a project carries an explicit
calendar of its own, is the active `wf_calendar` flagged ``is_default``. Since
E14-06 (#332) an MS Project import creates planning facets, so on an instance that
has no default calendar it is refused with the very same ``PROJECT_CALENDAR_MISSING``
(409) that ``POST /revisions/{id}/tasks`` already answers (#331). That is the
intended refusal -- a task is always schedulable (INV-15) -- and production seeds a
default calendar; a test database starts empty, hence this helper.

Idempotent on purpose: ``uq_wf_calendar_is_default_true`` allows a single default
system-wide, so a test that already seeded one gets that one back rather than a
constraint violation.
"""

from __future__ import annotations

from decimal import Decimal

from waterfall.db.session import get_session_factory
from waterfall.models.resources import Calendar, CalendarWeekday

#: Working hours of the seeded calendar: 8h Monday to Friday, nothing at the
#: weekend (``day_type`` 1 is Sunday and 7 Saturday, MS Project's convention).
WORKING_HOURS_PER_DAY = Decimal("8.00")


def ensure_default_calendar(
    *, code: str = "STANDARD", weeks_per_year: int = 52, name: str = "Standard"
) -> int:
    """Id of the active default calendar, created with its week if there is none."""
    with get_session_factory()() as session:
        existing = (
            session.query(Calendar)
            .filter(Calendar.is_default.is_(True))
            .filter(Calendar.is_active.is_(True))
            .first()
        )
        if existing is not None:
            return existing.id
        calendar = Calendar(
            code=code,
            name=name,
            weeks_per_year=weeks_per_year,
            is_active=True,
            is_default=True,
        )
        session.add(calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(
                calendar_id=calendar.id,
                day_type=day_type,
                hours_per_day=Decimal("0.00") if day_type in (1, 7) else WORKING_HOURS_PER_DAY,
            )
            for day_type in range(1, 8)
        )
        session.commit()
        return calendar.id
