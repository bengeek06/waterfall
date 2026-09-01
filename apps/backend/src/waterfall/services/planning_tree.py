from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import overload

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.schemas.projects import (
    PlanningTaskCreate,
    PlanningTaskDelete,
    PlanningTaskMove,
    PlanningTaskScheduleUpdate,
)
from waterfall.services.calendar_schedule import (
    ResolvedCalendar,
    compute_finish_at,
    compute_start_at,
    compute_start_at_for_finish_at_or_after,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
)
from waterfall.services.task_references import find_referenced_task_uids


class PlanningTreeMoveError(ValueError):
    """A hierarchy move command violates the planning tree contract."""


class PlanningTreeInvariantError(PlanningTreeMoveError):
    """The planning hierarchy would violate a structural invariant."""


class PlanningTreeMoveNotFoundError(PlanningTreeMoveError):
    """A task addressed by a hierarchy move command does not exist."""


class PlanningTreeCascadeConfirmationRequiredError(PlanningTreeMoveError):
    """A deletion selection has descendants that ``confirm_cascade`` did not confirm.

    ``descendant_uids`` lists every descendant (of every selected root) that
    would be deleted alongside the selection -- surfaced by the route as a
    structured 409 body so the caller can present the exact subtree to the
    user before resubmitting with ``confirm_cascade: true``.
    """

    def __init__(self, descendant_uids: list[int]) -> None:
        self.descendant_uids = descendant_uids
        super().__init__(
            "Deleting the selection would remove descendant tasks; "
            "resubmit with confirm_cascade=true to proceed"
        )


class PlanningTreeTaskReferencedError(PlanningTreeMoveError):
    """A task addressed for deletion is referenced by an estimate, assignment, or charge.

    ``task_uids`` lists every referenced task uid found among the selection
    and its (to-be-cascaded) descendants -- surfaced by the route as a
    structured 409 body, mirroring :class:`PlanningTreeCascadeConfirmationRequiredError`.
    """

    def __init__(self, task_uids: list[int]) -> None:
        self.task_uids = task_uids
        super().__init__(
            "Task is referenced by estimates, assignments, or charges and cannot be deleted"
        )


class PlanningTaskScheduleError(PlanningTreeMoveError):
    """A task schedule update (E3-03 manual/automatic mode) is invalid.

    Reuses ``PlanningTreeMoveError`` as its base so routes that already
    ``except PlanningTreeMoveError`` for a generic 400 keep working; every
    validation failure produced by :func:`update_planning_task_schedule` is
    a 400 (invalid combination of mode/dates/duration), never a 409 -- there
    is no structural-invariant case analogous to
    :class:`PlanningTreeInvariantError` for a single-task schedule edit.
    """


