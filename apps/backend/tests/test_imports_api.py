from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from _legacy_planning_support import legacy_project_tasks
from _object_storage_support import TEST_BUCKET, stored_object_keys
from waterfall.core.config import get_settings
from waterfall.core.object_storage import import_object_storage
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import Calendar, CalendarWeekday, CostCategory, CostType
from waterfall.models.wf_core import WfChargeLine, WfImportBatch
from waterfall.services.calendar_schedule import resolve_calendars_for_tasks

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

NS = {"ms": "http://schemas.microsoft.com/project"}
# Port 1 is privileged and cannot be bound by an unprivileged process, so a connection
# there is always refused -- unlike the configured test endpoint, which a developer may
# well have a real Garage listening on.
UNREACHABLE_ENDPOINT_URL = "http://127.0.0.1:1"
EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"
EXAMPLE_XML_FILES = [EXAMPLE_XML]
EXAMPLE_XML_WITH_CALENDARS = Path(__file__).resolve().parent / "planning_with_calendars.xml"


def _xml_expected_counters(xml_path: Path) -> tuple[int, int]:
    root = ET.parse(xml_path).getroot()

    task_count = 0
    link_count = 0
    for task_node in root.findall("ms:Tasks/ms:Task", NS):
        uid_node = task_node.find("ms:UID", NS)
        if uid_node is None or uid_node.text is None or uid_node.text.strip() == "":
            continue
        task_count += 1

        for pred_node in task_node.findall("ms:PredecessorLink", NS):
            pred_uid_node = pred_node.find("ms:PredecessorUID", NS)
            if pred_uid_node is None or pred_uid_node.text is None:
                continue
            if pred_uid_node.text.strip() == "":
                continue
            link_count += 1

    return task_count, link_count


def _auth_headers(client: TestClient, email: str = "import.tester@example.com") -> dict[str, str]:
    password = "SuperSecret123!"

    register_response: Response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert register_response.status_code == 201

    token_response: Response = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    )
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response: Response = client.post(
        "/projects",
        json={"name": "Import target"},
        headers=headers,
    )
    assert response.status_code == 201
    payload = cast(dict[str, Any], response.json())
    return cast(int, payload["id"])


def test_import_batch_minimal_flow() -> None:
    minimal_valid_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Project xmlns=\"http://schemas.microsoft.com/project\">
    <SaveVersion>14</SaveVersion>
    <Name>minimal.xml</Name>
    <ScheduleFromStart>1</ScheduleFromStart>
    <StartDate>2026-01-01T08:00:00</StartDate>
    <FinishDate>2026-01-10T18:00:00</FinishDate>
    <MinutesPerDay>480</MinutesPerDay>
    <MinutesPerWeek>2400</MinutesPerWeek>
    <DaysPerMonth>20</DaysPerMonth>
    <Tasks>
        <Task>
            <UID>1</UID>
            <ID>1</ID>
            <Name>T1</Name>
            <Type>0</Type>
            <Summary>0</Summary>
            <Milestone>0</Milestone>
            <Start>2026-01-01T08:00:00</Start>
            <Finish>2026-01-02T18:00:00</Finish>
        </Task>
    </Tasks>
