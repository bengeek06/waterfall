from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from lxml import etree

SUPPORTED_NAMESPACES = {
    "http://schemas.microsoft.com/project",
    "http://schemas.microsoft.com/project/2007",
}
SAVE_VERSIONS = {14: 2010, 15: 2013, 16: 2016}
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
CANONICAL_NAMESPACE = "http://schemas.microsoft.com/project/2007"
CANONICAL_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "resources"
    / "msproject-schemas"
    / "canonical"
    / "waterfall_msproject_subset.xsd"
)


@dataclass(frozen=True)
class ParsedTask:
    uid: int
    id_display: int | None
    name: str
    task_type: int | None
    outline_number: str | None
    outline_level: int | None
    wbs: str | None
    start_at: datetime | None
    finish_at: datetime | None
    duration_minutes: int | None
    duration_format: int | None
    percent_complete: int | None
    is_summary: bool
    is_milestone: bool
    is_manual: bool | None
    calendar_uid: int | None
    notes: str | None


@dataclass(frozen=True)
class ParsedLink:
    task_uid: int
    predecessor_uid: int
    link_type: int
    lag_tenth_minute: int | None
    lag_format: int | None


@dataclass(frozen=True)
class ParsedProject:
    namespace: str
    save_version: int
    source_version: int
    external_uid: str | None
    name: str | None
    schedule_from_start: bool
    start_date: datetime | None
    finish_date: datetime | None
    calendar_uid: int | None
    minutes_per_day: int
    minutes_per_week: int
    days_per_month: int
    currency_code: str | None
    tasks: tuple[ParsedTask, ...]
    links: tuple[ParsedLink, ...]
    warnings: tuple[dict[str, object], ...] = ()


class MsProjectValidationError(ValueError):
    def __init__(self, issues: list[dict[str, object]]) -> None:
        self.issues = issues
        super().__init__("MS Project XML validation failed")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node if _local_name(child.tag) == name]


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next(iter(_children(node, name)), None)


def _text(node: ET.Element, name: str) -> str | None:
    child = _child(node, name)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _boolean(value: str | None, field: str, issues: list[dict[str, object]]) -> bool:
    if value in {"1", "true"}:
        return True
    if value in {"0", "false", None}:
        return False
    issues.append({"code": "INVALID_BOOLEAN", "message": f"{field} is invalid"})
    return False


def _integer(value: str | None, field: str, issues: list[dict[str, object]]) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        issues.append({"code": "INVALID_INTEGER", "message": f"{field} must be an integer"})
        return None


def _datetime(value: str | None, field: str, issues: list[dict[str, object]]) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        issues.append({"code": "INVALID_DATETIME", "message": f"{field} is invalid"})
        return None


def parse_duration(value: str | None, minutes_per_day: int) -> int | None:
    if value is None:
        return None
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"Unsupported xsd:duration value: {value}")
    days = float(match.group("days") or 0)
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return round(days * minutes_per_day + hours * 60 + minutes + seconds / 60)


def format_duration(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    if minutes < 0:
        raise ValueError("Duration cannot be negative")
    return f"PT{minutes}M"


@lru_cache(maxsize=1)
def _canonical_schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(CANONICAL_SCHEMA_PATH)))


def validate_canonical_xml(xml_bytes: bytes) -> None:
    document = etree.fromstring(xml_bytes)
    if document.nsmap.get(None) != CANONICAL_NAMESPACE:
        raise MsProjectValidationError(
            [{"code": "UNSUPPORTED_NAMESPACE", "message": "Canonical export requires /2007"}]
        )
    if not _canonical_schema().validate(document):
        issues: list[dict[str, object]] = [
            {"code": "XSD_VALIDATION", "message": str(_canonical_schema().error_log)}
        ]
        raise MsProjectValidationError(issues)


