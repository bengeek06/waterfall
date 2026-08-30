from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.schemas.projects import PlanningTaskMove, PlanningTaskScheduleUpdate
from waterfall.services.calendar_schedule import (
    ResolvedCalendar,
    compute_finish_at,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
)


class PlanningTreeMoveError(ValueError):
    """A hierarchy move command violates the planning tree contract."""


class PlanningTreeInvariantError(PlanningTreeMoveError):
    """The planning hierarchy would violate a structural invariant."""


class PlanningTreeMoveNotFoundError(PlanningTreeMoveError):
    """A task addressed by a hierarchy move command does not exist."""


class PlanningTaskScheduleError(PlanningTreeMoveError):
    """A task schedule update (E3-03 manual/automatic mode) is invalid.

    Reuses ``PlanningTreeMoveError`` as its base so routes that already
    ``except PlanningTreeMoveError`` for a generic 400 keep working; every
    validation failure produced by :func:`update_planning_task_schedule` is
    a 400 (invalid combination of mode/dates/duration), never a 409 -- there
    is no structural-invariant case analogous to
    :class:`PlanningTreeInvariantError` for a single-task schedule edit.
    """


def _task_order(task: WfPlanningTaskSnapshot) -> tuple[int, int, int]:
    return (0 if task.position is not None else 1, task.position or 0, task.id)


def _validate_tree(tasks_by_uid: dict[int, WfPlanningTaskSnapshot]) -> None:
    for task in tasks_by_uid.values():
        if task.parent_uid is not None and task.parent_uid not in tasks_by_uid:
            raise PlanningTreeInvariantError(f"Task {task.uid} has an orphaned parent")

    visited: set[int] = set()
    visiting: set[int] = set()

    def visit(task_uid: int) -> None:
        if task_uid in visiting:
            raise PlanningTreeInvariantError("Planning hierarchy contains a cycle")
        if task_uid in visited:
            return
        visiting.add(task_uid)
        parent_uid = tasks_by_uid[task_uid].parent_uid
        if parent_uid is not None:
            visit(parent_uid)
        visiting.remove(task_uid)
        visited.add(task_uid)

    for task_uid in tasks_by_uid:
        visit(task_uid)


def _selected_roots(
    task_uids: list[int], tasks_by_uid: dict[int, WfPlanningTaskSnapshot]
) -> list[int]:
    if len(set(task_uids)) != len(task_uids):
        raise PlanningTreeMoveError("task_uids must not contain duplicates")
    missing = [task_uid for task_uid in task_uids if task_uid not in tasks_by_uid]
    if missing:
        raise PlanningTreeMoveNotFoundError(f"Task not found: {missing[0]}")

    selected = set(task_uids)
    roots: list[int] = []
    for task_uid in task_uids:
        parent_uid = tasks_by_uid[task_uid].parent_uid
        while parent_uid is not None:
            if parent_uid in selected:
                break
            parent_uid = tasks_by_uid[parent_uid].parent_uid
        else:
            roots.append(task_uid)
    return _depth_first_task_uids(tasks_by_uid, set(roots))


def _depth_first_task_uids(
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot], selected_uids: set[int]
) -> list[int]:
    children_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]] = defaultdict(list)
    for task in tasks_by_uid.values():
        children_by_parent[task.parent_uid].append(task)
    for siblings in children_by_parent.values():
        siblings.sort(key=_task_order)

    ordered_uids: list[int] = []

    def visit(parent_uid: int | None) -> None:
        for task in children_by_parent[parent_uid]:
            if task.uid in selected_uids:
                ordered_uids.append(task.uid)
            visit(task.uid)

    visit(None)
    return ordered_uids


