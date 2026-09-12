from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.calendar_schedule import (
    NoUsableCalendarError,
    ResolvedCalendar,
    compute_finish_at,
    compute_working_minutes_between,
    resolve_calendars_for_tasks,
)
from waterfall.services.msproject_xml import ParsedProject, ParsedTask, outline_parent_uids

logger = logging.getLogger(__name__)


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
    cost_losses: Mapping[int, list[dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    """Build the full import diff (issue #176, E14-06/#332).

    ``cost_losses`` carries Règle 3's safeguard, keyed by the external uid of the
    vanished task it belongs to: the cost facets that confirming this import would
    destroy, named so the removal is never silent. It is computed against the
    **revision** by :func:`waterfall.services.revision_import.plan_import` and
    injected rather than read here, because this function still describes the
    legacy snapshots -- the two tables the import writes in parallel until #333
    migrates the devis stack off `ms_task`. Unifying the whole diff onto the
    revision waits for the calendar-mismatch diagnostic below, which resolves
    calendars per legacy task uid and moves to the planning facet with its
    consumers.

    One caller, one mode
    --------------------

    This function used to take an ``include_calendar_mismatch`` flag, passed
    ``False`` by ``api.routes.imports._reject_diff_conflicts`` so that the
    calendar-mismatch diagnostic (and its round trip per unresolvable task, see
    :func:`_resolve_calendars_omitting_unusable`) would not run while that
    pre-flight held the ``SELECT ... FOR UPDATE`` project-row lock. E14-06 removed
    the pre-flight along with its 409 ``IMPORT_CONFLICT`` (#325), so the only
    caller left is the unlocked ``GET /imports/{batch_id}/diff`` preview, which
    wants the diagnostic. The flag went with the caller it existed for; the
    property it protected is still pinned by
    ``test_confirmed_run_never_resolves_calendars_under_the_project_lock``.
    """
    losses: Mapping[int, list[dict[str, object]]] = {} if cost_losses is None else cost_losses
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
    # No reference guard, on purpose (EPIC #326, resolves #325): a re-import targets a
    # **draft**, which is precisely where the user is entitled to remove anything. What
    # used to be a 409 ``IMPORT_CONFLICT`` raised by ``is_task_referenced`` is replaced
    # by the only rule left -- a validated revision refuses every write -- plus Règle
    # 3's safeguard, which names the chiffrage the removal takes away instead of
    # forbidding it.
    removed_uids = current.keys() - incoming.keys()
    orphaned_uids = _unattributable_loss_uids(losses, removed_uids, project.id)
    for uid in sorted(removed_uids | orphaned_uids):
        items.append(_removed_item(uid, losses.get(uid, []), synthesised=uid in orphaned_uids))
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
    items.extend(_calendar_mismatch_items(db, project.id, parsed.tasks))
    return items


def _removed_item(
    uid: int, cost_losses: list[dict[str, object]], *, synthesised: bool
) -> dict[str, object]:
    """One ``removed`` diff item, real or synthesised.

    ``synthesised`` marks the degraded case of
    :func:`_unattributable_loss_uids`: the **revision** removes this uid, the
    displayed legacy planning never carried it, so there is no snapshot row the item
    could have been derived from. The ``kind`` stays ``removed`` all the same,
    because the statement is true of the import as a whole -- confirming this batch
    does delete that node and does destroy the chiffrage listed here. Only the
    message says where it comes from.
    """
    message = (
        f"Task UID {uid} will be removed from the revision (the displayed planning does "
        "not carry it)"
        if synthesised
        else f"Task UID {uid} will be removed"
    )
    return {
        "kind": "removed",
        "uid": uid,
        "message": message,
        "fields": [],
        "cost_losses": cost_losses,
    }


def _unattributable_loss_uids(
    losses: Mapping[int, list[dict[str, object]]],
    removed_uids: AbstractSet[int],
    project_id: int,
) -> set[int]:
    """Uids whose Règle 3 warning has no ``removed`` item of its own to appear on.

    The safeguard joins two sources of truth by an external uid: the losses come
    from the **revision** the confirmed run writes into, the ``removed`` items from
    the **displayed legacy planning**. A uid the revision knows and the snapshot does
    not has no item to hang its warning on, so without this the warning would simply
    not be rendered -- money about to be destroyed, silently absent from the dialog
    that confirms destroying it.

    Reachable, through public endpoints answering 200/202 only
    ---------------------------------------------------------

    An earlier reading of this seam called the condition unreachable, on the grounds
    that creating a planning copies the tasks so its snapshot carries every uid the
    revision does. That is true and beside the point: ``set_displayed_planning``
    (``POST /projects/{id}/plannings/{planning_id}/display``) accepts **any** planning
    of the project, including an older one with a different uid set. Import ``(1, 2)``,
    validate the planning, import ``(1, 2, 3)`` -- a second planning is created and
    displayed -- then display the first again, and the revision knows uid 3 while the
    displayed snapshot does not. It is pinned end to end by
    ``test_a_loss_the_displayed_planning_cannot_attribute_is_degraded_not_five_hundred``.

    No route writes a ``RevisionCostFacet`` yet, so nothing in production reaches it
    today; #333 is the issue that opens that write.

    Degrade, do not refuse
    ----------------------

    This used to raise, and a raise meant a 500 on the preview. That destroys more
    than it protects: ``ImportDiffResponse.cost_losses`` -- the deduplicated total,
    the only summable figure Règle 3 has -- is read straight off the revision diff and
    never passes through this join, so it *survives* a degradation and does **not**
    survive a 500. Refusing therefore leaves the confirmation screen with neither the
    total nor the items, which is a worse under-report than the one it was guarding
    against. So the preview is served, the losses are attributed to a synthesised
    ``removed`` item (see :func:`_removed_item`) rather than dropped, and the failure
    is made loud **for the developer** -- a WARNING naming the uids -- instead of loud
    for the user.

    ``WARNING`` and not ``ERROR`` (#332 review, B-2), precisely because the section
    above shows the condition is reached by a *supported* user action: redisplaying an
    older planning answers 200, and after #333 a user who then refreshes the preview
    five times would emit five ``ERROR`` records without a stack, for a state neither
    the operator nor the platform can repair -- it is the user's display choice. Any
    alerting rule keyed on ``ERROR`` would fire on legitimate product usage. The
    record says exactly the same thing to a developer without also claiming an
    incident.
    """
    orphaned = set(losses) - set(removed_uids)
    if orphaned:
        logger.warning(
            "import_diff.cost_loss_unattributed uids=%s",
            sorted(orphaned),
            extra={"project_id": project_id, "orphaned_task_uids": sorted(orphaned)},
        )
    return orphaned
