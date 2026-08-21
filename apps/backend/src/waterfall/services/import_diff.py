from __future__ import annotations

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask
from waterfall.services.msproject_xml import ParsedProject


def build_import_diff(
    db: Session, project: MsProject, parsed: ParsedProject
) -> list[dict[str, object]]:
    current = {
        task.uid: task for task in db.query(MsTask).filter(MsTask.project_id == project.id).all()
    }
    incoming = {task.uid: task for task in parsed.tasks}
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
        items.append(
            {
                "kind": "removed",
                "uid": uid,
                "message": f"Task UID {uid} will be removed",
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
    return items
