"""Live resolution of an `EstimateTaskRow`'s task-derived display fields (E12-08, #290).

Historically, `EstimateTaskRow.task_name`/`outline_number`/`outline_level`/
`parent_task_id`/`position` were written once, at estimate-creation time
(`create_project_estimate`, `api/routes/estimates.py`), and never touched
again -- renaming or moving a task afterwards had no effect on an already
-created devis. This module replaces that frozen snapshot with a live lookup
for a *draft* estimate only: the source of truth is the project's currently
displayed planning (`WfPlanningTaskSnapshot`) when one exists, or the legacy
`MsTask` table otherwise -- the same planning-affiche-or-not arbitration
already used throughout `api/routes/tasks.py`/`api/routes/planning_support.py`
(`project.displayed_planning_id`).

A **validated** estimate deliberately keeps reading the frozen stored columns
instead (callers simply never invoke `resolve_live_task_display` for one): a
validated devis is a priced snapshot of the past and must not silently drift
when a task is renamed or moved afterwards -- it no longer has a "live task"
representation to show. The stored columns are kept on `EstimateTaskRow` for
exactly this purpose (and are still written once at row-creation time, see
`create_project_estimate`/`_create_estimate_planning_task`); they are simply
no longer treated as authoritative for a draft estimate's reads.

Only the *label* and the *position in the task tree* of a task already a
member of the estimate (i.e. already backing an `EstimateTaskRow`) become
live -- the estimate's own task membership stays fixed at creation time. A
task added to the planning after the devis was created never retroactively
appears here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanningTaskSnapshot
from waterfall.models.resources import EstimateTaskRow


@dataclass(frozen=True)
class ResolvedTaskDisplay:
    """A single `EstimateTaskRow`'s task-derived fields, resolved live."""

    task_uid: int
    task_name: str
    outline_number: str | None
    outline_level: int | None
    parent_task_id: int | None
    position: int


def _index_task_uids(tasks: Iterable[MsTask]) -> dict[int, int]:
    """Shared ``MsTask.id -> MsTask.uid`` index.

    Factored out so ``resolve_task_uid_by_id`` and ``resolve_live_task_display``
    build this mapping the exact same way, rather than two independent
    implementations drifting apart (E12-08 Finding Moyenne #4, round 4
    review).
    """
    return {task.id: task.uid for task in tasks}


def resolve_task_uid_by_id(db: Session, project: MsProject) -> dict[int, int]:
    """Task_id -> uid lookup, independent of an estimate's draft/validated status.

    Unlike ``task_name``/``outline_number``/``outline_level``/``parent_task_id``/
    ``position`` -- only ever safe to read live for a *draft* estimate, see this
    module's docstring -- a task's ``uid`` is a stable identity that never
    drifts when the task is renamed or moved. So a caller building
    ``EstimateTaskRowRead.task_uid`` for a **validated** estimate (which must
    keep reading its other fields frozen) can still resolve ``task_uid`` this
    way instead of leaving it ``None``: it was previously always ``None`` for a
    validated estimate, even though ``EstimateTaskRow.task_id`` itself is still
    present and resolvable (E12-08 Finding Moyenne #4, round 4 review).
    """
    tasks = db.query(MsTask).filter(MsTask.project_id == project.id).all()
    return _index_task_uids(tasks)


def _depth_first_uids(rows: Iterable[tuple[int, int | None, int | None, int]]) -> list[int]:
    """Depth-first, sibling-sorted order over plain ``(uid, parent_uid, position, id)`` rows.

    Intentionally duplicated from
    ``api.routes.planning_support._order_uids_depth_first`` rather than
    imported: that module (and everything it transitively imports, including
    ``api.routes.projects``) itself imports from the ``waterfall.services``
    package at module scope, so a service reaching back into ``api.routes``
    would create a circular import at package-init time (``services/__init__``
    eagerly imports every service module). Keeping the small, dependency-free
    traversal duplicated here is simpler and safer than restructuring that
    layering for this one helper.
    """
    materialized = list(rows)
    known_uids = {uid for uid, _parent_uid, _position, _id in materialized}
    children_by_parent: dict[int | None, list[tuple[int, int | None, int | None, int]]] = {}
    for row in materialized:
        _uid, parent_uid, _position, _id = row
        parent = parent_uid if parent_uid in known_uids else None
        children_by_parent.setdefault(parent, []).append(row)

    def sort_key(row: tuple[int, int | None, int | None, int]) -> tuple[int, int, int]:
        _uid, _parent_uid, position, row_id = row
        return (0 if position is not None else 1, position or 0, row_id)

    for group in children_by_parent.values():
        group.sort(key=sort_key)

    ordered: list[int] = []
    visited: set[int] = set()

    def traverse(start: tuple[int, int | None, int | None, int]) -> None:
        stack = [start]
        while stack:
            node = stack.pop()
            uid = node[0]
            if uid in visited:
                continue
            visited.add(uid)
            ordered.append(uid)
            stack.extend(reversed(children_by_parent.get(uid, [])))

    for root in children_by_parent.get(None, []):
        traverse(root)
    # Guard against orphan cycles that never surface as roots.
    for row in sorted(materialized, key=sort_key):
        if row[0] not in visited:
            traverse(row)

    return ordered


