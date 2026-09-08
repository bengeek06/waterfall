from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.msproject_xml import ParsedProject, outline_parent_uids, parse_msproject_xml
from waterfall.services.project_lifecycle import ensure_project_mutable


def _populate_parent_metadata(tasks: list[WfPlanningTaskSnapshot]) -> None:
    # outline_parent_uids (issue #176) is shared with the calendar-mismatch
    # import diagnostic in services/import_diff.py, which needs the exact same
    # outline-number-to-parent derivation over a raw ParsedTask list instead
    # of an already-persisted WfPlanningTaskSnapshot.
    parent_uids = outline_parent_uids((task.uid, task.outline_number) for task in tasks)
    for task in tasks:
        if task.uid not in parent_uids:
            continue
        assert task.outline_number is not None  # guaranteed by outline_parent_uids
        task.position = int(task.outline_number.split(".")[-1])
        task.parent_uid = parent_uids[task.uid]


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


def _task_kwargs(task: Any, planning_id: int) -> dict[str, object]:
    return {
        "planning_id": planning_id,
        "uid": task.uid,
        "id_display": task.id_display,
        "name": task.name,
        "notes": task.notes,
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
        "is_manual": task.is_manual,
        "calendar_uid": task.calendar_uid,
    }


def import_tasks_and_links(
    db: Session,
    xml_bytes: bytes,
    project: MsProject,
    parsed_project: ParsedProject | None = None,
) -> tuple[int, int, tuple[dict[str, object], ...]]:
    ensure_project_mutable(project)
    parsed = parsed_project if parsed_project is not None else parse_msproject_xml(xml_bytes)
    _apply_project_metadata(project, parsed)
    db.add(project)
    db.flush()
    now = datetime.now(UTC)
    displayed = (
        db.query(WfPlanning)
        .filter(WfPlanning.id == project.displayed_planning_id)
        .populate_existing()
        .with_for_update()
        .first()
        if project.displayed_planning_id is not None
        else None
    )
    if displayed is not None and displayed.status == "draft":
        planning = displayed
        db.query(WfPlanningLinkSnapshot).filter(
            WfPlanningLinkSnapshot.planning_id == planning.id
        ).delete(synchronize_session=False)
        db.query(WfPlanningTaskSnapshot).filter(
            WfPlanningTaskSnapshot.planning_id == planning.id
        ).update({WfPlanningTaskSnapshot.parent_uid: None}, synchronize_session=False)
        db.query(WfPlanningTaskSnapshot).filter(
            WfPlanningTaskSnapshot.planning_id == planning.id
        ).delete(synchronize_session=False)
    else:
        version_number = (
            db.query(func.max(WfPlanning.version_number))
            .filter(WfPlanning.project_id == project.id)
            .scalar()
            or 0
        ) + 1
        planning = WfPlanning(
            project_id=project.id,
            version_number=version_number,
            status="draft",
            note="Imported from MS Project",
            created_at=now,
        )
        db.add(planning)
        db.flush()

    tasks = [
        WfPlanningTaskSnapshot(**_task_kwargs(parsed_task, planning.id))
        for parsed_task in parsed.tasks
    ]
    db.add_all(tasks)
    db.flush()
    _populate_parent_metadata(tasks)
    db.add_all(
        WfPlanningLinkSnapshot(
            planning_id=planning.id,
            task_uid=link.task_uid,
            predecessor_uid=link.predecessor_uid,
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in parsed.links
    )
    project.displayed_planning_id = planning.id
    db.flush()
    return len(parsed.tasks), len(parsed.links), parsed.warnings
