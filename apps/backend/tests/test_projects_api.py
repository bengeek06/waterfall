from datetime import UTC, datetime
from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = "projects.tester@example.com"
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


def _seed_projects_and_tasks() -> tuple[int, int]:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Project API Test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
            finish_date=datetime(2026, 1, 20, 18, 0, tzinfo=UTC),
            calendar_uid=1,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()

        task1 = MsTask(
            project_id=project.id,
            uid=1001,
            id_display=1,
            name="Task One",
            task_type=0,
            outline_number="1",
            outline_level=1,
            wbs="1",
            start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
            finish_at=datetime(2026, 1, 6, 18, 0, tzinfo=UTC),
            duration_minutes=None,
            duration_format=None,
            work_minutes=None,
            percent_complete=20,
            is_summary=False,
            is_milestone=False,
            calendar_uid=1,
        )
        task2 = MsTask(
            project_id=project.id,
            uid=1002,
            id_display=2,
            name="Task Two",
            task_type=0,
            outline_number="2",
            outline_level=1,
            wbs="2",
            start_at=datetime(2026, 1, 7, 8, 0, tzinfo=UTC),
            finish_at=datetime(2026, 1, 10, 18, 0, tzinfo=UTC),
            duration_minutes=None,
            duration_format=None,
            work_minutes=None,
            percent_complete=0,
            is_summary=False,
            is_milestone=False,
            calendar_uid=1,
        )
        session.add_all([task1, task2])
        session.commit()
        return project.id, 2


def test_get_projects_and_project_tasks() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, expected_tasks = _seed_projects_and_tasks()

        projects_response: Response = client.get("/projects", headers=headers)
        assert projects_response.status_code == 200
        raw_projects_payload = projects_response.json()
        assert isinstance(raw_projects_payload, list)
        projects_payload = cast(list[dict[str, Any]], raw_projects_payload)
        assert len(projects_payload) >= 1
        assert any(project["id"] == project_id for project in projects_payload)

        project_response: Response = client.get(f"/projects/{project_id}", headers=headers)
        assert project_response.status_code == 200
        raw_project_payload = project_response.json()
        assert isinstance(raw_project_payload, dict)
        project_payload = cast(dict[str, Any], raw_project_payload)
        assert project_payload["id"] == project_id
        assert project_payload["name"] == "Project API Test"

        tasks_response: Response = client.get(
            f"/projects/{project_id}/tasks",
            headers=headers,
        )
        assert tasks_response.status_code == 200
        raw_tasks_payload = tasks_response.json()
        assert isinstance(raw_tasks_payload, list)
        tasks_payload = cast(list[dict[str, Any]], raw_tasks_payload)
        assert len(tasks_payload) == expected_tasks
        assert tasks_payload[0]["project_id"] == project_id
        assert all("description" in task for task in tasks_payload)


def test_patch_task_description_and_read_back() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks()

        patch_response: Response = client.patch(
            f"/projects/{project_id}/tasks/1001",
            json={"description": "Description enrichie depuis Waterfall"},
            headers=headers,
        )
        assert patch_response.status_code == 200
        patch_payload = patch_response.json()
        assert patch_payload["uid"] == 1001
        assert patch_payload["description"] == "Description enrichie depuis Waterfall"

        tasks_response: Response = client.get(
            f"/projects/{project_id}/tasks",
            headers=headers,
        )
        assert tasks_response.status_code == 200
        tasks_payload = cast(list[dict[str, Any]], tasks_response.json())

        task_by_uid = {task["uid"]: task for task in tasks_payload}
        assert task_by_uid[1001]["description"] == "Description enrichie depuis Waterfall"
        assert task_by_uid[1002]["description"] is None


def test_patch_task_description_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks()

        response: Response = client.patch(
            f"/projects/{project_id}/tasks/999999",
            json={"description": "X"},
            headers=headers,
        )
        assert response.status_code == 404


def test_get_project_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        response: Response = client.get("/projects/999999", headers=headers)
        assert response.status_code == 404


def test_get_projects_requires_auth() -> None:
    with TestClient(app) as client:
        response: Response = client.get("/projects")
        assert response.status_code == 401