def _recalculate_outline(
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    resolved_calendars: dict[int, ResolvedCalendar],
) -> None:
    children_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]] = defaultdict(list)
    for task in tasks_by_uid.values():
        children_by_parent[task.parent_uid].append(task)
    for siblings in children_by_parent.values():
        siblings.sort(key=_task_order)

    def update_children(parent_uid: int | None, prefix: str, level: int) -> None:
        for position, task in enumerate(children_by_parent[parent_uid], start=1):
            task.position = position
            task.outline_level = level
            task.outline_number = f"{prefix}.{position}" if prefix else str(position)
            update_children(task.uid, task.outline_number or "", level + 1)
            _recalculate_summary_fields(task, children_by_parent[task.uid], resolved_calendars)

    update_children(None, "", 1)


def _recalculate_summary_fields(
    task: WfPlanningTaskSnapshot,
    children: list[WfPlanningTaskSnapshot],
    resolved_calendars: dict[int, ResolvedCalendar],
) -> None:
    if not children:
        if task.is_summary:
            task.start_at = None
            task.finish_at = None
            task.duration_minutes = None
        task.is_summary = False
        return

    task.is_summary = True
    start_dates = [child.start_at for child in children if child.start_at is not None]
    finish_dates = [child.finish_at for child in children if child.finish_at is not None]
    task.start_at = min(start_dates) if start_dates else None
    task.finish_at = max(finish_dates) if finish_dates else None
    start_at = task.start_at
    finish_at = task.finish_at
    if start_at is None or finish_at is None:
        task.duration_minutes = None
    else:
        # E5-04: the summary duration is calendar-aware. The calendar used is
        # resolved from the summary task's own assigned resource role,
        # falling back to the org-wide default STANDARD calendar, and -- when
        # no calendar exists in the system at all -- an implicit 24h/day
        # calendar (source == "wall_clock_fallback") that is mathematically
        # equivalent to the raw wall-clock diff (proven by
        # test_compute_working_minutes_between_matches_wall_clock_diff_under_24h_calendar
        # and the property test in test_calendar_schedule.py), so a single
        # code path handles every tier.
        resolved = resolved_calendars[task.uid]
        task.duration_minutes = max(
            0, compute_working_minutes_between(start_at, finish_at, resolved.weekday_hours)
        )
        # Known v1 limitation (not fixed here, see the PR review that flagged
        # it): this is the *only* place duration_minutes gets recalculated
        # for a calendar-aware summary task, and it only runs as a side
        # effect of move_planning_tasks (drag/drop reordering). If a role's
        # calendar or a task's role assignment changes afterwards on a draft
        # planning, the previously stored duration_minutes is left stale
        # until the next move -- there is no invalidation hook today. Full
        # invalidation is deliberately out of scope (draft-only edge case,
        # low value for the size of the change) and is left for E3-03, which
        # will need to revisit this scheduling logic more broadly anyway.


def _validate_target_parent(
    target_parent_uid: int | None,
    selected_roots: list[int],
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
) -> None:
    if target_parent_uid is not None and target_parent_uid not in tasks_by_uid:
        raise PlanningTreeMoveNotFoundError(f"Task not found: {target_parent_uid}")
    if target_parent_uid is not None and tasks_by_uid[target_parent_uid].is_milestone:
        raise PlanningTreeInvariantError("A milestone cannot contain children")
    if target_parent_uid in selected_roots:
        raise PlanningTreeInvariantError("A task cannot be moved under itself")

    selected_root_set = set(selected_roots)
    parent_uid = target_parent_uid
    while parent_uid is not None:
        if parent_uid in selected_root_set:
            raise PlanningTreeInvariantError("A task cannot be moved under its descendant")
        parent_uid = tasks_by_uid[parent_uid].parent_uid


