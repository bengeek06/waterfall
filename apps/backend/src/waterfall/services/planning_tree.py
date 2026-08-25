from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.schemas.projects import PlanningTaskMove


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
    return roots


def _recalculate_outline(tasks_by_uid: dict[int, WfPlanningTaskSnapshot]) -> None:
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

    update_children(None, "", 1)


def _validate_target_parent(
    target_parent_uid: int | None,
    selected_roots: list[int],
    tasks_by_uid: dict[int, WfPlanningTaskSnapshot],
) -> None:
    if target_parent_uid is not None and target_parent_uid not in tasks_by_uid:
        raise PlanningTreeMoveNotFoundError(f"Task not found: {target_parent_uid}")
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

    moved = sorted((tasks_by_uid[task_uid] for task_uid in selected_roots), key=_task_order)
    target_siblings = siblings_by_parent[command.target_parent_uid]
    if command.position > len(target_siblings) + 1:
        raise PlanningTreeMoveError("position is outside the target sibling range")
    target_siblings[command.position - 1 : command.position - 1] = moved
    for task in moved:
        task.parent_uid = command.target_parent_uid

    for siblings in siblings_by_parent.values():
        for position, task in enumerate(siblings, start=1):
            task.position = position
    _recalculate_outline(tasks_by_uid)
