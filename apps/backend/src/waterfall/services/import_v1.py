from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.wf_core import WfTaskEnrichment

NS = {"ms": "http://schemas.microsoft.com/project"}


def _text(node: ET.Element, path: str) -> str | None:
    found = node.find(path, NS)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value if value else None


def _integer(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _boolean(value: str | None) -> bool:
    return value == "1"


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _populate_parent_metadata(tasks: list[MsTask]) -> None:
    by_outline = {
        task.outline_number: task
        for task in tasks
        if task.outline_number and all(part.isdigit() for part in task.outline_number.split("."))
    }
    for task in tasks:
        outline = task.outline_number
        if not outline or not all(part.isdigit() for part in outline.split(".")):
            continue
        parts = outline.split(".")
        task.position = int(parts[-1])
        parent_outline = ".".join(parts[:-1])
        parent = by_outline.get(parent_outline)
        task.parent_uid = parent.uid if parent is not None else None


def import_tasks_and_links(db: Session, xml_bytes: bytes, project: MsProject) -> tuple[int, int]:
    root = ET.fromstring(xml_bytes)
    save_version = _integer(_text(root, "ms:SaveVersion")) or 16
    source_version = {14: 2010, 15: 2013, 16: 2016}.get(save_version, 2016)

    if db.query(MsTask.id).filter(MsTask.project_id == project.id).first() is not None:
        raise ValueError("Project already contains tasks")

    project.external_uid = _text(root, "ms:GUID")
    project.source_version = source_version
    project.save_version_out = save_version if save_version in (14, 15, 16) else 16
    project.schedule_from_start = _boolean(_text(root, "ms:ScheduleFromStart"))
    project.start_date = _datetime(_text(root, "ms:StartDate"))
    project.finish_date = _datetime(_text(root, "ms:FinishDate"))
    project.calendar_uid = _integer(_text(root, "ms:CalendarUID"))
    project.minutes_per_day = _integer(_text(root, "ms:MinutesPerDay")) or 480
    project.minutes_per_week = _integer(_text(root, "ms:MinutesPerWeek")) or 2400
    project.days_per_month = _integer(_text(root, "ms:DaysPerMonth")) or 20
    project.currency_code = _text(root, "ms:CurrencyCode")
    db.add(project)
    db.flush()

    tasks: list[MsTask] = []
    links: list[MsTaskLink] = []
    enrichments: list[WfTaskEnrichment] = []
    now = datetime.now(UTC)

    for task_node in root.findall("ms:Tasks/ms:Task", NS):
        uid = _integer(_text(task_node, "ms:UID"))
        if uid is None:
            continue

        tasks.append(
            MsTask(
                project_id=project.id,
                uid=uid,
                id_display=_integer(_text(task_node, "ms:ID")),
                name=_text(task_node, "ms:Name") or f"Task {uid}",
                task_type=_integer(_text(task_node, "ms:Type")),
                outline_number=_text(task_node, "ms:OutlineNumber"),
                outline_level=_integer(_text(task_node, "ms:OutlineLevel")),
                wbs=_text(task_node, "ms:WBS"),
                start_at=_datetime(_text(task_node, "ms:Start")),
                finish_at=_datetime(_text(task_node, "ms:Finish")),
                duration_format=_integer(_text(task_node, "ms:DurationFormat")),
                percent_complete=_integer(_text(task_node, "ms:PercentComplete")),
                is_summary=_boolean(_text(task_node, "ms:Summary")),
                is_milestone=_boolean(_text(task_node, "ms:Milestone")),
                calendar_uid=_integer(_text(task_node, "ms:CalendarUID")),
            )
        )

        notes = _text(task_node, "ms:Notes")
        if notes is not None:
            enrichments.append(
                WfTaskEnrichment(
                    project_id=project.id,
                    task_uid=uid,
                    description=notes,
                    created_at=now,
                    updated_at=now,
                )
            )

        for predecessor_node in task_node.findall("ms:PredecessorLink", NS):
            predecessor_uid = _integer(_text(predecessor_node, "ms:PredecessorUID"))
            if predecessor_uid is None:
                continue
            links.append(
                MsTaskLink(
                    project_id=project.id,
                    task_uid=uid,
                    predecessor_uid=predecessor_uid,
                    link_type=_integer(_text(predecessor_node, "ms:Type")) or 1,
                    lag_tenth_minute=_integer(_text(predecessor_node, "ms:LinkLag")),
                    lag_format=_integer(_text(predecessor_node, "ms:LagFormat")),
                )
            )

    db.add_all(tasks)
    db.flush()
    _populate_parent_metadata(tasks)
    db.add_all(enrichments)
    db.flush()
    db.add_all(links)
    db.flush()
    return len(tasks), len(links)
