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


def test_resource_nodes_can_update_and_delete_leaf_nodes() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        create_response = client.post(
            "/resources/nodes",
            json={"code": "OLD", "name": "Ancien"},
            headers=headers,
        )
        node_id = create_response.json()["id"]

        update_response = client.patch(
            f"/resources/nodes/{node_id}",
            json={"code": "NEW", "name": "Nouveau"},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["code"] == "NEW"

        delete_response = client.delete(f"/resources/nodes/{node_id}", headers=headers)
        assert delete_response.status_code == 204
        listed_codes = [
            node["code"] for node in client.get("/resources/nodes", headers=headers).json()
        ]
        assert "NEW" not in listed_codes


def _full_week(hours: str = "7.00") -> list[dict[str, Any]]:
    return [{"day_type": day_type, "hours_per_day": hours} for day_type in range(1, 8)]


def _create_role_context(
    client: TestClient, headers: dict[str, str], suffix: str
) -> dict[str, int]:
    cost_type_id = cast(
        dict[str, Any],
        client.post(
            "/resources/cost-types",
            json={"code": f"MO-{suffix}", "name": "Main d'oeuvre", "kind": "labor"},
            headers=headers,
        ).json(),
    )["id"]
    category_id = cast(
        dict[str, Any],
        client.post(
            "/resources/categories",
            json={
                "cost_type_id": cost_type_id,
                "accounting_code": f"MO-CAT-{suffix}",
                "name": "Developpement",
            },
            headers=headers,
        ).json(),
    )["id"]
    node_id = cast(
        dict[str, Any],
        client.post(
            "/resources/nodes",
            json={"code": f"IT-{suffix}", "name": "Informatique"},
            headers=headers,
        ).json(),
    )["id"]
    return {"cost_category_id": category_id, "node_id": node_id}


def test_calendar_create_read_and_list_include_weekdays() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        create_response: Response = client.post(
            "/resources/calendars",
            json={
                "code": "STANDARD",
                "name": "Calendrier standard",
                "weeks_per_year": 47,
                "weekdays": _full_week(),
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = cast(dict[str, Any], create_response.json())
        calendar_id = cast(int, created["id"])
        assert created["is_active"] is True
        assert [weekday["day_type"] for weekday in created["weekdays"]] == [1, 2, 3, 4, 5, 6, 7]

        read_response: Response = client.get(f"/resources/calendars/{calendar_id}", headers=headers)
        assert read_response.status_code == 200
        assert len(cast(dict[str, Any], read_response.json())["weekdays"]) == 7

        list_response: Response = client.get("/resources/calendars", headers=headers)
        assert list_response.status_code == 200
        calendars = cast(list[dict[str, Any]], list_response.json())
        assert [calendar["code"] for calendar in calendars] == ["STANDARD"]
        assert len(calendars[0]["weekdays"]) == 7

        assert client.get("/resources/calendars/999999", headers=headers).status_code == 404


def test_calendar_duplicate_code_conflicts() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        payload = {"code": "STANDARD", "name": "Calendrier standard", "weeks_per_year": 47}
        assert client.post("/resources/calendars", json=payload, headers=headers).status_code == 201
        duplicate: Response = client.post("/resources/calendars", json=payload, headers=headers)
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "Calendar code already exists"


def test_calendar_payload_bounds_are_rejected() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        base = {"code": "BOUNDS", "name": "Bornes", "weeks_per_year": 47}

        too_many_hours: Response = client.post(
            "/resources/calendars",
            json={**base, "weekdays": [{"day_type": 2, "hours_per_day": "25"}]},
            headers=headers,
        )
        assert too_many_hours.status_code == 422

        invalid_day_type: Response = client.post(
            "/resources/calendars",
            json={**base, "weekdays": [{"day_type": 8, "hours_per_day": "7"}]},
            headers=headers,
        )
        assert invalid_day_type.status_code == 422

        invalid_weeks: Response = client.post(
            "/resources/calendars",
            json={**base, "weeks_per_year": 54},
            headers=headers,
        )
        assert invalid_weeks.status_code == 422


def test_calendar_rejects_duplicate_day_types() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        response: Response = client.post(
            "/resources/calendars",
            json={
                "code": "DUP",
                "name": "Doublon",
                "weeks_per_year": 47,
                "weekdays": [
                    {"day_type": 2, "hours_per_day": "7"},
                    {"day_type": 2, "hours_per_day": "8"},
                ],
            },
            headers=headers,
        )
        assert response.status_code == 422
        detail = cast(dict[str, Any], response.json())["detail"]
        assert "duplicate day_type" in str(detail)


def test_calendar_patch_replaces_weekdays() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = cast(
            dict[str, Any],
            client.post(
                "/resources/calendars",
                json={
                    "code": "STANDARD",
                    "name": "Calendrier standard",
                    "weeks_per_year": 47,
                    "weekdays": _full_week(),
                },
                headers=headers,
            ).json(),
        )["id"]

        patch_response: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={
                "name": "Calendrier 35h",
                "weeks_per_year": 45,
                "weekdays": [
                    {"day_type": day_type, "hours_per_day": "7.00"} for day_type in range(2, 7)
                ],
            },
            headers=headers,
        )
        assert patch_response.status_code == 200
        patched = cast(dict[str, Any], patch_response.json())
        assert patched["name"] == "Calendrier 35h"
        assert patched["weeks_per_year"] == 45
        assert [weekday["day_type"] for weekday in patched["weekdays"]] == [2, 3, 4, 5, 6]

        untouched: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"name": "Calendrier 35 heures"},
            headers=headers,
        )
        assert untouched.status_code == 200
        assert len(cast(dict[str, Any], untouched.json())["weekdays"]) == 5


