from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.resources import EstimateCostLine, EstimateTaskRow, TaskRoleAssignment
from waterfall.models.wf_core import WfChargeLine, WfTaskEnrichment
from waterfall.services.msproject_xml import ParsedProject, parse_msproject_xml


def _populate_parent_metadata(tasks: list[MsTask]) -> None:
    by_outline = {
        task.outline_number: task
        for task in tasks
        if task.outline_number and all(part.isdigit() for part in task.outline_number.split("."))
    }
    for task in tasks:
        if not task.outline_number or not all(
            part.isdigit() for part in task.outline_number.split(".")
        ):
            continue
        parts = task.outline_number.split(".")
        task.position = int(parts[-1])
        parent = by_outline.get(".".join(parts[:-1]))
        task.parent_uid = parent.uid if parent is not None else None


def _apply_project_metadata(project: MsProject, parsed: ParsedProject) -> None:
    project.external_uid = parsed.external_uid
    project.source_version = parsed.source_version
    project.save_version_out = parsed.save_version
    project.schedule_from_start = parsed.schedule_from_start
    project.start_date = parsed.start_date
    project.finish_date = parsed.finish_date
    project.calendar_uid = parsed.calendar_uid
    project.minutes_per_day = parsed.minutes_per_day
    project.minutes_per_week = parsed.minutes_per_week
    project.days_per_month = parsed.days_per_month
    project.currency_code = parsed.currency_code


def _task_kwargs(task: Any, project_id: int) -> dict[str, object]:
    return {
        "project_id": project_id,
        "uid": task.uid,
        "id_display": task.id_display,
        "name": task.name,
        "task_type": task.task_type,
        "outline_number": task.outline_number,
        "outline_level": task.outline_level,
        "wbs": task.wbs,
        "start_at": task.start_at,
        "finish_at": task.finish_at,
        "duration_minutes": task.duration_minutes,
        "duration_format": task.duration_format,
        "percent_complete": task.percent_complete,
        "is_summary": task.is_summary,
        "is_milestone": task.is_milestone,
        "calendar_uid": task.calendar_uid,
    }


def import_tasks_and_links(db: Session, xml_bytes: bytes, project: MsProject) -> tuple[int, int]:
    parsed = parse_msproject_xml(xml_bytes)
    _apply_project_metadata(project, parsed)
    db.add(project)
    db.flush()
    now = datetime.now(UTC)
    incoming_by_uid = {task.uid: task for task in parsed.tasks}
    existing_by_uid = {
        task.uid: task for task in db.query(MsTask).filter(MsTask.project_id == project.id).all()
    }
    removed = [task for uid, task in existing_by_uid.items() if uid not in incoming_by_uid]
    for task in removed:
        referenced = (
            db.query(TaskRoleAssignment.id).filter(TaskRoleAssignment.task_id == task.id).first()
            or db.query(EstimateCostLine.id).filter(EstimateCostLine.task_id == task.id).first()
            or db.query(EstimateTaskRow.id).filter(EstimateTaskRow.task_id == task.id).first()
            or db.query(WfChargeLine.id)
            .filter(WfChargeLine.project_id == project.id, WfChargeLine.task_uid == task.uid)
            .first()
        )
        if referenced:
            raise ValueError(f"Task UID {task.uid} is referenced and cannot be removed")
    for task in removed:
        task.parent_uid = None
        db.query(MsTaskLink).filter(
            MsTaskLink.project_id == project.id,
            (MsTaskLink.task_uid == task.uid) | (MsTaskLink.predecessor_uid == task.uid),
        ).delete(synchronize_session=False)
        db.query(WfTaskEnrichment).filter(
            WfTaskEnrichment.project_id == project.id,
            WfTaskEnrichment.task_uid == task.uid,
        ).delete(synchronize_session=False)
    db.flush()
    for task in removed:
        db.delete(task)
    db.flush()

    tasks: list[MsTask] = []
    for parsed_task in parsed.tasks:
        task = existing_by_uid.get(parsed_task.uid)
        if task is None:
            task = MsTask(**_task_kwargs(parsed_task, project.id))
            db.add(task)
        else:
            structure_key = task.structure_key
            structure_kind = task.structure_kind
            for field, value in _task_kwargs(parsed_task, project.id).items():
                if field not in {"project_id", "uid"}:
                    setattr(task, field, value)
            task.structure_key = structure_key
            task.structure_kind = structure_kind
        task.parent_uid = None
        tasks.append(task)
    db.flush()
    _populate_parent_metadata(tasks)
    db.query(MsTaskLink).filter(MsTaskLink.project_id == project.id).delete(
        synchronize_session=False
    )
    db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project.id).delete(
        synchronize_session=False
    )
    db.add_all(
        [
            WfTaskEnrichment(
                project_id=project.id,
                task_uid=task.uid,
                description=task.notes,
                created_at=now,
                updated_at=now,
            )
            for task in parsed.tasks
            if task.notes is not None
        ]
    )
    db.add_all([MsTaskLink(project_id=project.id, **link.__dict__) for link in parsed.links])
    db.flush()
    return len(parsed.tasks), len(parsed.links)
