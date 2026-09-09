"""E6-06/#67: add a task to the project's displayed draft planning from the Devis screen.

Covers ``POST /projects/{projectId}/estimates/{estimateId}/tasks``: a single
transaction that creates a ``WfPlanningTaskSnapshot`` (via
``create_planning_task``), a twin ``MsTask`` sharing the same uid, and the
corresponding ``EstimateTaskRow`` in the current estimate.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.resources import CostCategory, CostType, ResourceNode, ResourceRole


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"estimate.task.create.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    register_response: Response = client.post(
        "/auth/register", json={"email": email, "password": password}
    )
    assert register_response.status_code == 201
    token_response: Response = client.post(
        "/auth/token", data={"username": email, "password": password}
    )
    assert token_response.status_code == 200
    return {"Authorization": f"Bearer {token_response.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Devis task creation"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _structure_payload() -> dict[str, Any]:
    return {
        "posts": [
            {
                "key": "design",
                "name": "Design",
                "lots": [
                    {
                        "key": "specification",
                        "name": "Specification",
                        "deliverables": [{"key": "requirements", "name": "Requirements"}],
                    }
                ],
            }
        ]
    }


def _generate_structure(client: TestClient, headers: dict[str, str], project_id: int) -> None:
    response = client.post(
        f"/projects/{project_id}/planning-structure",
        json=_structure_payload(),
        headers=headers,
    )
    assert response.status_code == 201


def _create_estimate(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response = client.post(
        f"/projects/{project_id}/estimates",
        json={"kind": "initial", "currency_code": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _lot_uid(project_id: int) -> int:
    with get_session_factory()() as session:
        lot = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "lot")
            .one()
        )
        return lot.uid


def _seed_labor_role() -> int:
    with get_session_factory()() as session:
        node = ResourceNode(code=f"NODE-{uuid4().hex[:8]}", name="Direction")
        session.add(node)
        session.flush()
        cost_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code="MO-DEV",
            category_code="IDEX",
            name="Developpement",
        )
        session.add(category)
        session.flush()
        role = ResourceRole(node_id=node.id, cost_category_id=category.id, name="Developpeur")
        session.add(role)
        session.commit()
        return role.id


def test_create_estimate_task_creates_shared_uid_twin_and_row() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        lot_uid = _lot_uid(project_id)

        with get_session_factory()() as session:
            max_uid_before = max(
                session.query(MsTask.uid).filter(MsTask.project_id == project_id).all(),
                default=(0,),
            )[0]

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Chiffrage supplementaire", "target_parent_uid": lot_uid},
            headers=headers,
        )
        assert response.status_code == 201
        row = cast(dict[str, Any], response.json())
        assert row["estimate_id"] == estimate_id
        assert row["task_id"] is not None
        assert row["task_name"] == "Chiffrage supplementaire"
        assert row["is_milestone"] is False

        with get_session_factory()() as session:
            task = session.query(MsTask).filter(MsTask.id == row["task_id"]).one()
            snapshot = (
                session.query(WfPlanningTaskSnapshot)
                .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
                .filter(
                    WfPlanning.project_id == project_id,
                    WfPlanningTaskSnapshot.name == "Chiffrage supplementaire",
                )
                .one()
            )
            # Uid shared between the two tables (rather than independently
            # allocated), and unique project-wide.
            assert task.uid == snapshot.uid
            assert task.uid > max_uid_before
            assert task.parent_uid == lot_uid
            lot = (
                session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.uid == lot_uid)
                .one()
            )
            assert row["parent_task_id"] == lot.id
            assert row["outline_number"] == snapshot.outline_number
            assert row["outline_level"] == snapshot.outline_level

        # The twin MsTask row unblocks both role-assignment and cost-line creation,
        # which key off ms_task.id and previously 409'd for a snapshot-only task
        # (see create_task_role_assignment's "Snapshot-only tasks..." guard).
        role_id = _seed_labor_role()
        assignment_response = client.post(
            f"/projects/{project_id}/tasks/{task.uid}/role-assignments",
            json={"role_id": role_id, "quantity": "1.00", "hours": "10.00"},
            headers=headers,
        )
        assert assignment_response.status_code == 201

        material_category_id = _seed_material_cost_category()
        cost_line_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "task_id": row["task_id"],
                "cost_category_id": material_category_id,
                "label": "Materiel",
                "quantity": "1.00",
                "unit_cost": "100.00",
            },
            headers=headers,
        )
        assert cost_line_response.status_code == 201

        rows_response = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/task-rows",
            headers=headers,
        )
        assert rows_response.status_code == 200
        task_names = {
            item["task_name"] for item in cast(list[dict[str, Any]], rows_response.json()["items"])
        }
        assert "Chiffrage supplementaire" in task_names


def _seed_material_cost_category() -> int:
    with get_session_factory()() as session:
        cost_type = CostType(code=f"MAT-{uuid4().hex[:8]}", name="Materiel")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"ACC-{uuid4().hex[:8]}",
            category_code=f"CAT-{uuid4().hex[:8]}",
            name="Materiel",
        )
        session.add(category)
        session.commit()
        return category.id


def test_create_estimate_task_rejects_unknown_parent_uid() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Orphelin", "target_parent_uid": 999999},
            headers=headers,
        )
        assert response.status_code == 404


def _deliverable_uid(project_id: int) -> int:
    with get_session_factory()() as session:
        deliverable = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "livrable")
            .one()
        )
        return deliverable.uid


def test_create_estimate_task_flips_leaf_parent_to_summary_on_snapshot_and_ms_task() -> None:
    """A `livrable` generated by `generate_planning_structure` starts as a leaf
    (`is_summary=False`) on both its snapshot and its `MsTask` twin. Inserting a
    task under it must flip `is_summary` to True on *both* rows -- otherwise
    `get_estimate_validation_warnings` (E6-04) keeps flagging the now-container
    `MsTask` as a leaf missing a resource/cost, and the MS Project XML export
    keeps exporting it as a non-summary task.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        deliverable_uid = _deliverable_uid(project_id)

        with get_session_factory()() as session:
            deliverable_before = (
                session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.uid == deliverable_uid)
                .one()
            )
            assert deliverable_before.is_summary is False
            snapshot_before = (
                session.query(WfPlanningTaskSnapshot)
                .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
                .filter(
                    WfPlanning.project_id == project_id,
                    WfPlanningTaskSnapshot.uid == deliverable_uid,
                )
                .one()
            )
            assert snapshot_before.is_summary is False

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Sous-tache", "target_parent_uid": deliverable_uid},
            headers=headers,
        )
        assert response.status_code == 201

        with get_session_factory()() as session:
            deliverable_after = (
                session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.uid == deliverable_uid)
                .one()
            )
            assert deliverable_after.is_summary is True
            snapshot_after = (
                session.query(WfPlanningTaskSnapshot)
                .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
                .filter(
                    WfPlanning.project_id == project_id,
                    WfPlanningTaskSnapshot.uid == deliverable_uid,
                )
                .one()
            )
            assert snapshot_after.is_summary is True