def test_calendar_delete_deactivates_and_blocks_when_assigned() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "CAL")
        calendar_id = cast(
            dict[str, Any],
            client.post(
                "/resources/calendars",
                json={"code": "STANDARD", "name": "Standard", "weeks_per_year": 47},
                headers=headers,
            ).json(),
        )["id"]
        role_response: Response = client.post(
            "/resources/roles",
            json={
                "code": "DEV-CAL",
                "name": "Developpeur",
                "node_id": context["node_id"],
                "cost_category_id": context["cost_category_id"],
                "calendar_id": calendar_id,
            },
            headers=headers,
        )
        assert role_response.status_code == 201
        role_id = cast(int, cast(dict[str, Any], role_response.json())["calendar_id"])
        assert role_id == calendar_id

        blocked: Response = client.delete(f"/resources/calendars/{calendar_id}", headers=headers)
        assert blocked.status_code == 409

        client.patch(
            f"/resources/roles/{cast(dict[str, Any], role_response.json())['id']}",
            json={"is_active": False},
            headers=headers,
        )
        deleted: Response = client.delete(f"/resources/calendars/{calendar_id}", headers=headers)
        assert deleted.status_code == 204

        active_codes = [
            calendar["code"]
            for calendar in cast(
                list[dict[str, Any]], client.get("/resources/calendars", headers=headers).json()
            )
        ]
        assert "STANDARD" not in active_codes
        inactive_codes = [
            calendar["code"]
            for calendar in cast(
                list[dict[str, Any]],
                client.get("/resources/calendars?include_inactive=true", headers=headers).json(),
            )
        ]
        assert "STANDARD" in inactive_codes


def test_calendar_patch_deactivate_blocks_when_assigned() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "CALPATCH")
        calendar_id = cast(
            dict[str, Any],
            client.post(
                "/resources/calendars",
                json={"code": "STANDARD-PATCH", "name": "Standard", "weeks_per_year": 47},
                headers=headers,
            ).json(),
        )["id"]
        role_response: Response = client.post(
            "/resources/roles",
            json={
                "code": "DEV-CAL-PATCH",
                "name": "Developpeur",
                "node_id": context["node_id"],
                "cost_category_id": context["cost_category_id"],
                "calendar_id": calendar_id,
            },
            headers=headers,
        )
        assert role_response.status_code == 201

        blocked: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert blocked.status_code == 409

        active_codes = [
            calendar["code"]
            for calendar in cast(
                list[dict[str, Any]], client.get("/resources/calendars", headers=headers).json()
            )
        ]
        assert "STANDARD-PATCH" in active_codes

        client.patch(
            f"/resources/roles/{cast(dict[str, Any], role_response.json())['id']}",
            json={"is_active": False},
            headers=headers,
        )
        allowed: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert allowed.status_code == 200
        assert allowed.json()["is_active"] is False


def test_role_rejects_unknown_or_inactive_calendar() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "ROLECAL")

        unknown: Response = client.post(
            "/resources/roles",
            json={
                "code": "DEV-UNKNOWN-CAL",
                "name": "Developpeur",
                "node_id": context["node_id"],
                "cost_category_id": context["cost_category_id"],
                "calendar_id": 999999,
            },
            headers=headers,
        )
        assert unknown.status_code == 404
        assert unknown.json()["detail"] == "Calendar not found"

        calendar_id = cast(
            dict[str, Any],
            client.post(
                "/resources/calendars",
                json={"code": "OLD", "name": "Ancien", "weeks_per_year": 47},
                headers=headers,
            ).json(),
        )["id"]
        client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        inactive: Response = client.post(
            "/resources/roles",
            json={
                "code": "DEV-INACTIVE-CAL",
                "name": "Developpeur",
                "node_id": context["node_id"],
                "cost_category_id": context["cost_category_id"],
                "calendar_id": calendar_id,
            },
            headers=headers,
        )
        assert inactive.status_code == 400
        assert inactive.json()["detail"] == "Calendar is inactive and cannot be assigned"

        role_id = cast(
            dict[str, Any],
            client.post(
                "/resources/roles",
                json={
                    "code": "DEV-OK-CAL",
                    "name": "Developpeur",
                    "node_id": context["node_id"],
                    "cost_category_id": context["cost_category_id"],
                },
                headers=headers,
            ).json(),
        )["id"]
        patched: Response = client.patch(
            f"/resources/roles/{role_id}",
            json={"calendar_id": 999999},
            headers=headers,
        )
        assert patched.status_code == 404


def test_calendar_writes_require_admin() -> None:
    with TestClient(app) as client:
        headers = _register_user(client, "calendars.user@example.com")
        create_response: Response = client.post(
            "/resources/calendars",
            json={"code": "STANDARD", "name": "Standard", "weeks_per_year": 47},
            headers=headers,
        )
        assert create_response.status_code == 403
        assert client.get("/resources/calendars", headers=headers).status_code == 200
