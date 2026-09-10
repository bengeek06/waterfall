"""E6-07/#68: apply a chained-milestone template to a non-labor cost line.

Covers ``POST /projects/{projectId}/estimates/{estimateId}/cost-lines/{lineId}/milestones``:
a single transaction that creates the fixed "fourniture" (2 milestones, 1 FS link) or
"sous_traitance" (2 + N milestones, 1 + N FS links) template, reusing #67's
snapshot/``MsTask`` twin/``EstimateTaskRow`` wiring for each milestone and chaining
them with :func:`waterfall.services.planning_links.replace_task_predecessor_links`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from _estimate_grid_support import seed_root_grid_node
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import CostCategory, CostType, Estimate, EstimateCostLine


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"estimate.cost.line.milestones.{uuid4().hex}@example.com"
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
    response = client.post("/projects", json={"name": "Gabarits de jalons"}, headers=headers)
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


def _deliverable_uid(project_id: int) -> int:
    with get_session_factory()() as session:
        deliverable = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "livrable")
            .one()
        )
        return deliverable.uid


def _deliverable_task_id(project_id: int) -> int:
    with get_session_factory()() as session:
        deliverable = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "livrable")
            .one()
        )
        return deliverable.id


def _seed_material_cost_category() -> int:
    with get_session_factory()() as session:
        cost_type = CostType(code=f"MAT-{uuid4().hex[:8]}", name="Materiel", kind="supply")
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


def _create_cost_line(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    estimate_id: int,
    *,
    task_id: int | None = None,
) -> int:
    category_id = _seed_material_cost_category()
    payload: dict[str, Any] = {
        "cost_category_id": category_id,
        "label": "Fourniture chaudiere",
        "quantity": "1.00",
        "unit_cost": "1000.00",
    }
    if task_id is not None:
        payload["task_id"] = task_id
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _seed_labor_cost_line(project_id: int, estimate_id: int) -> int:
    """Direct DB insert: the cost-line creation API itself rejects a labor
    cost_category_id (``get_non_labor_category_or_400``), so a labor
    ``EstimateCostLine`` can only exist as a pre-existing/legacy row.
    """
    with get_session_factory()() as session:
        cost_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"MO-ACC-{uuid4().hex[:8]}",
            category_code="IDEX",
            name="Developpement",
        )
        session.add(category)
        session.flush()
        node_id = seed_root_grid_node(session, estimate_id, "cost_line")
        line = EstimateCostLine(
            estimate_id=estimate_id,
            cost_type_id=cost_type.id,
            cost_category_id=category.id,
            cost_type_code=cost_type.code,
            accounting_code=category.accounting_code,
            category_code=category.category_code,
            label="Main d'oeuvre chantier",
            quantity=Decimal("1.00"),
            unit_cost=Decimal("100.00"),
            purchase_cost=Decimal("100.00"),
            node_id=node_id,
        )
        session.add(line)
        session.commit()
        return line.id


def _links_for_task(project_id: int, task_uid: int) -> list[WfPlanningLinkSnapshot]:
    with get_session_factory()() as session:
        return (
            session.query(WfPlanningLinkSnapshot)
            .join(WfPlanning, WfPlanning.id == WfPlanningLinkSnapshot.planning_id)
            .filter(WfPlanning.project_id == project_id)
            .filter(WfPlanningLinkSnapshot.task_uid == task_uid)
            .all()
        )


def _milestones_path(project_id: int, estimate_id: int, line_id: int) -> str:
    return f"/projects/{project_id}/estimates/{estimate_id}/cost-lines/{line_id}/milestones"


def test_fourniture_template_creates_two_milestones_with_one_fs_link() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 1440},
            headers=headers,
        )
        assert response.status_code == 201
        body = cast(dict[str, Any], response.json())
        items = cast(list[dict[str, Any]], body["items"])
        assert len(items) == 2
        assert [item["task_name"] for item in items] == ["Commande", "Réception"]
        assert all(item["is_milestone"] is True for item in items)
        assert all(item["parent_task_id"] is None for item in items)

        with get_session_factory()() as session:
            reception_task = session.query(MsTask).filter(MsTask.id == items[1]["task_id"]).one()
            order_uid = session.query(MsTask).filter(MsTask.id == items[0]["task_id"]).one().uid
        links = _links_for_task(project_id, reception_task.uid)
        assert len(links) == 1
        assert links[0].predecessor_uid == order_uid
        assert links[0].link_type == 1
        assert links[0].lag_tenth_minute == 14400
        assert links[0].lag_format == 7


def test_sous_traitance_template_with_zero_intermediate_milestones() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "sous_traitance", "lag_minutes": 60},
            headers=headers,
        )
        assert response.status_code == 201
        items = cast(list[dict[str, Any]], response.json()["items"])
        assert [item["task_name"] for item in items] == ["Commande", "Livraison"]

        with get_session_factory()() as session:
            uids = [
                session.query(MsTask).filter(MsTask.id == item["task_id"]).one().uid
                for item in items
            ]
        all_links: list[WfPlanningLinkSnapshot] = []
        for uid in uids:
            all_links.extend(_links_for_task(project_id, uid))
        assert len(all_links) == 1


def test_sous_traitance_template_with_two_intermediate_milestones() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={
                "template": "sous_traitance",
                "intermediate_milestones_count": 2,
                "lag_minutes": 60,
            },
            headers=headers,
        )
        assert response.status_code == 201
        items = cast(list[dict[str, Any]], response.json()["items"])
        assert [item["task_name"] for item in items] == [
            "Commande",
            "Jalon intermédiaire 1",
            "Jalon intermédiaire 2",
            "Livraison",
        ]

        with get_session_factory()() as session:
            uids = [
                session.query(MsTask).filter(MsTask.id == item["task_id"]).one().uid
                for item in items
            ]
        all_links: list[WfPlanningLinkSnapshot] = []
        for uid in uids:
            all_links.extend(_links_for_task(project_id, uid))
        assert len(all_links) == 3
        predecessors = {link.task_uid: link.predecessor_uid for link in all_links}
        assert predecessors[uids[1]] == uids[0]
        assert predecessors[uids[2]] == uids[1]
        assert predecessors[uids[3]] == uids[2]
        assert all(link.lag_tenth_minute == 600 for link in all_links)


def test_milestones_become_children_of_cost_line_task_and_flip_parent_summary() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        deliverable_task_id = _deliverable_task_id(project_id)
        deliverable_uid = _deliverable_uid(project_id)
        line_id = _create_cost_line(
            client, headers, project_id, estimate_id, task_id=deliverable_task_id
        )

        with get_session_factory()() as session:
            deliverable_before = (
                session.query(MsTask).filter(MsTask.id == deliverable_task_id).one()
            )
            assert deliverable_before.is_summary is False

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 201
        items = cast(list[dict[str, Any]], response.json()["items"])
        assert all(item["parent_task_id"] == deliverable_task_id for item in items)

        with get_session_factory()() as session:
            deliverable_after = session.query(MsTask).filter(MsTask.id == deliverable_task_id).one()
            assert deliverable_after.is_summary is True
            children = (
                session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.parent_uid == deliverable_uid)
                .all()
            )
            assert {child.name for child in children} == {"Commande", "Réception"}


def test_rejects_intermediate_count_with_fourniture_template() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={
                "template": "fourniture",
                "intermediate_milestones_count": 1,
                "lag_minutes": 0,
            },
            headers=headers,
        )
        assert response.status_code == 400


def test_rejects_labor_cost_line() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _seed_labor_cost_line(project_id, estimate_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 400


def test_rejects_unknown_cost_line() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, 999999),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 404


def test_rejects_cost_line_from_another_estimate() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        with get_session_factory()() as session:
            other_estimate = Estimate(
                project_id=project_id,
                planning_id=None,
                version_number=99,
                kind="initial",
                status="draft",
                currency_code="EUR",
            )
            session.add(other_estimate)
            session.commit()
            other_estimate_id = other_estimate.id

        response = client.post(
            _milestones_path(project_id, other_estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 404


def test_requires_planning_draft() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        project = client.get(f"/projects/{project_id}", headers=headers).json()
        planning_id = cast(int, project["displayed_planning_id"])
        validated = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
        )
        assert validated.status_code == 200

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT"}


def test_requires_draft_estimate() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate", headers=headers
        )
        assert validate_response.status_code == 200

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 409


def test_requires_mutable_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "perdu"
            session.commit()

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 409


def test_schema_validation_returns_bad_request() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "invalid_template", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 400
        error_payload = cast(dict[str, Any], response.json())
        assert error_payload["detail"] == {"code": "GENERIC_ERROR"}


def test_root_milestones_appended_after_existing_root_tasks() -> None:
    """When the cost line has no ``task_id``, milestones are appended as the last
    root tasks -- not inserted ahead of the existing top-level ``poste``.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        line_id = _create_cost_line(client, headers, project_id, estimate_id)

        with get_session_factory()() as session:
            root_snapshots_before = (
                session.query(WfPlanningTaskSnapshot)
                .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
                .filter(WfPlanning.project_id == project_id)
                .filter(WfPlanningTaskSnapshot.parent_uid.is_(None))
                .all()
            )
            existing_root_uids = {task.uid for task in root_snapshots_before}

        response = client.post(
            _milestones_path(project_id, estimate_id, line_id),
            json={"template": "fourniture", "lag_minutes": 0},
            headers=headers,
        )
        assert response.status_code == 201
        items = cast(list[dict[str, Any]], response.json()["items"])

        with get_session_factory()() as session:
            root_snapshots_after = (
                session.query(WfPlanningTaskSnapshot)
                .join(WfPlanning, WfPlanning.id == WfPlanningTaskSnapshot.planning_id)
                .filter(WfPlanning.project_id == project_id)
                .filter(WfPlanningTaskSnapshot.parent_uid.is_(None))
                .order_by(WfPlanningTaskSnapshot.position.asc())
                .all()
            )
            new_task_ids = {item["task_id"] for item in items}
            new_uids = {
                task.uid
                for task in session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.id.in_(new_task_ids))
                .all()
            }
        ordered_uids = [task.uid for task in root_snapshots_after]
        # The two new milestones are the last two roots, after every pre-existing one.
        assert ordered_uids[-2:] == sorted(new_uids, key=ordered_uids.index)
        assert set(ordered_uids[:-2]) == existing_root_uids
