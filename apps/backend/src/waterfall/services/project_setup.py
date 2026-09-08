"""Issue #109: global setup-prerequisite checks surfaced to the frontend
before a project is created (``GET /projects/setup-warnings``).

Checks exactly the 3 prerequisites the issue lists as meaningfully
verifiable independently of any particular project:

- An active calendar flagged ``is_default`` with at least one working day
  (``hours_per_day > 0`` on at least one ``wf_calendar_weekday`` row) -- the
  one whose absence used to make :func:`waterfall.services.calendar_schedule.
  resolve_calendars_for_tasks` silently fall back to an implicit 24h/7d
  wall-clock calendar. That fallback is removed (see
  :class:`waterfall.services.calendar_schedule.NoUsableCalendarError`); this
  check is what is meant to make hitting it in normal use unreachable.
- At least one active ``CostCategory``.
- At least one active ``ResourceRole``.

``CostRate``/``InflationRate`` and ``RoleCapacity`` are deliberately not
checked here -- see the issue for why (not meaningfully verifiable before a
project has dated tasks, and not consumed by any calculation yet,
respectively).

This is purely advisory: it never blocks ``POST /projects``, it only backs a
read used by the frontend to warn the user before they create one.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.resources import Calendar, CalendarWeekday, CostCategory, ResourceRole
from waterfall.schemas.projects import ProjectSetupWarning, ProjectSetupWarningCode


def get_project_setup_warnings(db: Session) -> list[ProjectSetupWarning]:
    warnings: list[ProjectSetupWarning] = []

    default_calendar = (
        db.query(Calendar)
        .filter(Calendar.is_default.is_(True))
        .filter(Calendar.is_active.is_(True))
        .first()
    )
    if default_calendar is None:
        warnings.append(
            ProjectSetupWarning(
                code=ProjectSetupWarningCode.NO_DEFAULT_CALENDAR,
                message=(
                    "No active default calendar is configured; planning and scheduling "
                    "cannot compute calendar-aware durations without one."
                ),
            )
        )
    else:
        has_working_day = (
            db.query(CalendarWeekday)
            .filter(CalendarWeekday.calendar_id == default_calendar.id)
            .filter(CalendarWeekday.hours_per_day > 0)
            .first()
            is not None
        )
        if not has_working_day:
            warnings.append(
                ProjectSetupWarning(
                    code=ProjectSetupWarningCode.DEFAULT_CALENDAR_HAS_NO_WORKING_DAY,
                    message=(
                        "The default calendar has no working day configured; "
                        "every duration computed from it would be zero."
                    ),
                )
            )

    has_active_cost_category = (
        db.query(CostCategory).filter(CostCategory.is_active.is_(True)).first() is not None
    )
    if not has_active_cost_category:
        warnings.append(
            ProjectSetupWarning(
                code=ProjectSetupWarningCode.NO_ACTIVE_COST_CATEGORY,
                message="No active cost category is configured; estimates cannot be costed.",
            )
        )

    has_active_resource_role = (
        db.query(ResourceRole).filter(ResourceRole.is_active.is_(True)).first() is not None
    )
    if not has_active_resource_role:
        warnings.append(
            ProjectSetupWarning(
                code=ProjectSetupWarningCode.NO_ACTIVE_RESOURCE_ROLE,
                message="No active resource role is configured; tasks cannot be staffed.",
            )
        )

    return warnings