def parse_msproject_xml(xml_bytes: bytes) -> ParsedProject:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise MsProjectValidationError([{"code": "MALFORMED_XML", "message": str(exc)}]) from exc

    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    if namespace == CANONICAL_NAMESPACE:
        validate_canonical_xml(xml_bytes)
    issues: list[dict[str, object]] = []
    if namespace not in SUPPORTED_NAMESPACES:
        issues.append(
            {"code": "UNSUPPORTED_NAMESPACE", "message": namespace or "Missing XML namespace"}
        )

    save_version = _integer(_text(root, "SaveVersion"), "SaveVersion", issues) or 16
    if save_version not in SAVE_VERSIONS:
        issues.append({"code": "UNSUPPORTED_VERSION", "message": str(save_version)})
    source_version = SAVE_VERSIONS.get(save_version, 2016)
    minutes_per_day = _integer(_text(root, "MinutesPerDay"), "MinutesPerDay", issues) or 480
    minutes_per_week = _integer(_text(root, "MinutesPerWeek"), "MinutesPerWeek", issues) or 2400
    days_per_month = _integer(_text(root, "DaysPerMonth"), "DaysPerMonth", issues) or 20
    start_date = _datetime(_text(root, "StartDate"), "Project StartDate", issues)
    finish_date = _datetime(_text(root, "FinishDate"), "Project FinishDate", issues)
    tasks: list[ParsedTask] = []
    links: list[ParsedLink] = []
    task_uids: set[int] = set()
    task_nodes = _child(root, "Tasks")
    for task_node in _children(task_nodes, "Task") if task_nodes is not None else []:
        uid = _integer(_text(task_node, "UID"), "Task UID", issues)
        if uid is None:
            issues.append({"code": "MISSING_UID", "message": "Task UID is required"})
            continue
        if uid in task_uids:
            issues.append(
                {
                    "code": "DUPLICATE_UID",
                    "message": f"Task UID {uid} is duplicated",
                    "taskUid": uid,
                }
            )
            continue
        task_uids.add(uid)
        outline = _text(task_node, "OutlineNumber")
        level = _integer(_text(task_node, "OutlineLevel"), "OutlineLevel", issues)
        if outline is not None:
            segments = outline.split(".")
            if not all(segment.isdigit() and int(segment) > 0 for segment in segments):
                issues.append(
                    {
                        "code": "INVALID_OUTLINE",
                        "message": f"Task UID {uid} has an invalid outline",
                        "taskUid": uid,
                    }
                )
            elif level is not None and level != len(segments):
                issues.append(
                    {
                        "code": "OUTLINE_LEVEL_MISMATCH",
                        "message": f"Task UID {uid} outline level mismatch",
                        "taskUid": uid,
                    }
                )
        duration: int | None = None
        duration_text = _text(task_node, "Duration")
        if duration_text is not None:
            try:
                duration = parse_duration(duration_text, minutes_per_day)
            except ValueError as exc:
                issues.append({"code": "INVALID_DURATION", "message": str(exc), "taskUid": uid})
        task_type = _integer(_text(task_node, "Type"), "Task Type", issues)
        if task_type is not None and task_type not in (0, 1, 2):
            issues.append(
                {
                    "code": "INVALID_TASK_TYPE",
                    "message": f"Task UID {uid} has invalid Type",
                    "taskUid": uid,
                }
            )
        percent_complete = _integer(_text(task_node, "PercentComplete"), "PercentComplete", issues)
        if percent_complete is not None and not 0 <= percent_complete <= 100:
            issues.append(
                {
                    "code": "INVALID_PERCENT_COMPLETE",
                    "message": f"Task UID {uid} has invalid completion",
                    "taskUid": uid,
                }
            )
        task = ParsedTask(
            uid=uid,
            id_display=_integer(_text(task_node, "ID"), "Task ID", issues),
            name=_text(task_node, "Name") or f"Task {uid}",
            task_type=task_type,
            outline_number=outline,
            outline_level=level,
            wbs=_text(task_node, "WBS"),
            start_at=_datetime(_text(task_node, "Start"), "Task Start", issues),
            finish_at=_datetime(_text(task_node, "Finish"), "Task Finish", issues),
            duration_minutes=duration,
            duration_format=_integer(_text(task_node, "DurationFormat"), "DurationFormat", issues),
            percent_complete=percent_complete,
            is_summary=_boolean(_text(task_node, "Summary"), "Summary", issues),
            is_milestone=_boolean(_text(task_node, "Milestone"), "Milestone", issues),
            is_manual=(
                _boolean(_text(task_node, "Manual"), "Manual", issues)
                if _text(task_node, "Manual") is not None
                else None
            ),
            calendar_uid=_integer(_text(task_node, "CalendarUID"), "CalendarUID", issues),
            notes=_text(task_node, "Notes"),
        )
        tasks.append(task)
        for link_node in _children(task_node, "PredecessorLink"):
            predecessor_uid = _integer(_text(link_node, "PredecessorUID"), "PredecessorUID", issues)
            link_type = _integer(_text(link_node, "Type"), "Link Type", issues)
            if predecessor_uid is None or link_type is None:
                issues.append(
                    {
                        "code": "INCOMPLETE_LINK",
                        "message": f"Task UID {uid} has an incomplete predecessor link",
                        "taskUid": uid,
                    }
                )
                continue
            if link_type not in (0, 1, 2, 3):
                issues.append(
                    {
                        "code": "INVALID_LINK_TYPE",
                        "message": f"Invalid link type for task UID {uid}",
                        "taskUid": uid,
                    }
                )
            link = ParsedLink(
                task_uid=uid,
                predecessor_uid=predecessor_uid,
                link_type=link_type,
                lag_tenth_minute=_integer(_text(link_node, "LinkLag"), "LinkLag", issues),
                lag_format=_integer(_text(link_node, "LagFormat"), "LagFormat", issues),
            )
            links.append(link)

    link_keys = set()
    for link in links:
        key = (link.task_uid, link.predecessor_uid, link.link_type)
        if key in link_keys:
            issues.append(
                {
                    "code": "DUPLICATE_LINK",
                    "message": f"Duplicate link for task UID {link.task_uid}",
                    "taskUid": link.task_uid,
                }
            )
        link_keys.add(key)

    for link in links:
        if link.predecessor_uid not in task_uids:
            issues.append(
                {
                    "code": "ORPHAN_LINK",
                    "message": f"Predecessor UID {link.predecessor_uid} does not exist",
                    "taskUid": link.task_uid,
                    "predecessorUid": link.predecessor_uid,
                }
            )
        if link.task_uid == link.predecessor_uid:
            issues.append(
                {
                    "code": "DEPENDENCY_CYCLE",
                    "message": f"Task UID {link.task_uid} links to itself",
                    "taskUid": link.task_uid,
                }
            )

    graph: dict[int, list[int]] = {uid: [] for uid in task_uids}
    for link in links:
        if link.predecessor_uid in task_uids:
            graph[link.predecessor_uid].append(link.task_uid)
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(uid: int) -> None:
        if uid in visiting:
            issues.append(
                {
                    "code": "DEPENDENCY_CYCLE",
                    "message": f"Dependency cycle includes task UID {uid}",
                    "taskUid": uid,
                }
            )
            return
        if uid in visited:
            return
        visiting.add(uid)
        for child_uid in graph[uid]:
            visit(child_uid)
        visiting.remove(uid)
        visited.add(uid)

    for uid in task_uids:
        visit(uid)
    schedule_from_start = _boolean(_text(root, "ScheduleFromStart"), "ScheduleFromStart", issues)
    if schedule_from_start and start_date is None:
        issues.append(
            {"code": "MISSING_START_DATE", "message": "ScheduleFromStart requires StartDate"}
        )
    if not schedule_from_start and finish_date is None:
        issues.append(
            {"code": "MISSING_FINISH_DATE", "message": "ScheduleFromFinish requires FinishDate"}
        )

    # Waterfall is the source of truth for working calendars (E5-02): custom
    # calendars carried by an imported MS Project file are never written to
    # wf_calendar/wf_calendar_weekday. Their presence is only surfaced as a
    # non-blocking diagnostic so the import can proceed without silently
    # dropping information the caller may want to reconcile manually.
    warnings: list[dict[str, object]] = []
    calendars_node = _child(root, "Calendars")
    if calendars_node is not None:
        calendar_count = len(_children(calendars_node, "Calendar"))
        if calendar_count > 0:
            warnings.append(
                {
                    "code": "CUSTOM_CALENDARS_IGNORED",
                    "message": (
                        f"{calendar_count} calendrier(s) personnalisé(s) du fichier source "
                        "ignoré(s) : Waterfall reste le référentiel maître des calendriers "
                        "de travail."
                    ),
                }
            )

    if issues:
        raise MsProjectValidationError(issues)

    return ParsedProject(
        namespace=namespace,
        save_version=save_version,
        source_version=source_version,
        external_uid=_text(root, "GUID"),
        name=_text(root, "Name"),
        schedule_from_start=schedule_from_start,
        start_date=start_date,
        finish_date=finish_date,
        calendar_uid=_integer(_text(root, "CalendarUID"), "CalendarUID", issues),
        minutes_per_day=minutes_per_day,
        minutes_per_week=minutes_per_week,
        days_per_month=days_per_month,
        currency_code=_text(root, "CurrencyCode"),
        tasks=tuple(tasks),
        links=tuple(links),
        warnings=tuple(warnings),
    )