</Project>
"""

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        create_response: Response = client.post(
            "/imports/v1/batches",
            json={
                "projectId": project_id,
                "importMode": "standard",
                "sourceName": "planning_test.xml",
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        batch = cast(dict[str, Any], create_response.json())
        assert batch["status"] == "pending"
        batch_id = cast(int, batch["id"])

        upload_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={
                "file": (
                    "planning_test.xml",
                    minimal_valid_xml,
                    "application/xml",
                )
            },
            headers=headers,
        )
        assert upload_response.status_code == 202
        assert upload_response.json()["sourceName"] == "planning_test.xml"

        session_factory = get_session_factory()
        with session_factory() as session:
            stored_batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
            assert stored_batch.source_storage_path is not None
            assert stored_batch.log_json is not None
            assert "xml_b64" not in stored_batch.log_json

        run_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": True},
            headers=headers,
        )
        errors_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}/errors",
            headers=headers,
        )
        assert run_response.status_code == 202, errors_response.text
        assert run_response.json()["status"] == "pending"

        status_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["id"] == batch_id
        assert status_payload["status"] == "pending"
        assert status_payload["counters"]["tasks"] == 0
        assert "counters" in status_payload
        assert "warnings" in status_payload

        assert legacy_project_tasks(project_id) == []

        rerun_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": True},
            headers=headers,
        )
        assert rerun_response.status_code == 202
        assert rerun_response.json()["status"] == "pending"

        reupload_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={"file": ("planning_test.xml", minimal_valid_xml, "application/xml")},
            headers=headers,
        )
        assert reupload_response.status_code == 202

        assert errors_response.status_code == 200
        assert isinstance(errors_response.json()["items"], list)


def test_import_diff_is_non_mutating_and_requires_confirmation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.diff@example.com")
        project_id = _create_project(client, headers)
        xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><ID>1</ID><Name>One</Name></Task></Tasks></Project>'
        create_response = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        batch_id = create_response.json()["id"]
        upload_response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={"file": ("diff.xml", xml, "application/xml")},
            headers=headers,
        )
        assert upload_response.status_code == 202

        diff_response = client.get(
            f"/imports/v1/batches/{batch_id}/diff",
            headers=headers,
        )
        assert diff_response.status_code == 200
        assert diff_response.json()["items"][0]["kind"] == "added"
        assert legacy_project_tasks(project_id) == []

        confirmation_response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": False},
            headers=headers,
        )
        assert confirmation_response.status_code == 409


def test_import_diff_ignores_legacy_tasks_without_an_imported_snapshot() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.diff.snapshot@example.com")
        project_id = _create_project(client, headers)
        with get_session_factory()() as session:
            session.add(
                MsTask(
                    project_id=project_id,
                    uid=1,
                    name="Legacy only",
                    is_summary=False,
                    is_milestone=False,
                )
            )
            session.commit()

        batch = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        batch_id = batch.json()["id"]
        xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>2</UID><ID>1</ID><Name>Incoming</Name></Task></Tasks></Project>'
        assert (
            client.post(
                f"/imports/v1/batches/{batch_id}/xml",
                files={"file": ("diff.xml", xml, "application/xml")},
                headers=headers,
            ).status_code
            == 202
        )

        diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)

        assert diff.status_code == 200
        assert [item["uid"] for item in diff.json()["items"]] == [2]


def _seed_displayed_draft_with_snapshot(project_id: int, uid: int, *, referenced: bool) -> None:
    with get_session_factory()() as session:
        planning = WfPlanning(project_id=project_id, version_number=1, status="draft")
        session.add(planning)
        session.flush()
        session.add(
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=uid,
                name="Referenced snapshot",
                is_summary=False,
                is_milestone=False,
            )
        )
        project = session.get(MsProject, project_id)
        assert project is not None
        project.displayed_planning_id = planning.id
        if referenced:
            session.add(
                MsTask(
                    project_id=project_id,
                    uid=uid,
                    name="Referenced legacy",
                    is_summary=False,
                    is_milestone=False,
                )
            )
            session.flush()
            session.add(WfChargeLine(project_id=project_id, task_uid=uid, load_minutes=60))
        session.commit()


def _prepare_pending_batch(
    client: TestClient, headers: dict[str, str], project_id: int, xml: bytes
) -> int:
    create = client.post(
        "/imports/v1/batches",
        json={"projectId": project_id, "importMode": "standard"},
        headers=headers,
    )
    assert create.status_code == 201
    batch_id = cast(int, create.json()["id"])
    upload = client.post(
        f"/imports/v1/batches/{batch_id}/xml",
        files={"file": ("import.xml", xml, "application/xml")},
        headers=headers,
    )
    assert upload.status_code == 202
    return batch_id


def test_confirmation_rejects_referenced_task_removal_conflict() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.conflict@example.com")
        project_id = _create_project(client, headers)
        _seed_displayed_draft_with_snapshot(project_id, uid=1, referenced=True)

        # Incoming XML drops UID 1 (which is referenced) and only keeps UID 2.
        xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>2</UID><ID>1</ID><Name>Incoming</Name></Task></Tasks></Project>'
        batch_id = _prepare_pending_batch(client, headers, project_id, xml)

        run = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )

        assert run.status_code == 409
        detail = run.json()["detail"]
        assert detail["code"] == "IMPORT_CONFLICT"
        assert detail["conflicts"] == [1]

        status_response = client.get(f"/imports/v1/batches/{batch_id}", headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "pending"

        with get_session_factory()() as session:
            preserved = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.uid == 1)
                .count()
            )
            assert preserved == 1


def test_confirmation_succeeds_when_removed_task_is_not_referenced() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.no.conflict@example.com")
        project_id = _create_project(client, headers)
        _seed_displayed_draft_with_snapshot(project_id, uid=1, referenced=False)

        xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>2</UID><ID>1</ID><Name>Incoming</Name></Task></Tasks></Project>'
        batch_id = _prepare_pending_batch(client, headers, project_id, xml)

        run = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )

        assert run.status_code == 202
        assert run.json()["status"] == "success"


def _seed_supply_category() -> int:
    """An active supply `CostCategory`, the minimum needed to create a cost line."""
    with get_session_factory()() as session:
        cost_type = CostType(code=f"FOURN-{uuid4().hex[:8]}", name="Fourniture", kind="supply")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"FO-{uuid4().hex[:8]}",
            category_code="ACHAT",
            name="Cables",
        )
        session.add(category)
        session.commit()
        return category.id


def _tasks_xml(*uids: int) -> bytes:
    tasks = "".join(
        f"<Task><UID>{uid}</UID><ID>{uid}</ID><Name>T{uid}</Name>"
        f"<OutlineNumber>{uid}</OutlineNumber><OutlineLevel>1</OutlineLevel></Task>"
        for uid in uids
    )
    return (
        '<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion>'
        "<ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate>"
        f"<Tasks>{tasks}</Tasks></Project>"
    ).encode()


def test_reimport_conflicts_on_a_task_priced_by_an_existing_estimate() -> None:
    """Contract change introduced by issue #313, locked here on purpose.

    Now that the XML import writes the canonical `MsTask` rows, the
    `ms_task.id`-keyed branches of `is_task_referenced` (reached through
    `build_import_diff`) actually bite on an imported project: re-importing a
    file that drops a task already carrying an `EstimateCostLine` is rejected
    with 409 `IMPORT_CONFLICT` instead of silently deleting the priced task's
    planning side. Before the fix, an imported project had no `MsTask` at all,
    so those branches could never match.

    Note the conflict surface is wider than the cost line alone: creating a
    devis also fills `EstimateTaskRow.task_id`, itself a referencing column.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.estimate.conflict@example.com")
        project_id = _create_project(client, headers)

        batch_id = _prepare_pending_batch(client, headers, project_id, _tasks_xml(1, 2))
        first_run = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )
        assert first_run.status_code == 202
        assert first_run.json()["status"] == "success"

        estimate = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert estimate.status_code == 201
        estimate_id = cast(int, estimate.json()["id"])

        rows = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/task-rows", headers=headers
        )
        assert rows.status_code == 200
        task_id_by_uid = {
            cast(int, row["task_uid"]): cast(int, row["task_id"])
            for row in cast(list[dict[str, Any]], rows.json()["items"])
        }
        assert set(task_id_by_uid) == {1, 2}

        cost_line = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "task_id": task_id_by_uid[2],
                "cost_category_id": _seed_supply_category(),
                "label": "Cable",
                "quantity": "2.00",
                "unit_cost": "10.00",
            },
            headers=headers,
        )
        assert cost_line.status_code == 201

        second_batch_id = _prepare_pending_batch(client, headers, project_id, _tasks_xml(1))
        rerun = client.post(
            f"/imports/v1/batches/{second_batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )

        assert rerun.status_code == 409
        detail = rerun.json()["detail"]
        assert detail["code"] == "IMPORT_CONFLICT"
        assert detail["conflicts"] == [2]

        # The batch stays reusable, and nothing of the priced task was touched.
        batch_status = client.get(f"/imports/v1/batches/{second_batch_id}", headers=headers)
        assert batch_status.status_code == 200
        assert batch_status.json()["status"] == "pending"
        with get_session_factory()() as session:
            assert (
                session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.uid == 2)
                .count()
                == 1
            )
            assert (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.uid == 2)
                .count()
                == 1
            )


