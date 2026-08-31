from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from waterfall.models.resources import (
    EstimateCostLine,
    EstimateLine,
    EstimateTaskRow,
    TaskRoleAssignment,
)
from waterfall.models.wf_core import WfChargeLine

# Every column that keys a reference off the legacy ms_task.id -- kept as a
# single tuple so find_referenced_task_uids can batch each one into a single
# IN (...) query instead of re-checking is_task_referenced's five filters
# once per task.
_TASK_ID_REFERENCE_COLUMNS = (
    TaskRoleAssignment.task_id,
    EstimateCostLine.task_id,
    EstimateLine.task_id,
    EstimateTaskRow.task_id,
    EstimateTaskRow.parent_task_id,
)


def is_task_referenced(
    db: Session,
    *,
    project_id: int,
    task_uid: int,
    task_id: int | None,
) -> bool:
    if task_id is not None and (
        db.query(TaskRoleAssignment.id).filter(TaskRoleAssignment.task_id == task_id).first()
        is not None
        or db.query(EstimateCostLine.id).filter(EstimateCostLine.task_id == task_id).first()
        is not None
        or db.query(EstimateLine.id).filter(EstimateLine.task_id == task_id).first() is not None
        or db.query(EstimateTaskRow.id).filter(EstimateTaskRow.task_id == task_id).first()
        is not None
        or db.query(EstimateTaskRow.id).filter(EstimateTaskRow.parent_task_id == task_id).first()
        is not None
    ):
        return True

    return (
        db.query(WfChargeLine.id)
        .filter(WfChargeLine.project_id == project_id)
        .filter(WfChargeLine.task_uid == task_uid)
        .first()
        is not None
    )


def find_referenced_task_uids(
    db: Session,
    *,
    project_id: int,
    task_id_by_uid: dict[int, int | None],
) -> set[int]:
    """Batch variant of :func:`is_task_referenced` for a whole selection of task uids.

    ``task_id_by_uid`` maps every planning snapshot uid under consideration to
    its bridged legacy ``ms_task.id`` (or ``None`` when the uid has no legacy
    row). Runs one ``IN (...)``-batched query per referencing table instead of
    up to five queries per uid, so a large cascade selection under a row lock
    (see :func:`waterfall.services.planning_tree.delete_planning_tasks`) does
    not turn into an N+1 sequence of round trips.
    """
    if not task_id_by_uid:
        return set()

    uids_by_task_id: dict[int, set[int]] = defaultdict(set)
    for uid, task_id in task_id_by_uid.items():
        if task_id is not None:
            uids_by_task_id[task_id].add(uid)
    task_ids = set(uids_by_task_id)

    referenced: set[int] = set()

    if task_ids:
        for column in _TASK_ID_REFERENCE_COLUMNS:
            for (task_id,) in db.query(column).filter(column.in_(task_ids)).distinct():
                referenced.update(uids_by_task_id[task_id])

    task_uids = set(task_id_by_uid)
    for (task_uid,) in (
        db.query(WfChargeLine.task_uid)
        .filter(WfChargeLine.project_id == project_id)
        .filter(WfChargeLine.task_uid.in_(task_uids))
        .distinct()
    ):
        referenced.add(task_uid)

    return referenced
