from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.schemas.projects import PlanningTaskMove
from waterfall.services.calendar_schedule import (
    ResolvedCalendar,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
)


class PlanningTreeMoveError(ValueError):
    """A hierarchy move command violates the planning tree contract."""


class PlanningTreeInvariantError(PlanningTreeMoveError):
    """The planning hierarchy would violate a structural invariant."""


class PlanningTreeMoveNotFoundError(PlanningTreeMoveError):
    """A task addressed by a hierarchy move command does not exist."""


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
