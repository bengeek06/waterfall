from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.planning import WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import Calendar, CalendarWeekday
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.services.calendar_schedule import (
    resolve_default_calendar_id,
    resolve_task_calendar_ids,
)
from waterfall.services.msproject_xml import format_duration
from waterfall.services.revision_store import load_revision

MSP_NS = "http://schemas.microsoft.com/project/2007"


@dataclass(frozen=True)
class RevisionExportTask:
    """One planning node of a revision, reduced to what an MSPDI ``<Task>`` carries.

    ``uid`` is the **external** uid of the node's ``work_item`` (E14-06, #332): the
    import put it there and the export takes it back out, which is the whole of
    "exporting then re-importing restores the same external uids". It is read from
    the work item and from nowhere else -- never from a node id, never from a row
    number -- because a node id changes from one revision to the next while the
    identity of the element of work does not.
    """

    uid: int
    name: str
    task_type: int | None
    outline_number: str | None
    outline_level: int | None
    start_at: datetime | None
    finish_at: datetime | None
    duration_minutes: int | None
    duration_format: int | None
    percent_complete: int | None
    is_summary: bool
    is_milestone: bool
    is_manual: bool | None
    notes: str | None


@dataclass(frozen=True)
class RevisionExportLink:
    """One precedence link of a revision, named by external uid on both ends."""

    task_uid: int
    predecessor_uid: int
    link_type: int
    lag_tenth_minute: int | None
    lag_format: int | None


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


def _load_export_calendars(
    db: Session,
    project_id: int,
    tasks: list[MsTask] | list[WfPlanningTaskSnapshot] | list[RevisionExportTask],
    resolved_calendar_ids: Mapping[int, int] | None,
) -> tuple[
    dict[int, int],
    set[int],
    dict[int, Calendar],
    dict[int, list[CalendarWeekday]],
    int | None,
]:
    task_calendar_ids = (
        dict(resolved_calendar_ids)
        if resolved_calendar_ids is not None
        else resolve_task_calendar_ids(db, project_id, {task.uid for task in tasks})
    )
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
    return (
        task_calendar_ids,
        exported_calendar_ids,
        calendars_by_id,
        weekdays_by_calendar_id,
        default_calendar_id,
    )


def _append_project_header(
    root: ET.Element,
    project: MsProject,
    reference_calendar_id: int | None,
    header_minutes: tuple[int, int, int] | None,
) -> None:
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


def _append_calendars(
    root: ET.Element,
    exported_calendar_ids: set[int],
    calendars_by_id: dict[int, Calendar],
    weekdays_by_calendar_id: dict[int, list[CalendarWeekday]],
) -> None:
    if not exported_calendar_ids:
        return
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
            _append_calendar_weekday(
                weekdays_node, day_type, hours_by_day_type.get(day_type, Decimal(0))
            )


def _append_calendar_weekday(
    weekdays_node: ET.Element,
    day_type: int,
    hours_per_day: Decimal,
) -> None:
    weekday_node = ET.SubElement(weekdays_node, f"{{{MSP_NS}}}WeekDay")
    ET.SubElement(weekday_node, f"{{{MSP_NS}}}DayType").text = str(day_type)
    is_working = hours_per_day > 0
    ET.SubElement(weekday_node, f"{{{MSP_NS}}}DayWorking").text = _bool_to_msp_flag(is_working)
    if is_working:
        working_times_node = ET.SubElement(weekday_node, f"{{{MSP_NS}}}WorkingTimes")
        working_time_node = ET.SubElement(working_times_node, f"{{{MSP_NS}}}WorkingTime")
        ET.SubElement(working_time_node, f"{{{MSP_NS}}}FromTime").text = "00:00:00"
        ET.SubElement(
            working_time_node, f"{{{MSP_NS}}}ToTime"
        ).text = _calendar_working_time_to_text(hours_per_day)


