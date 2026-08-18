import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app

NS = {"ms": "http://schemas.microsoft.com/project"}
EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"


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
