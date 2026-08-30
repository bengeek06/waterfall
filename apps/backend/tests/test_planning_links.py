from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot

NS = {"ms": "http://schemas.microsoft.com/project/2007"}


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"planning.links.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Predecessor links"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _seed_planning(project_id: int, *, task_count: int = 4) -> int:
    """Seed a single draft planning with ``task_count`` flat sibling tasks (uid 1..N)."""
    with get_session_factory()() as session:
        planning = WfPlanning(project_id=project_id, version_number=1, status="draft")
        session.add(planning)
        session.flush()
        session.add_all(
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=uid,
                name=f"Task {uid}",
                position=uid,
                is_summary=False,
                is_milestone=False,
            )
            for uid in range(1, task_count + 1)
        )
        session.commit()
        return planning.id


def _seed_two_plannings(project_id: int, *, task_count: int = 4) -> tuple[int, int]:
    with get_session_factory()() as session:
        first = WfPlanning(project_id=project_id, version_number=1, status="draft")
        second = WfPlanning(project_id=project_id, version_number=2, status="draft")
        session.add_all([first, second])
        session.flush()
        for planning in (first, second):
            session.add_all(
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=uid,
                    name=f"Task {uid}",
                    position=uid,
                    is_summary=False,
                    is_milestone=False,
                )
                for uid in range(1, task_count + 1)
            )
        session.commit()
        return first.id, second.id


def _links_url(project_id: int, planning_id: int, task_uid: int) -> str:
    return f"/projects/{project_id}/plannings/{planning_id}/tasks/{task_uid}/links"


def _existing_links(planning_id: int) -> list[tuple[int, int, int]]:
    with get_session_factory()() as session:
        rows = (
            session.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning_id)
            .order_by(WfPlanningLinkSnapshot.id)
            .all()
        )
        return [(row.task_uid, row.predecessor_uid, row.link_type) for row in rows]


def test_replace_links_persists_all_link_types_and_lag() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=5)

        payload = {
            "links": [
                {"predecessor_uid": 1, "link_type": 1, "lag_tenth_minute": 0, "lag_format": 7},
                {"predecessor_uid": 2, "link_type": 3, "lag_tenth_minute": 480, "lag_format": 7},
                {
                    "predecessor_uid": 3,
                    "link_type": 0,
                    "lag_tenth_minute": None,
                    "lag_format": None,
                },
                {"predecessor_uid": 4, "link_type": 2, "lag_tenth_minute": -120, "lag_format": 7},
            ]
        }
        response = client.put(_links_url(project_id, planning_id, 5), json=payload, headers=headers)

        assert response.status_code == 200
        body = cast(dict[str, Any], response.json())
        task5 = next(task for task in body["tasks"] if task["uid"] == 5)
        links_by_predecessor = {
            link["predecessor_uid"]: link for link in task5["predecessor_links"]
        }
        assert links_by_predecessor[1]["link_type"] == 1
        assert links_by_predecessor[1]["lag_tenth_minute"] == 0
        assert links_by_predecessor[2]["link_type"] == 3
        assert links_by_predecessor[2]["lag_tenth_minute"] == 480
        assert links_by_predecessor[3]["link_type"] == 0
        assert links_by_predecessor[3]["lag_tenth_minute"] is None
        assert links_by_predecessor[4]["link_type"] == 2
        assert links_by_predecessor[4]["lag_tenth_minute"] == -120

        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert detail.status_code == 200
        detail_tasks = cast(list[dict[str, Any]], detail.json()["tasks"])
        detail_task5 = next(task for task in detail_tasks if task["uid"] == 5)
        assert {
            (link["predecessor_uid"], link["link_type"])
            for link in detail_task5["predecessor_links"]
        } == {(1, 1), (2, 3), (3, 0), (4, 2)}


