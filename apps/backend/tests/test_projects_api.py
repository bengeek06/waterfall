from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import CostCategory, CostType, ResourceNode, ResourceRole
from waterfall.models.wf_core import WfTaskEnrichment


def _auth_headers(client: TestClient, email: str | None = None) -> dict[str, str]:
    email = email or f"projects.tester.{uuid4().hex}@example.com"
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


def _current_user_id(client: TestClient, headers: dict[str, str]) -> int:
    response: Response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    payload = cast(dict[str, Any], response.json())
    return cast(int, payload["id"])


def _seed_projects_and_tasks(owner_id: int) -> tuple[int, int]:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=owner_id,
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


def _seed_roles() -> tuple[int, int]:
    session_factory = get_session_factory()
    with session_factory() as session:
        root = ResourceNode(code="DIRECTION", name="Direction")
        child = ResourceNode(code="SERVICE", name="Service", parent_id=None)
        session.add_all([root, child])
        session.flush()
        child.parent_id = root.id

        labor_type = CostType(code="MO", name="Main d'oeuvre")
        supply_type = CostType(code="FOURNITURE", name="Fourniture")
        session.add_all([labor_type, supply_type])
        session.flush()
        labor_category = CostCategory(
            cost_type_id=labor_type.id,
            code="MO-DEV",
            accounting_code="IDEX",
            name="Développement",
        )
        supply_category = CostCategory(
            cost_type_id=supply_type.id,
            code="FO-CABLE",
            accounting_code="ACHAT",
            name="Câbles",
        )
        session.add_all([labor_category, supply_category])
        session.flush()
        labor_role = ResourceRole(
            node_id=child.id,
            cost_category_id=labor_category.id,
            code="DEV",
            name="Développeur",
        )
        supply_role = ResourceRole(
            node_id=child.id,
            cost_category_id=supply_category.id,
            code="CABLE",
            name="Câble",
        )
        session.add_all([labor_role, supply_role])
        session.commit()
        return labor_role.id, supply_role.id


def test_get_projects_and_project_tasks() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, expected_tasks = _seed_projects_and_tasks(_current_user_id(client, headers))

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
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))

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
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))

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


def test_patch_project_name() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))

        response: Response = client.patch(
            f"/projects/{project_id}",
            json={"name": "Projet Renomme"},
            headers=headers,
        )
        assert response.status_code == 200
        payload = cast(dict[str, Any], response.json())
        assert payload["id"] == project_id
        assert payload["name"] == "Projet Renomme"


def test_delete_project_cascades_related_data() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))

        session_factory = get_session_factory()
        with session_factory() as session:
            enrichment = WfTaskEnrichment(
                project_id=project_id,
                task_uid=1001,
                description="A supprimer",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(enrichment)
            session.commit()

        response: Response = client.delete(f"/projects/{project_id}", headers=headers)
        assert response.status_code == 204

        project_response: Response = client.get(f"/projects/{project_id}", headers=headers)
        assert project_response.status_code == 404

        tasks_response: Response = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert tasks_response.status_code == 404


def test_projects_are_isolated_by_owner() -> None:
    with TestClient(app) as client:
        owner_headers = _auth_headers(client)
        owner_id = _current_user_id(client, owner_headers)
        project_id, _ = _seed_projects_and_tasks(owner_id)

        other_headers = _auth_headers(client, "projects.other@example.com")
        list_response: Response = client.get("/projects", headers=other_headers)
        assert list_response.status_code == 200
        other_projects = cast(list[dict[str, Any]], list_response.json())
        assert all(item["id"] != project_id for item in other_projects)

        for path in (
            f"/projects/{project_id}",
            f"/projects/{project_id}/tasks",
            f"/projects/{project_id}/export.xml",
        ):
            response: Response = client.get(path, headers=other_headers)
            assert response.status_code == 404

        update_response: Response = client.patch(
            f"/projects/{project_id}",
            json={"name": "Unauthorized"},
            headers=other_headers,
        )
        assert update_response.status_code == 404

        delete_response: Response = client.delete(f"/projects/{project_id}", headers=other_headers)
        assert delete_response.status_code == 404


def test_user_can_create_manual_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        response: Response = client.post(
            "/projects",
            json={"name": "Projet manuel", "currency_code": "eur"},
            headers=headers,
        )
        assert response.status_code == 201
        payload = cast(dict[str, Any], response.json())
        assert payload["name"] == "Projet manuel"
        assert payload["currency_code"] == "EUR"


def test_project_and_task_pagination() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        first_project_id, _ = _seed_projects_and_tasks(owner_id)
        second_project_id, _ = _seed_projects_and_tasks(owner_id)

        first_page = client.get("/projects?limit=1&offset=0", headers=headers)
        second_page = client.get("/projects?limit=1&offset=1", headers=headers)
        assert first_page.status_code == 200
        assert second_page.status_code == 200
        first_projects = cast(list[dict[str, Any]], first_page.json())
        second_projects = cast(list[dict[str, Any]], second_page.json())
        assert len(first_projects) == 1
        assert len(second_projects) == 1
        assert first_projects[0]["id"] != second_projects[0]["id"]

        task_page = client.get(
            f"/projects/{first_project_id}/tasks?limit=1&offset=1",
            headers=headers,
        )
        assert task_page.status_code == 200
        tasks = cast(list[dict[str, Any]], task_page.json())
        assert len(tasks) == 1
        assert tasks[0]["uid"] == 1002

        assert first_project_id != second_project_id


def test_project_estimate_snapshots_tasks_and_validates() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))

        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR", "note": "Chiffrage initial"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate = cast(dict[str, Any], create_response.json())
        estimate_id = cast(int, estimate["id"])
        assert estimate["version_number"] == 1
        assert estimate["status"] == "draft"

        rows_response = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/task-rows",
            headers=headers,
        )
        assert rows_response.status_code == 200
        rows = cast(list[dict[str, Any]], rows_response.json())
        assert [row["task_name"] for row in rows] == ["Task One", "Task Two"]
        assert [row["position"] for row in rows] == [1, 2]

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200
        assert validate_response.json()["status"] == "validated"
        assert validate_response.json()["validated_at"] is not None

        validate_again_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_again_response.status_code == 409