def test_confirmed_run_never_resolves_calendars_under_the_project_lock() -> None:
    """Issue #176 regression: _reject_diff_conflicts (called from
    _run_confirmed_import while still holding the project-row lock taken by
    _relock_pending_batch) must never trigger the calendar-mismatch
    diagnostic's calendar resolution -- it only ever reads "conflict" items,
    and resolving calendars for a result it never consumes would hold that
    lock longer for nothing (see build_import_diff's include_calendar_mismatch
    parameter). Spies on resolve_calendars_for_tasks to prove the confirmed
    run path never calls it, while the unlocked GET .../diff preview endpoint
    (which does need the diagnostic) still does."""
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.calendar.lock@example.com")
        project_id = _create_project(client, headers)

        with get_session_factory()() as session:
            calendar = Calendar(
                code="STANDARD", name="Standard", weeks_per_year=52, is_default=True
            )
            session.add(calendar)
            session.flush()
            session.add_all(
                CalendarWeekday(
                    calendar_id=calendar.id,
                    day_type=day_type,
                    hours_per_day=Decimal("0.00") if day_type in (1, 7) else Decimal("8.00"),
                )
                for day_type in range(1, 8)
            )
            session.commit()

        # Start/Finish spans two working days (Mon 08:00 -> Tue 16:00) but
        # Duration only claims one (480 min) -- a genuine calendar_mismatch
        # candidate if the diagnostic actually ran.
        xml = (
            b'<Project xmlns="http://schemas.microsoft.com/project">'
            b"<SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart>"
            b"<StartDate>2026-01-05T08:00:00</StartDate>"
            b"<Tasks><Task><UID>1</UID><ID>1</ID><Name>Mismatch candidate</Name>"
            b"<Type>0</Type><Summary>0</Summary><Milestone>0</Milestone><Manual>0</Manual>"
            b"<Start>2026-01-05T08:00:00</Start><Finish>2026-01-06T16:00:00</Finish>"
            b"<Duration>PT480M</Duration></Task></Tasks></Project>"
        )
        batch_id = _prepare_pending_batch(client, headers, project_id, xml)

        with patch(
            "waterfall.services.import_diff.resolve_calendars_for_tasks",
            wraps=resolve_calendars_for_tasks,
        ) as spy:
            diff_response = client.get(
                f"/imports/v1/batches/{batch_id}/diff",
                headers=headers,
            )
            assert diff_response.status_code == 200
            mismatch_items = [
                item
                for item in diff_response.json()["items"]
                if item["kind"] == "calendar_mismatch"
            ]
            assert mismatch_items, "fixture must actually produce a calendar_mismatch candidate"
            assert spy.call_count >= 1

            spy.reset_mock()

            run = client.post(
                f"/imports/v1/batches/{batch_id}/run",
                json={"dryRun": False, "confirm": True},
                headers=headers,
            )
            assert run.status_code == 202
            assert run.json()["status"] == "success"
            assert spy.call_count == 0


