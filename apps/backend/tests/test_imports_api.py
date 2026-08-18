import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app

NS = {"ms": "http://schemas.microsoft.com/project"}
EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"
EXAMPLE_XML_FILES = [EXAMPLE_XML]


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
    return response.json()["id"]


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
        batch = create_response.json()
        assert batch["status"] == "pending"
        batch_id = batch["id"]

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

        run_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": True, "failFast": True},
            headers=headers,
        )
        assert run_response.status_code == 202
        assert run_response.json()["status"] == "running"

        status_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["id"] == batch_id
        assert "counters" in status_payload
        assert "warnings" in status_payload

        errors_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}/errors",
            headers=headers,
        )
        assert errors_response.status_code == 200
        assert isinstance(errors_response.json()["items"], list)


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
            json={"dryRun": False, "failFast": True},
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
