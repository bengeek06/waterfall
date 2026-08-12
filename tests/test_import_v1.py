from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink

NS = {"ms": "http://schemas.microsoft.com/project"}
EXAMPLE_XML = Path(__file__).resolve().parents[1] / "examples" / "planning_rain.xml"
EXAMPLE_XML_FILES = sorted(
    (Path(__file__).resolve().parents[1] / "examples").glob("planning_*.xml")
)


def _txt(node: ET.Element, path: str) -> str | None:
    found = node.find(path, NS)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value if value != "" else None


def _as_int(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _as_bool(value: str | None) -> bool:
    return value == "1"


def _as_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _import_v1_tasks_and_links(xml_path: Path) -> tuple[int, int, int]:
    root = ET.parse(xml_path).getroot()

    save_version = _as_int(_txt(root, "ms:SaveVersion")) or 16
    source_version_map = {14: 2010, 15: 2013, 16: 2016}
    source_version = source_version_map.get(save_version, 2016)

    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            external_uid=_txt(root, "ms:GUID"),
            source_version=source_version,
            save_version_out=save_version if save_version in (14, 15, 16) else 16,
            name=_txt(root, "ms:Name") or xml_path.name,
            schedule_from_start=_as_bool(_txt(root, "ms:ScheduleFromStart")),
            start_date=_as_dt(_txt(root, "ms:StartDate")),
            finish_date=_as_dt(_txt(root, "ms:FinishDate")),
            calendar_uid=_as_int(_txt(root, "ms:CalendarUID")),
            minutes_per_day=_as_int(_txt(root, "ms:MinutesPerDay")) or 480,
            minutes_per_week=_as_int(_txt(root, "ms:MinutesPerWeek")) or 2400,
            days_per_month=_as_int(_txt(root, "ms:DaysPerMonth")) or 20,
            currency_code=_txt(root, "ms:CurrencyCode"),
        )
        session.add(project)
        session.flush()

        tasks: list[MsTask] = []
        links: list[MsTaskLink] = []

        for task_node in root.findall("ms:Tasks/ms:Task", NS):
            uid = _as_int(_txt(task_node, "ms:UID"))
            if uid is None:
                continue

            tasks.append(
                MsTask(
                    project_id=project.id,
                    uid=uid,
                    id_display=_as_int(_txt(task_node, "ms:ID")),
                    name=_txt(task_node, "ms:Name") or f"Task {uid}",
                    task_type=_as_int(_txt(task_node, "ms:Type")),
                    outline_number=_txt(task_node, "ms:OutlineNumber"),
                    outline_level=_as_int(_txt(task_node, "ms:OutlineLevel")),
                    wbs=_txt(task_node, "ms:WBS"),
                    start_at=_as_dt(_txt(task_node, "ms:Start")),
                    finish_at=_as_dt(_txt(task_node, "ms:Finish")),
                    duration_format=_as_int(_txt(task_node, "ms:DurationFormat")),
                    percent_complete=_as_int(_txt(task_node, "ms:PercentComplete")),
                    is_summary=_as_bool(_txt(task_node, "ms:Summary")),
                    is_milestone=_as_bool(_txt(task_node, "ms:Milestone")),
                    calendar_uid=_as_int(_txt(task_node, "ms:CalendarUID")),
                )
            )

            for pred_node in task_node.findall("ms:PredecessorLink", NS):
                predecessor_uid = _as_int(_txt(pred_node, "ms:PredecessorUID"))
                if predecessor_uid is None:
                    continue

                links.append(
                    MsTaskLink(
                        project_id=project.id,
                        task_uid=uid,
                        predecessor_uid=predecessor_uid,
                        link_type=_as_int(_txt(pred_node, "ms:Type")) or 1,
                        lag_tenth_minute=_as_int(_txt(pred_node, "ms:LinkLag")),
                        lag_format=_as_int(_txt(pred_node, "ms:LagFormat")),
                    )
                )

        session.add_all(tasks)
        session.flush()
        session.add_all(links)
        session.commit()

        task_count = session.query(MsTask).filter(MsTask.project_id == project.id).count()
        link_count = session.query(MsTaskLink).filter(MsTaskLink.project_id == project.id).count()

        return project.id, task_count, link_count


def test_import_v1_tasks_and_dependencies_from_example() -> None:
    assert EXAMPLE_XML.exists(), f"XML example not found: {EXAMPLE_XML}"

    project_id, task_count, link_count = _import_v1_tasks_and_links(EXAMPLE_XML)

    assert project_id > 0
    assert task_count > 0
    assert link_count > 0

    session_factory = get_session_factory()
    with session_factory() as session:
        task_uids = {
            uid
            for (uid,) in session.query(MsTask.uid).filter(MsTask.project_id == project_id).all()
        }
        links = session.query(MsTaskLink).filter(MsTaskLink.project_id == project_id).all()

        # Every dependency must point to existing tasks in the same imported project.
        assert all(link.task_uid in task_uids for link in links)
        assert all(link.predecessor_uid in task_uids for link in links)


@pytest.mark.parametrize("xml_path", EXAMPLE_XML_FILES, ids=lambda p: p.name)
def test_import_v1_all_real_examples(xml_path: Path) -> None:
    assert xml_path.exists(), f"XML example not found: {xml_path}"

    project_id, task_count, link_count = _import_v1_tasks_and_links(xml_path)

    assert project_id > 0
    assert task_count > 0
    assert link_count >= 0
