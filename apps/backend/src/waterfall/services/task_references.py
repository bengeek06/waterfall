from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.resources import (
    EstimateCostLine,
    EstimateLine,
    EstimateTaskRow,
    TaskRoleAssignment,
)
from waterfall.models.wf_core import WfChargeLine


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