@overload
def _to_naive_utc(value: datetime) -> datetime: ...
@overload
def _to_naive_utc(value: None) -> None: ...
@overload
def _to_naive_utc(value: datetime | None) -> datetime | None: ...
def _to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalize a possibly tz-aware datetime to naive UTC.

    ``WfPlanningTaskSnapshot.start_at``/``finish_at`` are declared as
    ``DateTime(timezone=True)``, but the application-level storage convention
    (see ``PlanningTaskScheduleUpdate._drop_tzinfo`` in
    ``waterfall.schemas.projects``) is naive UTC wall-clock, matching the MS
    Project XML import/export round-trip (``msproject_xml._datetime`` /
    ``routes.projects._dt_to_msp_text``). On PostgreSQL (the production
    target), this column type returns real timezone-aware ``datetime``
    objects on ``SELECT`` regardless of how the value was written, whereas a
    client-supplied payload value has already been normalized to naive by
    ``_drop_tzinfo``. Comparing (``min``/``max``) or arithmetic-combining a
    freshly reloaded, aware value with an already-naive one raises
    ``TypeError: can't compare offset-naive and offset-aware datetimes`` --
    invisible under SQLite, which does not preserve ``tzinfo`` across a
    round trip, so every value it returns is already naive. Every read of a
    ``start_at``/``finish_at`` value in this module that feeds into a
    comparison or gets propagated into a written value must go through this
    function first, to keep a single, consistent naive-UTC representation
    regardless of which value happened to come from the database versus the
    request payload.
    """
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


# MSPDI LagFormat/DurationFormat numeric convention, confirmed directly from
# this repo's own bundled schema documentation (see the "LagFormat"
# annotation in resources/msproject-schemas/2016/tasks_2016_schema.xml):
# "Values are: 3=m, 4=em, 5=h, 6=eh, 7=d, 8=ed, 9=w, 10=ew, 11=mo, 12=emo,
# 19=%, 20=e%, 35=m?, 36=em?, 37=h?, 38=eh?, 39=d?, 40=ed?, 41=w?, 42=ew?,
# 43=mo?, 44=emo?, 51=%? and 52=e%?." The "e" prefix denotes *elapsed* (raw
# wall-clock) time; its absence denotes a *working-time* unit that must be
# resolved through the applicable calendar. This codebase's own generated
# planning data (see ``services.planning_structure``) and its MS Project XML
# fixtures exclusively use 7 ("d", working days) for predecessor link lag.
_ELAPSED_LAG_FORMATS = frozenset({4, 6, 8, 10, 12, 20, 36, 38, 40, 42, 44, 52})


def _is_elapsed_lag_format(lag_format: int | None) -> bool:
    """Whether an MSPDI ``LagFormat`` value denotes elapsed (raw wall-clock) lag.

    ``None`` -- an omitted ``<LagFormat>``, legal per the MSPDI schema
    (``minOccurs="0"``) -- is treated as elapsed, preserving this module's
    pre-existing raw wall-clock lag arithmetic when no format is specified;
    that was the only behaviour available before ``lag_format`` was read at
    all, and defaulting absent data to the calendar-aware path would be an
    unreviewed, untested behaviour change.
    """
    return lag_format is None or lag_format in _ELAPSED_LAG_FORMATS


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
    # Normalized to naive UTC (see _to_naive_utc) before min()/max(): children
    # freshly reloaded from the database are timezone-aware on PostgreSQL,
    # while a sibling task just edited in the same request (e.g. through
    # update_planning_task_schedule) carries an already-naive value from the
    # request payload. Mixing the two raises TypeError on PostgreSQL.
    start_dates = [
        normalized
        for child in children
        if (normalized := _to_naive_utc(child.start_at)) is not None
    ]
    finish_dates = [
        normalized
        for child in children
        if (normalized := _to_naive_utc(child.finish_at)) is not None
    ]
    task.start_at = min(start_dates) if start_dates else None
    task.finish_at = max(finish_dates) if finish_dates else None
    start_at = task.start_at
    finish_at = task.finish_at
    if start_at is None or finish_at is None:
        task.duration_minutes = None
    else:
        # E5-04: the summary duration is calendar-aware. The calendar used is
        # resolved from the summary task's own assigned resource role,
        # falling back to the calendar flagged is_default, and -- when
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
    # _recalculate_outline recalculates every summary task's duration via
    # _recalculate_summary_fields, which walks the affected calendar day by
    # day through compute_working_minutes_between. That walk can raise
    # ValueError (the iteration ceiling in _guard_max_days_walked) or
    # OverflowError (date arithmetic pushed past date.max) when a moved
    # task's manually-scheduled start_at/finish_at is unreasonably far in
    # the future -- manual tasks have no server-side range validation (see
    # _apply_manual_schedule), so this is a genuinely-invalid-input case
    # rather than an internal error, and is surfaced as the same 400 as any
    # other PlanningTreeMoveError.
    try:
        _recalculate_outline(tasks_by_uid, resolved_calendars)
    except (ValueError, OverflowError) as exc:
        raise PlanningTreeMoveError(str(exc)) from exc


def create_planning_task(
    db: Session,
    planning: WfPlanning,
    command: PlanningTaskCreate,
) -> None:
    """Insert a single new task into a draft planning at an explicit position (E3-05).

    ``command.target_parent_uid`` -- when provided -- must reference an
    existing, non-milestone task (a milestone cannot contain children, same
    invariant as :func:`_validate_target_parent` enforces for a move).
    ``command.insert_after_uid`` -- when provided -- must be an existing
    sibling of the resolved parent; its absence places the new task as the
    first child of that parent (or the first root task when
    ``target_parent_uid`` is also absent).
    """
    tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    )
    tasks_by_uid = {task.uid: task for task in tasks}
    _validate_tree(tasks_by_uid)

    target_parent_uid = command.target_parent_uid
    if target_parent_uid is not None:
        if target_parent_uid not in tasks_by_uid:
            raise PlanningTreeMoveNotFoundError(f"Task not found: {target_parent_uid}")
        if tasks_by_uid[target_parent_uid].is_milestone:
            raise PlanningTreeInvariantError("A milestone cannot contain children")

    siblings = sorted(
        (task for task in tasks if task.parent_uid == target_parent_uid), key=_task_order
    )

    insert_after_uid = command.insert_after_uid
    if insert_after_uid is None:
        insert_index = 0
    else:
        if insert_after_uid not in tasks_by_uid:
            raise PlanningTreeMoveNotFoundError(f"Task not found: {insert_after_uid}")
        sibling_uids = [task.uid for task in siblings]
        if insert_after_uid not in sibling_uids:
            raise PlanningTreeMoveError(
                f"Task {insert_after_uid} is not a sibling of the target parent"
            )
        insert_index = sibling_uids.index(insert_after_uid) + 1

    # uid/id_display must be unique across every version of this project, not
    # just the current draft: WfPlanningTaskSnapshot.uid is a stable identity
    # reused across planning versions (see task_references.py) and MsTask
    # rows carry legacy references that must never collide with a snapshot
    # uid either. Scoping the max to the current draft's own tasks would let
    # a freshly-deleted-then-recreated uid collide with a task still alive
    # in another version of the same project.
    project_snapshot_max_uid = (
        db.query(func.max(WfPlanningTaskSnapshot.uid))
        .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
        .filter(WfPlanning.project_id == planning.project_id)
        .scalar()
        or 0
    )
    project_snapshot_max_id_display = (
        db.query(func.max(WfPlanningTaskSnapshot.id_display))
        .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
        .filter(WfPlanning.project_id == planning.project_id)
        .scalar()
        or 0
    )
    project_ms_task_max_uid = (
        db.query(func.max(MsTask.uid)).filter(MsTask.project_id == planning.project_id).scalar()
        or 0
    )
    project_ms_task_max_id_display = (
        db.query(func.max(MsTask.id_display))
        .filter(MsTask.project_id == planning.project_id)
        .scalar()
        or 0
    )
    max_uid = max(project_snapshot_max_uid, project_ms_task_max_uid)
    max_id_display = max(project_snapshot_max_id_display, project_ms_task_max_id_display)

    new_task = WfPlanningTaskSnapshot(
        planning_id=planning.id,
        uid=max_uid + 1,
        id_display=max_id_display + 1,
        parent_uid=target_parent_uid,
        position=insert_index + 1,
        name=command.name,
        task_type=0,
        is_summary=False,
        is_milestone=command.is_milestone,
    )
    db.add(new_task)
    # The session is autoflush=False (see db.session.get_session_factory), so
    # without an explicit flush the new row would not exist in the database
    # yet when the route's _planning_detail query re-reads every task by a
    # fresh SELECT afterwards, silently dropping the new task from the
    # response even though _recalculate_outline below correctly numbers it
    # in memory.
    db.flush()
    tasks_by_uid[new_task.uid] = new_task

    siblings.insert(insert_index, new_task)
    for position, task in enumerate(siblings, start=1):
        task.position = position

    resolved_calendars = resolve_calendars_for_tasks(
        db, planning.project_id, set(tasks_by_uid.keys())
    )
    # See the equivalent try/except in move_planning_tasks: _recalculate_outline
    # walks every summary task's affected calendar day by day and can raise
    # ValueError/OverflowError for an unreasonably far manually-scheduled date
    # elsewhere in the tree -- a genuinely-invalid-input case, not an internal
    # error, surfaced as the same 400 as any other PlanningTreeMoveError.
    try:
        _recalculate_outline(tasks_by_uid, resolved_calendars)
    except (ValueError, OverflowError) as exc:
        raise PlanningTreeMoveError(str(exc)) from exc


def _subtree_uids(
    root_uid: int, children_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]]
) -> list[int]:
    collected = [root_uid]
    for child in children_by_parent.get(root_uid, []):
        collected.extend(_subtree_uids(child.uid, children_by_parent))
    return collected


def delete_planning_tasks(
    db: Session,
    planning: WfPlanning,
    command: PlanningTaskDelete,
) -> None:
    """Delete a multi-uid selection of tasks from a draft planning, with cascade control (E3-05).

    A selection mixing a parent and one of its own descendants is normalized
    through :func:`_selected_roots`, exactly like :func:`move_planning_tasks`.
    Every check -- cascade confirmation, then task-reference -- is run for the
    *entire* selection before any mutation happens, so a violation on one
    root never leaves an earlier root partially deleted.
    """
    tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    )
    tasks_by_uid = {task.uid: task for task in tasks}
    _validate_tree(tasks_by_uid)
    selected_roots = _selected_roots(command.task_uids, tasks_by_uid)

    children_by_parent: dict[int | None, list[WfPlanningTaskSnapshot]] = defaultdict(list)
    for task in tasks:
        children_by_parent[task.parent_uid].append(task)

    to_delete: set[int] = set()
    descendant_uids: set[int] = set()
    for root_uid in selected_roots:
        subtree = _subtree_uids(root_uid, children_by_parent)
        to_delete.update(subtree)
        descendant_uids.update(uid for uid in subtree if uid != root_uid)

    if descendant_uids and not command.confirm_cascade:
        raise PlanningTreeCascadeConfirmationRequiredError(sorted(descendant_uids))

    # Bridges each snapshot uid to its legacy MsTask row (if any) so
    # find_referenced_task_uids -- which keys estimate/assignment references
    # off ms_task.id, not the planning snapshot -- can resolve a task_id,
    # exactly like the legacy delete_project_task endpoint did before E3-05.
    legacy_tasks_by_uid = {
        task.uid: task
        for task in db.query(MsTask)
        .filter(MsTask.project_id == planning.project_id)
        .filter(MsTask.uid.in_(to_delete))
        .all()
    }
    # Batched into a handful of IN (...) queries rather than one
    # is_task_referenced call per task uid: this cascade can select an
    # arbitrarily large subtree while the caller still holds a row lock on
    # ms_project/wf_planning, so an N+1 loop here would block every other
    # concurrent writer for the duration.
    task_id_by_uid = {
        task_uid: (legacy_tasks_by_uid[task_uid].id if task_uid in legacy_tasks_by_uid else None)
        for task_uid in to_delete
    }
    referenced_uids = sorted(
        find_referenced_task_uids(
            db,
            project_id=planning.project_id,
            task_id_by_uid=task_id_by_uid,
        )
    )
    if referenced_uids:
        raise PlanningTreeTaskReferencedError(referenced_uids)

    db.query(WfPlanningLinkSnapshot).filter(
        WfPlanningLinkSnapshot.planning_id == planning.id,
        (WfPlanningLinkSnapshot.task_uid.in_(to_delete))
        | (WfPlanningLinkSnapshot.predecessor_uid.in_(to_delete)),
    ).delete(synchronize_session=False)
    db.query(WfPlanningTaskSnapshot).filter(
        WfPlanningTaskSnapshot.planning_id == planning.id,
        WfPlanningTaskSnapshot.uid.in_(to_delete),
    ).delete(synchronize_session=False)

    remaining_tasks_by_uid = {
        uid: task for uid, task in tasks_by_uid.items() if uid not in to_delete
    }
    resolved_calendars = resolve_calendars_for_tasks(
        db, planning.project_id, set(remaining_tasks_by_uid.keys())
    )
    try:
        _recalculate_outline(remaining_tasks_by_uid, resolved_calendars)
    except (ValueError, OverflowError) as exc:
        raise PlanningTreeMoveError(str(exc)) from exc


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
    start_at = payload.start_at if payload.start_at is not None else _to_naive_utc(task.start_at)
    if start_at is None:
        raise PlanningTaskScheduleError("start_at is required to schedule a milestone")

    _check_milestone_duration_and_finish_consistency(payload, start_at)

    task.start_at = start_at
    task.finish_at = start_at
    task.duration_minutes = 0


def _apply_automatic_milestone_schedule(
    db: Session,
    planning: WfPlanning,
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
    start_at -- no calendar-aware forward computation is needed for the
    milestone's own duration, but its predecessor links' lag still is (see
    :func:`_resolve_lag_offset`), hence resolving the task's own calendar
    here.
    """
    resolved_calendar = resolve_calendars_for_tasks(db, planning.project_id, {task.uid})[task.uid]
    # See the equivalent try/except in _apply_automatic_schedule: a
    # working-time FS/SS/FF/SF lag resolved through _resolve_lag_offset (and,
    # for FF/SF, the subsequent compute_start_at call in
    # _resolve_predecessor_constraints) can raise OverflowError (not just
    # ValueError) when walked past datetime.max/date.max.
    try:
        constraints = _resolve_predecessor_constraints(
            links, tasks_by_uid, duration_minutes=0, resolved_calendar=resolved_calendar
        )
    except (ValueError, OverflowError) as exc:
        raise PlanningTaskScheduleError(str(exc)) from exc

    if constraints:
        start_at = max(constraints)
    elif payload.start_at is not None:
        start_at = payload.start_at
    elif task.start_at is not None:
        start_at = _to_naive_utc(task.start_at)
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


