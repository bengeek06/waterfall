from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.wf_core import WfTaskEnrichment
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
    if db.query(MsTask.id).filter(MsTask.project_id == project.id).first() is not None:
        raise ValueError("Project already contains tasks")

    _apply_project_metadata(project, parsed)
    db.add(project)
    db.flush()
    now = datetime.now(UTC)
    tasks = [MsTask(**_task_kwargs(task, project.id)) for task in parsed.tasks]
    db.add_all(tasks)
    db.flush()
    _populate_parent_metadata(tasks)
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
    db.add_all(
        [
            MsTaskLink(
                project_id=project.id,
                task_uid=link.task_uid,
                predecessor_uid=link.predecessor_uid,
                link_type=link.link_type,
                lag_tenth_minute=link.lag_tenth_minute,
                lag_format=link.lag_format,
            )
            for link in parsed.links
        ]
    )
    db.flush()
    return len(parsed.tasks), len(parsed.links)
