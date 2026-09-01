import random
from datetime import UTC, date, datetime, timedelta
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
    _has_any_working_day,  # pyright: ignore[reportPrivateUsage]
    compute_finish_at,
    compute_start_at,
    compute_start_at_for_finish_at_or_after,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
    resolve_default_calendar_id,
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


def test_compute_finish_at_hours_that_previously_truncated_to_zero_no_longer_hang() -> None:
    """Regression test for a confirmed infinite-loop bug: hours_per_day is
    legally as small as Decimal("0.01") (DB constraint is only 0 <= hours <=
    24), and Decimal("0.01") * 60 = 0.6 minutes/day. The previous ``int(...)``
    conversion truncated that to 0 minutes of daily capacity while
    ``_has_any_working_day`` still reported the calendar as usable (0.01 > 0
    on the raw value) -- so ``compute_finish_at``'s ``while remaining > 0``
    loop would advance ``current_date`` forever without ever consuming
    ``remaining``. ``round(...)`` instead rounds 0.6 up to a genuine 1
    minute/day capacity, so scheduling now terminates correctly (in exactly
    ``duration_minutes`` calendar days, since every day contributes 1
    minute) instead of hanging."""
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    all_days_barely_positive_hours = {day_type: Decimal("0.01") for day_type in range(1, 8)}

    finish = compute_finish_at(start, 5, all_days_barely_positive_hours)

    assert finish == datetime(2026, 1, 9, 8, 1, tzinfo=UTC)
    assert compute_working_minutes_between(start, finish, all_days_barely_positive_hours) == 5


def test_compute_finish_at_still_rejects_a_calendar_whose_capacity_rounds_to_zero() -> None:
    """Defense-in-depth companion to the above: an hours_per_day value below
    what the DB's 2-decimal-place ``Numeric(4, 2)`` column can ever legally
    store (e.g. Decimal("0.001"), which is not reachable through the API but
    could in principle reach this function through a hand-built
    ``WeekdayHours`` dict) still rounds down to 0 minutes/day. The
    minute-aware ``_has_any_working_day`` guard must still catch that case
    and raise instead of ever letting ``compute_finish_at`` spin on a
    genuinely zero-capacity day."""
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    all_days_sub_precision_hours = {day_type: Decimal("0.001") for day_type in range(1, 8)}

    with pytest.raises(ValueError, match="no working day"):
        compute_finish_at(start, 5, all_days_sub_precision_hours)


def test_compute_start_at_short_lead_fits_within_the_anchors_own_day() -> None:
    """A lead short enough to fit within the anchor's own day's remaining
    capacity must resolve to earlier that *same* day, not skip back to the
    calendar date before it.

    Regression test for a confirmed bug: an earlier version of
    :func:`compute_start_at` unconditionally started its backward walk on
    ``anchor.date() - 1 day``, so even a 60-minute lead anchored on a Monday
    morning (well within Monday's own 7h capacity) incorrectly resolved to
    the *previous* Friday instead of staying on the Monday -- burning an
    entire extra working day (and, in this case, a whole weekend) before it
    even started counting down the lead."""
    anchor = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)  # Monday

    assert compute_start_at(anchor, 60, STANDARD_HOURS) == datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def test_compute_start_at_mono_day_fits_within_the_anchors_own_days_capacity() -> None:
    """Mirror of ``test_compute_finish_at_mono_day_fits_within_one_days_capacity``:
    a lag under a single day's capacity resolves entirely within ``anchor``'s
    own calendar date -- symmetric to how :func:`compute_finish_at` makes
    ``start_at``'s own date available to consume going forward."""
    anchor = datetime(2026, 1, 6, 8, 0, tzinfo=UTC)  # Tuesday

    assert compute_start_at(anchor, 300, STANDARD_HOURS) == datetime(2026, 1, 6, 3, 0, tzinfo=UTC)


def test_compute_start_at_multi_day_lead_skips_weekend_backward() -> None:
    """A lead spanning two full working days' worth of capacity, anchored on
    a Monday, must retreat across the intervening weekend to the preceding
    Friday (consuming Monday's own capacity first, then walking backward
    through the non-working Sunday/Saturday to reach Friday), not simply
    subtract raw wall-clock time into the weekend."""
    anchor = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)  # Monday

    assert compute_start_at(anchor, 840, STANDARD_HOURS) == datetime(2026, 1, 9, 1, 0, tzinfo=UTC)
    # Friday, not Saturday/Sunday: the weekend is skipped entirely.
    assert compute_start_at(anchor, 840, STANDARD_HOURS).date() == date(2026, 1, 9)