def _resolve_lag_offset(
    anchor: datetime,
    lag_minutes: float,
    lag_format: int | None,
    resolved_calendar: ResolvedCalendar,
) -> datetime:
    """Offset a predecessor-link ``anchor`` date by its link's lag.

    Shared by all four MS Project link types (FS, SS, FF, SF; see
    :func:`_resolve_predecessor_constraints`): for FS/SS, ``anchor`` is the
    predecessor's own ``finish_at``/``start_at`` and the result is used
    directly as the successor's start constraint. For FF/SF, ``anchor`` is
    likewise the predecessor's ``finish_at``/``start_at``, but the result is
    the successor's *target finish* date -- :func:`_resolve_predecessor_constraints`
    then converts that into a start constraint via :func:`compute_start_at`.
    Either way, this function only ever does one thing: "the date ``lag``
    working (or elapsed) minutes after/before ``anchor``".

    An elapsed ``lag_format`` (or an absent one, see
    :func:`_is_elapsed_lag_format`), or a zero lag, keeps the pre-existing raw
    wall-clock ``timedelta`` arithmetic -- there is no calendar to resolve a
    zero offset through regardless of format. A working-time ``lag_format``
    instead resolves through the task's applicable calendar: a positive lag
    (the ordinary case) via :func:`compute_finish_at`, the same "advance N
    working minutes forward" primitive already used to schedule a task's own
    duration in :func:`_apply_automatic_schedule`; a negative lag -- a valid
    MS Project "lead"/advance, per the LinkLag field in this repo's own
    bundled MSPDI schema, which places no restriction on the sign -- via
    :func:`compute_start_at`, the equivalent "retreat N working minutes
    backward" primitive. Before this was handled, *any* negative working-time
    lag silently fell back to raw wall-clock arithmetic, which could retreat
    into a non-working day (e.g. landing on a weekend) instead of the correct
    preceding working day.

    A lag that fits within a single calendar day always resolves within that
    same date regardless of the anchor's time-of-day (identical to how
    ``compute_finish_at`` already behaves for a task's own duration, see
    ``test_compute_finish_at_mono_day_fits_within_one_days_capacity`` in
    ``test_calendar_schedule.py``); only a lag exceeding a day's working
    capacity walks forward (or backward) across non-working days (e.g. a
    weekend).

    ``lag_minutes`` is a float (``lag_tenth_minute / 10``, see
    :func:`_resolve_predecessor_constraints`) and can carry a sub-minute
    fraction (e.g. ``lag_tenth_minute=5`` -> ``lag_minutes=0.5``).
    :func:`compute_finish_at`/:func:`compute_start_at` both require an
    ``int`` ``duration_minutes`` and only ever make progress in whole-minute
    steps.

    5th E3-03 PR review round, finding #1: an earlier version of this
    function walked ``math.trunc(lag_minutes)`` whole minutes and then
    layered the sub-minute remainder on top as a raw ``timedelta``. That is
    unsound whenever the truncated whole-minute walk exactly exhausts the
    last working day's capacity it touches: ``compute_finish_at`` (and
    symmetrically ``compute_start_at``) resolve an exact capacity match by
    returning that day's own closing (opening) instant *without* rolling
    over to the next (preceding) working day -- see their docstrings/
    implementation in ``calendar_schedule.py``. Adding the leftover
    remainder on top of that instant as a raw ``timedelta`` then pushes the
    result past the working window's boundary on a day that has no more
    capacity left (e.g. lag=420.5 minutes with a Friday of exactly 420
    minutes' capacity: ``whole_minutes=420`` returns "Friday 15:00:00" --
    the exact end of Friday's window -- and naively adding the 0.5-minute
    remainder produces "Friday 15:00:30", stranded 30 seconds past close,
    instead of rolling over into the next working day (e.g. Monday) the way
    a 421st working minute legitimately would.

    Instead, this walks ``math.ceil(abs(lag_minutes))`` whole minutes --
    rounding the absolute value *up* rather than truncating it down -- so
    the calendar walk itself resolves any day/working-hour boundary the
    extra fractional minute would cross, exactly like any other whole-minute
    walk. The walk then overshoots the true (fractional) lag by
    ``complement_minutes = ceil(abs(lag_minutes)) - abs(lag_minutes)``,
    always strictly less than one minute, which is corrected by stepping the
    result back by that same complement -- in the direction *opposite* the
    walk's own direction of travel: a positive lag walks forward via
    :func:`compute_finish_at`, so the overshoot is undone by subtracting the
    complement (moving the result slightly earlier); a negative lag
    (lead/advance) walks backward via :func:`compute_start_at`, so the
    overshoot is undone by adding the complement (moving the result slightly
    later). Because the complement is always under a minute, this correction
    step can only move the result within the same working window the
    whole-minute walk already landed inside -- it can never itself cross
    another day/working-hour boundary, unlike the remainder in the old
    truncate-then-add approach.
    """
    if _is_elapsed_lag_format(lag_format) or lag_minutes == 0:
        return anchor + timedelta(minutes=lag_minutes)

    whole_minutes = math.ceil(abs(lag_minutes))
    complement_minutes = whole_minutes - abs(lag_minutes)
    if lag_minutes > 0:
        base = compute_finish_at(anchor, whole_minutes, resolved_calendar.weekday_hours)
        return base - timedelta(minutes=complement_minutes)
    base = compute_start_at(anchor, whole_minutes, resolved_calendar.weekday_hours)
    return base + timedelta(minutes=complement_minutes)


