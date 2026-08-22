from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    EstimateCostLine,
    EstimateLine,
    EstimateTaskRow,
    TaskRoleAssignment,
)
from waterfall.models.wf_core import WfChargeLine
from waterfall.services.msproject_xml import ParsedProject


def build_import_diff(
    db: Session, project: MsProject, parsed: ParsedProject
) -> list[dict[str, object]]:
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
    legacy_tasks = (
        db.query(MsTask).filter(MsTask.project_id == project.id).all() if displayed is None else []
    )
    if displayed is None:
        current = {task.uid: task for task in legacy_tasks}
    incoming = {task.uid: task for task in parsed.tasks}
    link_query = (
        db.query(WfPlanningLinkSnapshot).filter(WfPlanningLinkSnapshot.planning_id == displayed.id)
        if displayed is not None
        else db.query(MsTaskLink).filter(MsTaskLink.project_id == project.id)
    )
    current_links = {
        (
            link.task_uid,
            link.predecessor_uid,
            link.link_type,
            link.lag_tenth_minute,
            link.lag_format,
        )
        for link in link_query.all()
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
        task = current[uid]
        legacy_task_id = next(
            (legacy.id for legacy in legacy_tasks if legacy.uid == uid),
            task.id if displayed is None else None,
        )
        referenced = (
            legacy_task_id is not None
            and (
                db.query(TaskRoleAssignment.id)
                .filter(TaskRoleAssignment.task_id == legacy_task_id)
                .first()
                or db.query(EstimateCostLine.id)
                .filter(EstimateCostLine.task_id == legacy_task_id)
                .first()
                or db.query(EstimateLine.id).filter(EstimateLine.task_id == legacy_task_id).first()
                or db.query(EstimateTaskRow.id)
                .filter(EstimateTaskRow.task_id == legacy_task_id)
                .first()
            )
            or db.query(WfChargeLine.id)
            .filter(WfChargeLine.project_id == project.id, WfChargeLine.task_uid == uid)
            .first()
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
    return items