def test_compute_start_at_multi_day_lead_anchored_on_friday_lands_on_thursday() -> None:
    """A lead spanning two full working days' worth of capacity, anchored on
    a Friday, consumes Friday's own capacity then Thursday's -- both
    weekdays, with no weekend to skip."""
    anchor = datetime(2026, 1, 9, 8, 0, tzinfo=UTC)  # Friday

    assert compute_start_at(anchor, 840, STANDARD_HOURS) == datetime(2026, 1, 8, 1, 0, tzinfo=UTC)


def test_compute_start_at_crosses_two_weekends() -> None:
    """Mirror of ``test_compute_finish_at_crosses_two_weekends``, and in fact
    its exact inverse now that ``anchor``'s own calendar date is consumed
    like any other day: retreating the same duration from
    ``compute_finish_at``'s own result lands back on that call's original
    ``start_at``."""
    anchor = datetime(2026, 1, 20, 11, 0, tzinfo=UTC)

    assert compute_start_at(anchor, 4800, STANDARD_HOURS) == datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def test_compute_start_at_zero_duration_returns_anchor_unchanged() -> None:
    anchor = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    assert compute_start_at(anchor, 0, STANDARD_HOURS) == anchor


def test_compute_start_at_rejects_negative_duration() -> None:
    anchor = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_start_at(anchor, -1, STANDARD_HOURS)


def test_compute_start_at_rejects_calendar_with_no_working_day() -> None:
    anchor = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_start_at(anchor, 100, NO_WORKING_DAY_HOURS)


def test_compute_start_at_variable_capacity_calendar_reviewer_counter_example() -> None:
    """Regression test for the 9th PR-review round's confirmed round-trip
    bug: a calendar whose working days have *different* capacities from one
    another (Monday=7h, Tuesday=4h) broke ``compute_start_at``, because an
    earlier version derived ``start_at``'s time-of-day from ``anchor.time()
    - last_day_minutes_used`` -- mixing ``anchor``'s own (Tuesday) clock time
    with a quantity of minutes actually consumed on a *different* day
    (Monday, the resulting ``start_date``), which has a different capacity.

    Walking forward from the previous (buggy) result confirms the bug: from
    ``Monday 05:00`` for 500 minutes lands on ``Tuesday 06:20``, not back on
    the original ``Tuesday 09:20`` anchor. The fix must round-trip exactly:
    ``compute_finish_at(compute_start_at(anchor, 500, cal), 500, cal) ==
    anchor``, landing on ``Monday 08:00`` (Monday's own 420-minute capacity
    consumed in full, leaving exactly 80 minutes -- not 500 minus a whole
    Monday plus a naive subtraction from Tuesday's clock time -- for
    Tuesday's truncated terminal chunk)."""
    variable_hours = {
        1: Decimal("0.00"),  # Sunday
        2: Decimal("7.00"),  # Monday
        3: Decimal("4.00"),  # Tuesday
        4: Decimal("0.00"),  # Wednesday
        5: Decimal("0.00"),  # Thursday
        6: Decimal("0.00"),  # Friday
        7: Decimal("0.00"),  # Saturday
    }
    anchor = datetime(2026, 1, 6, 9, 20, tzinfo=UTC)  # Tuesday

    start = compute_start_at(anchor, 500, variable_hours)

    assert start == datetime(2026, 1, 5, 8, 0, tzinfo=UTC)  # Monday
    assert compute_finish_at(start, 500, variable_hours) == anchor


def test_compute_start_at_variable_capacity_mono_day() -> None:
    """Mono-day case under a variable-capacity calendar: a duration short
    enough to fit within the anchor's own day's capacity resolves entirely
    within that date, same as the uniform-calendar mono-day tests above --
    pinning down that the variable-capacity fix does not regress the
    single-day path."""
    variable_hours = {
        1: Decimal("0.00"),  # Sunday
        2: Decimal("7.00"),  # Monday
        3: Decimal("4.00"),  # Tuesday
        4: Decimal("0.00"),  # Wednesday
        5: Decimal("0.00"),  # Thursday
        6: Decimal("0.00"),  # Friday
        7: Decimal("0.00"),  # Saturday
    }
    anchor = datetime(2026, 1, 6, 9, 20, tzinfo=UTC)  # Tuesday, 4h/240min capacity

    start = compute_start_at(anchor, 200, variable_hours)

    assert start == datetime(2026, 1, 6, 6, 0, tzinfo=UTC)
    assert compute_finish_at(start, 200, variable_hours) == anchor


