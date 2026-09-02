from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import Calendar, CalendarWeekday
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.services.calendar_schedule import (
    resolve_default_calendar_id,
    resolve_task_calendar_ids,
)
from waterfall.services.msproject_xml import format_duration

MSP_NS = "http://schemas.microsoft.com/project/2007"


def _bool_to_msp_flag(value: bool) -> str:
    return "1" if value else "0"


def _dt_to_msp_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return value.isoformat(timespec="seconds")


def _resolve_project_reference_calendar(
    default_calendar_id: int | None,
    task_calendar_ids: dict[int, int],
    calendars_by_id: dict[int, Calendar],
    weekdays_by_calendar_id: dict[int, list[CalendarWeekday]],
) -> tuple[int | None, tuple[int, int, int] | None]:
    candidate_ids: list[int] = []
    if default_calendar_id is not None:
        candidate_ids.append(default_calendar_id)
    if task_calendar_ids:
        fallback_id = min(task_calendar_ids.values())
        if fallback_id not in candidate_ids:
            candidate_ids.append(fallback_id)

    for calendar_id in candidate_ids:
        calendar = calendars_by_id.get(calendar_id)
        if calendar is None:
            continue
        header_minutes = _calendar_header_minutes(
            calendar, weekdays_by_calendar_id.get(calendar_id, [])
        )
        if header_minutes is not None:
            return calendar_id, header_minutes
    return None, None


def _calendar_header_minutes(
    calendar: Calendar, weekdays: list[CalendarWeekday]
) -> tuple[int, int, int] | None:
    working = [weekday for weekday in weekdays if weekday.hours_per_day > 0]
    if not working:
        return None
    total_hours = sum((weekday.hours_per_day for weekday in working), start=Decimal(0))
    minutes_per_day = round(total_hours / len(working) * 60)
    minutes_per_week = round(total_hours * 60)
    days_per_month = max(1, round(calendar.weeks_per_year * len(working) / 12))
    return minutes_per_day, minutes_per_week, days_per_month


