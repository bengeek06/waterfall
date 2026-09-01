from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.exc import IntegrityError

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.resources import Calendar
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
        assert [role["name"] for role in roles] == ["Developpeur"]


def test_role_creation_succeeds_without_code() -> None:
    """ResourceRole no longer has a `code` field (issue #46): creating a role
    with a payload that omits `code` entirely must succeed."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "NOCODE")

        response: Response = client.post(
            "/resources/roles",
            json={
                "name": "Developpeur",
                "node_id": context["node_id"],
                "cost_category_id": context["cost_category_id"],
            },
            headers=headers,
        )
        assert response.status_code == 201
        payload = cast(dict[str, Any], response.json())
        assert "code" not in payload
        assert payload["name"] == "Developpeur"


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


def test_role_reactivation_revalidates_effective_calendar() -> None:
    """Regression test: PATCHing only `is_active` must still enforce that an
    active role's calendar is active, even when `calendar_id` itself is not
    part of the payload.

    Reproduces the gap found in PR #60 review: an inactive role can end up
    referencing a calendar that gets deactivated while the role is inactive
    (allowed, since no *active* role references it). Reactivating the role via
    `{"is_active": true}` alone must revalidate the calendar it still carries,
    not just calendars explicitly passed in the same PATCH.
    """
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "REACT")
        calendar_id = cast(
            dict[str, Any],
            client.post(
                "/resources/calendars",
                json={"code": "STANDARD-REACT", "name": "Standard", "weeks_per_year": 47},
                headers=headers,
            ).json(),
        )["id"]
        role_id = cast(
            dict[str, Any],
            client.post(
                "/resources/roles",
                json={
                    "name": "Developpeur",
                    "node_id": context["node_id"],
                    "cost_category_id": context["cost_category_id"],
                    "calendar_id": calendar_id,
                },
                headers=headers,
            ).json(),
        )["id"]

        deactivate_role: Response = client.patch(
            f"/resources/roles/{role_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivate_role.status_code == 200

        # Allowed: no active role references this calendar anymore.
        deactivate_calendar: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivate_calendar.status_code == 200
        assert deactivate_calendar.json()["is_active"] is False

        # Reactivating the role without touching calendar_id must still catch
        # that its (unchanged) calendar is inactive.
        reactivate_role: Response = client.patch(
            f"/resources/roles/{role_id}",
            json={"is_active": True},
            headers=headers,
        )
        assert reactivate_role.status_code == 400
        assert reactivate_role.json()["detail"] == "Calendar is inactive and cannot be assigned"

        # The role must remain inactive -- the rejected PATCH must not have
        # partially applied.
        unchanged: Response = client.get(f"/resources/roles/{role_id}", headers=headers)
        assert unchanged.status_code == 200
        assert unchanged.json()["is_active"] is False


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


def _create_calendar_via_api(client: TestClient, headers: dict[str, str], code: str) -> int:
    response: Response = client.post(
        "/resources/calendars",
        json={"code": code, "name": f"Calendrier {code}", "weeks_per_year": 47},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, cast(dict[str, Any], response.json())["id"])


def _promote_default(client: TestClient, headers: dict[str, str], calendar_id: int) -> Response:
    return client.patch(
        f"/resources/calendars/{calendar_id}",
        json={"is_default": True},
        headers=headers,
    )


def test_calendar_patch_deactivate_blocked_when_default() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "DEFAULT-DEACT")
        assert _promote_default(client, headers, calendar_id).status_code == 200

        blocked: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == (
            "Calendar is the system default calendar and cannot be deactivated or deleted"
        )


def test_calendar_delete_blocked_when_default() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "DEFAULT-DEL")
        assert _promote_default(client, headers, calendar_id).status_code == 200

        blocked: Response = client.delete(f"/resources/calendars/{calendar_id}", headers=headers)
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == (
            "Calendar is the system default calendar and cannot be deactivated or deleted"
        )


def test_calendar_patch_cannot_unset_default_without_promoting_replacement() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "DEFAULT-UNSET")
        assert _promote_default(client, headers, calendar_id).status_code == 200

        blocked: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_default": False},
            headers=headers,
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == (
            "Cannot unset the default calendar directly; promote another calendar as "
            "default instead (PATCH it with is_default=true)"
        )

        # The rejected PATCH must not have applied.
        unchanged: Response = client.get(f"/resources/calendars/{calendar_id}", headers=headers)
        assert unchanged.json()["is_default"] is True


def test_calendar_patch_is_default_false_on_non_default_is_a_noop() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "NOT-DEFAULT")

        response: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_default": False},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["is_default"] is False


def test_calendar_patch_promotes_new_default_and_demotes_previous_one() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        old_default_id = _create_calendar_via_api(client, headers, "OLD-DEFAULT")
        assert _promote_default(client, headers, old_default_id).status_code == 200

        new_default_id = _create_calendar_via_api(client, headers, "NEW-DEFAULT")
        promote_response = _promote_default(client, headers, new_default_id)
        assert promote_response.status_code == 200
        assert promote_response.json()["is_default"] is True

        old_default: Response = client.get(
            f"/resources/calendars/{old_default_id}", headers=headers
        )
        assert old_default.json()["is_default"] is False

        new_default: Response = client.get(
            f"/resources/calendars/{new_default_id}", headers=headers
        )
        assert new_default.json()["is_default"] is True

        # The flag, not the code, is what is protected: the old default calendar can
        # now be freely renamed and deactivated.
        renamed: Response = client.patch(
            f"/resources/calendars/{old_default_id}",
            json={"code": "OLD-DEFAULT-RENAMED"},
            headers=headers,
        )
        assert renamed.status_code == 200
        assert renamed.json()["code"] == "OLD-DEFAULT-RENAMED"

        deactivated: Response = client.patch(
            f"/resources/calendars/{old_default_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False


def test_calendar_patch_promote_requires_active_calendar() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "INACTIVE-PROMOTE")
        deactivate: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivate.status_code == 200

        promote: Response = _promote_default(client, headers, calendar_id)
        assert promote.status_code == 400
        assert promote.json()["detail"] == "Only an active calendar can be set as default"


def test_calendar_patch_promote_allows_activating_and_promoting_in_same_request() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "ACTIVATE-AND-PROMOTE")
        client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )

        promote: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": True, "is_default": True},
            headers=headers,
        )
        assert promote.status_code == 200
        payload = cast(dict[str, Any], promote.json())
        assert payload["is_active"] is True
        assert payload["is_default"] is True


def test_calendar_patch_deactivate_and_promote_in_one_request_on_current_default() -> None:
    """The is_active guard must fire before the is_default promotion logic even runs:

    a single PATCH that both deactivates and (re)promotes the *current* default
    calendar is rejected as a 409 on the deactivation check, not a 400 from the
    promotion check -- `_ensure_calendar_not_default` runs first in `update_calendar`,
    ahead of the `is_default` branch."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "DEFAULT-COMBO")
        assert _promote_default(client, headers, calendar_id).status_code == 200

        response: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False, "is_default": True},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Calendar is the system default calendar and cannot be deactivated or deleted"
        )