def test_compute_start_at_variable_capacity_crosses_weekend() -> None:
    """A lead spanning several working days' worth of capacity, anchored on
    a Monday, must retreat across the intervening weekend into a preceding
    week whose working days have *different* capacities from Monday's own
    (Monday=8h, Tuesday=0h/non-working, Wed-Fri=6h each) -- exercising both
    the weekend skip and the variable-capacity fix together."""
    variable_hours = {
        1: Decimal("0.00"),  # Sunday
        2: Decimal("8.00"),  # Monday
        3: Decimal("0.00"),  # Tuesday
        4: Decimal("6.00"),  # Wednesday
        5: Decimal("6.00"),  # Thursday
        6: Decimal("6.00"),  # Friday
        7: Decimal("0.00"),  # Saturday
    }
    anchor = datetime(2026, 1, 12, 5, 0, tzinfo=UTC)  # Monday

    start = compute_start_at(anchor, 900, variable_hours)

    # Monday's own 480-minute capacity is consumed in full (non-terminal),
    # leaving 420 minutes; Tuesday (0h) and the weekend are skipped; Friday's
    # 360-minute capacity is consumed in full, leaving 60 minutes, which
    # land as Thursday's truncated terminal chunk.
    assert start == datetime(2026, 1, 8, 2, 0, tzinfo=UTC)  # Thursday
    assert compute_finish_at(start, 900, variable_hours) == anchor


def test_compute_start_at_is_the_exact_inverse_of_compute_finish_at_for_random_calendars() -> None:
    """Property-based regression test (tightened-iteration permanent version
    of the ad hoc fuzz verification run for this fix): for a broad sample of
    randomly generated calendars -- including zero-capacity (non-working)
    days and widely varying per-weekday capacities -- and randomly generated
    (start_at, duration) pairs, ``compute_start_at`` must be an *exact*
    inverse of ``compute_finish_at``:
    ``compute_finish_at(compute_start_at(finish_at, duration, cal), duration,
    cal) == finish_at`` for every combination, not merely the hand-picked
    examples above.

    ``finish_at`` is generated via ``compute_finish_at`` itself (rather than
    a fully arbitrary datetime) so every case is guaranteed reachable: a
    sufficiently sparse calendar (e.g. a single working weekday) can make an
    arbitrary anchor date genuinely unreachable by any ``compute_finish_at``
    call at all (``compute_start_at`` correctly raises ``ValueError`` for
    those, which is exercised by
    ``test_compute_start_at_rejects_an_anchor_unreachable_under_a_sparse_calendar``
    below), which is not what this property test is checking."""
    rng = random.Random(20260831)
    verified = 0
    for _ in range(200):
        weekday_hours: dict[int, Decimal] = {}
        for day_type in range(1, 8):
            if rng.random() < 0.3:
                weekday_hours[day_type] = Decimal("0.00")
            else:
                weekday_hours[day_type] = Decimal(
                    str(rng.choice([1, 2, 4, 7, 8, 10, 15, 23, 24, 0.5, 0.25]))
                )
        if not _has_any_working_day(weekday_hours):
            weekday_hours[rng.randint(1, 7)] = Decimal("6.00")

        base_date = date(2020, 1, 1) + timedelta(days=rng.randint(0, 4000))
        base_time = timedelta(minutes=rng.randint(0, 1439))
        start_at = datetime.combine(base_date, datetime.min.time(), tzinfo=UTC) + base_time
        duration_minutes = rng.randint(1, 20_000)

        try:
            finish_at = compute_finish_at(start_at, duration_minutes, weekday_hours)
        except ValueError:
            continue  # calendar walk exceeded the max-days-walked guard; not this test's concern.

        recovered_start = compute_start_at(finish_at, duration_minutes, weekday_hours)

        assert compute_finish_at(recovered_start, duration_minutes, weekday_hours) == finish_at, (
            f"round trip failed for weekday_hours={weekday_hours}, "
            f"start_at={start_at}, duration_minutes={duration_minutes}, "
            f"finish_at={finish_at}, recovered_start={recovered_start}"
        )
        verified += 1

    assert verified > 100  # sanity check that the guard-skip above didn't swallow the whole sample.


