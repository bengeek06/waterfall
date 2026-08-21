from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = "planning.structure@example.com"
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
    return {"Authorization": f"Bearer {token_response.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Structured project"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _payload() -> dict[str, Any]:
    return {
        "posts": [
            {
                "key": "design",
                "name": "Design",
                "lots": [
                    {
                        "key": "specification",
                        "name": "Specification",
                        "deliverables": [
                            {"key": "requirements", "name": "Requirements"},
                            {"key": "architecture", "name": "Architecture"},
                        ],
                    },
                    {
                        "key": "validation",
                        "name": "Validation",
                        "deliverables": [{"key": "review", "name": "Review"}],
                    },
                ],
            }
        ]
    }


def test_create_planning_structure_generates_hierarchy_and_links() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        response = client.post(
            f"/projects/{project_id}/planning-structure",
            json=_payload(),
            headers=headers,
        )

        assert response.status_code == 201
        tasks = cast(list[dict[str, Any]], response.json()["tasks"])
        assert [task["structure_kind"] for task in tasks] == [
            "poste",
            "lot",
            "livrable",
            "livrable",
            "milestone",
            "lot",
            "livrable",
            "milestone",
        ]
        assert tasks[0]["outline_number"] == "1"
        assert tasks[1]["outline_number"] == "1.1"
        assert tasks[2]["parent_uid"] == tasks[1]["uid"]
        assert tasks[4]["is_milestone"] is True

        links_response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert links_response.status_code == 200
        assert links_response.content.count(b"<PredecessorLink>") == 3

        tree_response = client.get(
            f"/projects/{project_id}/planning-tree",
            headers=headers,
        )
        assert tree_response.status_code == 200
        roots = cast(list[dict[str, Any]], tree_response.json()["tasks"])
        assert len(roots) == 1
        assert len(roots[0]["children"]) == 2
        assert len(roots[0]["children"][0]["children"]) == 3


def test_create_planning_structure_is_idempotent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        second = client.post(path, json=_payload(), headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        first_tasks = cast(list[dict[str, Any]], first.json()["tasks"])
        second_tasks = cast(list[dict[str, Any]], second.json()["tasks"])
        assert [task["uid"] for task in second_tasks] == [task["uid"] for task in first_tasks]

        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        listed_tasks = cast(list[dict[str, Any]], listed.json())
        assert len(listed_tasks) == len(first_tasks)


def test_create_planning_structure_resynchronizes_names() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 201
        payload = _payload()
        payload["posts"][0]["lots"][0]["deliverables"][0]["name"] = "Updated requirements"

        second = client.post(path, json=payload, headers=headers)

        assert second.status_code == 201
        tasks = cast(list[dict[str, Any]], second.json()["tasks"])
        assert tasks[2]["name"] == "Updated requirements"


def test_create_planning_structure_reconciles_removed_lots() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 201
        payload = _payload()
        payload["posts"][0]["lots"] = payload["posts"][0]["lots"][:1]

        second = client.post(path, json=payload, headers=headers)

        assert second.status_code == 201
        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        tasks = cast(list[dict[str, Any]], listed.json())
        assert len(tasks) == 5
        assert all(task["structure_key"] != "design/validation" for task in tasks)


def test_create_planning_structure_rejects_duplicate_keys_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        payload = _payload()
        payload["posts"][0]["lots"][1]["key"] = "specification"

        response = client.post(
            f"/projects/{project_id}/planning-structure",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 422
        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        assert listed.json() == []


def test_structure_versions_validated_planning_is_immutable_and_reopenable() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 201
        project = client.get(f"/projects/{project_id}", headers=headers).json()
        assert project["status"] == "initialise"
        first_planning_id = project["displayed_planning_id"]
        assert first_planning_id is not None

        assert client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/validate",
            headers=headers,
        ).status_code == 200
        assert client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/reference",
            headers=headers,
        ).status_code == 200

        reopened_from_validated = client.post(
            f"/projects/{project_id}/planning-structure/reopen", headers=headers
        )
        assert reopened_from_validated.status_code == 200
        reopened_planning_id = reopened_from_validated.json()["displayed_planning_id"]
        assert reopened_planning_id not in {first_planning_id, None}

        changed = _payload()
        changed["posts"][0]["lots"] = changed["posts"][0]["lots"][:1]
        second = client.post(path, json=changed, headers=headers)
        assert second.status_code == 201
        second_planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]
        assert second_planning_id != first_planning_id
        second_tasks = cast(list[dict[str, Any]], second.json()["tasks"])
        assert len(second_tasks) == 5

        original = client.get(
            f"/projects/{project_id}/plannings/{first_planning_id}", headers=headers
        )
        assert original.status_code == 200
        original_tasks = cast(list[dict[str, Any]], original.json()["tasks"])
        assert len(original_tasks) == 8

        reopened = client.post(
            f"/projects/{project_id}/planning-structure/reopen", headers=headers
        )
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "initialise"
        assert reopened.json()["displayed_planning_id"] == second_planning_id