def resolve_effective_task_uid(
    row: EstimateTaskRow,
    resolved: ResolvedTaskDisplay | None,
    task_uid_by_task_id: dict[int, int],
) -> int | None:
    """Shared ``task_uid`` fallback: ``resolved`` (live, draft-only) when present,
    else ``task_uid_by_task_id`` (``resolve_task_uid_by_id``, safe regardless of
    draft/validated status -- see that function's own docstring).

    Factored out so `to_estimate_task_row_read` (`api/routes/projects.py`) and
    the devis grid's merged ``row_number`` computation
    (`api/routes/estimates.py`'s `_load_estimate_grid_context`, E12-09/#291)
    compute a task row's `task_uid` the exact same way, rather than two
    independent implementations drifting apart -- the same rationale
    `_index_task_uids` above already documents (E12-08 Finding Moyenne #4).
    """
    return (
        resolved.task_uid
        if resolved is not None
        else (task_uid_by_task_id.get(row.task_id) if row.task_id is not None else None)
    )


def resolve_live_task_display(
    db: Session,
    project: MsProject,
    task_rows: Sequence[EstimateTaskRow],
) -> dict[int, ResolvedTaskDisplay]:
    """Resolve live task-derived fields for `task_rows`, keyed by `EstimateTaskRow.id`.

    Only ever called for a *draft* estimate (see module docstring) -- callers
    are responsible for that guard, since a validated estimate must keep
    reading the frozen stored columns instead.

    A row is silently omitted from the result (letting the caller fall back
    to its own stored columns) when it has no `task_id` at all, or when that
    `task_id` can no longer be resolved against a live task -- both are
    pre-existing degenerate states (see `_resolve_legacy_parent_task`'s own
    docstring), never expected in the common case.

    `position` is renumbered 1..N, depth-first, across only the tasks present
    in `task_rows` -- not a global rank over the whole project tree -- so a
    devis with 3 of a planning's 50 tasks still reports a dense, useful
    ordering for its own grid.
    """
    task_ids = {row.task_id for row in task_rows if row.task_id is not None}
    if not task_ids:
        return {}

    # Deliberately unfiltered by `task_ids`: a task's live parent can be any
    # task of the project, not just one already backing an EstimateTaskRow of
    # this estimate -- mirrors `create_project_estimate`'s own `task_by_uid`.
    legacy_tasks = db.query(MsTask).filter(MsTask.project_id == project.id).all()
    uid_by_task_id = _index_task_uids(legacy_tasks)
    task_id_by_uid = {task.uid: task.id for task in legacy_tasks}

    live_tasks: Sequence[WfPlanningTaskSnapshot | MsTask]
    if project.displayed_planning_id is not None:
        live_tasks = (
            db.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == project.displayed_planning_id)
            .all()
        )
    else:
        live_tasks = legacy_tasks
    by_uid: dict[int, WfPlanningTaskSnapshot | MsTask] = {task.uid: task for task in live_tasks}

    ordered_uids = _depth_first_uids(
        (task.uid, task.parent_uid, task.position, task.id) for task in live_tasks
    )
    present_uids = {uid_by_task_id[task_id] for task_id in task_ids if task_id in uid_by_task_id}
    position_by_uid = {
        uid: position
        for position, uid in enumerate((uid for uid in ordered_uids if uid in present_uids), 1)
    }

    resolved: dict[int, ResolvedTaskDisplay] = {}
    for row in task_rows:
        if row.task_id is None:
            continue
        uid = uid_by_task_id.get(row.task_id)
        if uid is None:
            continue
        live_task = by_uid.get(uid)
        if live_task is None:
            continue
        parent_task_id = (
            task_id_by_uid.get(live_task.parent_uid) if live_task.parent_uid is not None else None
        )
        resolved[row.id] = ResolvedTaskDisplay(
            task_uid=uid,
            task_name=live_task.name,
            outline_number=live_task.outline_number,
            outline_level=live_task.outline_level,
            parent_task_id=parent_task_id,
            position=position_by_uid.get(uid, row.position),
        )
    return resolved