def test_create_estimate_task_schema_validation_returns_bad_request() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        path = f"/projects/{project_id}/estimates/{estimate_id}/tasks"

        for payload in (
            {"name": ""},
            {"name": "New leaf", "target_parent_uid": 0},
            {"name": "New leaf", "insert_after_uid": 0},
        ):
            response = client.post(path, json=payload, headers=headers)
            assert response.status_code == 400
            error_payload = cast(dict[str, Any], response.json())
            assert set(error_payload) == {"detail"}
            # Mirrors _PlanningTaskBodyValidationRoute's contract on the sibling
            # planning-task creation route (test_create_task_schema_validation_
            # returns_bad_request in test_planning_task_create_delete.py): a
            # request-body validation error is reported as a 400 with the
            # generic, translatable error shape, not FastAPI's raw 422.
            assert error_payload["detail"] == {"code": "GENERIC_ERROR"}


def _milestone_uid(project_id: int) -> int:
    with get_session_factory()() as session:
        milestone = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "milestone")
            .one()
        )
        return milestone.uid


def test_create_estimate_task_rejects_milestone_parent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        milestone_uid = _milestone_uid(project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Sous jalon", "target_parent_uid": milestone_uid},
            headers=headers,
        )
        assert response.status_code == 409


def test_create_estimate_task_rejects_insert_after_uid_not_a_sibling() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        milestone_uid = _milestone_uid(project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Malplace", "insert_after_uid": milestone_uid},
            headers=headers,
        )
        assert response.status_code == 400


def test_create_estimate_task_requires_planning_draft() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)

        project = client.get(f"/projects/{project_id}", headers=headers).json()
        planning_id = cast(int, project["displayed_planning_id"])
        validated = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
        )
        assert validated.status_code == 200

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Trop tard"},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT"}


def test_create_estimate_task_requires_draft_estimate() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate", headers=headers
        )
        assert validate_response.status_code == 200

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Trop tard"},
            headers=headers,
        )
        assert response.status_code == 409
        # Plain-string HTTPException details are rewritten to a generic,
        # translatable code by _generic_http_exception_handler (see main.py).
        assert response.json()["detail"] == {"code": "GENERIC_ERROR"}


def test_create_estimate_task_requires_mutable_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)

        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "perdu"
            session.commit()

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/tasks",
            json={"name": "Refuse"},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "GENERIC_ERROR"}
