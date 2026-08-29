from datetime import UTC, datetime
from decimal import Decimal

import pytest

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    Calendar,
    CalendarWeekday,
    CostCategory,
    CostType,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.services.calendar_schedule import (
    compute_finish_at,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
)

STANDARD_HOURS = {
    day_type: Decimal("0.00") if day_type in (1, 7) else Decimal("7.00") for day_type in range(1, 8)
}
NO_WORKING_DAY_HOURS = {day_type: Decimal("0.00") for day_type in range(1, 8)}


def test_compute_finish_at_mono_day_fits_within_one_days_capacity() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    assert compute_finish_at(start, 300, STANDARD_HOURS) == datetime(2026, 1, 5, 13, 0, tzinfo=UTC)


def test_compute_finish_at_crosses_two_weekends() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    assert compute_finish_at(start, 4800, STANDARD_HOURS) == datetime(
        2026, 1, 20, 11, 0, tzinfo=UTC
    )


def test_compute_finish_at_skips_non_working_days() -> None:
    start = datetime(2026, 1, 9, 8, 0, tzinfo=UTC)

    assert compute_finish_at(start, 840, STANDARD_HOURS) == datetime(2026, 1, 12, 15, 0, tzinfo=UTC)


def test_compute_finish_at_zero_duration_returns_start_unchanged() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    assert compute_finish_at(start, 0, STANDARD_HOURS) == start


def test_compute_finish_at_rejects_negative_duration() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_finish_at(start, -1, STANDARD_HOURS)


def test_compute_finish_at_rejects_calendar_with_no_working_day() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_finish_at(start, 100, NO_WORKING_DAY_HOURS)


def test_compute_working_minutes_between_caps_finish_day_at_its_own_capacity() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    finish = datetime(2026, 1, 7, 8, 0, tzinfo=UTC)

    # Monday 08:00-15:00 and Tuesday 08:00-15:00 are both fully inside the
    # range (2 * 420 = 840). Wednesday's shift window is [08:00, 15:00), but
    # finish_at is exactly Wednesday 08:00, so there is zero overlap on
    # Wednesday: 840, not a full extra partial day.
    assert compute_working_minutes_between(start, finish, STANDARD_HOURS) == 840


def test_compute_working_minutes_between_credits_exactly_the_elapsed_minutes_same_day() -> None:
    """Regression test: a short same-day span must not be credited a full
    day's capacity (previously returned 420 for a 1-minute span)."""
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    finish = datetime(2026, 1, 5, 8, 1, tzinfo=UTC)

    assert compute_working_minutes_between(start, finish, STANDARD_HOURS) == 1


@pytest.mark.parametrize("duration_minutes", [300, 3120])
def test_compute_working_minutes_between_is_the_inverse_of_compute_finish_at(
    duration_minutes: int,
) -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    finish = compute_finish_at(start, duration_minutes, STANDARD_HOURS)

    assert compute_working_minutes_between(start, finish, STANDARD_HOURS) == duration_minutes


def test_compute_working_minutes_between_skips_weekend() -> None:
    start = datetime(2026, 1, 8, 8, 0, tzinfo=UTC)
    finish = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)

    assert compute_working_minutes_between(start, finish, STANDARD_HOURS) == 840


def test_compute_working_minutes_between_returns_zero_when_finish_not_after_start() -> None:
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    assert compute_working_minutes_between(start, start, STANDARD_HOURS) == 0
    assert compute_working_minutes_between(start, start.replace(hour=7), STANDARD_HOURS) == 0