def test_invalid_import_exposes_structured_validation_errors() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.invalid@example.com")
        project_id = _create_project(client, headers)
        response = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        batch_id = response.json()["id"]
        client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={"file": ("invalid.xml", b"<Project", "application/xml")},
            headers=headers,
        )
        run = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"confirm": True},
            headers=headers,
        )
        assert run.status_code == 400
        errors = client.get(f"/imports/v1/batches/{batch_id}/errors", headers=headers)
        assert errors.status_code == 200
        assert errors.json()["items"][0]["code"] == "MALFORMED_XML"


def test_invalid_confirmed_import_parses_the_xml_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed confirm-path import must not re-parse the XML under the project lock."""
    import waterfall.api.routes.imports as imports_module

    call_count = 0
    real_parse = imports_module.parse_msproject_xml

    def counting_parse(xml_bytes: bytes) -> object:
        nonlocal call_count
        call_count += 1
        return real_parse(xml_bytes)

    monkeypatch.setattr(imports_module, "parse_msproject_xml", counting_parse)

    with TestClient(app) as client:
        headers = _auth_headers(client, "import.invalid-once@example.com")
        project_id = _create_project(client, headers)
        response = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        batch_id = response.json()["id"]
        client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={"file": ("invalid.xml", b"<Project", "application/xml")},
            headers=headers,
        )
        run = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"confirm": True},
            headers=headers,
        )
        assert run.status_code == 400

    assert call_count == 1


def test_identical_source_is_detected_without_reapplying() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.identical@example.com")
        project_id = _create_project(client, headers)
        xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><ID>1</ID><Name>One</Name></Task></Tasks></Project>'
        batch_ids: list[int] = []
        for index in range(2):
            response = client.post(
                "/imports/v1/batches",
                json={"projectId": project_id, "importMode": "standard"},
                headers=headers,
            )
            batch_id = cast(int, response.json()["id"])
            batch_ids.append(batch_id)
            upload = client.post(
                f"/imports/v1/batches/{batch_id}/xml",
                files={"file": (f"same-{index}.xml", xml, "application/xml")},
                headers=headers,
            )
            assert upload.status_code == 202
            run = client.post(
                f"/imports/v1/batches/{batch_id}/run",
                json={"confirm": True},
                headers=headers,
            )
            assert run.status_code == 202

        status = client.get(f"/imports/v1/batches/{batch_ids[1]}", headers=headers)
        assert status.status_code == 200
        assert status.json()["counters"]["tasks"] == 1


def test_identical_source_after_validation_creates_a_new_draft() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.identical.validated@example.com")
        project_id = _create_project(client, headers)
        xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><ID>1</ID><Name>One</Name></Task></Tasks></Project>'

        def import_source() -> int:
            batch = client.post(
                "/imports/v1/batches",
                json={"projectId": project_id, "importMode": "standard"},
                headers=headers,
            )
            batch_id = cast(int, batch.json()["id"])
            assert (
                client.post(
                    f"/imports/v1/batches/{batch_id}/xml",
                    files={"file": ("same.xml", xml, "application/xml")},
                    headers=headers,
                ).status_code
                == 202
            )
            assert (
                client.post(
                    f"/imports/v1/batches/{batch_id}/run",
                    json={"confirm": True},
                    headers=headers,
                ).status_code
                == 202
            )
            return batch_id

        import_source()
        planning = client.get(f"/projects/{project_id}/plannings", headers=headers).json()["items"][
            0
        ]
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning['id']}/validate", headers=headers
            ).status_code
            == 200
        )
        second_batch_id = import_source()

        plannings = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        assert [item["status"] for item in plannings.json()["items"]] == ["validated", "draft"]
        session_factory = get_session_factory()
        with session_factory() as session:
            second_batch = (
                session.query(WfImportBatch).filter(WfImportBatch.id == second_batch_id).one()
            )
            assert json.loads(second_batch.log_json or "{}")["identical_source"] is True


@pytest.mark.parametrize("xml_path", EXAMPLE_XML_FILES, ids=lambda p: p.name)
def test_import_batch_real_examples_via_api_with_counters(xml_path: Path) -> None:
    expected_tasks, expected_links = _xml_expected_counters(xml_path)

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        create_response: Response = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard", "sourceName": xml_path.name},
            headers=headers,
        )
        assert create_response.status_code == 201
        batch_id = create_response.json()["id"]

        upload_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={
                "file": (
                    xml_path.name,
                    xml_path.read_bytes(),
                    "application/xml",
                )
            },
            headers=headers,
        )
        assert upload_response.status_code == 202

        run_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )
        assert run_response.status_code == 202

        status_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["status"] == "success"
        assert status_payload["counters"]["tasks"] == expected_tasks
        assert status_payload["counters"]["links"] == expected_links


def test_import_of_custom_calendars_is_ignored_but_reported_as_warning() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        calendar_count_before = session.query(Calendar).count()
        weekday_count_before = session.query(CalendarWeekday).count()

    with TestClient(app) as client:
        headers = _auth_headers(client, "import.calendars@example.com")
        project_id = _create_project(client, headers)

        create_response: Response = client.post(
            "/imports/v1/batches",
            json={
                "projectId": project_id,
                "importMode": "standard",
                "sourceName": EXAMPLE_XML_WITH_CALENDARS.name,
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        batch_id = create_response.json()["id"]

        upload_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={
                "file": (
                    EXAMPLE_XML_WITH_CALENDARS.name,
                    EXAMPLE_XML_WITH_CALENDARS.read_bytes(),
                    "application/xml",
                )
            },
            headers=headers,
        )
        assert upload_response.status_code == 202

        run_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )
        assert run_response.status_code == 202

        status_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = cast(dict[str, Any], status_response.json())
        assert status_payload["status"] == "success"
        warnings = cast(list[dict[str, Any]], status_payload["warnings"])
        assert len(warnings) == 1
        assert warnings[0]["code"] == "CUSTOM_CALENDARS_IGNORED"

    with session_factory() as session:
        assert session.query(Calendar).count() == calendar_count_before
        assert session.query(CalendarWeekday).count() == weekday_count_before


def test_import_api_writes_draft_snapshots_and_preserves_validated_history() -> None:
    source = EXAMPLE_XML.read_bytes()
    updated_source = source.replace(b"Etude documentaire", b"Etude documentaire v2")

    with TestClient(app) as client:
        headers = _auth_headers(client, "import.lifecycle@example.com")
        project_id = _create_project(client, headers)

        first_create = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        assert first_create.status_code == 201
        first_batch_id = cast(int, first_create.json()["id"])
        assert (
            client.post(
                f"/imports/v1/batches/{first_batch_id}/xml",
                files={"file": ("first.xml", source, "application/xml")},
                headers=headers,
            ).status_code
            == 202
        )
        assert (
            client.post(
                f"/imports/v1/batches/{first_batch_id}/run",
                json={"confirm": True},
                headers=headers,
            ).status_code
            == 202
        )

        first_planning_response = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert first_planning_response.status_code == 200
        first_planning_items = cast(list[dict[str, Any]], first_planning_response.json()["items"])
        assert len(first_planning_items) == 1
        first_planning_id = cast(int, first_planning_items[0]["id"])

        validate_response = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        second_create = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        assert second_create.status_code == 201
        second_batch_id = cast(int, second_create.json()["id"])
        assert (
            client.post(
                f"/imports/v1/batches/{second_batch_id}/xml",
                files={"file": ("second.xml", updated_source, "application/xml")},
                headers=headers,
            ).status_code
            == 202
        )
        assert (
            client.post(
                f"/imports/v1/batches/{second_batch_id}/run",
                json={"confirm": True},
                headers=headers,
            ).status_code
            == 202
        )

        status_response = client.get(f"/imports/v1/batches/{second_batch_id}", headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["counters"] == {"tasks": 2, "links": 1}

        session_factory = get_session_factory()
        with session_factory() as session:
            plannings = (
                session.query(WfPlanning)
                .filter(WfPlanning.project_id == project_id)
                .order_by(WfPlanning.version_number)
                .all()
            )
            assert [planning.status for planning in plannings] == ["validated", "draft"]
            assert (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == plannings[0].id)
                .filter(WfPlanningTaskSnapshot.name == "Etude documentaire")
                .count()
                == 1
            )
            assert (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == plannings[1].id)
                .count()
                == 2
            )
            assert (
                session.query(WfPlanningTaskSnapshot)
                .filter(
                    WfPlanningTaskSnapshot.planning_id == plannings[1].id,
                    WfPlanningTaskSnapshot.name == "Etude documentaire v2",
                )
                .count()
                == 1
            )
            assert (
                session.query(WfPlanningLinkSnapshot)
                .filter(WfPlanningLinkSnapshot.planning_id == plannings[1].id)
                .count()
                == 1
            )


def test_import_batch_isolated_by_project_owner() -> None:
    with TestClient(app) as client:
        owner_headers = _auth_headers(client)
        project_id = _create_project(client, owner_headers)
        create_response = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=owner_headers,
        )
        assert create_response.status_code == 201
        batch_id = create_response.json()["id"]

        other_headers = _auth_headers(client, "import.other@example.com")
        for path in (f"/imports/v1/batches/{batch_id}", f"/imports/v1/batches/{batch_id}/errors"):
            response: Response = client.get(path, headers=other_headers)
            assert response.status_code == 404


def test_upload_rejects_files_over_configured_limit(
    monkeypatch: pytest.MonkeyPatch, object_storage: S3Client
) -> None:
    monkeypatch.setenv("IMPORT_MAX_UPLOAD_BYTES", "8")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            headers = _auth_headers(client)
            project_id = _create_project(client, headers)
            create_response = client.post(
                "/imports/v1/batches",
                json={"projectId": project_id, "importMode": "standard"},
                headers=headers,
            )
            assert create_response.status_code == 201
            batch_id = create_response.json()["id"]

            upload_response = client.post(
                f"/imports/v1/batches/{batch_id}/xml",
                files={"file": ("too-large.xml", b"123456789", "application/xml")},
                headers=headers,
            )
            assert upload_response.status_code == 413
            # The limit is enforced while the request body is being read, before the
            # upload call: an oversized file must never reach the bucket at all.
            assert stored_object_keys(object_storage) == []
    finally:
        get_settings.cache_clear()


def test_uploaded_source_is_stored_under_an_object_key_not_a_disk_path(
    object_storage: S3Client,
) -> None:
    """E13-02: `source_storage_path` names an object in the bucket, not a local file."""
    xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><ID>1</ID><Name>One</Name></Task></Tasks></Project>'

    with TestClient(app) as client:
        headers = _auth_headers(client, "import.storage.key@example.com")
        project_id = _create_project(client, headers)
        batch_id = _prepare_pending_batch(client, headers, project_id, xml)

        with get_session_factory()() as session:
            stored_batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
            storage_key = stored_batch.source_storage_path
            assert storage_key == f"imports/batch-{batch_id}.xml"

        assert storage_key is not None
        assert not Path(storage_key).is_absolute()
        assert not Path(storage_key).exists()

        # The object really is in the bucket, byte for byte, and the staging object used
        # during the upload was cleaned up.
        body = object_storage.get_object(Bucket=TEST_BUCKET, Key=storage_key)["Body"].read()
        assert body == xml
        assert stored_object_keys(object_storage) == [storage_key]

        # And the batch is usable end to end from that key alone.
        run = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"confirm": True},
            headers=headers,
        )
        assert run.status_code == 202


@pytest.mark.no_object_storage_mock
def test_upload_reports_object_storage_outage_without_touching_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garage down during an upload: explicit 503, and the batch stays untouched."""
    monkeypatch.setenv("GARAGE_ENDPOINT_URL", UNREACHABLE_ENDPOINT_URL)
    get_settings.cache_clear()
    import_object_storage.reset()
    try:
        with TestClient(app) as client:
            headers = _auth_headers(client, "import.storage.down@example.com")
            project_id = _create_project(client, headers)
            create_response = client.post(
                "/imports/v1/batches",
                json={"projectId": project_id, "importMode": "standard"},
                headers=headers,
            )
            assert create_response.status_code == 201
            batch_id = cast(int, create_response.json()["id"])

            upload = client.post(
                f"/imports/v1/batches/{batch_id}/xml",
                files={"file": ("import.xml", b"<Project/>", "application/xml")},
                headers=headers,
            )

            assert upload.status_code == 503
            # main.py's _generic_http_exception_handler rewrites every string detail into
            # this translatable code, so the storage endpoint never leaks into the body.
            assert upload.json() == {"detail": {"code": "GENERIC_ERROR"}}

            with get_session_factory()() as session:
                batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
                # Still pending, still without a source: no half-written state to clean up.
                assert batch.status == "pending"
                assert batch.source_storage_path is None
                assert batch.source_sha256 is None
    finally:
        get_settings.cache_clear()
        import_object_storage.reset()