def _append_task(
    tasks_node: ET.Element,
    task: MsTask | WfPlanningTaskSnapshot | RevisionExportTask,
    row_number: int,
    task_calendar_ids: dict[int, int],
    calendars_by_id: dict[int, Calendar],
    descriptions_by_uid: dict[int, str | None],
    links_by_task_uid: dict[int, list[Any]],
) -> None:
    task_node = ET.SubElement(tasks_node, f"{{{MSP_NS}}}Task")
    ET.SubElement(task_node, f"{{{MSP_NS}}}UID").text = str(task.uid)
    # <ID> used to be filled from the now-removed id_display column (#146/E9-01), which was
    # allocated once and never recalculated. It's now the computed row_number (#147/E9-02) --
    # the task's 1-based rank in the exported document's own depth-first order, always in sync
    # with the actual displayed order, never a stale round-tripped value from a prior import.
    ET.SubElement(task_node, f"{{{MSP_NS}}}ID").text = str(row_number)
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
        ET.SubElement(task_node, f"{{{MSP_NS}}}PercentComplete").text = str(task.percent_complete)
    ET.SubElement(task_node, f"{{{MSP_NS}}}Summary").text = _bool_to_msp_flag(task.is_summary)
    ET.SubElement(task_node, f"{{{MSP_NS}}}Milestone").text = _bool_to_msp_flag(task.is_milestone)
    if task.is_manual is not None:
        ET.SubElement(task_node, f"{{{MSP_NS}}}Manual").text = _bool_to_msp_flag(task.is_manual)
    task_calendar_id = task_calendar_ids.get(task.uid)
    if task_calendar_id is not None and task_calendar_id in calendars_by_id:
        ET.SubElement(task_node, f"{{{MSP_NS}}}CalendarUID").text = str(task_calendar_id)
    description = getattr(task, "notes", None) or descriptions_by_uid.get(task.uid)
    if description:
        ET.SubElement(task_node, f"{{{MSP_NS}}}Notes").text = description
    _append_predecessor_links(task_node, links_by_task_uid.get(task.uid, []))


def _append_predecessor_links(task_node: ET.Element, links: list[Any]) -> None:
    for link in links:
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


def build_project_export_xml(
    db: Session,
    project: MsProject,
    tasks: list[MsTask] | list[WfPlanningTaskSnapshot] | list[RevisionExportTask],
    links: list[MsTaskLink] | list[WfPlanningLinkSnapshot] | list[RevisionExportLink],
    *,
    resolved_calendar_ids: Mapping[int, int] | None = None,
) -> bytes:
    """Caller contract: `tasks` must already be in the exact order to export -- each task's
    exported `<ID>` is its 1-based position in this list (row_number, #147/E9-02), not
    recomputed here. Callers should order with `order_snapshots_depth_first`/
    `order_ms_tasks_depth_first` (planning_support.py) before calling this.

    ``resolved_calendar_ids`` overrides the calendar resolution instead of reading
    it back from the roles. The revision path passes it (E14-06, #332) because
    there the calendar is a **stored attribute of the planning facet** (Règle 1)
    rather than something derived on read: leaving
    ``resolve_task_calendar_ids`` to answer would reintroduce the legacy
    tie-break -- the smallest ``role_id`` wins -- next to a facet that already
    holds Règle 1's answer, the first MO facet in depth-first order. The legacy
    callers pass nothing and keep the resolution they always had."""
    enrichments = db.query(WfTaskEnrichment).filter(WfTaskEnrichment.project_id == project.id).all()
    descriptions_by_uid: dict[int, str | None] = {
        enrichment.task_uid: enrichment.description for enrichment in enrichments
    }
    links_by_task_uid: dict[int, list[Any]] = {}
    for link in links:
        links_by_task_uid.setdefault(link.task_uid, []).append(link)

    (
        task_calendar_ids,
        exported_calendar_ids,
        calendars_by_id,
        weekdays_by_calendar_id,
        default_calendar_id,
    ) = _load_export_calendars(db, project.id, tasks, resolved_calendar_ids)

    reference_calendar_id, header_minutes = _resolve_project_reference_calendar(
        default_calendar_id, task_calendar_ids, calendars_by_id, weekdays_by_calendar_id
    )

    ET.register_namespace("", MSP_NS)
    root = ET.Element(f"{{{MSP_NS}}}Project")
    _append_project_header(root, project, reference_calendar_id, header_minutes)
    _append_calendars(root, exported_calendar_ids, calendars_by_id, weekdays_by_calendar_id)

    tasks_node = ET.SubElement(root, f"{{{MSP_NS}}}Tasks")
    for row_number, task in enumerate(tasks, start=1):
        _append_task(
            tasks_node,
            task,
            row_number,
            task_calendar_ids,
            calendars_by_id,
            descriptions_by_uid,
            links_by_task_uid,
        )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# --------------------------------------------------------------------------------------