@pytest.mark.parametrize(
    ("start", "finish"),
    [
        # Same-day short span.
        (datetime(2026, 1, 5, 9, 17, tzinfo=UTC), datetime(2026, 1, 5, 14, 42, tzinfo=UTC)),
        # Multi-day span, start_at not at midnight.
        (datetime(2026, 1, 5, 8, 0, tzinfo=UTC), datetime(2026, 1, 7, 8, 0, tzinfo=UTC)),
        # Span crossing a weekend boundary (irrelevant under a 24h/day
        # calendar since every day is "working", but exercises the day-walk
        # loop across a boundary that matters for other calendars).
        (datetime(2026, 1, 8, 17, 30, tzinfo=UTC), datetime(2026, 1, 12, 6, 15, tzinfo=UTC)),
        # Large multi-week span.
        (datetime(2026, 1, 1, 23, 45, tzinfo=UTC), datetime(2026, 2, 20, 3, 10, tzinfo=UTC)),
    ],
)
def test_compute_working_minutes_between_matches_wall_clock_diff_under_24h_calendar(
    start: datetime, finish: datetime
) -> None:
    """A uniform 24h/day calendar (what the "wall_clock_fallback" tier uses)
    must be mathematically equivalent to the raw wall-clock difference,
    regardless of start_at's time-of-day: each day's shift window tiles
    exactly 24h back-to-back starting from start_at's clock time, so the
    per-day overlap sum always collapses back to the literal elapsed time.
    This is what lets planning_tree._recalculate_summary_fields route every
    ResolvedCalendar source (including "wall_clock_fallback") through
    compute_working_minutes_between via a single code path."""
    wall_clock_hours = {day_type: Decimal(24) for day_type in range(1, 8)}

    assert compute_working_minutes_between(start, finish, wall_clock_hours) == int(
        (finish - start).total_seconds() // 60
    )


def _create_standard_calendar() -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=47)
        session.add(calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(
                calendar_id=calendar.id,
                day_type=day_type,
                hours_per_day=Decimal("0.00") if day_type in (1, 7) else Decimal("7.00"),
            )
            for day_type in range(1, 8)
        )
        session.commit()
        return calendar.id


def _create_project_with_task(uid: int) -> tuple[int, int]:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Calendar schedule resolution test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, 8, tzinfo=UTC),
            finish_date=datetime(2026, 1, 31, 18, tzinfo=UTC),
            calendar_uid=None,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()
        task = MsTask(project_id=project.id, uid=uid, name="Task without a role assignment")
        session.add(task)
        session.commit()
        return project.id, task.id


def test_resolve_calendars_for_tasks_falls_back_to_default_standard_calendar() -> None:
    calendar_id = _create_standard_calendar()
    project_id, _ = _create_project_with_task(uid=1)

    session_factory = get_session_factory()
    with session_factory() as session:
        resolved = resolve_calendars_for_tasks(session, project_id, {1})

    assert resolved[1].source == "default"
    assert resolved[1].calendar_id == calendar_id
    assert resolved[1].weekday_hours == STANDARD_HOURS


def test_resolve_calendars_for_tasks_falls_back_to_wall_clock_when_no_calendar_exists() -> None:
    project_id, _ = _create_project_with_task(uid=1)

    session_factory = get_session_factory()
    with session_factory() as session:
        resolved = resolve_calendars_for_tasks(session, project_id, {1})

    assert resolved[1].source == "wall_clock_fallback"
    assert resolved[1].calendar_id is None
    assert all(hours == Decimal(24) for hours in resolved[1].weekday_hours.values())


def test_resolve_calendars_for_tasks_falls_through_when_role_calendar_has_no_working_day() -> None:
    """A calendar with zero configured working days must not be reported as
    a usable "role" resolution: it would silently zero out every duration
    computed from it. With no STANDARD calendar in the DB either, this must
    fall all the way through to the wall-clock tier."""
    session_factory = get_session_factory()
    with session_factory() as session:
        empty_calendar = Calendar(code="EMPTY", name="Empty", weeks_per_year=47)
        session.add(empty_calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(
                calendar_id=empty_calendar.id,
                day_type=day_type,
                hours_per_day=Decimal("0.00"),
            )
            for day_type in range(1, 8)
        )

        cost_type = CostType(code="MO", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code="DEV",
            category_code="IDEX",
            name="Developpement",
        )
        node = ResourceNode(code="IT", name="Departement informatique")
        session.add_all([category, node])
        session.flush()
        role = ResourceRole(
            node_id=node.id,
            cost_category_id=category.id,
            calendar_id=empty_calendar.id,
            code="DEV-EMPTY",
            name="Developpeur calendrier vide",
        )
        session.add(role)
        session.flush()
        role_id = role.id
        session.commit()

    project_id, task_id = _create_project_with_task(uid=1)

    with session_factory() as session:
        session.add(
            TaskRoleAssignment(
                task_id=task_id,
                role_id=role_id,
                quantity=Decimal("1.00"),
                hours=Decimal("10.00"),
            )
        )
        session.commit()

    with session_factory() as session:
        resolved = resolve_calendars_for_tasks(session, project_id, {1})

    assert resolved[1].source == "wall_clock_fallback"
    assert resolved[1].calendar_id is None
    assert all(hours == Decimal(24) for hours in resolved[1].weekday_hours.values())