def test_estimate_cost_lines_support_non_labor_costs_and_draft_locking() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))
        labor_role_id, supply_role_id = _seed_roles()

        session_factory = get_session_factory()
        with session_factory() as session:
            labor_category_id = (
                session.query(ResourceRole)
                .filter(ResourceRole.id == labor_role_id)
                .one()
                .cost_category_id
            )
            supply_category_id = (
                session.query(ResourceRole)
                .filter(ResourceRole.id == supply_role_id)
                .one()
                .cost_category_id
            )
            fee_type = CostType(code="FRAIS", name="Frais")
            work_unit_type = CostType(code="UO", name="Unité d'oeuvre")
            session.add_all([fee_type, work_unit_type])
            session.flush()
            fee_category = CostCategory(
                cost_type_id=fee_type.id,
                code="FR-TRAVEL",
                accounting_code="FRAIS",
                name="Déplacement",
            )
            work_unit_category = CostCategory(
                cost_type_id=work_unit_type.id,
                code="UO-TEST",
                accounting_code="UO",
                name="Essais",
            )
            session.add_all([fee_category, work_unit_category])
            session.commit()
            fee_category_id = fee_category.id
            work_unit_category_id = work_unit_category.id

        estimate_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert estimate_response.status_code == 201
        estimate_id = estimate_response.json()["id"]

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "task_id": 1,
                "cost_category_id": supply_category_id,
                "label": "Câble réseau",
                "quantity": "3",
                "unit_cost": "12.50",
                "supply_status": "ordered",
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        cost_line = cast(dict[str, Any], create_response.json())
        cost_line_id = cast(int, cost_line["id"])
        assert cost_line["cost_type_code"] == "FOURNITURE"
        assert cost_line["cost_category_code"] == "FO-CABLE"
        assert cost_line["accounting_code"] == "ACHAT"
        assert cost_line["purchase_cost"] == "37.50"
        assert cost_line["supply_status"] == "ordered"

        other_headers = _auth_headers(client, "cost-line.other@example.com")
        other_response = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            headers=other_headers,
        )
        assert other_response.status_code == 404

        fee_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "cost_category_id": fee_category_id,
                "label": "Déplacement",
                "quantity": "2",
                "unit_cost": "120",
            },
            headers=headers,
        )
        assert fee_response.status_code == 201
        assert fee_response.json()["cost_type_code"] == "FRAIS"
        assert fee_response.json()["task_id"] is None
        assert fee_response.json()["supply_status"] is None

        work_unit_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "cost_category_id": work_unit_category_id,
                "label": "Essais laboratoire",
                "quantity": "4",
                "unit_cost": "80",
            },
            headers=headers,
        )
        assert work_unit_response.status_code == 201
        assert work_unit_response.json()["cost_type_code"] == "UO"

        status_for_fee_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "cost_category_id": fee_category_id,
                "label": "Statut non valide",
                "quantity": "1",
                "unit_cost": "1",
                "supply_status": "ordered",
            },
            headers=headers,
        )
        assert status_for_fee_response.status_code == 400

        labor_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "cost_category_id": labor_category_id,
                "label": "Non autorisé",
                "quantity": "1",
                "unit_cost": "1",
            },
            headers=headers,
        )
        assert labor_response.status_code == 400

        invalid_task_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "task_id": 999999,
                "cost_category_id": supply_category_id,
                "label": "Tâche absente",
                "quantity": "1",
                "unit_cost": "1",
            },
            headers=headers,
        )
        assert invalid_task_response.status_code == 400

        invalid_status_response = client.patch(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines/{cost_line_id}",
            json={"supply_status": "received", "unit_cost": "15"},
            headers=headers,
        )
        assert invalid_status_response.status_code == 200
        assert invalid_status_response.json()["purchase_cost"] == "45.00"

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        locked_response = client.delete(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines/{cost_line_id}",
            headers=headers,
        )
        assert locked_response.status_code == 409