def move_planning_tasks(
    db: Session,
    planning: WfPlanning,
    command: PlanningTaskMove,
) -> None:
    tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    )
    tasks_by_uid = {task.uid: task for task in tasks}
    _validate_tree(tasks_by_uid)
    selected_roots = _selected_roots(command.task_uids, tasks_by_uid)
    _validate_target_parent(command.target_parent_uid, selected_roots, tasks_by_uid)
    selected_root_set = set(selected_roots)

    siblings_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]] = defaultdict(list)
    for task in tasks:
        if task.uid not in selected_root_set:
            siblings_by_parent[task.parent_uid].append(task)
    for siblings in siblings_by_parent.values():
        siblings.sort(key=_task_order)

    moved = [tasks_by_uid[task_uid] for task_uid in selected_roots]
    target_siblings = siblings_by_parent[command.target_parent_uid]
    if command.position > len(target_siblings) + 1:
        raise PlanningTreeMoveError("position is outside the target sibling range")
    target_siblings[command.position - 1 : command.position - 1] = moved
    for task in moved:
        task.parent_uid = command.target_parent_uid

    for siblings in siblings_by_parent.values():
        for position, task in enumerate(siblings, start=1):
            task.position = position
    resolved_calendars = resolve_calendars_for_tasks(
        db, planning.project_id, set(tasks_by_uid.keys())
    )
    _recalculate_outline(tasks_by_uid, resolved_calendars)


def _check_milestone_duration_and_finish_consistency(
    payload: PlanningTaskScheduleUpdate, start_at: datetime
) -> None:
    """Shared rejection rules for both manual and automatic milestone edits.

    A milestone always has a zero duration and ``start_at == finish_at``.
    ``duration_minutes``/``finish_at`` are accepted if they are simply absent
    or already consistent, and rejected outright if the client explicitly
    asked for something else -- per the E3-03 issue's acceptance test for
    "milestone with a non-zero duration must be rejected with an actionable
    message". This applies identically regardless of scheduling mode: a
    milestone's shape invariant is not something ``is_manual`` can opt out of.
    """
    fields_set = payload.model_fields_set
    if "duration_minutes" in fields_set and payload.duration_minutes not in (None, 0):
        raise PlanningTaskScheduleError("A milestone must have a zero duration")
    if (
        "finish_at" in fields_set
        and payload.finish_at is not None
        and payload.finish_at != start_at
    ):
        raise PlanningTaskScheduleError("A milestone's finish_at must equal its start_at")


def _apply_manual_milestone_schedule(
    task: WfPlanningTaskSnapshot, payload: PlanningTaskScheduleUpdate
) -> None:
    """A manually scheduled milestone's own date is not derived, only anchored
    and normalized: ``payload.start_at`` if provided, else the task's own
    already-stored ``start_at``.
    """
    start_at = payload.start_at if payload.start_at is not None else task.start_at
    if start_at is None:
        raise PlanningTaskScheduleError("start_at is required to schedule a milestone")

    _check_milestone_duration_and_finish_consistency(payload, start_at)

    task.start_at = start_at
    task.finish_at = start_at
    task.duration_minutes = 0


def _apply_automatic_milestone_schedule(
    links: list[WfPlanningLinkSnapshot],
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    task: WfPlanningTaskSnapshot,
    payload: PlanningTaskScheduleUpdate,
) -> None:
    """An automatically scheduled milestone is constrained by its
    predecessors exactly like a regular automatic task of zero duration (see
    :func:`_apply_automatic_schedule`/:func:`_resolve_predecessor_constraints`),
    falling back to ``payload.start_at`` then the task's own stored
    ``start_at`` when it has no predecessor link contributing a constraint.
    Since a milestone's duration is always 0, its finish_at always equals its
    start_at -- no calendar-aware forward computation is needed.
    """
    constraints = _resolve_predecessor_constraints(links, tasks_by_uid, duration_minutes=0)
    if constraints:
        start_at = max(constraints)
    elif payload.start_at is not None:
        start_at = payload.start_at
    elif task.start_at is not None:
        start_at = task.start_at
    else:
        raise PlanningTaskScheduleError(
            "start_at is required for an automatically scheduled milestone without predecessors"
        )

    _check_milestone_duration_and_finish_consistency(payload, start_at)

    task.start_at = start_at
    task.finish_at = start_at
    task.duration_minutes = 0


