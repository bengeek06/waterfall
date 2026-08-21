from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.resources import EstimateCostLine, EstimateTaskRow, TaskRoleAssignment
from waterfall.models.wf_core import WfChargeLine
from waterfall.services.msproject_xml import ParsedProject


def build_import_diff(
    db: Session, project: MsProject, parsed: ParsedProject
) -> list[dict[str, object]]:
    current = {
        task.uid: task for task in db.query(MsTask).filter(MsTask.project_id == project.id).all()
    }
    incoming = {task.uid: task for task in parsed.tasks}
    current_links = {
        (link.task_uid, link.predecessor_uid, link.link_type, link.lag_tenth_minute)
        for link in db.query(MsTaskLink).filter(MsTaskLink.project_id == project.id).all()
    }
    incoming_links = {
        (link.task_uid, link.predecessor_uid, link.link_type, link.lag_tenth_minute)
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
        referenced = (
            db.query(TaskRoleAssignment.id).filter(TaskRoleAssignment.task_id == task.id).first()
            or db.query(EstimateCostLine.id).filter(EstimateCostLine.task_id == task.id).first()
            or db.query(EstimateTaskRow.id).filter(EstimateTaskRow.task_id == task.id).first()
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
        for uid in affected_uids:
            items.append(
                {
                    "kind": "modified",
                    "uid": uid,
                    "message": f"Task UID {uid} predecessor links will be updated",
                    "fields": ["predecessor_links"],
                }
            )
    return items