def _calendar_working_time_to_text(hours_per_day: Decimal) -> str:
    total_seconds = int(hours_per_day * 3600)
    if total_seconds >= 24 * 3600:
        return "23:59:59"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def build_project_export_xml(
    db: Session,
    project: MsProject,
    tasks: list[MsTask] | list[WfPlanningTaskSnapshot],
    links: list[MsTaskLink] | list[WfPlanningLinkSnapshot],
) -> bytes:
    enrichments = db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project.id).all()
    descriptions_by_uid = {
        enrichment.task_uid: enrichment.description for enrichment in enrichments
    }
    links_by_task_uid: dict[int, list[Any]] = {}
    for link in links:
        links_by_task_uid.setdefault(link.task_uid, []).append(link)

    task_calendar_ids = resolve_task_calendar_ids(db, project.id, {task.uid for task in tasks})
    default_calendar_id = resolve_default_calendar_id(db)
    exported_calendar_ids = set(task_calendar_ids.values())
    if default_calendar_id is not None:
        exported_calendar_ids.add(default_calendar_id)

    calendars_by_id: dict[int, Calendar] = {}
    weekdays_by_calendar_id: dict[int, list[CalendarWeekday]] = {}
    if exported_calendar_ids:
        calendars_by_id = {
            calendar.id: calendar
            for calendar in db.query(Calendar).filter(Calendar.id.in_(exported_calendar_ids)).all()
        }
        for weekday in (
            db.query(CalendarWeekday)
            .filter(CalendarWeekday.calendar_id.in_(exported_calendar_ids))
            .all()
        ):
            weekdays_by_calendar_id.setdefault(weekday.calendar_id, []).append(weekday)

    reference_calendar_id, header_minutes = _resolve_project_reference_calendar(
        default_calendar_id, task_calendar_ids, calendars_by_id, weekdays_by_calendar_id
    )

    ET.register_namespace("", MSP_NS)
    root = ET.Element(f"{{{MSP_NS}}}Project")

    ET.SubElement(root, f"{{{MSP_NS}}}SaveVersion").text = str(project.save_version_out)
    if project.external_uid is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}GUID").text = project.external_uid
    ET.SubElement(root, f"{{{MSP_NS}}}Name").text = project.name
    ET.SubElement(root, f"{{{MSP_NS}}}ScheduleFromStart").text = _bool_to_msp_flag(
        project.schedule_from_start
    )

    start_date = _dt_to_msp_text(project.start_date)
    if start_date is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}StartDate").text = start_date
    finish_date = _dt_to_msp_text(project.finish_date)
    if finish_date is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}FinishDate").text = finish_date
    if reference_calendar_id is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}CalendarUID").text = str(reference_calendar_id)

    if header_minutes is not None:
        minutes_per_day, minutes_per_week, days_per_month = header_minutes
    else:
        minutes_per_day = project.minutes_per_day
        minutes_per_week = project.minutes_per_week
        days_per_month = project.days_per_month
    ET.SubElement(root, f"{{{MSP_NS}}}MinutesPerDay").text = str(minutes_per_day)
    ET.SubElement(root, f"{{{MSP_NS}}}MinutesPerWeek").text = str(minutes_per_week)
    ET.SubElement(root, f"{{{MSP_NS}}}DaysPerMonth").text = str(days_per_month)
    if project.currency_code is not None:
        ET.SubElement(root, f"{{{MSP_NS}}}CurrencyCode").text = project.currency_code

    if exported_calendar_ids:
        calendars_node = ET.SubElement(root, f"{{{MSP_NS}}}Calendars")
        for calendar_id in sorted(exported_calendar_ids):
            calendar = calendars_by_id.get(calendar_id)
            if calendar is None:
                continue
            calendar_node = ET.SubElement(calendars_node, f"{{{MSP_NS}}}Calendar")
            ET.SubElement(calendar_node, f"{{{MSP_NS}}}UID").text = str(calendar.id)
            ET.SubElement(calendar_node, f"{{{MSP_NS}}}Name").text = calendar.name
            weekdays_node = ET.SubElement(calendar_node, f"{{{MSP_NS}}}WeekDays")
            hours_by_day_type = {
                weekday.day_type: weekday.hours_per_day
                for weekday in weekdays_by_calendar_id.get(calendar_id, [])
            }
            for day_type in range(1, 8):
                hours_per_day = hours_by_day_type.get(day_type, Decimal(0))
                weekday_node = ET.SubElement(weekdays_node, f"{{{MSP_NS}}}WeekDay")
                ET.SubElement(weekday_node, f"{{{MSP_NS}}}DayType").text = str(day_type)
                is_working = hours_per_day > 0
                ET.SubElement(weekday_node, f"{{{MSP_NS}}}DayWorking").text = _bool_to_msp_flag(
                    is_working
                )
                if is_working:
                    working_times_node = ET.SubElement(weekday_node, f"{{{MSP_NS}}}WorkingTimes")
                    working_time_node = ET.SubElement(
                        working_times_node, f"{{{MSP_NS}}}WorkingTime"
                    )
                    ET.SubElement(working_time_node, f"{{{MSP_NS}}}FromTime").text = "00:00:00"
                    ET.SubElement(
                        working_time_node, f"{{{MSP_NS}}}ToTime"
                    ).text = _calendar_working_time_to_text(hours_per_day)

    tasks_node = ET.SubElement(root, f"{{{MSP_NS}}}Tasks")
    for task in tasks:
        task_node = ET.SubElement(tasks_node, f"{{{MSP_NS}}}Task")
        ET.SubElement(task_node, f"{{{MSP_NS}}}UID").text = str(task.uid)
        if task.id_display is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}ID").text = str(task.id_display)
        ET.SubElement(task_node, f"{{{MSP_NS}}}Name").text = task.name
        if task.task_type is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Type").text = str(task.task_type)
        if task.outline_number is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}OutlineNumber").text = task.outline_number
        if task.outline_level is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}OutlineLevel").text = str(task.outline_level)
        start_at = _dt_to_msp_text(task.start_at)
        if start_at is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Start").text = start_at
        finish_at = _dt_to_msp_text(task.finish_at)
        if finish_at is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Finish").text = finish_at
        duration = format_duration(task.duration_minutes)
        if duration is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Duration").text = duration
        if task.duration_format is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}DurationFormat").text = str(task.duration_format)
        if task.percent_complete is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}PercentComplete").text = str(
                task.percent_complete
            )
        ET.SubElement(task_node, f"{{{MSP_NS}}}Summary").text = _bool_to_msp_flag(task.is_summary)
        ET.SubElement(task_node, f"{{{MSP_NS}}}Milestone").text = _bool_to_msp_flag(
            task.is_milestone
        )
        if task.is_manual is not None:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Manual").text = _bool_to_msp_flag(task.is_manual)
        task_calendar_id = task_calendar_ids.get(task.uid)
        if task_calendar_id is not None and task_calendar_id in calendars_by_id:
            ET.SubElement(task_node, f"{{{MSP_NS}}}CalendarUID").text = str(task_calendar_id)
        description = getattr(task, "notes", None) or descriptions_by_uid.get(task.uid)
        if description:
            ET.SubElement(task_node, f"{{{MSP_NS}}}Notes").text = description
        for link in links_by_task_uid.get(task.uid, []):
            predecessor_link_node = ET.SubElement(task_node, f"{{{MSP_NS}}}PredecessorLink")
            ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}PredecessorUID").text = str(
                link.predecessor_uid
            )
            ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}Type").text = str(link.link_type)
            if link.lag_tenth_minute is not None:
                ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}LinkLag").text = str(
                    link.lag_tenth_minute
                )
            if link.lag_format is not None:
                ET.SubElement(predecessor_link_node, f"{{{MSP_NS}}}LagFormat").text = str(
                    link.lag_format
                )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