def test_compute_start_at_rejects_an_anchor_unreachable_under_a_sparse_calendar() -> None:
    """A calendar sparse enough that a given calendar date has no working
    capacity anywhere near it (here: only Mondays are ever worked) can make
    an arbitrary ``anchor`` genuinely unreachable by *any*
    ``compute_finish_at`` call, for any ``start_at`` -- since
    ``compute_finish_at`` only ever lands its result on the working
    (terminal) day's own date or the calendar date right after it.
    ``compute_start_at`` must raise ``ValueError`` in that case instead of
    silently returning an incorrect ``start_at`` that does not actually
    round-trip."""
    monday_only_hours = {
        day_type: Decimal("8.00") if day_type == 2 else Decimal("0.00") for day_type in range(1, 8)
    }
    anchor = datetime(2026, 1, 8, 12, 0, tzinfo=UTC)  # Thursday; neither it nor Wednesday works.

    with pytest.raises(ValueError, match="not reachable"):
        compute_start_at(anchor, 100, monday_only_hours)


def test_compute_start_at_for_finish_at_or_after_matches_when_exactly_reachable() -> None:
    """10th E3-03 PR review round: when ``target_finish`` is itself exactly
    reachable (the common case, and the only case before this fix), the new
    lower-bound-aware primitive must return exactly the same value as the
    plain :func:`compute_start_at` it wraps -- no behaviour change for
    already-tested FF/SF scenarios."""
    anchor = datetime(2026, 1, 12, 15, 0, tzinfo=UTC)  # Monday, exactly reachable.

    assert compute_start_at_for_finish_at_or_after(anchor, 60, STANDARD_HOURS) == compute_start_at(
        anchor, 60, STANDARD_HOURS
    )


def test_compute_start_at_for_finish_at_or_after_falls_back_to_next_working_day() -> None:
    """Regression test for the 10th E3-03 PR review round's confirmed bug:
    an FF/SF ``target_finish`` landing on a non-working day (here a Saturday,
    reachable e.g. via an elapsed-format lag that is never calendar-snapped)
    must resolve to the earliest reachable finish *at or after* it, not raise
    ``ValueError``. Same-day-of-week/time walked forward to the next Monday:
    ``compute_start_at(Monday 08:00, 60, STANDARD_HOURS)`` resolves to
    Monday 07:00, which is exactly what is returned here."""
    target_finish = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)  # Saturday.

    start_at = compute_start_at_for_finish_at_or_after(target_finish, 60, STANDARD_HOURS)

    assert start_at == datetime(2026, 1, 12, 7, 0, tzinfo=UTC)  # Monday.
    assert compute_finish_at(start_at, 60, STANDARD_HOURS) == datetime(
        2026, 1, 12, 8, 0, tzinfo=UTC
    )
    # The resulting finish is at or after the original (unreachable) target.
    assert compute_finish_at(start_at, 60, STANDARD_HOURS) >= target_finish


def test_compute_start_at_for_finish_at_or_after_walks_past_a_multi_day_non_working_stretch() -> (
    None
):
    """The forward walk is not limited to a single weekend: anchored on a
    Thursday under a Monday-only calendar (three non-working days in a row:
    Tue/Wed/Thu, plus the surrounding weekend), it must keep walking forward
    until it reaches the next Monday rather than giving up early."""
    monday_only_hours = {
        day_type: Decimal("8.00") if day_type == 2 else Decimal("0.00") for day_type in range(1, 8)
    }
    target_finish = datetime(2026, 1, 8, 12, 0, tzinfo=UTC)  # Thursday.

    start_at = compute_start_at_for_finish_at_or_after(target_finish, 100, monday_only_hours)

    assert start_at.date() == date(2026, 1, 12)  # The following Monday.
    finish_at = compute_finish_at(start_at, 100, monday_only_hours)
    assert finish_at.date() == date(2026, 1, 12)
    assert finish_at >= target_finish


def test_compute_start_at_for_finish_at_or_after_zero_duration_returns_target_unchanged() -> None:
    target_finish = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)  # Saturday; irrelevant for duration 0.

    result = compute_start_at_for_finish_at_or_after(target_finish, 0, STANDARD_HOURS)

    assert result == target_finish


def test_compute_start_at_for_finish_at_or_after_rejects_negative_duration() -> None:
    target_finish = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_start_at_for_finish_at_or_after(target_finish, -1, STANDARD_HOURS)


