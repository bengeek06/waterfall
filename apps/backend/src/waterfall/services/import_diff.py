from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.msproject_xml import ParsedProject
from waterfall.services.task_references import is_task_referenced


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
    return items