@pytest.mark.no_object_storage_mock
def test_run_reports_object_storage_outage_and_leaves_the_batch_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garage down between upload and run: explicit 503, batch still replayable.

    The batch must not be marked `failed`: nothing about it is wrong, and flipping it
    out of `pending` would make the retry that becomes possible once storage is back
    impossible (run_batch only accepts pending batches).
    """
    monkeypatch.setenv("GARAGE_ENDPOINT_URL", UNREACHABLE_ENDPOINT_URL)
    get_settings.cache_clear()
    import_object_storage.reset()
    try:
        with TestClient(app) as client:
            headers = _auth_headers(client, "import.storage.run.down@example.com")
            project_id = _create_project(client, headers)
            create_response = client.post(
                "/imports/v1/batches",
                json={"projectId": project_id, "importMode": "standard"},
                headers=headers,
            )
            assert create_response.status_code == 201
            batch_id = cast(int, create_response.json()["id"])

            # Simulate a batch uploaded while storage was up: only the row matters here,
            # the object itself is exactly what the outage makes unreachable.
            with get_session_factory()() as session:
                batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
                batch.source_storage_path = f"imports/batch-{batch_id}.xml"
                batch.source_sha256 = "0" * 64
                batch.log_json = json.dumps({"uploaded_bytes": 10})
                session.commit()

            for payload in ({"dryRun": True}, {"confirm": True}):
                run = client.post(
                    f"/imports/v1/batches/{batch_id}/run", json=payload, headers=headers
                )
                assert run.status_code == 503, payload
                assert run.json() == {"detail": {"code": "GENERIC_ERROR"}}

            diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)
            assert diff.status_code == 503

            with get_session_factory()() as session:
                batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
                assert batch.status == "pending"
                assert batch.finished_at is None
                assert batch.source_sha256 == "0" * 64
    finally:
        get_settings.cache_clear()
        import_object_storage.reset()


def test_missing_bucket_is_reported_as_an_outage_not_as_a_dead_batch(
    object_storage: S3Client,
) -> None:
    """A vanished bucket is broken infrastructure (503), never a broken batch (409).

    `NoSuchBucket` used to be classified alongside `NoSuchKey`, so a half-finished
    garage-init (layout applied, bucket never created) or a wiped volume answered 409
    "Uploaded XML is unavailable" -- a permanent state conflict, telling the user to
    give up on a batch that is in fact perfectly replayable once the bucket is back.
    """
    xml = b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><ID>1</ID><Name>One</Name></Task></Tasks></Project>'

    with TestClient(app) as client:
        headers = _auth_headers(client, "import.storage.nobucket@example.com")
        project_id = _create_project(client, headers)
        batch_id = _prepare_pending_batch(client, headers, project_id, xml)

        for key in stored_object_keys(object_storage):
            object_storage.delete_object(Bucket=TEST_BUCKET, Key=key)
        object_storage.delete_bucket(Bucket=TEST_BUCKET)

        run = client.post(
            f"/imports/v1/batches/{batch_id}/run", json={"confirm": True}, headers=headers
        )
        assert run.status_code == 503
        assert run.json() == {"detail": {"code": "GENERIC_ERROR"}}

        diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)
        assert diff.status_code == 503

        with get_session_factory()() as session:
            batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
            assert batch.status == "pending"
            assert batch.finished_at is None


def test_legacy_batch_pointing_at_a_disk_path_is_rejected(object_storage: S3Client) -> None:
    """E13-02 migrates no data: a pre-switch batch is simply unusable, and says so.

    Its `source_storage_path` is a filesystem path, which the bucket resolves as an
    ordinary (missing) key. 409, not 503: nothing is down, that source really is gone
    for good, and the user has to re-upload.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client, "import.legacy.path@example.com")
        project_id = _create_project(client, headers)
        create = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        assert create.status_code == 201
        batch_id = cast(int, create.json()["id"])

        with get_session_factory()() as session:
            batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
            batch.source_storage_path = f"/data/imports/batch-{batch_id}.xml"
            batch.source_sha256 = "0" * 64
            batch.log_json = json.dumps({"uploaded_bytes": 10})
            session.commit()

        for payload in ({"dryRun": True}, {"confirm": True}):
            run = client.post(f"/imports/v1/batches/{batch_id}/run", json=payload, headers=headers)
            assert run.status_code == 409, payload

        diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)
        assert diff.status_code == 409

        # No object was created under that path, and the batch stays replayable after a
        # fresh upload.
        assert stored_object_keys(object_storage) == []
        with get_session_factory()() as session:
            batch = session.query(WfImportBatch).filter(WfImportBatch.id == batch_id).one()
            assert batch.status == "pending"


