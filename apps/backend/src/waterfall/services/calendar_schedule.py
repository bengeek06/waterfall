"""Calendar-aware duration/date scheduling (E5-04).

Resolves the working calendar that applies to a planning task from its
assigned resource role (falling back to the org-wide default ``STANDARD``
calendar, and -- only when no calendar exists in the system at all -- to an
implicit 24h/day calendar), and exposes pure duration<->dates scheduling
functions. These are used today by the summary-task duration recalculation
in :mod:`waterfall.services.planning_tree`, and are designed to be reused by
a future "automatic mode" task scheduler (E3-03, out of scope here).

Known v1 limitation: durations resolved through this module are only ever
recomputed as a side effect of a planning-tree move (``move_planning_tasks``).
Editing a calendar's weekdays, changing a role's assigned calendar, or
adding/removing a task's role assignment does not retroactively recalculate
the ``duration_minutes`` already stored on a draft planning task -- it stays
stale until the next move. This is accepted for v1 (draft-only edge case)
and is expected to be revisited by E3-03's broader scheduling rework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsTask
from waterfall.models.resources import Calendar, CalendarWeekday, ResourceRole, TaskRoleAssignment

DEFAULT_CALENDAR_CODE = "STANDARD"

WeekdayHours = dict[int, Decimal]
"""MS Project DayType (1=Sunday .. 7=Saturday) -> working hours per day."""

_WALL_CLOCK_WEEKDAY_HOURS: WeekdayHours = {day_type: Decimal(24) for day_type in range(1, 8)}


@dataclass(frozen=True)
class ResolvedCalendar:
    """The working calendar resolved for a single planning task.

    ``source`` records which tier of the E5-04 fallback chain produced this
    calendar, so callers (and tests) can assert *how* a duration was derived
    instead of only observing the resulting number:

    - ``"role"``: the calendar assigned to the resource role staffed on the
      task (lowest ``role_id`` wins when several roles are assigned, see
      :func:`resolve_task_calendar_ids`).
    - ``"default"``: no role calendar was found, but the org-wide default
      ``STANDARD`` calendar exists and was used instead.
    - ``"wall_clock_fallback"``: no calendar exists in the system at all
      (neither a role-assigned one nor ``STANDARD``); every day is treated
      as a 24h/day working day, which is the only way to keep this tier from
      inventing non-working days nobody configured.

    A calendar that resolves but has no configured working day at all (no
    ``CalendarWeekday`` rows, or every row's ``hours_per_day`` is ``0``) is
    treated as if it had not been found: :func:`resolve_calendars_for_tasks`
    falls through to the next tier instead of reporting ``"role"``/``"default"``
    with a calendar that would silently zero out every duration computed from
    it (see :func:`_has_any_working_day`).
    """

    calendar_id: int | None
    code: str
    weekday_hours: WeekdayHours
    source: Literal["role", "default", "wall_clock_fallback"]


def resolve_task_calendar_ids(db: Session, project_id: int, task_uids: set[int]) -> dict[int, int]:
    """Resolve each task's working calendar id from its role assignments.

    Originally written for MS Project XML export (E5-02), this is also used
    by E5-04's planning-tree calendar resolution (:func:`resolve_calendars_for_tasks`)
    to derive calendar-aware summary task durations -- not just XML export.

    wf_task_role_assignment always references ms_task.id (the live task table),
    never a wf_planning_task_snapshot row -- so the uid -> ms_task.id mapping is
    resolved from ms_task regardless of whether the export is reading from a
    planning snapshot or from ms_task directly.

    A task may have several roles assigned with different calendars; MS Project
    only carries a single CalendarUID per task. The issue (E5-02) does not
    settle this ambiguity, so we deterministically keep the calendar of the
    assigned role with the lowest role_id. Tasks without any role assignment,
    or whose assigned roles have no calendar, are omitted from the mapping and
    export without a Task/CalendarUID (MS Project then applies the project
    calendar, which is the standard behaviour for an unset task calendar).

    This intentionally does not filter on ResourceRole.is_active: a role
    assignment is a historical fact about how a task was staffed, and export
    determinism must not change retroactively just because the role was
    deactivated after the assignment was made.
    """
    if not task_uids:
        return {}

    uid_by_task_id: dict[int, int] = {
        task_id: uid
        for task_id, uid in db.query(MsTask.id, MsTask.uid)
        .filter(MsTask.project_id == project_id)
        .filter(MsTask.uid.in_(task_uids))
        .all()
    }
    if not uid_by_task_id:
        return {}

    rows = (
        db.query(TaskRoleAssignment.task_id, ResourceRole.calendar_id)
        .join(ResourceRole, TaskRoleAssignment.role_id == ResourceRole.id)
        .filter(TaskRoleAssignment.task_id.in_(uid_by_task_id.keys()))
        .order_by(TaskRoleAssignment.role_id.asc())
        .all()
    )

    resolved: dict[int, int] = {}
    for task_id, calendar_id in rows:
        if calendar_id is None:
            continue
        uid = uid_by_task_id[task_id]
        if uid in resolved:
            continue
        resolved[uid] = calendar_id
    return resolved


def resolve_default_calendar_id(db: Session) -> int | None:
    """Return the id of the active org-wide default (``STANDARD``) calendar, if any."""
    calendar = (
        db.query(Calendar)
        .filter(Calendar.code == DEFAULT_CALENDAR_CODE)
        .filter(Calendar.is_active.is_(True))
        .first()
    )
    return calendar.id if calendar is not None else None


def _day_capacity_minutes(hours: Decimal) -> int:
    """Convert an ``hours_per_day`` value to whole minutes, by rounding.

    Shared by every place that turns a ``CalendarWeekday.hours_per_day``
    value into a per-day working-minutes capacity, so the hours->minutes
    conversion only exists once. Rounding (not truncating via ``int(...)``)
    matters here: ``hours_per_day`` is legally as small as ``0.01`` (the DB
    constraint only enforces ``0 <= hours_per_day <= 24``), and
    ``int(Decimal("0.01") * 60)`` truncates to ``0`` even though the value is
    a genuine, non-zero working day. A day capacity of ``0`` minutes for a
    day that ``_has_any_working_day`` reports as "working" is what causes
    :func:`compute_finish_at`'s ``while remaining > 0`` loop to never make
    progress -- see the regression tests guarding this in
    ``test_calendar_schedule.py``.
    """
    return round(hours * 60)


def _has_any_working_day(weekday_hours: WeekdayHours) -> bool:
    """Return whether ``weekday_hours`` has at least one day with capacity > 0.

    Capacity is evaluated in whole minutes (via :func:`_day_capacity_minutes`),
    not on the raw ``Decimal`` hours value: a hours value that is positive but
    rounds down to 0 minutes (e.g. ``Decimal("0.001")``, which is not legal
    per the DB constraint's 2-decimal precision but is defensively guarded
    against here anyway) must not be reported as "working", or callers that
    treat this as a green light to schedule with the calendar would hang.
    """
    return any(_day_capacity_minutes(hours) > 0 for hours in weekday_hours.values())


# Hard ceiling on the number of calendar days :func:`compute_finish_at` and
# :func:`compute_start_at` will walk one day at a time before giving up.
#
# ``duration_minutes`` is bounded at the schema level (see
# ``PlanningTaskScheduleUpdate.duration_minutes``'s ``le=7_884_000``, ~15
# calendar years of minutes) but that bound alone does not cap how many
# *iterations* of the day-stepping loop below actually run: duration is
# working minutes, not calendar minutes, and a legally configured calendar
# can have an arbitrarily small non-zero capacity on as little as a single
# weekday per week (``hours_per_day`` down to ``0.01``, i.e. 1 minute/day
# once rounded -- see :func:`_day_capacity_minutes`). Walking off such a
# calendar to absorb even a modest duration would need millions of loop
# iterations, long before either function's own date arithmetic would ever
# overflow -- a real latency/DoS risk independent of the duration bound.
#
# ~100 years of calendar days is generous for any legitimate planning
# horizon this system supports, while still bounding the loop to a small,
# constant number of iterations regardless of how sparse the calendar is.
_MAX_CALENDAR_DAYS_WALKED = 366 * 100


def _guard_max_days_walked(days_walked: int) -> None:
    """Abort a :func:`compute_finish_at`/:func:`compute_start_at` walk that
    has stepped through an unreasonable number of calendar days.

    Raises ``ValueError`` (not a raw loop that spins forever, or an
    unbounded-latency success) so callers -- which already translate a
    ``ValueError`` from these functions into a 400 -- surface this as an
    actionable client error instead of a slow request or a 500.
    """
    if days_walked >= _MAX_CALENDAR_DAYS_WALKED:
        raise ValueError(
            "scheduling would require walking too many calendar days "
            f"(exceeded {_MAX_CALENDAR_DAYS_WALKED} calendar days); "
            "check the calendar has enough working capacity for this duration"
        )


def resolve_calendars_for_tasks(
    db: Session, project_id: int, task_uids: set[int]
) -> dict[int, ResolvedCalendar]:
    """Batch-resolve the working calendar of every task in ``task_uids``.

    Every uid in ``task_uids`` is guaranteed an entry in the returned dict.
    Calendar weekday rows are loaded once per distinct calendar id actually
    needed (role-assigned ones plus the default), not once per task.

    A calendar with no configured working day at all (no ``CalendarWeekday``
    rows, or all of them at ``hours_per_day == 0``) is treated as if it had
    not been resolved: a role calendar with no working day falls through to
    the default ``STANDARD`` calendar, and a default calendar with no working
    day falls through to ``"wall_clock_fallback"``. This prevents an
    under-configured calendar from silently zeroing out a task's computed
    duration (see :func:`_has_any_working_day`).
    """
    if not task_uids:
        return {}

    task_calendar_ids = resolve_task_calendar_ids(db, project_id, task_uids)
    default_calendar_id = resolve_default_calendar_id(db)

    distinct_calendar_ids = set(task_calendar_ids.values())
    if default_calendar_id is not None:
        distinct_calendar_ids.add(default_calendar_id)

    calendars_by_id: dict[int, Calendar] = {}
    weekday_hours_by_calendar_id: dict[int, WeekdayHours] = {}
    if distinct_calendar_ids:
        calendars_by_id = {
            calendar.id: calendar
            for calendar in db.query(Calendar).filter(Calendar.id.in_(distinct_calendar_ids)).all()
        }
        for weekday in (
            db.query(CalendarWeekday)
            .filter(CalendarWeekday.calendar_id.in_(distinct_calendar_ids))
            .all()
        ):
            weekday_hours_by_calendar_id.setdefault(weekday.calendar_id, {})[weekday.day_type] = (
                weekday.hours_per_day
            )

    wall_clock_resolved = ResolvedCalendar(
        calendar_id=None,
        code="",
        weekday_hours=dict(_WALL_CLOCK_WEEKDAY_HOURS),
        source="wall_clock_fallback",
    )

    default_resolved: ResolvedCalendar = wall_clock_resolved
    if default_calendar_id is not None:
        default_weekday_hours = weekday_hours_by_calendar_id.get(default_calendar_id, {})
        if _has_any_working_day(default_weekday_hours):
            default_resolved = ResolvedCalendar(
                calendar_id=default_calendar_id,
                code=calendars_by_id[default_calendar_id].code,
                weekday_hours=default_weekday_hours,
                source="default",
            )

    resolved: dict[int, ResolvedCalendar] = {}
    for uid in task_uids:
        calendar_id = task_calendar_ids.get(uid)
        if calendar_id is None:
            resolved[uid] = default_resolved
            continue
        role_weekday_hours = weekday_hours_by_calendar_id.get(calendar_id, {})
        if not _has_any_working_day(role_weekday_hours):
            resolved[uid] = default_resolved
            continue
        resolved[uid] = ResolvedCalendar(
            calendar_id=calendar_id,
            code=calendars_by_id[calendar_id].code,
            weekday_hours=role_weekday_hours,
            source="role",
        )
    return resolved


def _day_type(day: date) -> int:
    """Convert a Python weekday (Monday=1..Sunday=7 via isoweekday) to MS
    Project's DayType convention (Sunday=1..Saturday=7)."""
    return (day.isoweekday() % 7) + 1


def compute_finish_at(
    start_at: datetime, duration_minutes: int, weekday_hours: WeekdayHours
) -> datetime:
    """Schedule ``duration_minutes`` of working time forward from ``start_at``."""
    if duration_minutes < 0:
        raise ValueError("duration_minutes must not be negative")
    if duration_minutes == 0:
        return start_at
    if not _has_any_working_day(weekday_hours):
        raise ValueError("calendar has no working day; scheduling would never terminate")

    remaining = duration_minutes
    current_date = start_at.date()
    last_worked_date = current_date
    last_day_minutes_used = 0
    days_walked = 0
    while remaining > 0:
        _guard_max_days_walked(days_walked)
        day_capacity = _day_capacity_minutes(weekday_hours.get(_day_type(current_date), Decimal(0)))
        if day_capacity > 0:
            used = min(remaining, day_capacity)
            remaining -= used
            last_worked_date = current_date
            last_day_minutes_used = used
        current_date += timedelta(days=1)
        days_walked += 1

    return datetime.combine(last_worked_date, start_at.time(), tzinfo=start_at.tzinfo) + timedelta(
        minutes=last_day_minutes_used
    )


def _resolve_backward_terminal_day(
    last_worked_date: date,
    duration_minutes: int,
    weekday_hours: WeekdayHours,
    max_terminal_minutes: int,
) -> tuple[date, int] | None:
    """For a *fixed* candidate ``last_worked_date`` (the calendar date on
    which :func:`compute_finish_at`'s forward walk would have landed its
    truncated terminal chunk), find the ``(start_date, terminal_minutes_used)``
    pair that a genuine forward walk from ``start_date`` would produce: every
    calendar date from ``start_date`` up to (but excluding) ``last_worked_date``
    contributes its FULL capacity, and ``last_worked_date`` itself contributes
    exactly ``terminal_minutes_used`` -- capped by ``max_terminal_minutes``
    (how many minutes of ``last_worked_date`` are even available before
    reaching the anchor's own clock position; see :func:`compute_start_at`).

    Returns ``None`` when ``last_worked_date`` cannot possibly be the
    terminal day for this ``duration_minutes``/calendar combination -- either
    because it has no capacity (or none within ``max_terminal_minutes``) at
    all, or because the very next working day walked backward already has
    more capacity on its own than ``duration_minutes`` could ever leave for
    a non-terminal day: a single day's FULL capacity can only ever be
    absorbed by a *forward* walk that does not terminate on that day first,
    so a candidate whose own capacity alone would already meet or exceed
    ``duration_minutes`` can never be a non-terminal day preceding
    ``last_worked_date`` -- see the regression tests guarding this in
    ``test_calendar_schedule.py``.
    """
    terminal_capacity = _day_capacity_minutes(
        weekday_hours.get(_day_type(last_worked_date), Decimal(0))
    )
    cap_bound = min(terminal_capacity, max_terminal_minutes)
    if cap_bound <= 0:
        return None
    if duration_minutes <= cap_bound:
        return last_worked_date, duration_minutes

    threshold = duration_minutes - cap_bound
    running_full_capacity = 0
    current_date = last_worked_date - timedelta(days=1)
    start_date: date | None = None
    days_walked = 0
    while running_full_capacity < threshold:
        _guard_max_days_walked(days_walked)
        day_capacity = _day_capacity_minutes(weekday_hours.get(_day_type(current_date), Decimal(0)))
        if day_capacity > 0:
            candidate_running = running_full_capacity + day_capacity
            if candidate_running >= duration_minutes:
                # This day's own full capacity alone would already meet or
                # exceed the entire duration, so last_worked_date can never
                # be the terminal day of a forward walk that passes through
                # this date at full capacity -- the true terminal day would
                # be this earlier date instead.
                return None
            running_full_capacity = candidate_running
            start_date = current_date
        current_date -= timedelta(days=1)
        days_walked += 1

    assert start_date is not None  # a loop iteration always runs since threshold > 0 here
    return start_date, duration_minutes - running_full_capacity


def compute_start_at(
    anchor: datetime, duration_minutes: int, weekday_hours: WeekdayHours
) -> datetime:
    """Schedule ``duration_minutes`` of working time backward from ``anchor``.

    The true reverse of :func:`compute_finish_at` -- added for E3-03's PR
    review finding on negative (lead/advance) predecessor link lag (see
    ``_resolve_lag_offset`` in ``waterfall.services.planning_tree``) and
    later reused for FF/SF's "target finish -> start" conversion (see
    ``_resolve_predecessor_constraints``) -- meaning
    ``compute_finish_at(compute_start_at(anchor, duration, cal), duration,
    cal) == anchor`` exactly, including for a calendar whose working days
    have different capacities from one another (e.g. a Wednesday half-day).

    An earlier version of this function computed ``anchor.time() -
    last_day_minutes_used`` directly, mixing ``anchor``'s own clock time
    (which belongs to the *finish* day) with a quantity of minutes consumed
    on a *different* day (the earliest day reached walking backward, i.e.
    the resulting ``start_date``), which can have a different capacity under
    a non-uniform calendar. That produced the wrong ``start_at`` -- correct
    only by coincidence when every working day happens to share the same
    capacity -- and, worse, is not actually invertible that way in general:
    a fixed ``anchor`` can be consistent with several different terminal-day
    candidates, only one of which corresponds to a genuinely self-consistent
    clock time.

    :func:`compute_finish_at`'s own return value is always
    ``combine(last_worked_date, start_at.time()) + last_day_minutes_used``,
    where every calendar date walked *before* ``last_worked_date`` (the
    terminal day the walk's ``remaining`` duration is exhausted on)
    contributes its full capacity, and only ``last_worked_date`` itself is
    truncated to whatever ``remaining`` duration is left. This function
    inverts that relationship directly instead of mirroring the forward
    walk's day-stepping structure verbatim:

    1. ``last_worked_date`` (the terminal day of the *forward* walk that
       would have produced ``anchor``) can only be ``anchor.date()`` itself
       or the calendar date immediately before it: :func:`compute_finish_at`
       adds at most one working day's capacity (<= 1440 minutes) to a clock
       time already within ``[00:00, 24:00)``, so its result's own date is
       always within one calendar day of ``last_worked_date``. Both
       candidates are tried, in that order.
    2. For a candidate ``last_worked_date``, the number of minutes it can
       possibly have contributed as the terminal (truncated) chunk is capped
       not only by that date's own capacity, but also by how many minutes
       separate ``anchor`` from that candidate date's own midnight -- a
       terminal chunk any larger would require a *negative* ``start_at``
       time-of-day on that same date, which is impossible. See
       :func:`_resolve_backward_terminal_day`, which also locates the
       resulting ``start_date`` by walking further back, one calendar day at
       a time, accumulating each work day's FULL capacity, until enough of
       ``duration_minutes`` is accounted for that what is left fits within
       the capped terminal-chunk bound.
    3. ``start_at``'s time-of-day is then derived directly from that
       relationship -- ``anchor`` minus the resolved terminal chunk's
       minutes -- rather than from ``anchor.time()`` combined with a
       reliquat consumed on a different day; a final self-consistency check
       (the result must still fall on the same candidate
       ``last_worked_date``) rejects a candidate that turns out
       inconsistent, falling through to the other one.

    Raises ``ValueError`` if neither candidate ``last_worked_date`` is
    workable -- i.e. ``anchor`` is not a value :func:`compute_finish_at`
    could ever have produced for this ``duration_minutes``/calendar
    combination (only possible with a sufficiently sparse calendar, e.g. one
    with a single working weekday, and an ``anchor`` far from any of its
    working days) -- the same way an unschedulable input is already reported
    elsewhere in this module.
    """
    if duration_minutes < 0:
        raise ValueError("duration_minutes must not be negative")
    if duration_minutes == 0:
        return anchor
    if not _has_any_working_day(weekday_hours):
        raise ValueError("calendar has no working day; scheduling would never terminate")

    for candidate_last_worked_date in (anchor.date(), anchor.date() - timedelta(days=1)):
        candidate_midnight = datetime.combine(
            candidate_last_worked_date, time.min, tzinfo=anchor.tzinfo
        )
        max_terminal_minutes = int((anchor - candidate_midnight).total_seconds() // 60)
        if max_terminal_minutes <= 0:
            continue
        result = _resolve_backward_terminal_day(
            candidate_last_worked_date, duration_minutes, weekday_hours, max_terminal_minutes
        )
        if result is None:
            continue
        start_date, terminal_minutes_used = result
        candidate_start = anchor - timedelta(minutes=terminal_minutes_used)
        if candidate_start.date() != candidate_last_worked_date:
            continue
        return datetime.combine(start_date, candidate_start.time(), tzinfo=anchor.tzinfo)

    raise ValueError(
        "anchor is not reachable as a working-time finish under this calendar for this "
        "duration; check the calendar has enough working capacity near this date"
    )


def compute_start_at_for_finish_at_or_after(
    target_finish: datetime, duration_minutes: int, weekday_hours: WeekdayHours
) -> datetime:
    """Resolve the ``start_at`` whose resulting finish is the earliest one
    reachable at or after ``target_finish`` -- the correct CPM semantics for
    an FF/SF predecessor-link constraint (10th E3-03 PR review round; see
    ``_resolve_predecessor_constraints`` in ``waterfall.services.planning_tree``).

    An FF/SF link only ever bounds the successor's finish *from below*: "the
    successor finishes no earlier than target_finish", exactly mirroring how
    an FS/SS link bounds the successor's *start* from below (see
    ``_apply_automatic_schedule``, which takes ``max(constraints)`` over
    every link). :func:`compute_start_at` alone only solves the strictly
    narrower "finishes at *exactly* target_finish" case: when
    ``target_finish`` is not itself a value :func:`compute_finish_at` could
    ever produce for this calendar/duration -- most commonly because it
    falls on a day with zero working capacity, e.g. a Saturday under a
    Mon-Fri calendar, which a raw wall-clock (elapsed-format) lag can land
    on freely since it is never calendar-snapped -- it raises ``ValueError``
    even though a perfectly valid, later (but still minimal) finish exists
    and should be used instead of rejecting an otherwise valid schedule.

    Algorithm: try :func:`compute_start_at` against ``target_finish`` as-is
    first. If it is exactly reachable (the common case, and the only case
    before this fix), its result is returned verbatim -- no behaviour change
    for it. Otherwise, walk ``target_finish`` forward one calendar day at a
    time (same time-of-day at each step) and retry, until a day is found on
    which :func:`compute_start_at` succeeds; that day's result is both
    reachable and, by construction of the walk, the earliest such date
    tried, hence "at or after" rather than an arbitrary later fallback.

    This calendar model only ever expresses a *weekly repeating* pattern
    (``CalendarWeekday.day_type`` 1-7 with no per-date holiday overrides --
    see ``models.resources.CalendarWeekday``), so any calendar that has at
    least one working day at all (already required to reach this point, see
    the ``_has_any_working_day`` guard below) is guaranteed to repeat that
    working day at least once every 7 calendar days; in practice this
    forward walk converges within a handful of iterations for every
    realistic calendar. It is still bounded by
    :func:`_guard_max_days_walked`/``_MAX_CALENDAR_DAYS_WALKED`` regardless,
    as defense-in-depth against a pathological input, matching every other
    unbounded calendar walk in this module, and raises the same ``ValueError``
    they do when that ceiling is hit.

    Each retried day is still resolved through the exact same, unmodified
    :func:`compute_start_at` -- exact and calendar-aware -- so the only new
    behaviour this function introduces is *which* date is offered to it as
    ``target_finish``; no naive/aware handling or sub-minute precision logic
    already solved there is duplicated or reimplemented here.
    """
    if duration_minutes < 0:
        raise ValueError("duration_minutes must not be negative")
    if not _has_any_working_day(weekday_hours):
        raise ValueError("calendar has no working day; scheduling would never terminate")

    candidate_finish = target_finish
    days_walked = 0
    while True:
        try:
            return compute_start_at(candidate_finish, duration_minutes, weekday_hours)
        except ValueError:
            _guard_max_days_walked(days_walked)
            days_walked += 1
            candidate_finish += timedelta(days=1)


def compute_working_minutes_between(
    start_at: datetime, finish_at: datetime, weekday_hours: WeekdayHours
) -> int:
    """Compute the working minutes a calendar attributes to ``[start_at, finish_at]``.

    For every calendar date ``d`` from ``start_at.date()`` to ``finish_at.date()``
    inclusive, the day's work shift window is ``[combine(d, start_at.time()),
    combine(d, start_at.time()) + day_capacity(d) minutes)`` -- i.e. the shift
    always starts at ``start_at``'s own clock time, every day, and lasts
    exactly that date's capacity. The minutes credited for that date are the
    overlap between ``[start_at, finish_at]`` and that window (capped at the
    window's own capacity, defensively).

    Anchoring every day's shift to ``start_at``'s time-of-day (instead of
    midnight) is what makes this function a true inverse of
    :func:`compute_finish_at`, which schedules forward using the exact same
    "day_capacity minutes starting from start_at's clock time" convention for
    every day it walks. Round-tripping ``duration -> compute_finish_at ->
    compute_working_minutes_between`` must return the original duration; this
    is required by the future E3-03 automatic scheduler.

    Guarded by the same :func:`_guard_max_days_walked` ceiling as
    :func:`compute_finish_at`/:func:`compute_start_at`: unlike those two
    functions, ``start_at``/``finish_at`` here are not derived from a bounded
    ``duration_minutes`` walk -- they can be an arbitrary pair of dates (e.g.
    a manually scheduled task's verbatim, unbounded ``start_at``/``finish_at``,
    see ``PlanningTaskScheduleUpdate`` / ``_apply_manual_schedule`` in
    ``waterfall.services.planning_tree``), so this loop needs its own
    unbounded-iteration guard rather than inheriting one transitively.
    """
    if finish_at <= start_at:
        return 0

    total_minutes = 0
    current_date = start_at.date()
    finish_date = finish_at.date()
    days_walked = 0
    while current_date <= finish_date:
        _guard_max_days_walked(days_walked)
        day_capacity = _day_capacity_minutes(weekday_hours.get(_day_type(current_date), Decimal(0)))
        if day_capacity > 0:
            shift_start = datetime.combine(current_date, start_at.time(), tzinfo=start_at.tzinfo)
            shift_end = shift_start + timedelta(minutes=day_capacity)
            overlap_start = max(start_at, shift_start)
            overlap_end = min(finish_at, shift_end)
            if overlap_end > overlap_start:
                overlap_minutes = int((overlap_end - overlap_start).total_seconds() // 60)
                total_minutes += min(overlap_minutes, day_capacity)
        current_date += timedelta(days=1)
        days_walked += 1
    return total_minutes