def _apply_manual_schedule(
    task: WfPlanningTaskSnapshot, payload: PlanningTaskScheduleUpdate
) -> None:
    """A manual task is stored exactly as provided, with no server-side recalculation."""
    if payload.start_at is None:
        raise PlanningTaskScheduleError("start_at is required for a manually scheduled task")
    if payload.finish_at is not None and payload.finish_at < payload.start_at:
        raise PlanningTaskScheduleError("finish_at must not be before start_at")

    task.start_at = payload.start_at
    task.finish_at = payload.finish_at
    task.duration_minutes = payload.duration_minutes


def _resolve_predecessor_constraints(
    links: list[WfPlanningLinkSnapshot],
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    duration_minutes: int,
) -> list[datetime]:
    """Derive start_at lower-bound constraints from a task's predecessor links.

    MS Project link_type convention: 0=FF, 1=FS, 2=SF, 3=SS. ``lag_tenth_minute``
    is stored in tenths of a minute and converted to minutes here.

    FS and SS constraints are resolved directly from the predecessor's own
    stored ``finish_at``/``start_at`` -- exact, no approximation.

    Known v1 limitation: FF and SF constraints logically bound the
    *successor's finish* date, not its start. Resolving them exactly would
    require a calendar-aware backward walk from a target finish date back to
    a start date, which ``calendar_schedule.py`` does not expose today
    (``compute_finish_at`` only schedules forward). This is approximated here
    with raw wall-clock minute arithmetic: the implied finish constraint
    (``predecessor date + lag``) is converted to a start constraint by
    subtracting the task's own ``duration_minutes`` directly, ignoring the
    successor's calendar's non-working days in that subtraction. This can
    under- or over-constrain ``start_at`` by up to the calendar's non-working
    time within the task's own duration window, compared to a true
    calendar-aware backward computation. Accepted for v1 per the E3-03 issue;
    a regression test freezes this documented behaviour rather than silently
    tolerating it. Revisit if FF/SF links turn out to be common in practice.
    """
    constraints: list[datetime] = []
    for link in links:
        predecessor = tasks_by_uid.get(link.predecessor_uid)
        if predecessor is None:
            continue
        lag_minutes = (link.lag_tenth_minute or 0) / 10
        if link.link_type == 1 and predecessor.finish_at is not None:  # FS
            constraints.append(predecessor.finish_at + timedelta(minutes=lag_minutes))
        elif link.link_type == 3 and predecessor.start_at is not None:  # SS
            constraints.append(predecessor.start_at + timedelta(minutes=lag_minutes))
        elif link.link_type == 0 and predecessor.finish_at is not None:  # FF (approximated)
            constraints.append(
                predecessor.finish_at + timedelta(minutes=lag_minutes - duration_minutes)
            )
        elif link.link_type == 2 and predecessor.start_at is not None:  # SF (approximated)
            constraints.append(
                predecessor.start_at + timedelta(minutes=lag_minutes - duration_minutes)
            )
    return constraints


def _apply_automatic_schedule(
    db: Session,
    planning: WfPlanning,
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    links: list[WfPlanningLinkSnapshot],
    task: WfPlanningTaskSnapshot,
    payload: PlanningTaskScheduleUpdate,
) -> None:
    """An automatic task's dates are always computed server-side.

    ``payload.start_at``/``payload.finish_at`` are never stored verbatim:
    ``start_at`` only serves as the fallback anchor when the task has no
    predecessor link contributing a constraint (see
    :func:`_resolve_predecessor_constraints`), and ``finish_at`` is ignored
    entirely -- it is always recomputed from ``start_at`` and
    ``duration_minutes`` through the task's resolved calendar, so the server
    never returns a value inconsistent with its own computation.
    """
    duration_minutes = payload.duration_minutes
    if duration_minutes is None or duration_minutes <= 0:
        raise PlanningTaskScheduleError(
            "An automatically scheduled task requires a positive duration_minutes"
        )

    constraints = _resolve_predecessor_constraints(links, tasks_by_uid, duration_minutes)
    if constraints:
        start_at = max(constraints)
    elif payload.start_at is not None:
        start_at = payload.start_at
    elif task.start_at is not None:
        start_at = task.start_at
    else:
        raise PlanningTaskScheduleError(
            "start_at is required for an automatically scheduled task without predecessors"
        )

    resolved_calendars = resolve_calendars_for_tasks(db, planning.project_id, {task.uid})
    resolved = resolved_calendars[task.uid]
    try:
        finish_at = compute_finish_at(start_at, duration_minutes, resolved.weekday_hours)
    except ValueError as exc:
        raise PlanningTaskScheduleError(str(exc)) from exc

    task.start_at = start_at
    task.finish_at = finish_at
    task.duration_minutes = duration_minutes