# Exporting a revision (E14-06, #332)
# --------------------------------------------------------------------------------------


def _plan_children(revision: domain.ProjectRevision, parent_id: int | None) -> list[int]:
    """Ids of the planning children of ``parent_id``, in display order.

    Cost children are skipped: they have no image in an MS Project file, and
    counting them would shift the outline numbers of their planning siblings.
    """
    return [
        node.id
        for node in domain.children_of(revision, parent_id)
        if node.id in revision.plan_facets
    ]


def _outline_numbers(revision: domain.ProjectRevision) -> dict[int, str]:
    """Dotted outline number of every planning node, derived from the tree itself.

    Never stored, for the reason E9 settled and the node model makes structural: a
    position a move would have to renumber is a position that drifts. It is the
    same derivation the re-import reads back through
    :func:`~waterfall.services.msproject_xml.outline_parent_uids`, so a round trip
    lands on the same parents.
    """
    numbers: dict[int, str] = {}
    stack: list[tuple[int | None, str]] = [(None, "")]
    while stack:
        parent_id, prefix = stack.pop()
        for rank, node_id in enumerate(_plan_children(revision, parent_id), start=1):
            number = f"{prefix}{rank}" if not prefix else f"{prefix}.{rank}"
            numbers[node_id] = number
            stack.append((node_id, number))
    return numbers


def _document_uids(project: domain.Project, revision: domain.ProjectRevision) -> dict[int, int]:
    """``node id -> uid to export``, the work item's ``external_uid`` wherever there is one.

    A planning node whose work item carries none was created in Waterfall and has
    never left it (Rule 3 a). MSPDI still requires a ``<UID>``, so one is allocated
    **for this document only**, above every external uid the *project* uses, and
    nothing is written back: an export is a read.

    Read off ``project.work_items`` and **not** off the nodes of this revision --
    the #332 review (H1) caught the difference, and it is not cosmetic. A work item
    outlives the node that carried it: a re-import removes nodes and facets
    (``delete_nodes``) and never a work item, so an uid this revision no longer
    shows is still taken by the project. Allocating above the revision's uids alone
    handed a locally created task the identity of one of those survivors, and a
    re-import of that very document then landed it on that stranger's
    ``work_item_id`` -- the single join key the reconciliation of a forecast against
    its budget has, silently rewritten, with two tasks of the same name left in the
    tree.

    Known limit, deliberate and not an oversight, and it **accumulates** (#332
    review, B8): re-importing such a document creates a *new* work item for that uid
    rather than recognising the local task, because the file and the project have no
    identifier in common for it. The original keeps no external uid through that
    re-import either, so the next export allocates it yet another one and the next
    re-import duplicates it again. One round trip over a tree holding one locally
    created task leaves two of them, two round trips leave three, three leave four --
    one extra copy per local task per round trip, and nothing bounds the growth.
    ``test_a_local_task_never_exports_the_uid_of_a_work_item_that_outlived_its_node``
    walks two rounds and asserts exactly that.

    Every task of an *imported* planning does carry an external uid, so the round
    trip this issue pins is unaffected -- only a task created in Waterfall is
    concerned, and no route creates one on a revision this export serves today.
    Deciding whether a locally created task earns an external identity -- and at
    which moment -- belongs with the editable tree of E14-10 (#336), which is also
    what would wire this export into a route serving hand-built plannings.
    """
    uids: dict[int, int] = {}
    unnamed: list[int] = []
    highest = max(
        (
            item.external_uid
            for item in project.work_items.values()
            if item.external_uid is not None
        ),
        default=0,
    )
    for node_id in revision.plan_facets:
        work_item = project.work_items.get(revision.nodes[node_id].work_item_id)
        external_uid = None if work_item is None else work_item.external_uid
        if external_uid is None:
            unnamed.append(node_id)
        else:
            uids[node_id] = external_uid
    for offset, node_id in enumerate(sorted(unnamed), start=1):
        uids[node_id] = highest + offset
    return uids


