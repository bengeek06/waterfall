import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.user import User
from waterfall.services.msproject_xml import parse_msproject_xml

NS = {"ms": "http://schemas.microsoft.com/project/2007"}
EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"
EXAMPLE_XML_WITH_CALENDARS = Path(__file__).resolve().parent / "planning_with_calendars.xml"


def _admin_headers(client: TestClient, email: str) -> dict[str, str]:
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

    session_factory = get_session_factory()
    with session_factory() as session:
        user = session.query(User).filter(User.email == email).one()
        user.is_admin = True
        session.add(user)
        session.commit()

    return {"Authorization": f"Bearer {token}"}


def _create_calendar(
    client: TestClient,
    headers: dict[str, str],
    *,
    code: str,
    weeks_per_year: int,
    weekday_hours: str,
) -> int:
    weekdays = [
        {"day_type": day_type, "hours_per_day": weekday_hours if 2 <= day_type <= 6 else "0"}
        for day_type in range(1, 8)
    ]
    response: Response = client.post(
        "/resources/calendars",
        json={
            "code": code,
            "name": f"Calendrier {code}",
            "weeks_per_year": weeks_per_year,
            "weekdays": weekdays,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, cast(dict[str, Any], response.json())["id"])


def _create_role_with_calendar(
    client: TestClient, headers: dict[str, str], *, suffix: str, calendar_id: int
) -> int:
    cost_type_id = cast(
        dict[str, Any],
        client.post(
            "/resources/cost-types",
            json={"code": f"MO-{suffix}", "name": "Main d'oeuvre", "kind": "labor"},
            headers=headers,
        ).json(),
    )["id"]
    category_id = cast(
        dict[str, Any],
        client.post(
            "/resources/categories",
            json={
                "cost_type_id": cost_type_id,
                "accounting_code": f"MO-CAT-{suffix}",
                "name": "Developpement",
            },
            headers=headers,
        ).json(),
    )["id"]
    node_id = cast(
        dict[str, Any],
        client.post(
            "/resources/nodes",
            json={"code": f"IT-{suffix}", "name": "Informatique"},
            headers=headers,
        ).json(),
    )["id"]
    role_response: Response = client.post(
        "/resources/roles",
        json={
            "code": f"DEV-{suffix}",
            "name": "Developpeur",
            "node_id": node_id,
            "cost_category_id": category_id,
            "calendar_id": calendar_id,
        },
        headers=headers,
    )
    assert role_response.status_code == 201
    return cast(int, cast(dict[str, Any], role_response.json())["id"])


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = "export.tester@example.com"
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


def test_export_xml_contains_task_notes_from_description() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_response: Response = client.post(
            "/projects",
            json={"name": "Export target"},
            headers=headers,
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        create_response: Response = client.post(
            "/imports/v1/batches",
            json={
                "projectId": project_id,
                "importMode": "standard",
                "sourceName": EXAMPLE_XML.name,
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        batch_id = create_response.json()["id"]

        upload_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={
                "file": (
                    EXAMPLE_XML.name,
                    EXAMPLE_XML.read_bytes(),
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
        project_id = status_payload["projectId"]
        assert isinstance(project_id, int)

        tasks_response: Response = client.get(
            f"/projects/{project_id}/tasks",
            headers=headers,
        )
        assert tasks_response.status_code == 200
        raw_tasks_payload = tasks_response.json()
        assert isinstance(raw_tasks_payload, list)
        tasks_payload = cast(list[dict[str, Any]], raw_tasks_payload)
        assert len(tasks_payload) > 0
        task_uid = cast(int, tasks_payload[0]["uid"])
        source_description = tasks_payload[0]["description"]
        assert source_description == "description de l'étude"

        source_export_response: Response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert source_export_response.status_code == 200
        source_root = ET.fromstring(cast(bytes, source_export_response.content))
        source_notes = source_root.find("ms:Tasks/ms:Task/ms:Notes", NS)
        assert source_notes is not None
        assert source_notes.text == source_description

        description = "Description E2E export notes"
        patch_response: Response = client.patch(
            f"/projects/{project_id}/tasks/{task_uid}",
            json={"description": description},
            headers=headers,
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["description"] == description

        export_response: Response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert export_response.status_code == 200
        assert export_response.headers["content-type"].startswith("application/xml")

        xml_content = cast(bytes, export_response.content)
        root = ET.fromstring(xml_content)
        assert root.tag == "{http://schemas.microsoft.com/project/2007}Project"
        round_trip = parse_msproject_xml(xml_content)
        assert {task.uid for task in round_trip.tasks} == {
            cast(int, task["uid"]) for task in tasks_payload
        }
        assert len(round_trip.links) == 1
        notes_by_uid: dict[int, str] = {}
        for task_node in root.findall("ms:Tasks/ms:Task", NS):
            uid_node = task_node.find("ms:UID", NS)
            notes_node = task_node.find("ms:Notes", NS)
            if (
                uid_node is None
                or uid_node.text is None
                or notes_node is None
                or notes_node.text is None
            ):
                continue
            notes_by_uid[int(uid_node.text)] = notes_node.text

        assert notes_by_uid.get(task_uid) == description


def test_export_includes_task_calendar_and_reference_minutes() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client, "export.calendars@example.com")

        project_response: Response = client.post(
            "/projects",
            json={"name": "Calendar export target"},
            headers=headers,
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        task_response: Response = client.post(
            f"/projects/{project_id}/tasks",
            json={"name": "Task with role"},
            headers=headers,
        )
        assert task_response.status_code == 201
        task_uid = cast(int, task_response.json()["uid"])

        # Monday(2)..Friday(6) at 7h/day, weekend at 0h -- same shape as the
        # STANDARD calendar seeded by the E5-01 migration, but a distinct code
        # so the reference resolution exercises the "no STANDARD calendar"
        # fallback (E5-02, smallest referenced calendar id).
        calendar_id = _create_calendar(
            client, headers, code="CAL1", weeks_per_year=47, weekday_hours="7.00"
        )
        role_id = _create_role_with_calendar(
            client, headers, suffix="CAL1", calendar_id=calendar_id
        )

        assignment_response: Response = client.post(
            f"/projects/{project_id}/tasks/{task_uid}/role-assignments",
            json={"role_id": role_id, "quantity": "1", "hours": "10"},
            headers=headers,
        )
        assert assignment_response.status_code == 201

        export_response: Response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert export_response.status_code == 200

        root = ET.fromstring(cast(bytes, export_response.content))

        calendar_nodes = root.findall("ms:Calendars/ms:Calendar", NS)
        assert len(calendar_nodes) == 1
        calendar_uid_node = calendar_nodes[0].find("ms:UID", NS)
        assert calendar_uid_node is not None and calendar_uid_node.text == str(calendar_id)

        task_calendar_node = root.find("ms:Tasks/ms:Task/ms:CalendarUID", NS)
        assert task_calendar_node is not None
        assert task_calendar_node.text == str(calendar_id)

        project_calendar_node = root.find("ms:CalendarUID", NS)
        assert project_calendar_node is not None
        assert project_calendar_node.text == str(calendar_id)

        # Expected values recomputed from the same rule as the export code
        # (services/../projects.py::_calendar_header_minutes): 5 working days
        # at 7h/day.
        working_days = 5
        hours_per_day = 7
        expected_minutes_per_day = round(hours_per_day * 60)
        expected_minutes_per_week = round(working_days * hours_per_day * 60)

        minutes_per_day_node = root.find("ms:MinutesPerDay", NS)
        minutes_per_week_node = root.find("ms:MinutesPerWeek", NS)
        assert minutes_per_day_node is not None
        assert minutes_per_week_node is not None
        assert minutes_per_day_node.text == str(expected_minutes_per_day)
        assert minutes_per_week_node.text == str(expected_minutes_per_week)

        # The export must remain valid against the canonical XSD (checked
        # implicitly by the 200 status: export_project_xml re-validates the
        # generated document and would 500 on a schema violation).
        parse_msproject_xml(cast(bytes, export_response.content))

        _assert_no_dangling_calendar_uid_references(root)


def _assert_no_dangling_calendar_uid_references(root: ET.Element) -> None:
    """Lock the E5-02 acceptance criterion: every emitted CalendarUID (at
    project level and at task level) must reference a Calendar/UID that is
    actually present in the same exported document -- no dangling reference.
    """
    declared_calendar_uids = {
        node.text for node in root.findall("ms:Calendars/ms:Calendar/ms:UID", NS)
    }
    referenced_calendar_uids = {node.text for node in root.findall(".//ms:CalendarUID", NS)}
    assert referenced_calendar_uids <= declared_calendar_uids


def test_export_task_calendar_uses_lowest_role_id_among_multiple_assignments() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client, "export.multi.calendars@example.com")

        project_response: Response = client.post(
            "/projects",
            json={"name": "Multi role calendar target"},
            headers=headers,
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        task_response: Response = client.post(
            f"/projects/{project_id}/tasks",
            json={"name": "Task with two roles"},
            headers=headers,
        )
        assert task_response.status_code == 201
        task_uid = cast(int, task_response.json()["uid"])

        calendar_a_id = _create_calendar(
            client, headers, code="CALA", weeks_per_year=47, weekday_hours="7.00"
        )
        calendar_b_id = _create_calendar(
            client, headers, code="CALB", weeks_per_year=47, weekday_hours="8.00"
        )

        role_a_id = _create_role_with_calendar(
            client, headers, suffix="CALA", calendar_id=calendar_a_id
        )
        role_b_id = _create_role_with_calendar(
            client, headers, suffix="CALB", calendar_id=calendar_b_id
        )

        # Assign the roles in an order that does not match role_id order, to
        # make sure the resolution rule really keys off role_id and not
        # insertion order.
        higher_role_id, lower_role_id = sorted([role_a_id, role_b_id], reverse=True)
        calendar_by_role_id = {role_a_id: calendar_a_id, role_b_id: calendar_b_id}
        expected_calendar_id = calendar_by_role_id[lower_role_id]

        for role_id in (higher_role_id, lower_role_id):
            assignment_response: Response = client.post(
                f"/projects/{project_id}/tasks/{task_uid}/role-assignments",
                json={"role_id": role_id, "quantity": "1", "hours": "10"},
                headers=headers,
            )
            assert assignment_response.status_code == 201

        export_response: Response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert export_response.status_code == 200

        root = ET.fromstring(cast(bytes, export_response.content))
        task_calendar_node = root.find("ms:Tasks/ms:Task/ms:CalendarUID", NS)
        assert task_calendar_node is not None
        assert task_calendar_node.text == str(expected_calendar_id)

        parse_msproject_xml(cast(bytes, export_response.content))
        _assert_no_dangling_calendar_uid_references(root)


def test_export_of_imported_project_never_reuses_source_calendar_uid() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client, "export.imported.calendars@example.com")

        # A STANDARD calendar must exist for the project reference calendar to
        # resolve to something (E5-02 fallback rule); its wf_calendar.id is
        # whatever the DB assigns, deliberately not equal to the source file's
        # arbitrary Calendar UID (999) below.
        standard_calendar_id = _create_calendar(
            client, headers, code="STANDARD", weeks_per_year=47, weekday_hours="7.00"
        )

        project_response: Response = client.post(
            "/projects",
            json={"name": "Imported calendars target"},
            headers=headers,
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

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

        export_response: Response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert export_response.status_code == 200

        root = ET.fromstring(cast(bytes, export_response.content))
        calendar_uid_nodes = root.findall("ms:Calendars/ms:Calendar/ms:UID", NS)
        exported_uids = {node.text for node in calendar_uid_nodes}

        # The source file's Calendar UID (999) must never leak into the export;
        # every exported Calendar/UID is derived from wf_calendar.id.
        assert "999" not in exported_uids
        assert exported_uids == {str(standard_calendar_id)}

        parse_msproject_xml(cast(bytes, export_response.content))
        _assert_no_dangling_calendar_uid_references(root)


def test_export_of_imported_project_preserves_original_dates_without_a_move() -> None:
    """E5-04 guardrail: a planning imported and never passed through a tree
    move (i.e. never touching move_planning_tasks/_recalculate_summary_fields)
    keeps its original Start/Finish dates exactly, byte-for-byte."""
    with TestClient(app) as client:
        headers = _admin_headers(client, "export.no_move.calendars@example.com")

        project_response: Response = client.post(
            "/projects",
            json={"name": "No-move export target"},
            headers=headers,
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

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
        assert cast(dict[str, Any], status_response.json())["status"] == "success"

        # No tree-move call happens here: this is the whole point of the test.
        export_response: Response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert export_response.status_code == 200

        root = ET.fromstring(cast(bytes, export_response.content))
        dates_by_uid: dict[str, tuple[str | None, str | None]] = {}
        for task_node in root.findall("ms:Tasks/ms:Task", NS):
            uid_node = task_node.find("ms:UID", NS)
            start_node = task_node.find("ms:Start", NS)
            finish_node = task_node.find("ms:Finish", NS)
            assert uid_node is not None and uid_node.text is not None
            dates_by_uid[uid_node.text] = (
                start_node.text if start_node is not None else None,
                finish_node.text if finish_node is not None else None,
            )

        assert dates_by_uid == {
            "1": ("2026-11-30T09:00:00", "2027-01-15T18:00:00"),
            "2": ("2027-01-18T09:00:00", "2027-06-25T18:00:00"),
        }