def _resolve_predecessor_constraints(
    links: list[WfPlanningLinkSnapshot],
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    duration_minutes: int,
    resolved_calendar: ResolvedCalendar,
) -> list[datetime]:
    """Derive start_at lower-bound constraints from a task's predecessor links.

    MS Project link_type convention: 0=FF, 1=FS, 2=SF, 3=SS. ``lag_tenth_minute``
    is stored in tenths of a minute and converted to minutes here.

    FS and SS constraints are resolved directly from the predecessor's own
    stored ``finish_at``/``start_at`` -- exact, no approximation -- and,
    since E3-03's lag_format fix, calendar-aware for a working-time
    ``lag_format`` (see :func:`_resolve_lag_offset`).

    FF and SF constraints logically bound the *successor's finish* date, not
    its start: the predecessor's ``finish_at`` (FF) or ``start_at`` (SF) is
    first offset by the link's lag through :func:`_resolve_lag_offset` --
    the same calendar-aware primitive FS/SS use -- to get the successor's
    target *finish* date, which is then converted into a start constraint via
    :func:`compute_start_at_for_finish_at_or_after`. This makes FF and SF
    exact and calendar-aware too, on the same footing as FS/SS -- no raw
    wall-clock approximation remains for any of the four link types (6th/7th
    E3-03 PR review rounds: ``compute_start_at``, added for the FS/SS
    negative-lag fix, turned out to be exactly the backward primitive FF/SF
    needed too).

    Like FS/SS, FF and SF are lower bounds, not equalities: "the successor
    finishes no earlier than target_finish" (10th E3-03 PR review round).
    ``target_finish`` is not always itself a value the calendar can produce
    as an exact finish -- most commonly because a raw wall-clock
    (elapsed-format) lag lands it on a day with zero working capacity (e.g.
    a Saturday under a Mon-Fri calendar); FS/SS never hit this because an
    unreachable *start* is not an error (``compute_finish_at`` happily walks
    forward from any calendar day, working or not), but an unreachable exact
    *finish* used to be rejected outright by :func:`compute_start_at`. Using
    :func:`compute_start_at_for_finish_at_or_after` instead resolves the
    successor's start from the earliest finish that is both reachable under
    the calendar and at or after ``target_finish`` -- returning
    :func:`compute_start_at`'s own result verbatim whenever ``target_finish``
    is already exactly reachable (no behaviour change for that, the common,
    already-tested case), and only falling back to a later date when it is
    not.
    """
    constraints: list[datetime] = []
    for link in links:
        predecessor = tasks_by_uid.get(link.predecessor_uid)
        if predecessor is None:
            continue
        lag_minutes = (link.lag_tenth_minute or 0) / 10
        predecessor_finish = _to_naive_utc(predecessor.finish_at)
        predecessor_start = _to_naive_utc(predecessor.start_at)
        if link.link_type == 1 and predecessor_finish is not None:  # FS
            constraints.append(
                _resolve_lag_offset(
                    predecessor_finish, lag_minutes, link.lag_format, resolved_calendar
                )
            )
        elif link.link_type == 3 and predecessor_start is not None:  # SS
            constraints.append(
                _resolve_lag_offset(
                    predecessor_start, lag_minutes, link.lag_format, resolved_calendar
                )
            )
        elif link.link_type == 0 and predecessor_finish is not None:  # FF
            target_finish = _resolve_lag_offset(
                predecessor_finish, lag_minutes, link.lag_format, resolved_calendar
            )
            constraints.append(
                compute_start_at_for_finish_at_or_after(
                    target_finish, duration_minutes, resolved_calendar.weekday_hours
                )
            )
        elif link.link_type == 2 and predecessor_start is not None:  # SF
            target_finish = _resolve_lag_offset(
                predecessor_start, lag_minutes, link.lag_format, resolved_calendar
            )
            constraints.append(
                compute_start_at_for_finish_at_or_after(
                    target_finish, duration_minutes, resolved_calendar.weekday_hours
                )
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

    # Resolved before _resolve_predecessor_constraints (rather than only
    # afterwards, as before the E3-03 lag_format fix) because a working-time
    # FS/SS lag now needs the task's own calendar too, not just its duration.
    resolved_calendars = resolve_calendars_for_tasks(db, planning.project_id, {task.uid})
    resolved = resolved_calendars[task.uid]

    # _resolve_predecessor_constraints (via _resolve_lag_offset's own
    # compute_finish_at/compute_start_at calls for a working-time lag, and,
    # for FF/SF, its own additional compute_start_at call deriving the start
    # constraint from the target finish date) walks the calendar day by day
    # and can raise OverflowError -- not just ValueError -- when the walk is
    # pushed past datetime.max/date.max (e.g. a predecessor date close to
    # datetime.max combined with a positive lag). This is a
    # genuinely-invalid-input case from the caller's perspective, so it is
    # caught here and surfaced as the same 400 as any other schedule
    # validation failure.
    try:
        constraints = _resolve_predecessor_constraints(
            links, tasks_by_uid, duration_minutes, resolved_calendar=resolved
        )
    except (ValueError, OverflowError) as exc:
        raise PlanningTaskScheduleError(str(exc)) from exc

    if constraints:
        start_at = max(constraints)
    elif payload.start_at is not None:
        start_at = payload.start_at
    elif task.start_at is not None:
        start_at = _to_naive_utc(task.start_at)
    else:
        raise PlanningTaskScheduleError(
            "start_at is required for an automatically scheduled task without predecessors"
        )

    # compute_finish_at walks the calendar day by day too, and the same
    # datetime.max/date.max overflow risk applies here for start_at + a
    # large enough duration.
    try:
        finish_at = compute_finish_at(start_at, duration_minutes, resolved.weekday_hours)
    except (ValueError, OverflowError) as exc:
        raise PlanningTaskScheduleError(str(exc)) from exc

    task.start_at = start_at
    task.finish_at = finish_at
    task.duration_minutes = duration_minutes


def _discover_cascade_candidates(
    edited_task_uid: int,
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    links_by_predecessor: dict[int, list[WfPlanningLinkSnapshot]],
) -> set[int]:
    """Phase A of the issue #73 cascade: BFS forward from the edited task.

    Walks :class:`WfPlanningLinkSnapshot` edges from a task to the tasks that
    reference it as ``predecessor_uid`` (i.e. the opposite direction from
    :func:`_resolve_predecessor_constraints`, which walks a task back to its
    own predecessors). A manual successor is a dead end -- its own dates
    never move as a side effect of a predecessor edit, so nothing downstream
    of it can need recalculating *through* it either -- but it is still
    marked visited so a diamond or cycle in the link graph cannot revisit it
    and loop. A dangling link (``task_uid`` not in ``tasks_by_uid``) or a
    summary successor (its dates are derived from its children, never from a
    predecessor link -- see :func:`update_planning_task_schedule`'s own
    rejection of a direct edit on a summary task) is likewise treated as a
    dead end rather than crashing or being added to the candidate set.

    ``is_manual`` is nullable at the model level (``NULL`` when an imported
    MS Project task never carried an explicit ``<Manual>`` element -- see
    ``msproject_xml.py`` -- and is a genuinely reachable value in real data,
    not just a theoretical one). Only ``is_manual is False`` (confirmed
    automatic) is eligible for the cascade; ``None`` (never decided) must be
    treated exactly like ``True`` (explicitly manual) -- a dead end whose
    dates are left untouched -- rather than falsy-coerced into "confirmed
    automatic" and silently rescheduled while its own ``is_manual`` column
    stays ``NULL`` forever.

    Critically, this only *discovers* which tasks are affected -- it does
    not decide the order to recompute them in. A plain BFS/DFS visit order
    is not safe to also use as the recompute order whenever two branches of
    the walk reconverge on the same task (a diamond: B and C both successors
    of the edited task, D a successor of both B and C) -- see
    :func:`_topological_cascade_order`, which is responsible for that.
    """
    visited = {edited_task_uid}
    candidates: set[int] = set()
    queue: deque[int] = deque([edited_task_uid])
    while queue:
        current_uid = queue.popleft()
        for link in links_by_predecessor.get(current_uid, []):
            successor_uid = link.task_uid
            if successor_uid in visited:
                continue
            visited.add(successor_uid)
            successor = tasks_by_uid.get(successor_uid)
            if successor is None or successor.is_summary or successor.is_manual is not False:
                continue
            candidates.add(successor_uid)
            queue.append(successor_uid)
    return candidates


def _topological_cascade_order(
    edited_task_uid: int,
    candidates: set[int],
    links_by_task: dict[int, list[WfPlanningLinkSnapshot]],
) -> list[int]:
    """Phase B of the issue #73 cascade: Kahn's algorithm over ``candidates``.

    Required on top of :func:`_discover_cascade_candidates`'s BFS because of
    diamonds: if B and C are both successors of the edited task, and D is a
    successor of both B and C, D must only be recomputed after *both* B and
    C have themselves been recomputed -- a naive single-pass BFS/DFS visiting
    D through whichever of B/C is walked first would recompute D against one
    stale and one fresh predecessor.

    In-degree is counted only for edges whose source is the edited task
    itself or another candidate: an edge from a predecessor *outside* the
    affected set never needs to be waited for, because that predecessor's
    stored value has not changed and is already correct in ``tasks_by_uid``.

    ``waterfall.services.planning_links._validate_no_cycles`` already
    rejects a cyclic predecessor graph at link-write time, but this function
    does not trust that blindly: if Kahn's algorithm terminates with
    candidates that were never dequeued (their in-degree never reached
    zero), that is a residual invariant violation, surfaced as a
    :class:`PlanningTaskScheduleError` rather than silently dropping those
    tasks from the cascade or looping forever.

    ``edited_task_uid`` itself is also checked for a residual cycle looping
    back to it, not just cycles fully contained within ``candidates``: it is
    unconditionally treated as already resolved below (its own schedule was
    computed before this function ever runs -- see ``_release(edited_task_uid)``
    further down), so a candidate whose own predecessor link points back at
    ``edited_task_uid`` can never be made to wait on anything through the
    normal Kahn queue mechanism -- ``edited_task_uid`` never itself passes
    through that queue, so such an edge's source side can never decrement
    down to a dequeue. Left unchecked, that residual edge is invisible to
    both this function's in-degree bookkeeping (which only tracks in-degree
    for members of ``candidates``) and to the plain "unresolved candidates"
    check above, because the candidate on the other end of that edge can
    still resolve to in-degree 0 and be dequeued normally -- e.g.
    ``edited -> B -> edited``: B's only incoming edge is from
    ``edited_task_uid``, so B is released immediately and ``order == [B]``,
    even though B's own outgoing edge back to ``edited_task_uid`` means
    ``edited_task_uid``'s already-applied schedule was computed against B's
    stale, pre-cascade dates. This is therefore checked explicitly, up
    front, rather than relying on the queue to surface it.
    """
    in_degree: dict[int, int] = dict.fromkeys(candidates, 0)
    dependents_by_source: dict[int, list[int]] = defaultdict(list)
    for candidate_uid in candidates:
        for link in links_by_task.get(candidate_uid, []):
            source_uid = link.predecessor_uid
            if source_uid == edited_task_uid or source_uid in candidates:
                in_degree[candidate_uid] += 1
                dependents_by_source[source_uid].append(candidate_uid)

    residual_predecessors = sorted(
        {
            link.predecessor_uid
            for link in links_by_task.get(edited_task_uid, [])
            if link.predecessor_uid in candidates
        }
    )
    if residual_predecessors:
        raise PlanningTaskScheduleError(
            "Planning predecessor links contain a cycle that loops back to the task "
            f"being edited (uid={edited_task_uid}) through affected successor(s): "
            f"{residual_predecessors}"
        )

    queue: deque[int] = deque()

    def _release(source_uid: int) -> None:
        for dependent_uid in dependents_by_source.get(source_uid, []):
            in_degree[dependent_uid] -= 1
            if in_degree[dependent_uid] == 0:
                queue.append(dependent_uid)

    # The edited task's own schedule is already applied by the time this
    # function runs: it is never itself a candidate, but its outgoing edges
    # still have to be released into the queue exactly as though it had
    # already been dequeued -- otherwise a candidate whose only incoming
    # edge comes directly from the edited task (in-degree 1, which can never
    # reach 0 on its own since the edited task never goes through this same
    # queue) would never be queued at all. Safe to do unconditionally only
    # because the residual-cycle guard above already ruled out any edge
    # feeding back into edited_task_uid from a candidate.
    _release(edited_task_uid)

    order: list[int] = []
    while queue:
        current_uid = queue.popleft()
        order.append(current_uid)
        _release(current_uid)

    if len(order) != len(candidates):
        unresolved = sorted(candidates - set(order))
        raise PlanningTaskScheduleError(
            "Planning predecessor links contain a cycle among the tasks affected by this "
            f"schedule edit: {unresolved}"
        )
    return order


def _cascade_successor_schedules(
    db: Session,
    planning: WfPlanning,
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
    edited_task: WfPlanningTaskSnapshot,
) -> list[WfPlanningTaskSnapshot]:
    """Issue #73: reschedule every automatic-mode successor affected by editing ``edited_task``.

    Reuses :func:`_apply_automatic_schedule`/:func:`_apply_automatic_milestone_schedule`
    verbatim for each affected successor -- the same constraint-resolution
    logic a direct edit of that successor would go through, never a
    duplicated/divergent copy of it -- via a synthetic
    :class:`PlanningTaskScheduleUpdate` representing "no explicit override,
    just re-derive from the current predecessor links and the task's own
    already-stored duration/start as fallback anchor". ``finish_at`` is
    deliberately left unset (not in ``model_fields_set``): ``_apply_automatic_schedule``
    ignores it entirely, and setting it could otherwise wrongly trip
    ``_check_milestone_duration_and_finish_consistency`` for a milestone
    successor. For a milestone candidate, ``duration_minutes`` is instead
    explicitly passed as ``None`` (not populated from
    ``candidate.duration_minutes``, and not omitted from the constructor
    call either -- it still ends up in ``payload.model_fields_set``):
    ``_apply_automatic_milestone_schedule`` never reads it for anything
    except that same consistency check, which accepts an explicit ``None``
    value, and a milestone's duration is always definitionally 0 regardless
    of what a stale/drifted stored value happens to be (e.g. leftover from
    imported data) -- populating it from the stored value here would
    spuriously fail an otherwise-unrelated cascade the moment that stored
    value isn't ``None``/``0``.

    Unlike every other :class:`PlanningTaskScheduleUpdate` construction in
    this module, this one is built from already-stored database values
    rather than a validated request body, so it is not protected by the
    route's request-body 422->400 conversion. ``duration_minutes`` in
    particular has no upper-bound DB constraint and can be out of the
    schema's ``ge=0``/``le=...`` range for data that predates that bound or
    was imported from an MS Project XML file with no equivalent limit (see
    ``msproject_xml.parse_duration``); constructing the payload is wrapped
    below so a malformed stored value surfaces as this module's own
    :class:`PlanningTaskScheduleError` (converted by the route to a
    documented 400) instead of leaking a bare ``pydantic.ValidationError``
    as an uncaught 500.

    Each candidate is looked up using its *own* full incoming link list from
    ``links_by_task`` -- not just the edges discovered by the BFS -- because
    a successor can have other, unaffected predecessors too, and
    ``_resolve_predecessor_constraints`` already takes the max across all of
    them, exactly like a direct edit would.

    Returns the list of successor tasks actually recomputed (in topological
    order), so the caller can recalculate summary ancestors for each of
    them too, on top of ``edited_task``'s own.

    Known, accepted performance tradeoff (not fixed here): this loop calls
    :func:`_apply_automatic_schedule`/:func:`_apply_automatic_milestone_schedule`
    once per candidate, and each of those independently re-resolves its own
    task's calendar via :func:`resolve_calendars_for_tasks` (a fresh query
    per candidate rather than one batched resolution for the whole affected
    set); :func:`_recalculate_ancestor_summaries`, called once per touched
    task by the caller below, likewise rebuilds ``children_by_parent`` and
    re-resolves calendars per call rather than once for the whole batch.
    This is real, avoidable N+1-style query overhead for a long cascade
    chain or a wide diamond -- all still inside the single row lock the
    caller already holds, so it does serialize other writers longer than
    strictly necessary -- but it is not a correctness bug, and batching it
    properly would require changing
    :func:`_apply_automatic_schedule`'s/:func:`_apply_automatic_milestone_schedule`'s
    signatures to accept a pre-resolved calendar map, too large a change for
    this ticket. Deliberately left unoptimized here for typical planning
    sizes; not an oversight.
    """
    all_links = (
        db.query(WfPlanningLinkSnapshot)
        .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
        .all()
    )
    links_by_task: dict[int, list[WfPlanningLinkSnapshot]] = defaultdict(list)
    links_by_predecessor: dict[int, list[WfPlanningLinkSnapshot]] = defaultdict(list)
    for link in all_links:
        links_by_task[link.task_uid].append(link)
        links_by_predecessor[link.predecessor_uid].append(link)

    candidates = _discover_cascade_candidates(edited_task.uid, tasks_by_uid, links_by_predecessor)
    if not candidates:
        return []

    order = _topological_cascade_order(edited_task.uid, candidates, links_by_task)

    touched: list[WfPlanningTaskSnapshot] = []
    for candidate_uid in order:
        candidate = tasks_by_uid[candidate_uid]
        candidate_links = links_by_task.get(candidate_uid, [])
        try:
            synthetic_payload = PlanningTaskScheduleUpdate(
                is_manual=False,
                duration_minutes=None if candidate.is_milestone else candidate.duration_minutes,
                start_at=_to_naive_utc(candidate.start_at),
            )
        except ValidationError as exc:
            raise PlanningTaskScheduleError(
                f"Successor task {candidate_uid} has an out-of-range stored "
                "duration_minutes and cannot be automatically rescheduled"
            ) from exc
        # Mirrors the ValidationError handling immediately above: a
        # candidate's own stored data can independently violate
        # _apply_automatic_schedule's/_apply_automatic_milestone_schedule's
        # internal checks (most commonly duration_minutes<=0 or None on an
        # automatic-mode task -- realistic imported data, since MS Project
        # XML import writes duration_minutes=None whenever the <Duration>
        # element is absent, with is_manual set independently and no
        # cross-check) even when it passes the schema's own Field(ge=0, ...)
        # validation above and so never trips the ValidationError branch.
        # Without this, that pre-existing, unrelated degenerate data on a
        # cascade candidate raises a bare, unattributed
        # PlanningTaskScheduleError straight out of this loop, surfacing as a
        # 400 that looks like it is about the caller's own (perfectly valid)
        # edit rather than about this candidate's own stored data.
        try:
            if candidate.is_milestone:
                _apply_automatic_milestone_schedule(
                    db, planning, candidate_links, tasks_by_uid, candidate, synthetic_payload
                )
            else:
                _apply_automatic_schedule(
                    db, planning, tasks_by_uid, candidate_links, candidate, synthetic_payload
                )
        except PlanningTaskScheduleError as exc:
            raise PlanningTaskScheduleError(
                f"Successor task {candidate_uid} cannot be automatically rescheduled: {exc}"
            ) from exc
        touched.append(candidate)
    return touched


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

    Issue #73: after ``task``'s own schedule is applied, every automatic-mode
    successor transitively affected by the change -- other tasks whose
    :class:`WfPlanningLinkSnapshot` references ``task_uid`` (or a successor
    of it, and so on) as ``predecessor_uid`` -- is rescheduled too, via
    :func:`_cascade_successor_schedules`, so an automatic successor's
    FS/SS/FF/SF constraint against its *direct, non-summary* predecessor is
    always satisfied immediately, in the same request/response, rather than
    only becoming consistent the next time that successor happens to be
    edited directly. A manual successor is left untouched (dead end, its
    dates are frozen by definition), and nothing recomputes *through* it --
    but a task reachable through some other, still-live automatic path is
    still recomputed normally (see :func:`_discover_cascade_candidates`'s
    docstring for the manual-interrupts-chain case, and
    :func:`_topological_cascade_order`'s for why a diamond in the link graph
    needs a real topological sort rather than a plain BFS/DFS visit order).

    Known, documented, out-of-scope-for-#73 limitation: this cascade only
    walks forward from ``task_uid`` itself via direct predecessor links. It
    does *not* reach a task whose ``predecessor_uid`` points at a *summary*
    task, even when editing ``task`` changes that summary's own aggregate
    ``start_at``/``finish_at`` via :func:`_recalculate_ancestor_summaries`
    (which runs after this cascade, below). Nothing in
    ``planning_links.py``'s validation prevents a predecessor link from
    referencing a summary task (it only rejects "not found",
    self-referencing, and duplicate links), so this is a real, reachable
    gap -- see
    ``test_cascade_does_not_propagate_through_a_summary_task_acting_as_a_predecessor``
    -- but closing it is a materially larger change (cascading through
    summary-derived date changes, not just through direct predecessor
    edits) and is left as a candidate follow-up rather than fixed here.
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
        _apply_automatic_milestone_schedule(db, planning, links, tasks_by_uid, task, payload)
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

    # Issue #73: cascade the edit forward to every automatic-mode successor
    # transitively affected by it (see _cascade_successor_schedules). Must
    # run before the ancestor-summary recalculation below so that a
    # successor sharing a summary ancestor with `task` (e.g. a sibling under
    # the same summary parent) is reflected into that ancestor's min/max
    # window in the same pass, rather than the ancestor recalculation seeing
    # a stale successor date.
    cascaded_tasks = _cascade_successor_schedules(db, planning, tasks_by_uid, task)

    # _recalculate_ancestor_summaries recalculates every summary ancestor's
    # duration via _recalculate_summary_fields, which walks the affected
    # calendar day by day through compute_working_minutes_between. That walk
    # can raise ValueError (the iteration ceiling in _guard_max_days_walked)
    # or OverflowError (date arithmetic pushed past date.max) when a manually
    # scheduled task's start_at/finish_at is unreasonably far in the future
    # -- manual tasks have no server-side range validation (see
    # _apply_manual_schedule), so a task like that landing under a summary
    # ancestor is a genuinely-invalid-input case rather than an internal
    # error, and is surfaced as the same 400 as any other schedule
    # validation failure. This applies identically to a cascaded successor's
    # own ancestors, not just `task`'s -- _recalculate_ancestor_summaries is
    # naturally idempotent (re-derives purely from each ancestor's current
    # children on every call), so calling it once per touched task below is
    # correct regardless of call order.
    try:
        _recalculate_ancestor_summaries(db, planning, tasks_by_uid, task)
        for cascaded_task in cascaded_tasks:
            _recalculate_ancestor_summaries(db, planning, tasks_by_uid, cascaded_task)
    except (ValueError, OverflowError) as exc:
        raise PlanningTaskScheduleError(str(exc)) from exc
    return task
