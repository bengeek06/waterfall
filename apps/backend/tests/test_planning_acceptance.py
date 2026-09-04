"""Acceptance coverage for the planning version and draft lifecycle (E4-02, #14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import update

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject

STRUCTURE_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "data" / "planning" / "versioned-structure.json"
)
IMPORT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
    <SaveVersion>16</SaveVersion>
    <ScheduleFromStart>1</ScheduleFromStart>
    <StartDate>2026-01-01T08:00:00</StartDate>
    <Tasks>
        <Task>
            <UID>1</UID>
            <ID>1</ID>
            <Name>Imported acceptance task</Name>
            <Type>0</Type>
            <Summary>0</Summary>
            <Milestone>0</Milestone>
            <Start>2026-01-01T08:00:00</Start>
            <Finish>2026-01-02T18:00:00</Finish>
        </Task>
    </Tasks>
</Project>
"""


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"planning.acceptance.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    register = client.post("/auth/register", json={"email": email, "password": password})
    assert register.status_code == 201
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _import_xml(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    xml: bytes,
    filename: str,
    *,
    confirm: bool = True,
) -> int:
    batch_response = client.post(
        "/imports/v1/batches",
        json={"projectId": project_id, "importMode": "standard"},
        headers=headers,
    )
    assert batch_response.status_code == 201
    batch_id = cast(int, batch_response.json()["id"])

    upload_response = client.post(
        f"/imports/v1/batches/{batch_id}/xml",
        files={"file": (filename, xml, "application/xml")},
        headers=headers,
    )
    assert upload_response.status_code == 202

    if confirm:
        run_response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )
        assert run_response.status_code == 202
        assert run_response.json()["status"] == "success"
    return batch_id


def test_planning_version_and_draft_lifecycle() -> None:
    structure = cast(dict[str, Any], json.loads(STRUCTURE_FIXTURE.read_text()))

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_response: Response = client.post(
            "/projects", json={"name": "Planning acceptance"}, headers=headers
        )
        assert project_response.status_code == 201
        project_id = cast(int, project_response.json()["id"])

        draft_path = f"/projects/{project_id}/planning-structure/draft"
        saved_draft = client.put(draft_path, json=structure, headers=headers)
        assert saved_draft.status_code == 200
        assert saved_draft.json()["structure"] == structure

        generated = client.post(
            f"/projects/{project_id}/planning-structure",
            json=structure,
            headers=headers,
        )
        assert generated.status_code == 201
        generated_payload = cast(dict[str, Any], generated.json())
        assert len(cast(list[dict[str, Any]], generated_payload["tasks"])) == 9
        versions_after_generation = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert versions_after_generation.status_code == 200
        first_planning = cast(dict[str, Any], versions_after_generation.json()[0])
        first_planning_id = cast(int, first_planning["id"])
        assert first_planning["status"] == "draft"

        first_validation = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/validate",
            headers=headers,
        )
        assert first_validation.status_code == 200
        assert first_validation.json()["status"] == "validated"

        first_reference = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/reference",
            headers=headers,
        )
        assert first_reference.status_code == 200
        assert first_reference.json()["planning_reference_id"] == first_planning_id

        versions = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert versions.status_code == 200
        versions_by_id = {version["id"]: version for version in versions.json()}
        assert versions_by_id[first_planning_id]["status"] == "validated"

        displayed = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/display",
            headers=headers,
        )
        assert displayed.status_code == 200
        assert displayed.json()["displayed_planning_id"] == first_planning_id


def test_import_diff_confirmation_and_export_lifecycle() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_response = client.post(
            "/projects", json={"name": "Import acceptance"}, headers=headers
        )
        assert project_response.status_code == 201
        project_id = cast(int, project_response.json()["id"])

        batch_response = client.post(
            "/imports/v1/batches",
            json={"projectId": project_id, "importMode": "standard"},
            headers=headers,
        )
        assert batch_response.status_code == 201
        batch_id = cast(int, batch_response.json()["id"])

        upload_response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={"file": ("acceptance.xml", IMPORT_XML, "application/xml")},
            headers=headers,
        )
        assert upload_response.status_code == 202

        diff_response = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)
        assert diff_response.status_code == 200
        diff_items = cast(list[dict[str, Any]], diff_response.json()["items"])
        assert diff_items[0]["kind"] == "added"
        assert client.get(f"/projects/{project_id}/tasks", headers=headers).json() == []

        without_confirmation = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": False},
            headers=headers,
        )
        assert without_confirmation.status_code == 409

        confirmed = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )
        assert confirmed.status_code == 202
        assert confirmed.json()["status"] == "success"

        planning_response = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert planning_response.status_code == 200
        planning_payload = cast(list[dict[str, Any]], planning_response.json())
        assert len(planning_payload) == 1
        planning_id = cast(int, planning_payload[0]["id"])
        assert planning_payload[0]["status"] == "draft"

        exported = client.get(f"/projects/{project_id}/export.xml", headers=headers)
        assert exported.status_code == 200
        assert b"Imported acceptance task" in exported.content

        validated = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/validate",
            headers=headers,
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "validated"