def test_calendar_patch_deactivate_and_promote_in_one_request_on_non_default() -> None:
    """On a non-default, active calendar, the same combined payload's *effective*
    is_active (after this same request) is False, so the promotion check must reject
    it with a 400 -- there is no deactivation guard to trip first here, since the
    calendar isn't the default."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "NON-DEFAULT-COMBO")

        response: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False, "is_default": True},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Only an active calendar can be set as default"


def test_calendar_patch_explicit_null_is_default_matches_false_on_current_default() -> None:
    """`payload.model_dump(exclude_unset=True)` keeps an explicitly-sent `null` the same
    as an explicitly-sent `false` -- both land in the `elif calendar.is_default:` branch
    once `is_default` is popped from `values`, since `pop()` returns the falsy `None`.
    This documents existing, already-correct behavior; it is not a behavior change."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "NULL-DEFAULT")
        assert _promote_default(client, headers, calendar_id).status_code == 200

        response: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_default": None},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Cannot unset the default calendar directly; promote another calendar as "
            "default instead (PATCH it with is_default=true)"
        )

        unchanged: Response = client.get(f"/resources/calendars/{calendar_id}", headers=headers)
        assert unchanged.json()["is_default"] is True


def test_calendar_is_default_partial_unique_index_rejects_two_defaults() -> None:
    """DB-level backstop test: even bypassing the API-layer promotion guard, the
    partial unique index on wf_calendar.is_default must reject a second row flagged
    is_default=True."""
    session_factory = get_session_factory()
    with session_factory() as session:
        first = Calendar(code="IDX-1", name="Index 1", weeks_per_year=47, is_default=True)
        session.add(first)
        session.commit()

        second = Calendar(code="IDX-2", name="Index 2", weeks_per_year=47, is_default=True)
        session.add(second)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("only one calendar may be flagged is_default at a time")
