from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def _auth_headers(client: TestClient, email: str | None = None) -> dict[str, str]:
    email = email or f"cost-codes.tester.{uuid4().hex}@example.com"
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


def _list_cost_codes(
    client: TestClient, headers: dict[str, str], project_id: int
) -> list[dict[str, Any]]:
    response: Response = client.get(f"/projects/{project_id}/cost-codes", headers=headers)
    assert response.status_code == 200
    payload = cast(dict[str, Any], response.json())
    return cast(list[dict[str, Any]], payload["items"])


def _create_project(
    client: TestClient, headers: dict[str, str], name: str, code: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if code is not None:
        payload["code"] = code
    response: Response = client.post("/projects", json=payload, headers=headers)
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_project_creation_creates_root_cost_code_from_project_code() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Avec Code", code="PRJ-042")

        items = _list_cost_codes(client, headers, project["id"])
        assert len(items) == 1
        root = items[0]
        assert root["code"] == "PRJ-042"
        assert root["parent_id"] is None
        assert root["is_active"] is True


def test_project_creation_falls_back_to_prj_id_when_project_has_no_code() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Sans Code")

        root = _list_cost_codes(client, headers, project["id"])[0]
        assert root["code"] == f"PRJ-{project['id']}"
        assert root["parent_id"] is None


def test_sub_cost_code_can_be_created_under_any_node_of_same_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Sous-codes")
        project_id = project["id"]

        root = _list_cost_codes(client, headers, project_id)[0]

        child_response: Response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT-1", "name": "Lot 1", "parent_id": root["id"]},
            headers=headers,
        )
        assert child_response.status_code == 201
        child = cast(dict[str, Any], child_response.json())
        assert child["parent_id"] == root["id"]

        grandchild_response: Response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT-1-A", "name": "Lot 1 - Sous-lot A", "parent_id": child["id"]},
            headers=headers,
        )
        assert grandchild_response.status_code == 201

        codes = {item["code"] for item in _list_cost_codes(client, headers, project_id)}
        assert codes == {root["code"], "LOT-1", "LOT-1-A"}


def test_create_cost_code_rejects_parent_from_another_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_a = _create_project(client, headers, "Projet A")
        project_b = _create_project(client, headers, "Projet B")

        root_b = _list_cost_codes(client, headers, project_b["id"])[0]

        response: Response = client.post(
            f"/projects/{project_a['id']}/cost-codes",
            json={"code": "LOT-X", "name": "Lot X", "parent_id": root_b["id"]},
            headers=headers,
        )
        assert response.status_code == 400


def test_update_cost_code_rejects_parent_from_another_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_a = _create_project(client, headers, "Projet A Update")
        project_b = _create_project(client, headers, "Projet B Update")

        root_a = _list_cost_codes(client, headers, project_a["id"])[0]
        root_b = _list_cost_codes(client, headers, project_b["id"])[0]

        child_response: Response = client.post(
            f"/projects/{project_a['id']}/cost-codes",
            json={"code": "LOT-Y", "name": "Lot Y", "parent_id": root_a["id"]},
            headers=headers,
        )
        assert child_response.status_code == 201
        child_id = child_response.json()["id"]

        update_response: Response = client.patch(
            f"/projects/{project_a['id']}/cost-codes/{child_id}",
            json={"parent_id": root_b["id"]},
            headers=headers,
        )
        assert update_response.status_code == 400


def test_update_cost_code_rejects_reparenting_under_its_own_descendant() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Cycle")
        project_id = project["id"]
        root = _list_cost_codes(client, headers, project_id)[0]

        child_response: Response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT", "name": "Lot", "parent_id": root["id"]},
            headers=headers,
        )
        assert child_response.status_code == 201
        child_id = child_response.json()["id"]

        grandchild_response: Response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LIVRABLE", "name": "Livrable", "parent_id": child_id},
            headers=headers,
        )
        assert grandchild_response.status_code == 201
        grandchild_id = grandchild_response.json()["id"]

        # Direct self-parenting.
        self_parent_response: Response = client.patch(
            f"/projects/{project_id}/cost-codes/{child_id}",
            json={"parent_id": child_id},
            headers=headers,
        )
        assert self_parent_response.status_code == 400

        # Re-parenting under its own descendant (grandchild) would create a cycle.
        descendant_response: Response = client.patch(
            f"/projects/{project_id}/cost-codes/{child_id}",
            json={"parent_id": grandchild_id},
            headers=headers,
        )
        assert descendant_response.status_code == 400