def test_import_modify_export_reimport_round_trip() -> None:
    modified_xml = IMPORT_XML.replace(b"Imported acceptance task", b"Imported acceptance task v2")

    with TestClient(app) as client:
        headers = _auth_headers(client)
        source_project = client.post(
            "/projects", json={"name": "Round-trip source"}, headers=headers
        )
        assert source_project.status_code == 201
        source_project_id = cast(int, source_project.json()["id"])

        _import_xml(client, headers, source_project_id, IMPORT_XML, "initial.xml")
        first_planning = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{source_project_id}/plannings", headers=headers).json(),
        )[0]
        first_planning_id = cast(int, first_planning["id"])
        assert (
            client.post(
                f"/projects/{source_project_id}/plannings/{first_planning_id}/validate",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/projects/{source_project_id}/plannings/{first_planning_id}/reference",
                headers=headers,
            ).status_code
            == 200
        )

        modified_batch_id = _import_xml(
            client,
            headers,
            source_project_id,
            modified_xml,
            "modified.xml",
            confirm=False,
        )
        diff = client.get(f"/imports/v1/batches/{modified_batch_id}/diff", headers=headers)
        assert diff.status_code == 200
        diff_items = cast(list[dict[str, Any]], diff.json()["items"])
        assert any(item["kind"] == "modified" for item in diff_items)
        confirmed = client.post(
            f"/imports/v1/batches/{modified_batch_id}/run",
            json={"dryRun": False, "confirm": True},
            headers=headers,
        )
        assert confirmed.status_code == 202
        assert confirmed.json()["status"] == "success"

        plannings = client.get(f"/projects/{source_project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        planning_statuses = [item["status"] for item in plannings.json()]
        assert planning_statuses == ["validated", "draft"]
        source_export = client.get(f"/projects/{source_project_id}/export.xml", headers=headers)
        assert source_export.status_code == 200
        assert b"Imported acceptance task v2" in source_export.content

        target_project = client.post(
            "/projects", json={"name": "Round-trip target"}, headers=headers
        )
        assert target_project.status_code == 201
        target_project_id = cast(int, target_project.json()["id"])
        _import_xml(
            client,
            headers,
            target_project_id,
            cast(bytes, source_export.content),
            "round-trip.xml",
        )
        target_tasks = client.get(f"/projects/{target_project_id}/tasks", headers=headers)
        assert target_tasks.status_code == 200
        assert target_tasks.json()[0]["name"] == "Imported acceptance task v2"


def test_import_round_trip_allows_direct_draft_edit() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = client.post("/projects", json={"name": "Direct edit acceptance"}, headers=headers)
        assert project.status_code == 201
        project_id = cast(int, project.json()["id"])
        _import_xml(client, headers, project_id, IMPORT_XML, "direct-edit.xml")

        planning = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/plannings", headers=headers).json(),
        )[0]
        planning_id = cast(int, planning["id"])
        update_response = client.patch(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/1",
            json={
                "is_manual": True,
                "start_at": "2026-01-05T08:00:00Z",
                "finish_at": "2026-01-06T18:00:00Z",
                "duration_minutes": 480,
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert update_response.status_code == 200
        assert update_response.json()["revision"] == 1
        edited_task = update_response.json()["tasks"][0]
        assert edited_task["is_manual"] is True
        assert edited_task["start_at"] == "2026-01-05T08:00:00"


def test_validated_planning_rejects_direct_edit_without_mutating() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = client.post("/projects", json={"name": "Validated acceptance"}, headers=headers)
        assert project.status_code == 201
        project_id = cast(int, project.json()["id"])
        _import_xml(client, headers, project_id, IMPORT_XML, "validated.xml")
        planning = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/plannings", headers=headers).json(),
        )[0]
        planning_id = cast(int, planning["id"])
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
            ).status_code
            == 200
        )

        update_response = client.patch(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/1",
            json={
                "is_manual": True,
                "start_at": "2026-01-05T08:00:00Z",
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert update_response.status_code == 409
        current = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert current.status_code == 200
        assert current.json()["revision"] == 0


@pytest.mark.parametrize("project_status", ["perdu", "termine", "abandonne"])
def test_read_only_project_rejects_direct_edit_without_mutating(project_status: str) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = client.post("/projects", json={"name": "Read-only acceptance"}, headers=headers)
        assert project.status_code == 201
        project_id = cast(int, project.json()["id"])
        _import_xml(client, headers, project_id, IMPORT_XML, f"{project_status}.xml")
        planning = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/plannings", headers=headers).json(),
        )[0]
        planning_id = cast(int, planning["id"])

        with get_session_factory()() as session:
            session.execute(
                update(MsProject).where(MsProject.id == project_id).values(status=project_status)
            )
            session.commit()

        update_response = client.patch(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/1",
            json={
                "is_manual": True,
                "start_at": "2026-01-05T08:00:00Z",
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert update_response.status_code == 409
        current = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert current.status_code == 200
        assert current.json()["revision"] == 0