def test_upload_larger_than_the_multipart_threshold_is_stored_intact(
    object_storage: S3Client,
) -> None:
    """Above 8 MiB, s3transfer would have switched to multipart; a single PUT must not.

    That threshold sits well below the 25 MB upload limit, so this size range is the
    normal case for a large MS Project export -- and it is the one where s3transfer
    re-buffers every part in memory, which is exactly what the spooled staging buffer
    exists to avoid.
    """
    padding = b"<!--" + b"x" * (9 * 1024 * 1024) + b"-->"
    xml = (
        b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion>'
        b"<ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate>"
        + padding
        + b"<Tasks><Task><UID>1</UID><ID>1</ID><Name>One</Name></Task></Tasks></Project>"
    )
    assert len(xml) > 8 * 1024 * 1024
    assert len(xml) < get_settings().import_max_upload_bytes

    with TestClient(app) as client:
        headers = _auth_headers(client, "import.storage.large@example.com")
        project_id = _create_project(client, headers)
        batch_id = _prepare_pending_batch(client, headers, project_id, xml)

        key = f"imports/batch-{batch_id}.xml"
        assert stored_object_keys(object_storage) == [key]
        assert object_storage.get_object(Bucket=TEST_BUCKET, Key=key)["Body"].read() == xml

        run = client.post(
            f"/imports/v1/batches/{batch_id}/run", json={"confirm": True}, headers=headers
        )
        assert run.status_code == 202