def test_compute_start_at_for_finish_at_or_after_rejects_calendar_with_no_working_day() -> None:
    target_finish = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        compute_start_at_for_finish_at_or_after(target_finish, 100, NO_WORKING_DAY_HOURS)


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


def test_compute_finish_at_rounding_matches_previous_truncation_for_larger_fractions() -> None:
    """Decimal("0.02") * 60 = 1.2 minutes/day, which both the previous
    ``int(...)`` truncation and the new ``round(...)`` conversion collapse to
    1 minute of daily capacity. This pins down that switching to rounding
    does not silently change already-correct behaviour above the
    Decimal("0.01") truncation edge case fixed by this regression."""
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    hours = {day_type: Decimal("0.02") for day_type in range(1, 8)}

    finish = compute_finish_at(start, 1, hours)

    assert finish == datetime(2026, 1, 5, 8, 1, tzinfo=UTC)
    assert compute_working_minutes_between(start, finish, hours) == 1


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
        calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=47, is_default=True)
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


def test_resolve_default_calendar_id_is_code_independent() -> None:
    """Regression test for issue #51: the system default calendar is resolved
    purely from the ``is_default`` flag, never from a well-known ``code``
    value like ``"STANDARD"``. A calendar flagged ``is_default`` under a
    completely different code must still resolve as the default."""
    session_factory = get_session_factory()
    with session_factory() as session:
        calendar = Calendar(code="FOO", name="Foo", weeks_per_year=47, is_default=True)
        session.add(calendar)
        session.commit()
        calendar_id = calendar.id

    with session_factory() as session:
        assert resolve_default_calendar_id(session) == calendar_id


def test_resolve_default_calendar_id_ignores_standard_code_without_flag() -> None:
    """Counterpart of the test above: a calendar whose code is literally
    ``"STANDARD"`` but that is not flagged ``is_default`` must not be
    resolved as the system default."""
    session_factory = get_session_factory()
    with session_factory() as session:
        session.add(Calendar(code="STANDARD", name="Standard", weeks_per_year=47))
        session.commit()

    with session_factory() as session:
        assert resolve_default_calendar_id(session) is None


def test_resolve_calendars_for_tasks_falls_back_to_wall_clock_when_no_calendar_exists() -> None:
    project_id, _ = _create_project_with_task(uid=1)

    session_factory = get_session_factory()
    with session_factory() as session:
        resolved = resolve_calendars_for_tasks(session, project_id, {1})

    assert resolved[1].source == "wall_clock_fallback"
    assert resolved[1].calendar_id is None
    assert all(hours == Decimal(24) for hours in resolved[1].weekday_hours.values())


def test_resolve_calendars_for_tasks_resolves_role_calendar_with_minimal_legal_hours() -> None:
    """Regression test: a role calendar where every day is Decimal("0.01")
    hours -- the smallest positive value the DB's ``Numeric(4, 2)``
    ``hours_per_day`` column can legally store -- must resolve as a usable
    "role" calendar, not be discarded as if it had no working day.
    0.01 * 60 = 0.6 minutes/day, which correctly *rounds* up to a genuine 1
    minute/day capacity. Before this fix (``int(...)`` truncation instead of
    ``round(...)``), that capacity truncated to 0 minutes while still being
    reported as usable, which would have hung the first time
    ``compute_finish_at`` walked it -- this pins down that the fix resolves
    the calendar correctly instead of merely making it fall through."""
    session_factory = get_session_factory()
    with session_factory() as session:
        barely_positive_calendar = Calendar(
            code="BARELY-POSITIVE", name="Barely positive", weeks_per_year=47
        )
        session.add(barely_positive_calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(
                calendar_id=barely_positive_calendar.id,
                day_type=day_type,
                hours_per_day=Decimal("0.01"),
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
            calendar_id=barely_positive_calendar.id,
            name="Developpeur calendrier presque vide",
        )
        session.add(role)
        session.flush()
        role_id = role.id
        barely_positive_calendar_id = barely_positive_calendar.id
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

    assert resolved[1].source == "role"
    assert resolved[1].calendar_id == barely_positive_calendar_id
    assert all(hours == Decimal("0.01") for hours in resolved[1].weekday_hours.values())

    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    finish = compute_finish_at(start, 5, resolved[1].weekday_hours)
    assert finish == datetime(2026, 1, 9, 8, 1, tzinfo=UTC)


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