def test_forecast_estimate_requires_same_project_reference() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))

        missing_reference_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "forecast_remaining", "currency_code": "EUR"},
            headers=headers,
        )
        assert missing_reference_response.status_code == 400

        initial_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert initial_response.status_code == 201
        initial_id = initial_response.json()["id"]

        forecast_response = client.post(
            f"/projects/{project_id}/estimates",
            json={
                "kind": "forecast_remaining",
                "currency_code": "EUR",
                "reference_estimate_id": initial_id,
            },
            headers=headers,
        )
        assert forecast_response.status_code == 201
        assert forecast_response.json()["reference_estimate_id"] == initial_id
        assert forecast_response.json()["version_number"] == 2

        other_headers = _auth_headers(client, "estimate.other@example.com")
        hidden_response = client.get(
            f"/projects/{project_id}/estimates/{initial_id}",
            headers=other_headers,
        )
        assert hidden_response.status_code == 404


def test_task_role_assignment_lifecycle_and_labor_validation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_projects_and_tasks(_current_user_id(client, headers))
        labor_role_id, supply_role_id = _seed_roles()

        rejected_response = client.post(
            f"/projects/{project_id}/tasks/1001/role-assignments",
            json={"role_id": supply_role_id, "quantity": "1", "hours": "7.4"},
            headers=headers,
        )
        assert rejected_response.status_code == 400

        create_response = client.post(
            f"/projects/{project_id}/tasks/1001/role-assignments",
            json={"role_id": labor_role_id, "quantity": "2", "hours": "7.4"},
            headers=headers,
        )
        assert create_response.status_code == 201
        assignment = cast(dict[str, Any], create_response.json())
        assignment_id = cast(int, assignment["id"])
        assert assignment["role_code"] == "DEV"
        assert assignment["cost_category_code"] == "MO-DEV"

        list_response = client.get(
            f"/projects/{project_id}/tasks/1001/role-assignments",
            headers=headers,
        )
        assert list_response.status_code == 200
        assignments = cast(list[dict[str, Any]], list_response.json())
        assert len(assignments) == 1

        update_response = client.patch(
            f"/projects/{project_id}/tasks/1001/role-assignments/{assignment_id}",
            json={"hours": "14.8"},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["hours"] == "14.80"

        delete_response = client.delete(
            f"/projects/{project_id}/tasks/1001/role-assignments/{assignment_id}",
            headers=headers,
        )
        assert delete_response.status_code == 204


def test_role_filter_can_include_descendant_nodes() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        labor_role_id, _ = _seed_roles()

        session_factory = get_session_factory()
        with session_factory() as session:
            role = session.query(ResourceRole).filter(ResourceRole.id == labor_role_id).one()
            root_id = session.query(ResourceNode).filter(ResourceNode.code == "DIRECTION").one().id

        direct_response = client.get(f"/resources/roles?node_id={root_id}", headers=headers)
        descendants_response = client.get(
            f"/resources/roles?node_id={root_id}&include_descendants=true",
            headers=headers,
        )
        assert direct_response.status_code == 200
        assert descendants_response.status_code == 200
        assert direct_response.json() == []
        assert role.id in [item["id"] for item in descendants_response.json()]
