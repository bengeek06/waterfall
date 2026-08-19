from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.user import User


def _register_user(client: TestClient, email: str) -> dict[str, str]:
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


def _admin_headers(client: TestClient) -> dict[str, str]:
    headers = _register_user(client, "resources.admin@example.com")
    session_factory = get_session_factory()
    with session_factory() as session:
        user = session.query(User).filter(User.email == "resources.admin@example.com").one()
        user.is_admin = True
        session.add(user)
        session.commit()
    return headers


def test_admin_can_manage_resource_reference_data() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)

        cost_type_response = client.post(
            "/resources/cost-types",
            json={"code": "MO", "name": "Main d'oeuvre", "kind": "labor"},
            headers=headers,
        )
        assert cost_type_response.status_code == 201
        cost_type_payload = cast(dict[str, Any], cost_type_response.json())
        cost_type_id = cast(int, cost_type_payload["id"])

        category_response = client.post(
            "/resources/categories",
            json={
                "cost_type_id": cost_type_id,
                "accounting_code": "DEV",
                "category_code": "IDEX",
                "name": "Developpement",
            },
            headers=headers,
        )
        assert category_response.status_code == 201
        category_payload = cast(dict[str, Any], category_response.json())
        category_id = cast(int, category_payload["id"])

        node_response = client.post(
            "/resources/nodes",
            json={"code": "IT", "name": "Informatique"},
            headers=headers,
        )
        assert node_response.status_code == 201
        node_payload = cast(dict[str, Any], node_response.json())
        node_id = cast(int, node_payload["id"])

        role_response = client.post(
            "/resources/roles",
            json={
                "code": "DEV-SW",
                "name": "Developpeur",
                "node_id": node_id,
                "cost_category_id": category_id,
            },
            headers=headers,
        )
        assert role_response.status_code == 201
        role_payload = cast(dict[str, Any], role_response.json())
        role_id = cast(int, role_payload["id"])

        rate_response = client.post(
            "/resources/rates",
            json={
                "cost_category_id": category_id,
                "year": 2026,
                "hourly_rate": "100",
                "currency_code": "eur",
            },
            headers=headers,
        )
        assert rate_response.status_code == 201
        assert rate_response.json()["currency_code"] == "EUR"

        inflation_response = client.put(
            "/resources/inflation/2026",
            json={"coefficient": "1.05"},
            headers=headers,
        )
        assert inflation_response.status_code == 200

        capacity_response = client.post(
            "/resources/capacities",
            json={
                "role_id": role_id,
                "period_start": "2026-01-01",
                "period_end": "2027-01-01",
                "person_count": "2",
                "available_hours": "3200",
            },
            headers=headers,
        )
        assert capacity_response.status_code == 201

        roles_response = client.get("/resources/roles?node_id=" + str(node_id), headers=headers)
        assert roles_response.status_code == 200
        roles = cast(list[dict[str, Any]], roles_response.json())
        assert [role["code"] for role in roles] == ["DEV-SW"]


def test_resource_writes_require_admin() -> None:
    with TestClient(app) as client:
        headers = _register_user(client, "resources.user@example.com")
        response = client.post(
            "/resources/nodes",
            json={"code": "IT", "name": "Informatique"},
            headers=headers,
        )
        assert response.status_code == 403


def test_inactive_cost_category_hidden_unless_included() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        cost_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "FRAIS-I", "name": "Frais", "kind": "other"},
                headers=headers,
            ).json(),
        )["id"]
        category = cast(
            dict[str, Any],
            client.post(
                "/resources/categories",
                json={
                    "cost_type_id": cost_type_id,
                    "accounting_code": "FRAIS-CAT-I",
                    "name": "Frais divers",
                },
                headers=headers,
            ).json(),
        )
        category_id = category["id"]

        deactivate_response: Response = client.patch(
            f"/resources/categories/{category_id}",
            json={"is_active": False, "accounting_code": "FRAIS-CAT-I-RENAMED"},
            headers=headers,
        )
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False
        assert deactivate_response.json()["accounting_code"] == "FRAIS-CAT-I-RENAMED"

        active_only: Response = client.get("/resources/categories", headers=headers)
        active_payload = cast(list[dict[str, Any]], active_only.json())
        assert all(item["id"] != category_id for item in active_payload)

        with_inactive: Response = client.get(
            "/resources/categories?include_inactive=true", headers=headers
        )
        inactive_payload = cast(list[dict[str, Any]], with_inactive.json())
        assert any(item["id"] == category_id for item in inactive_payload)


def test_role_creation_rejects_inactive_category() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        cost_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "MO-I", "name": "Main d'oeuvre", "kind": "labor"},
                headers=headers,
            ).json(),
        )["id"]
        category = cast(
            dict[str, Any],
            client.post(
                "/resources/categories",
                json={
                    "cost_type_id": cost_type_id,
                    "accounting_code": "MO-CAT-I",
                    "name": "Developpement",
                },
                headers=headers,
            ).json(),
        )
        category_id = category["id"]
        client.patch(
            f"/resources/categories/{category_id}",
            json={"is_active": False},
            headers=headers,
        )
        node_id = cast(
            dict[str, Any],
            client.post(
                "/resources/nodes", json={"code": "IT-I", "name": "Informatique"}, headers=headers
            ).json(),
        )["id"]

        response: Response = client.post(
            "/resources/roles",
            json={
                "code": "DEV-INACTIVE",
                "name": "Developpeur",
                "node_id": node_id,
                "cost_category_id": category_id,
            },
            headers=headers,
        )
        assert response.status_code == 400


def test_category_type_change_blocked_when_in_use() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        labor_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "MO-U", "name": "Main d'oeuvre", "kind": "labor"},
                headers=headers,
            ).json(),
        )["id"]
        other_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "FRAIS-U", "name": "Frais", "kind": "other"},
                headers=headers,
            ).json(),
        )["id"]
        category = cast(
            dict[str, Any],
            client.post(
                "/resources/categories",
                json={
                    "cost_type_id": labor_type_id,
                    "accounting_code": "MO-CAT-U",
                    "name": "Developpement",
                },
                headers=headers,
            ).json(),
        )
        category_id = category["id"]
        node_id = cast(
            dict[str, Any],
            client.post(
                "/resources/nodes", json={"code": "IT-U", "name": "Informatique"}, headers=headers
            ).json(),
        )["id"]
        client.post(
            "/resources/roles",
            json={
                "code": "DEV-U",
                "name": "Developpeur",
                "node_id": node_id,
                "cost_category_id": category_id,
            },
            headers=headers,
        )

        response: Response = client.patch(
            f"/resources/categories/{category_id}",
            json={"cost_type_id": other_type_id},
            headers=headers,
        )
        assert response.status_code == 409


def test_resource_nodes_reject_indirect_cycles() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        root_response = client.post(
            "/resources/nodes",
            json={"code": "ROOT", "name": "Racine"},
            headers=headers,
        )
        assert root_response.status_code == 201
        root_payload = cast(dict[str, Any], root_response.json())
        root_id = cast(int, root_payload["id"])

        child_response = client.post(
            "/resources/nodes",
            json={"code": "CHILD", "name": "Enfant", "parent_id": root_id},
            headers=headers,
        )
        assert child_response.status_code == 201
        child_payload = cast(dict[str, Any], child_response.json())
        child_id = cast(int, child_payload["id"])

        cycle_response = client.patch(
            f"/resources/nodes/{root_id}",
            json={"parent_id": child_id},
            headers=headers,
        )
        assert cycle_response.status_code == 400