def test_duplicate_code_within_project_conflicts_but_reuse_across_projects_is_allowed() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_a = _create_project(client, headers, "Projet Dup A")
        project_b = _create_project(client, headers, "Projet Dup B")

        root_a = _list_cost_codes(client, headers, project_a["id"])[0]

        first_response: Response = client.post(
            f"/projects/{project_a['id']}/cost-codes",
            json={"code": "SHARED", "name": "Premier", "parent_id": root_a["id"]},
            headers=headers,
        )
        assert first_response.status_code == 201

        duplicate_response: Response = client.post(
            f"/projects/{project_a['id']}/cost-codes",
            json={"code": "SHARED", "name": "Doublon", "parent_id": root_a["id"]},
            headers=headers,
        )
        assert duplicate_response.status_code == 409

        root_b = _list_cost_codes(client, headers, project_b["id"])[0]
        reused_response: Response = client.post(
            f"/projects/{project_b['id']}/cost-codes",
            json={"code": "SHARED", "name": "Reutilise", "parent_id": root_b["id"]},
            headers=headers,
        )
        assert reused_response.status_code == 201


def test_deactivate_cost_code_blocked_by_active_children_then_succeeds_without() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Desactivation")
        project_id = project["id"]

        root = _list_cost_codes(client, headers, project_id)[0]

        child_response: Response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT-Z", "name": "Lot Z", "parent_id": root["id"]},
            headers=headers,
        )
        assert child_response.status_code == 201
        child_id = child_response.json()["id"]

        blocked_response: Response = client.delete(
            f"/projects/{project_id}/cost-codes/{root['id']}", headers=headers
        )
        assert blocked_response.status_code == 409

        deactivate_child_response: Response = client.delete(
            f"/projects/{project_id}/cost-codes/{child_id}", headers=headers
        )
        assert deactivate_child_response.status_code == 204

        assert _list_cost_codes(client, headers, project_id) == [root]


def test_deactivate_cost_code_rejects_the_projects_root_even_without_children() -> None:
    """E6-02 (#63) needs every project to always keep an active root as its default
    cost-imputation attachment point -- unlike every other node, the root is never
    deactivatable, even once childless."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Racine Protegee")
        project_id = project["id"]
        root = _list_cost_codes(client, headers, project_id)[0]

        delete_response: Response = client.delete(
            f"/projects/{project_id}/cost-codes/{root['id']}", headers=headers
        )
        assert delete_response.status_code == 409

        patch_response: Response = client.patch(
            f"/projects/{project_id}/cost-codes/{root['id']}",
            json={"is_active": False},
            headers=headers,
        )
        assert patch_response.status_code == 409

        assert _list_cost_codes(client, headers, project_id) == [root]


def test_cost_codes_are_scoped_to_project_owner() -> None:
    with TestClient(app) as client:
        owner_headers = _auth_headers(client, "cost-codes.owner@example.com")
        other_headers = _auth_headers(client, "cost-codes.other@example.com")
        project = _create_project(client, owner_headers, "Projet Prive")

        response: Response = client.get(
            f"/projects/{project['id']}/cost-codes", headers=other_headers
        )
        assert response.status_code == 404


def test_update_cost_code_renames_code_and_name() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = _create_project(client, headers, "Projet Renommage")
        project_id = project["id"]
        root = _list_cost_codes(client, headers, project_id)[0]

        update_response: Response = client.patch(
            f"/projects/{project_id}/cost-codes/{root['id']}",
            json={"code": "RACINE", "name": "Racine renommee"},
            headers=headers,
        )
        assert update_response.status_code == 200
        updated = cast(dict[str, Any], update_response.json())
        assert updated["code"] == "RACINE"
        assert updated["name"] == "Racine renommee"
