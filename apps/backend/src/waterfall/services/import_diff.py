from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.calendar_schedule import (
    NoUsableCalendarError,
    ResolvedCalendar,
    compute_finish_at,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
)
from waterfall.services.msproject_xml import ParsedProject, ParsedTask, outline_parent_uids
from waterfall.services.task_references import is_task_referenced


@dataclass(frozen=True)
class _MismatchCandidate:
    """A task from the imported file eligible for the calendar-mismatch
    diagnostic (issue #176), with the span/duration to check already resolved
    from the file alone -- before any calendar is consulted.

    For a leaf task, ``start_at``/``finish_at`` are the task's own file
    values. For a summary task, they are its children's span **within the
    imported file** (see :func:`_summary_children_span`), mirroring
    :func:`waterfall.services.planning_tree._recalculate_summary_dates`.
    """

    is_summary: bool
    start_at: datetime
    finish_at: datetime
    file_duration_minutes: int


def _summary_children_span(children: list[ParsedTask]) -> tuple[datetime, datetime] | None:
    """Span ``[min(start_at), max(finish_at)]`` of a summary task's own
    children as recorded in the imported file, mirroring
    :func:`waterfall.services.planning_tree._recalculate_summary_dates` --
    except read-only over ``ParsedTask`` and never touching
    ``duration_minutes`` itself.

    Returns ``None`` when no child carries a start_at/finish_at at all (same
    guard as the function it mirrors), meaning the summary task is excluded
    from the diagnostic entirely.
    """
    starts = [child.start_at for child in children if child.start_at is not None]
    finishes = [child.finish_at for child in children if child.finish_at is not None]
    if not starts or not finishes:
        return None
    return min(starts), max(finishes)


def _task_span(task: ParsedTask, children: list[ParsedTask]) -> tuple[datetime, datetime] | None:
    """The ``[start_at, finish_at]`` span to check ``task`` against, or
    ``None`` when it carries too little date information to compare at all
    (an undated leaf, or a summary whose file children carry no date --
    see :func:`_summary_children_span`)."""
    if task.is_summary:
        return _summary_children_span(children)
    if task.start_at is None or task.finish_at is None:
        return None
    return task.start_at, task.finish_at


def _calendar_mismatch_candidates(
    tasks: tuple[ParsedTask, ...],
) -> dict[int, _MismatchCandidate]:
    """Tasks eligible for the calendar-mismatch diagnostic: datable,
    confirmed-automatic tasks only.

    ``is_manual is not False`` excludes both explicitly manual (``True``) and
    undecided (``None``) tasks -- the same "confirmed automatic" convention
    already used by ``waterfall.services.planning_tree`` for cascading a
    schedule edit, so a task MS Project never marked ``<Manual>`` at all is
    treated like a manual one here too, never flagged.
    """
    tasks_by_uid = {task.uid: task for task in tasks}
    parent_uids = outline_parent_uids((task.uid, task.outline_number) for task in tasks)
    children_by_parent: dict[int, list[ParsedTask]] = defaultdict(list)
    for uid, parent_uid in parent_uids.items():
        if parent_uid is not None:
            children_by_parent[parent_uid].append(tasks_by_uid[uid])

    candidates: dict[int, _MismatchCandidate] = {}
    for task in tasks:
        if task.is_manual is not False or task.duration_minutes is None:
            continue
        span = _task_span(task, children_by_parent.get(task.uid, []))
        if span is None:
            continue
        candidates[task.uid] = _MismatchCandidate(
            is_summary=task.is_summary,
            start_at=span[0],
            finish_at=span[1],
            file_duration_minutes=task.duration_minutes,
        )
    return candidates


def _resolve_calendars_omitting_unusable(
    db: Session, project_id: int, task_uids: set[int]
) -> dict[int, ResolvedCalendar]:
    """Batch-resolve calendars for the calendar-mismatch diagnostic, omitting
    -- rather than failing the whole diff on -- any task
    :func:`resolve_calendars_for_tasks` cannot resolve a usable calendar for
    (issue #176's read-only counterpart to issue #109's
    :class:`~waterfall.services.calendar_schedule.NoUsableCalendarError`).

    Peels off one unresolvable uid at a time and retries, so the common case
    (every task resolves) still costs a single batched call, and only tasks
    that genuinely can't be resolved add an extra round trip each.
    """
    remaining = set(task_uids)
    while remaining:
        try:
            return resolve_calendars_for_tasks(db, project_id, remaining)
        except NoUsableCalendarError as exc:
            remaining.discard(exc.task_uid)
    return {}


def _calendar_mismatch_item(
    uid: int, candidate: _MismatchCandidate, weekday_hours: ResolvedCalendar
) -> dict[str, object] | None:
    """Build a single ``calendar_mismatch`` diff item, or ``None`` when the
    file's duration already matches what Waterfall's calendar would compute.

    A summary task's span is taken as-is from the file (``compute_finish_at``
    does not apply to it); only a leaf task's ``finish_at`` is recomputed
    from its own file ``start_at``/``duration_minutes``, exactly like
    ``_apply_automatic_schedule`` does for a real automatic reschedule.
    """
    hours = weekday_hours.weekday_hours
    expected_duration_minutes = max(
        0,
        compute_working_minutes_between(candidate.start_at, candidate.finish_at, hours),
    )
    if candidate.is_summary:
        mismatched = expected_duration_minutes != candidate.file_duration_minutes
    else:
        expected_finish_at = compute_finish_at(
            candidate.start_at, candidate.file_duration_minutes, hours
        )
        mismatched = expected_finish_at != candidate.finish_at
    if not mismatched:
        return None
    return {
        "kind": "calendar_mismatch",
        "uid": uid,
        "message": (
            f"Task UID {uid} file duration ({candidate.file_duration_minutes} min) differs "
            f"from the duration Waterfall's calendar would compute ({expected_duration_minutes} "
            "min)"
        ),
        "fields": ["duration_minutes"],
        "calendar_mismatch": {
            "task_uid": uid,
            "file_duration_minutes": candidate.file_duration_minutes,
            "expected_duration_minutes": expected_duration_minutes,
        },
    }