def _revision_export_task(
    project: domain.Project,
    revision: domain.ProjectRevision,
    node_id: int,
    uid: int,
    outline_number: str,
) -> RevisionExportTask:
    facet = revision.plan_facets[node_id]
    work_item = project.work_items.get(revision.nodes[node_id].work_item_id)
    return RevisionExportTask(
        uid=uid,
        name=facet.name,
        # MSPDI's <Type> (fixed units/duration/work) has no home on the planning
        # facet, so it is omitted rather than invented; the importer treats an
        # absent <Type> as unset.
        task_type=None,
        outline_number=outline_number,
        outline_level=outline_number.count(".") + 1,
        start_at=facet.start_at,
        finish_at=facet.finish_at,
        duration_minutes=facet.duration_minutes,
        duration_format=facet.duration_format,
        percent_complete=facet.percent_complete,
        is_summary=bool(_plan_children(revision, node_id)),
        is_milestone=facet.is_milestone,
        is_manual=facet.is_manual,
        notes=None if work_item is None else work_item.description,
    )


def build_revision_export_xml(db: Session, project: MsProject, revision_id: int) -> bytes:
    """The MSPDI document of one revision, keyed by the external uid of its work items.

    The counterpart of :mod:`waterfall.services.revision_import`: what that module
    puts on ``wf_work_item.external_uid`` is what comes back out here, so exporting
    a planning and re-importing the file restores the same external uids -- and
    therefore lands on the same work items rather than duplicating the tree.

    The calendar of each task is read from its planning facet (Règle 1) and handed
    to :func:`build_project_export_xml` rather than resolved from the roles: on the
    revision path the facet *is* the answer.
    """
    loaded = load_revision(db, revision_id)
    ordered = [
        node.id
        for node in domain.depth_first(loaded.revision)
        if node.id in loaded.revision.plan_facets
    ]
    uids = _document_uids(loaded.project, loaded.revision)
    outline_numbers = _outline_numbers(loaded.revision)
    tasks = [
        _revision_export_task(
            loaded.project, loaded.revision, node_id, uids[node_id], outline_numbers[node_id]
        )
        for node_id in ordered
    ]
    links = [
        RevisionExportLink(
            task_uid=uids[link.node_id],
            predecessor_uid=uids[link.predecessor_node_id],
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in loaded.revision.links
        if link.node_id in uids and link.predecessor_node_id in uids
    ]
    calendars = {
        uids[node_id]: loaded.revision.plan_facets[node_id].calendar_id
        for node_id in ordered
        if loaded.revision.plan_facets[node_id].calendar_id is not None
    }
    return build_project_export_xml(
        db,
        project,
        tasks,
        links,
        resolved_calendar_ids={
            uid: calendar_id for uid, calendar_id in calendars.items() if calendar_id is not None
        },
    )