def _recalculate_ancestor_summaries(
    db: Session,
    planning: WfPlanning,
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    task: WfPlanningTaskSnapshot,
) -> None:
    """Recalculate every summary ancestor of ``task``, bottom-up.

    Reuses :func:`_recalculate_summary_fields` (the same calendar-aware
    min/max/duration derivation ``move_planning_tasks`` uses) instead of
    duplicating it, so a task edited through
    :func:`update_planning_task_schedule` immediately reflects into its
    ancestor summaries -- closing the "Known v1 limitation" gap called out
    in :func:`_recalculate_summary_fields`'s own docstring, where this
    recalculation used to only ever run as a side effect of a tree move.
    """
    children_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]] = defaultdict(list)
    for candidate in tasks_by_uid.values():
        children_by_parent[candidate.parent_uid].append(candidate)

    ancestor_uids: list[int] = []
    parent_uid = task.parent_uid
    while parent_uid is not None and parent_uid in tasks_by_uid:
        ancestor_uids.append(parent_uid)
        parent_uid = tasks_by_uid[parent_uid].parent_uid

    if not ancestor_uids:
        return

    resolved_calendars = resolve_calendars_for_tasks(db, planning.project_id, set(ancestor_uids))
    # ancestor_uids is ordered from the immediate parent outward, i.e.
    # bottom-up -- required so a grandparent's recalculation sees its own
    # child's (the parent's) already-updated start_at/finish_at.
    for ancestor_uid in ancestor_uids:
        ancestor = tasks_by_uid[ancestor_uid]
        children = children_by_parent[ancestor_uid]
        _recalculate_summary_fields(ancestor, children, resolved_calendars)


def update_planning_task_schedule(
    db: Session,
    planning: WfPlanning,
    task_uid: int,
    payload: PlanningTaskScheduleUpdate,
) -> WfPlanningTaskSnapshot:
    """Apply an E3-03 manual/automatic scheduling edit to a single draft task.

    Only reads predecessor links (:class:`WfPlanningLinkSnapshot`); editing
    the links themselves is out of scope (E3-04).
    """
    tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    )
    tasks_by_uid = {snapshot.uid: snapshot for snapshot in tasks}
    task = tasks_by_uid.get(task_uid)
    if task is None:
        raise PlanningTreeMoveNotFoundError(f"Task not found: {task_uid}")

    if task.is_summary:
        raise PlanningTaskScheduleError(
            "A summary task's dates are derived from its children and cannot be edited directly"
        )

    if task.is_milestone and payload.is_manual:
        _apply_manual_milestone_schedule(task, payload)
    elif task.is_milestone:
        links = (
            db.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
            .filter(WfPlanningLinkSnapshot.task_uid == task_uid)
            .all()
        )
        _apply_automatic_milestone_schedule(links, tasks_by_uid, task, payload)
    elif payload.is_manual:
        _apply_manual_schedule(task, payload)
    else:
        links = (
            db.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
            .filter(WfPlanningLinkSnapshot.task_uid == task_uid)
            .all()
        )
        _apply_automatic_schedule(db, planning, tasks_by_uid, links, task, payload)

    task.is_manual = payload.is_manual
    _recalculate_ancestor_summaries(db, planning, tasks_by_uid, task)
    return task