def _calendar_mismatch_items(
    db: Session, project_id: int, tasks: tuple[ParsedTask, ...]
) -> list[dict[str, object]]:
    """Diagnose, for every eligible task in the imported file, whether its
    duration diverges from what Waterfall's own calendar engine would compute
    for it (issue #176). Purely a read-only, non-blocking diagnostic: it
    never writes anything and never raises to the caller.
    """
    candidates = _calendar_mismatch_candidates(tasks)
    if not candidates:
        return []
    resolved_calendars = _resolve_calendars_omitting_unusable(db, project_id, set(candidates))
    items: list[dict[str, object]] = []
    for uid in sorted(resolved_calendars):
        item = _calendar_mismatch_item(uid, candidates[uid], resolved_calendars[uid])
        if item is not None:
            items.append(item)
    return items


def build_import_diff(
    db: Session,
    project: MsProject,
    parsed: ParsedProject,
    *,
    include_calendar_mismatch: bool = True,
) -> list[dict[str, object]]:
    """Build the full import diff (issue #109 lock-safety note, issue #176):

    ``include_calendar_mismatch`` defaults to ``True`` for the actual
    ``GET /imports/{batch_id}/diff`` preview endpoint (``get_batch_diff``,
    unlocked), but must be passed ``False`` by
    ``api.routes.imports._reject_diff_conflicts`` -- called from
    ``_run_confirmed_import`` while still holding the ``SELECT ... FOR
    UPDATE`` project-row lock taken by ``_relock_pending_batch`` -- which only
    ever reads ``kind == "conflict"`` items and would otherwise pay for
    calendar resolution (plus a DB round trip per unresolvable task, see
    :func:`_resolve_calendars_omitting_unusable`) entirely under that lock for
    a result it never consumes. This is the exact anti-pattern already
    documented elsewhere in ``imports.py`` (see the comments guarding against
    avoidable costly work while holding this same lock).
    """
    displayed = (
        db.query(WfPlanning)
        .filter(WfPlanning.project_id == project.id)
        .filter(WfPlanning.id == project.displayed_planning_id)
        .one_or_none()
        if project.displayed_planning_id is not None
        else None
    )
    snapshot_tasks = (
        db.query(WfPlanningTaskSnapshot)
        .filter(WfPlanningTaskSnapshot.planning_id == displayed.id)
        .all()
        if displayed is not None
        else []
    )
    current = {task.uid: task for task in snapshot_tasks}
    incoming = {task.uid: task for task in parsed.tasks}
    link_query = (
        db.query(WfPlanningLinkSnapshot).filter(WfPlanningLinkSnapshot.planning_id == displayed.id)
        if displayed is not None
        else None
    )
    current_link_rows = link_query.all() if link_query is not None else []
    current_links = {
        (
            link.task_uid,
            link.predecessor_uid,
            link.link_type,
            link.lag_tenth_minute,
            link.lag_format,
        )
        for link in current_link_rows
    }
    incoming_links = {
        (
            link.task_uid,
            link.predecessor_uid,
            link.link_type,
            link.lag_tenth_minute,
            link.lag_format,
        )
        for link in parsed.links
    }
    items: list[dict[str, object]] = []
    for uid in sorted(incoming.keys() - current.keys()):
        items.append(
            {
                "kind": "added",
                "uid": uid,
                "message": f"Task UID {uid} will be added",
                "fields": [],
            }
        )
    for uid in sorted(current.keys() - incoming.keys()):
        legacy_task_id = (
            db.query(MsTask.id).filter(MsTask.project_id == project.id, MsTask.uid == uid).scalar()
        )
        referenced = is_task_referenced(
            db,
            project_id=project.id,
            task_uid=uid,
            task_id=legacy_task_id,
        )
        items.append(
            {
                "kind": "conflict" if referenced else "removed",
                "uid": uid,
                "message": (
                    f"Task UID {uid} is referenced and cannot be removed"
                    if referenced
                    else f"Task UID {uid} will be removed"
                ),
                "fields": [],
            }
        )
    fields = ("name", "start_at", "finish_at", "duration_minutes", "task_type", "is_milestone")
    for uid in sorted(current.keys() & incoming.keys()):
        old = current[uid]
        new = incoming[uid]
        changed = [field for field in fields if getattr(old, field) != getattr(new, field)]
        if changed:
            items.append(
                {
                    "kind": "modified",
                    "uid": uid,
                    "message": f"Task UID {uid} will be updated",
                    "fields": changed,
                }
            )
    if current_links != incoming_links:
        affected_uids = sorted(
            {link[0] for link in current_links.symmetric_difference(incoming_links)}
        )
        changes = current_links.symmetric_difference(incoming_links)
        for uid in affected_uids:
            items.append(
                {
                    "kind": "modified",
                    "uid": uid,
                    "message": f"Task UID {uid} predecessor links will be updated",
                    "fields": ["predecessor_links"],
                    "link_changes": [
                        {
                            "action": "removed" if link in current_links else "added",
                            "taskUid": link[0],
                            "predecessorUid": link[1],
                            "linkType": link[2],
                            "lagTenthMinute": link[3],
                            "lagFormat": link[4],
                        }
                        for link in changes
                        if link[0] == uid
                    ],
                }
            )
    if include_calendar_mismatch:
        items.extend(_calendar_mismatch_items(db, project.id, parsed.tasks))
    return items
