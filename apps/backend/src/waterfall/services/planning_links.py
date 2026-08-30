from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.schemas.projects import TaskLinkWrite


class PlanningLinkError(ValueError):
    """A predecessor link command violates the planning link contract."""


class PlanningLinkNotFoundError(PlanningLinkError):
    """A task addressed by a predecessor link command does not exist."""


class PlanningLinkInvariantError(PlanningLinkError):
    """The planning predecessor links would violate a structural invariant."""


def _validate_no_cycles(edges: dict[int, list[int]]) -> None:
    visited: set[int] = set()
    visiting: set[int] = set()

    def visit(task_uid: int) -> None:
        if task_uid in visiting:
            raise PlanningLinkInvariantError("Planning predecessor links contain a cycle")
        if task_uid in visited:
            return
        visiting.add(task_uid)
        for predecessor_uid in edges.get(task_uid, []):
            visit(predecessor_uid)
        visiting.remove(task_uid)
        visited.add(task_uid)

    for task_uid in edges:
        visit(task_uid)


def replace_task_predecessor_links(
    db: Session,
    planning: WfPlanning,
    task_uid: int,
    links: list[TaskLinkWrite],
) -> None:
    tasks_uids = {
        task.uid
        for task in db.query(WfPlanningTaskSnapshot.uid)
        .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
        .all()
    }
    if task_uid not in tasks_uids:
        raise PlanningLinkNotFoundError(f"Task not found: {task_uid}")

    missing = [link.predecessor_uid for link in links if link.predecessor_uid not in tasks_uids]
    if missing:
        raise PlanningLinkNotFoundError(f"Task not found: {missing[0]}")

    self_referencing = [link for link in links if link.predecessor_uid == task_uid]
    if self_referencing:
        raise PlanningLinkError("A task cannot be its own predecessor")

    seen: set[tuple[int, int]] = set()
    for link in links:
        key = (link.predecessor_uid, link.link_type)
        if key in seen:
            raise PlanningLinkError(
                f"Duplicate predecessor link: predecessor_uid={link.predecessor_uid}, "
                f"link_type={link.link_type}"
            )
        seen.add(key)

    edges: dict[int, list[int]] = defaultdict(list)
    for link in (
        db.query(WfPlanningLinkSnapshot)
        .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
        .filter(WfPlanningLinkSnapshot.task_uid != task_uid)
        .all()
    ):
        edges[link.task_uid].append(link.predecessor_uid)
    edges[task_uid] = [link.predecessor_uid for link in links]
    _validate_no_cycles(edges)

    db.query(WfPlanningLinkSnapshot).filter(
        WfPlanningLinkSnapshot.planning_id == planning.id,
        WfPlanningLinkSnapshot.task_uid == task_uid,
    ).delete(synchronize_session=False)
    db.add_all(
        WfPlanningLinkSnapshot(
            planning_id=planning.id,
            task_uid=task_uid,
            predecessor_uid=link.predecessor_uid,
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in links
    )
    # The session is configured with autoflush=False, so the deletion and the
    # new rows above must be flushed explicitly for a same-transaction read
    # (e.g. the route capturing the response detail before commit) to see them.
    db.flush()