def test_replace_links_accepts_multiple_predecessors() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=4)

        response = client.put(
            _links_url(project_id, planning_id, 4),
            json={
                "links": [
                    {"predecessor_uid": 1, "link_type": 1},
                    {"predecessor_uid": 2, "link_type": 1},
                    {"predecessor_uid": 3, "link_type": 1},
                ]
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = cast(list[dict[str, Any]], response.json()["tasks"])
        task4 = next(task for task in tasks if task["uid"] == 4)
        assert {link["predecessor_uid"] for link in task4["predecessor_links"]} == {1, 2, 3}


def test_replace_links_full_replacement_leaves_other_tasks_intact() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=4)

        first = client.put(
            _links_url(project_id, planning_id, 3),
            json={"links": [{"predecessor_uid": 1, "link_type": 1}]},
            headers=headers,
        )
        assert first.status_code == 200
        other = client.put(
            _links_url(project_id, planning_id, 4),
            json={"links": [{"predecessor_uid": 2, "link_type": 1}]},
            headers=headers,
        )
        assert other.status_code == 200

        replace = client.put(
            _links_url(project_id, planning_id, 3),
            json={"links": [{"predecessor_uid": 2, "link_type": 3}]},
            headers=headers,
        )

        assert replace.status_code == 200
        body = cast(dict[str, Any], replace.json())
        task3 = next(task for task in body["tasks"] if task["uid"] == 3)
        assert [
            (link["predecessor_uid"], link["link_type"]) for link in task3["predecessor_links"]
        ] == [(2, 3)]
        task4 = next(task for task in body["tasks"] if task["uid"] == 4)
        assert [
            (link["predecessor_uid"], link["link_type"]) for link in task4["predecessor_links"]
        ] == [(2, 1)]

        rows = _existing_links(planning_id)
        assert set(rows) == {(3, 2, 3), (4, 2, 1)}


def test_replace_links_rejects_missing_task() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        response = client.put(
            _links_url(project_id, planning_id, 999),
            json={"links": [{"predecessor_uid": 1, "link_type": 1}]},
            headers=headers,
        )

        assert response.status_code == 404
        assert _existing_links(planning_id) == []


def test_replace_links_rejects_missing_predecessor() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        response = client.put(
            _links_url(project_id, planning_id, 1),
            json={"links": [{"predecessor_uid": 999, "link_type": 1}]},
            headers=headers,
        )

        assert response.status_code == 404
        assert _existing_links(planning_id) == []


def test_replace_links_rejects_self_reference() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        response = client.put(
            _links_url(project_id, planning_id, 1),
            json={"links": [{"predecessor_uid": 1, "link_type": 1}]},
            headers=headers,
        )

        assert response.status_code == 400
        assert _existing_links(planning_id) == []


def test_replace_links_rejects_direct_cycle_without_partial_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        first = client.put(
            _links_url(project_id, planning_id, 1),
            json={"links": [{"predecessor_uid": 2, "link_type": 1}]},
            headers=headers,
        )
        assert first.status_code == 200

        cycle = client.put(
            _links_url(project_id, planning_id, 2),
            json={"links": [{"predecessor_uid": 1, "link_type": 1}]},
            headers=headers,
        )

        assert cycle.status_code == 409
        assert _existing_links(planning_id) == [(1, 2, 1)]


def test_replace_links_rejects_indirect_cycle_without_partial_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=3)

        assert (
            client.put(
                _links_url(project_id, planning_id, 2),
                json={"links": [{"predecessor_uid": 1, "link_type": 1}]},
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.put(
                _links_url(project_id, planning_id, 3),
                json={"links": [{"predecessor_uid": 2, "link_type": 1}]},
                headers=headers,
            ).status_code
            == 200
        )

        cycle = client.put(
            _links_url(project_id, planning_id, 1),
            json={"links": [{"predecessor_uid": 3, "link_type": 1}]},
            headers=headers,
        )

        assert cycle.status_code == 409
        assert set(_existing_links(planning_id)) == {(2, 1, 1), (3, 2, 1)}


def test_replace_links_rejects_duplicate_pair_in_payload() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        response = client.put(
            _links_url(project_id, planning_id, 1),
            json={
                "links": [
                    {"predecessor_uid": 2, "link_type": 1},
                    {"predecessor_uid": 2, "link_type": 1},
                ]
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert _existing_links(planning_id) == []


def test_replace_links_rejects_missing_links_key() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        response = client.put(
            _links_url(project_id, planning_id, 1),
            json={},
            headers=headers,
        )

        assert response.status_code == 422
        assert _existing_links(planning_id) == []


def test_replace_links_reflected_in_export_xml() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id, task_count=2)

        response = client.put(
            _links_url(project_id, planning_id, 2),
            json={
                "links": [
                    {"predecessor_uid": 1, "link_type": 1, "lag_tenth_minute": 60, "lag_format": 7}
                ]
            },
            headers=headers,
        )
        assert response.status_code == 200

        export_response = client.get(
            f"/projects/{project_id}/export.xml",
            params={"planning_id": planning_id},
            headers=headers,
        )
        assert export_response.status_code == 200

        root = ET.fromstring(cast(bytes, export_response.content))
        task_nodes = root.findall("ms:Tasks/ms:Task", NS)
        task2_node = next(
            node for node in task_nodes if node.findtext("ms:UID", namespaces=NS) == "2"
        )
        predecessor_link = task2_node.find("ms:PredecessorLink", NS)
        assert predecessor_link is not None
        assert predecessor_link.findtext("ms:PredecessorUID", namespaces=NS) == "1"
        assert predecessor_link.findtext("ms:Type", namespaces=NS) == "1"
        assert predecessor_link.findtext("ms:LinkLag", namespaces=NS) == "60"


def test_replace_links_rejects_validated_planning_and_read_only_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        first_planning_id, second_planning_id = _seed_two_plannings(project_id)
        payload = {"links": [{"predecessor_uid": 2, "link_type": 1}]}

        assert (
            client.post(
                f"/projects/{project_id}/plannings/{first_planning_id}/validate", headers=headers
            ).status_code
            == 200
        )
        validated = client.put(
            _links_url(project_id, first_planning_id, 1), json=payload, headers=headers
        )
        assert validated.status_code == 409

        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "termine"
            session.commit()

        read_only = client.put(
            _links_url(project_id, second_planning_id, 1), json=payload, headers=headers
        )
        assert read_only.status_code == 409
