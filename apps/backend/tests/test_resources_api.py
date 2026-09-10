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
        roles_payload = cast(dict[str, Any], roles_response.json())
        assert roles_payload["total"] == 1
        roles = cast(list[dict[str, Any]], roles_payload["items"])
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
        active_payload = cast(list[dict[str, Any]], active_only.json()["items"])
        assert all(item["id"] != category_id for item in active_payload)

        with_inactive: Response = client.get(
            "/resources/categories?include_inactive=true", headers=headers
        )
        inactive_body = cast(dict[str, Any], with_inactive.json())
        inactive_payload = cast(list[dict[str, Any]], inactive_body["items"])
        assert any(item["id"] == category_id for item in inactive_payload)
        assert inactive_body["total"] == len(inactive_payload)


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
            node["code"] for node in client.get("/resources/nodes", headers=headers).json()["items"]
        ]
        assert "NEW" not in listed_codes


def test_inactive_resource_node_hidden_unless_included() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        node_id = cast(
            dict[str, Any],
            client.post(
                "/resources/nodes",
                json={"code": "NODE-I", "name": "Noeud inactif"},
                headers=headers,
            ).json(),
        )["id"]

        deactivate_response = client.delete(f"/resources/nodes/{node_id}", headers=headers)
        assert deactivate_response.status_code == 204

        active_only: Response = client.get("/resources/nodes", headers=headers)
        active_payload = cast(list[dict[str, Any]], active_only.json()["items"])
        assert all(item["id"] != node_id for item in active_payload)

        with_inactive: Response = client.get(
            "/resources/nodes?include_inactive=true", headers=headers
        )
        inactive_body = cast(dict[str, Any], with_inactive.json())
        inactive_payload = cast(list[dict[str, Any]], inactive_body["items"])
        assert any(item["id"] == node_id for item in inactive_payload)
        assert inactive_body["total"] == len(inactive_payload)


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
        list_payload = cast(dict[str, Any], list_response.json())
        assert list_payload["total"] == 1
        assert list_payload["limit"] is None
        assert list_payload["offset"] == 0
        calendars = cast(list[dict[str, Any]], list_payload["items"])
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
        assert duplicate.json()["detail"] == {"code": "GENERIC_ERROR"}


def test_first_calendar_created_becomes_default_automatically() -> None:
    """Issue #110: on a database with no calendar at all yet, the first calendar
    created via POST /resources/calendars is automatically flagged is_default, so
    a fresh install is never left without a default calendar."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        empty_payload = cast(
            dict[str, Any], client.get("/resources/calendars", headers=headers).json()
        )
        assert empty_payload == {"items": [], "total": 0, "limit": None, "offset": 0}

        created: Response = client.post(
            "/resources/calendars",
            json={"code": "FIRST", "name": "Premier calendrier", "weeks_per_year": 47},
            headers=headers,
        )
        assert created.status_code == 201
        assert cast(dict[str, Any], created.json())["is_default"] is True


def test_second_calendar_created_is_not_default() -> None:
    """The auto-default bootstrap (issue #110) only fires when the table is
    completely empty: a second calendar created afterward is not automatically
    promoted, and the first calendar keeps its default flag -- no double
    promotion, no violation of the partial unique index."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        first: Response = client.post(
            "/resources/calendars",
            json={"code": "FIRST", "name": "Premier calendrier", "weeks_per_year": 47},
            headers=headers,
        )
        assert first.status_code == 201
        first_payload = cast(dict[str, Any], first.json())
        assert first_payload["is_default"] is True
        first_id = first_payload["id"]

        second: Response = client.post(
            "/resources/calendars",
            json={"code": "SECOND", "name": "Second calendrier", "weeks_per_year": 47},
            headers=headers,
        )
        assert second.status_code == 201
        assert cast(dict[str, Any], second.json())["is_default"] is False

        unchanged_first: Response = client.get(f"/resources/calendars/{first_id}", headers=headers)
        assert cast(dict[str, Any], unchanged_first.json())["is_default"] is True


def test_new_calendar_is_not_auto_promoted_when_legacy_rows_have_no_default() -> None:
    """The auto-default bootstrap (issue #110) is scoped to a table that is
    completely empty before the insert, not merely to "no calendar is currently
    flagged default". A legacy/historical database can end up with calendars that
    exist but where none is default (an incomplete-setup gap flagged by issue #109
    as a frontend warning, never auto-resolved). Simulate that state by inserting
    calendars directly through the session -- bypassing the API, which never lets
    is_default drop to false on every row -- then verify that creating another,
    unrelated calendar through the API does NOT get silently promoted to default."""
    with TestClient(app) as client:
        headers = _admin_headers(client)

        session_factory = get_session_factory()
        with session_factory() as session:
            session.add_all(
                [
                    Calendar(code="LEGACY-A", name="Legacy A", weeks_per_year=47, is_default=False),
                    Calendar(code="LEGACY-B", name="Legacy B", weeks_per_year=47, is_default=False),
                ]
            )
            session.commit()

        created: Response = client.post(
            "/resources/calendars",
            json={"code": "THIRD", "name": "Troisieme calendrier", "weeks_per_year": 47},
            headers=headers,
        )
        assert created.status_code == 201
        assert cast(dict[str, Any], created.json())["is_default"] is False


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
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so STANDARD below is not itself the system default and
        # stays freely deactivatable, which is what this test exercises.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-CAL")
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
                list[dict[str, Any]],
                client.get("/resources/calendars", headers=headers).json()["items"],
            )
        ]
        assert "STANDARD" not in active_codes
        inactive_codes = [
            calendar["code"]
            for calendar in cast(
                list[dict[str, Any]],
                client.get("/resources/calendars?include_inactive=true", headers=headers).json()[
                    "items"
                ],
            )
        ]
        assert "STANDARD" in inactive_codes


def test_calendar_patch_deactivate_blocks_when_assigned() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        # See test_calendar_delete_deactivates_and_blocks_when_assigned: absorbs the
        # bootstrap default (issue #110) so STANDARD-PATCH is not itself the default.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-CALPATCH")
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
                list[dict[str, Any]],
                client.get("/resources/calendars", headers=headers).json()["items"],
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
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so OLD below is not itself the default and stays freely
        # deactivatable, which is what this test exercises.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-ROLECAL")
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
        assert unknown.json()["detail"] == {"code": "GENERIC_ERROR"}

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
        assert inactive.json()["detail"] == {"code": "GENERIC_ERROR"}

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
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so STANDARD-REACT below is not itself the default and stays
        # freely deactivatable, which is what this test exercises.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-REACT")
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
        assert reactivate_role.json()["detail"] == {"code": "GENERIC_ERROR"}

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
        assert blocked.json()["detail"] == {"code": "GENERIC_ERROR"}


def test_calendar_delete_blocked_when_default() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        calendar_id = _create_calendar_via_api(client, headers, "DEFAULT-DEL")
        assert _promote_default(client, headers, calendar_id).status_code == 200

        blocked: Response = client.delete(f"/resources/calendars/{calendar_id}", headers=headers)
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == {"code": "GENERIC_ERROR"}


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
        assert blocked.json()["detail"] == {"code": "GENERIC_ERROR"}

        # The rejected PATCH must not have applied.
        unchanged: Response = client.get(f"/resources/calendars/{calendar_id}", headers=headers)
        assert unchanged.json()["is_default"] is True


def test_calendar_patch_is_default_false_on_non_default_is_a_noop() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so NOT-DEFAULT below is actually not the default.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-NOT-DEFAULT")
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


def test_calendar_patch_promotes_default_with_lower_id_than_current_default() -> None:
    """Regression test for the flush-ordering bug in issue #51's follow-up review:
    SQLAlchemy's unit of work batches same-table UPDATEs ordered by primary key, not
    by session-attach order. The happy-path promotion test above always promotes a
    calendar whose id is HIGHER than the current default's id, which happens to flush
    in the safe order by accident. This test promotes a calendar whose id is LOWER
    than the current default's id -- the exact case where, without an explicit flush
    of the demotion before the promotion, the promoting UPDATE would be sent to the
    database first and transiently violate the partial unique index, surfacing as a
    spurious 409 instead of a successful 200."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        lower_id_calendar_id = _create_calendar_via_api(client, headers, "LOWER-ID")
        higher_id_calendar_id = _create_calendar_via_api(client, headers, "HIGHER-ID")
        assert lower_id_calendar_id < higher_id_calendar_id

        assert _promote_default(client, headers, higher_id_calendar_id).status_code == 200

        promote_response = _promote_default(client, headers, lower_id_calendar_id)
        assert promote_response.status_code == 200
        assert promote_response.json()["is_default"] is True

        previous_default: Response = client.get(
            f"/resources/calendars/{higher_id_calendar_id}", headers=headers
        )
        assert previous_default.json()["is_default"] is False


def test_calendar_patch_promote_requires_active_calendar() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so INACTIVE-PROMOTE below is not itself the default and
        # stays freely deactivatable, which is what this test exercises.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-INACTIVE-PROMOTE")
        calendar_id = _create_calendar_via_api(client, headers, "INACTIVE-PROMOTE")
        deactivate: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivate.status_code == 200

        promote: Response = _promote_default(client, headers, calendar_id)
        assert promote.status_code == 400
        assert promote.json()["detail"] == {"code": "GENERIC_ERROR"}


def test_calendar_patch_promote_allows_activating_and_promoting_in_same_request() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so ACTIVATE-AND-PROMOTE below is not itself the default and
        # the intermediate deactivation below actually succeeds instead of tripping
        # the "default calendar cannot be deactivated" guard.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-ACTIVATE-AND-PROMOTE")
        calendar_id = _create_calendar_via_api(client, headers, "ACTIVATE-AND-PROMOTE")
        deactivate_response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivate_response.status_code == 200

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
        assert response.json()["detail"] == {"code": "GENERIC_ERROR"}


def test_calendar_patch_deactivate_and_promote_in_one_request_on_non_default() -> None:
    """On a non-default, active calendar, the same combined payload's *effective*
    is_active (after this same request) is False, so the promotion check must reject
    it with a 400 -- there is no deactivation guard to trip first here, since the
    calendar isn't the default."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        # Absorbs the "first calendar in an empty DB becomes default" bootstrap
        # (issue #110) so NON-DEFAULT-COMBO below is actually not the default.
        _create_calendar_via_api(client, headers, "BOOTSTRAP-NON-DEFAULT-COMBO")
        calendar_id = _create_calendar_via_api(client, headers, "NON-DEFAULT-COMBO")

        response: Response = client.patch(
            f"/resources/calendars/{calendar_id}",
            json={"is_active": False, "is_default": True},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == {"code": "GENERIC_ERROR"}


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
        assert response.json()["detail"] == {"code": "GENERIC_ERROR"}

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


# --- EPIC E7 (#114): pagination/tri/recherche sur les endpoints de liste ---


def test_calendars_pagination_sort_and_search() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        _create_calendar_via_api(client, headers, "PAG-B")
        _create_calendar_via_api(client, headers, "PAG-A")
        _create_calendar_via_api(client, headers, "PAG-C")

        # No limit: every row of the filtered set is returned, total matches.
        unpaginated = cast(
            dict[str, Any], client.get("/resources/calendars", headers=headers).json()
        )
        assert unpaginated["total"] == 3
        assert unpaginated["limit"] is None
        assert len(unpaginated["items"]) == 3

        # limit truncates items but total still reflects the full filtered set.
        first_page = cast(
            dict[str, Any],
            client.get("/resources/calendars?limit=2", headers=headers).json(),
        )
        assert first_page["total"] == 3
        assert first_page["limit"] == 2
        assert first_page["offset"] == 0
        assert len(first_page["items"]) == 2

        second_page = cast(
            dict[str, Any],
            client.get("/resources/calendars?limit=2&offset=2", headers=headers).json(),
        )
        assert second_page["total"] == 3
        assert len(second_page["items"]) == 1

        # sort=code / sort=-code.
        ascending = cast(
            dict[str, Any],
            client.get("/resources/calendars?sort=code", headers=headers).json(),
        )
        assert [c["code"] for c in ascending["items"]] == ["PAG-A", "PAG-B", "PAG-C"]

        descending = cast(
            dict[str, Any],
            client.get("/resources/calendars?sort=-code", headers=headers).json(),
        )
        assert [c["code"] for c in descending["items"]] == ["PAG-C", "PAG-B", "PAG-A"]

        # q searches both code and name (case-insensitive substring).
        searched = cast(
            dict[str, Any],
            client.get("/resources/calendars?q=pag-b", headers=headers).json(),
        )
        assert [c["code"] for c in searched["items"]] == ["PAG-B"]
        assert searched["total"] == 1

        # An undeclared sort column is rejected, never interpolated into SQL.
        invalid_sort = client.get("/resources/calendars?sort=weeks_per_year", headers=headers)
        assert invalid_sort.status_code == 400

        # include_inactive still combines with the new params.
        inactive_calendar_id = _create_calendar_via_api(client, headers, "PAG-INACTIVE")
        client.patch(
            f"/resources/calendars/{inactive_calendar_id}",
            json={"is_active": False},
            headers=headers,
        )
        active_sorted = cast(
            dict[str, Any],
            client.get("/resources/calendars?sort=code", headers=headers).json(),
        )
        assert "PAG-INACTIVE" not in [c["code"] for c in active_sorted["items"]]
        with_inactive_sorted = cast(
            dict[str, Any],
            client.get(
                "/resources/calendars?include_inactive=true&sort=code", headers=headers
            ).json(),
        )
        assert with_inactive_sorted["total"] == 4
        assert [c["code"] for c in with_inactive_sorted["items"]] == [
            "PAG-A",
            "PAG-B",
            "PAG-C",
            "PAG-INACTIVE",
        ]

        # offset without limit is rejected (PaginationMeta's offset/limit rule).
        offset_only = client.get("/resources/calendars?offset=1", headers=headers)
        assert offset_only.status_code == 400


def test_roles_pagination_sort_search_and_node_filter() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "PAGROLE")
        other_context = _create_role_context(client, headers, "PAGROLE2")
        for name in ("Charlie", "Alice", "Bob"):
            response = client.post(
                "/resources/roles",
                json={
                    "name": name,
                    "node_id": context["node_id"],
                    "cost_category_id": context["cost_category_id"],
                },
                headers=headers,
            )
            assert response.status_code == 201
        other_role = client.post(
            "/resources/roles",
            json={
                "name": "Dana",
                "node_id": other_context["node_id"],
                "cost_category_id": other_context["cost_category_id"],
            },
            headers=headers,
        )
        assert other_role.status_code == 201

        # node_id filter still combines with limit/sort.
        filtered = cast(
            dict[str, Any],
            client.get(
                f"/resources/roles?node_id={context['node_id']}&sort=name&limit=2",
                headers=headers,
            ).json(),
        )
        assert filtered["total"] == 3
        assert len(filtered["items"]) == 2
        assert [role["name"] for role in filtered["items"]] == ["Alice", "Bob"]

        descending = cast(
            dict[str, Any],
            client.get(
                f"/resources/roles?node_id={context['node_id']}&sort=-name", headers=headers
            ).json(),
        )
        assert [role["name"] for role in descending["items"]] == ["Charlie", "Bob", "Alice"]

        searched = cast(
            dict[str, Any],
            client.get("/resources/roles?q=ali", headers=headers).json(),
        )
        assert [role["name"] for role in searched["items"]] == ["Alice"]

        # `q` also matches the node's code, not just the role's own name -- this
        # is the text shown as "name -- code (#id)" in the frontend, so search
        # must cover all three parts. "IT-PAGROLE2" is unique to other_context's
        # node (it would also substring-match "IT-PAGROLE" the other way around,
        # which is why the assertion below only relies on this specific code
        # matching its own, more specific node).
        searched_by_node_code = cast(
            dict[str, Any],
            client.get("/resources/roles?q=IT-PAGROLE2", headers=headers).json(),
        )
        assert [role["name"] for role in searched_by_node_code["items"]] == ["Dana"]

        # `q` also matches the role's id, with or without the leading "#" the
        # frontend label displays it with.
        other_role_id = cast(dict[str, Any], other_role.json())["id"]
        searched_by_id = cast(
            dict[str, Any],
            client.get(f"/resources/roles?q={other_role_id}", headers=headers).json(),
        )
        assert [role["name"] for role in searched_by_id["items"]] == ["Dana"]

        searched_by_hash_id = cast(
            dict[str, Any],
            client.get(f"/resources/roles?q=%23{other_role_id}", headers=headers).json(),
        )
        assert [role["name"] for role in searched_by_hash_id["items"]] == ["Dana"]

        invalid_sort = client.get("/resources/roles?sort=node_id", headers=headers)
        assert invalid_sort.status_code == 400


def test_inactive_resource_role_hidden_unless_included() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "ROLE-I")
        role_id = cast(
            dict[str, Any],
            client.post(
                "/resources/roles",
                json={
                    "name": "Developpeur inactif",
                    "node_id": context["node_id"],
                    "cost_category_id": context["cost_category_id"],
                },
                headers=headers,
            ).json(),
        )["id"]

        deactivate_response = client.patch(
            f"/resources/roles/{role_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False

        active_only: Response = client.get("/resources/roles", headers=headers)
        active_payload = cast(list[dict[str, Any]], active_only.json()["items"])
        assert all(item["id"] != role_id for item in active_payload)

        with_inactive: Response = client.get(
            "/resources/roles?include_inactive=true", headers=headers
        )
        inactive_body = cast(dict[str, Any], with_inactive.json())
        inactive_payload = cast(list[dict[str, Any]], inactive_body["items"])
        assert any(item["id"] == role_id for item in inactive_payload)
        assert inactive_body["total"] == len(inactive_payload)


def test_categories_pagination_sort_and_search() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        cost_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "PAGCT", "name": "Cout pagine", "kind": "other"},
                headers=headers,
            ).json(),
        )["id"]

        def _create_category(accounting_code: str, category_code: str, name: str) -> int:
            response = client.post(
                "/resources/categories",
                json={
                    "cost_type_id": cost_type_id,
                    "accounting_code": accounting_code,
                    "category_code": category_code,
                    "name": name,
                },
                headers=headers,
            )
            assert response.status_code == 201
            return cast(int, cast(dict[str, Any], response.json())["id"])

        _create_category("PAG-CAT-B", "SUB-B", "Beta")
        _create_category("PAG-CAT-A", "SUB-A", "Alpha")
        inactive_id = _create_category("PAG-CAT-Z", "SUB-Z", "Zulu")
        client.patch(
            f"/resources/categories/{inactive_id}",
            json={"is_active": False},
            headers=headers,
        )

        by_accounting_code = cast(
            dict[str, Any],
            client.get("/resources/categories?sort=accounting_code", headers=headers).json(),
        )
        assert [c["accounting_code"] for c in by_accounting_code["items"]] == [
            "PAG-CAT-A",
            "PAG-CAT-B",
        ]

        by_name_desc = cast(
            dict[str, Any],
            client.get(
                "/resources/categories?sort=-name&include_inactive=true", headers=headers
            ).json(),
        )
        assert [c["name"] for c in by_name_desc["items"]] == ["Zulu", "Beta", "Alpha"]

        searched = cast(
            dict[str, Any],
            client.get("/resources/categories?q=SUB-A", headers=headers).json(),
        )
        assert [c["accounting_code"] for c in searched["items"]] == ["PAG-CAT-A"]

        limited = cast(
            dict[str, Any],
            client.get(
                "/resources/categories?limit=1&sort=accounting_code", headers=headers
            ).json(),
        )
        assert limited["total"] == 2
        assert len(limited["items"]) == 1

        invalid_sort = client.get("/resources/categories?sort=cost_type_id", headers=headers)
        assert invalid_sort.status_code == 400


def test_cost_types_pagination_and_sort() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        for code, name in (("PAG-CT-B", "Beta"), ("PAG-CT-A", "Alpha")):
            response = client.post(
                "/resources/cost-types",
                json={"code": code, "name": name, "kind": "other"},
                headers=headers,
            )
            assert response.status_code == 201

        sorted_by_code = cast(
            dict[str, Any],
            client.get("/resources/cost-types?sort=code&limit=1", headers=headers).json(),
        )
        assert sorted_by_code["total"] == 2
        assert [c["code"] for c in sorted_by_code["items"]] == ["PAG-CT-A"]

        invalid_sort = client.get("/resources/cost-types?sort=kind", headers=headers)
        assert invalid_sort.status_code == 400


def test_category_rates_pagination_and_sort() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        cost_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "PAG-RATE-CT", "name": "Rate", "kind": "other"},
                headers=headers,
            ).json(),
        )["id"]
        category_id = cast(
            dict[str, Any],
            client.post(
                "/resources/categories",
                json={
                    "cost_type_id": cost_type_id,
                    "accounting_code": "PAG-RATE-CAT",
                    "name": "Rate category",
                },
                headers=headers,
            ).json(),
        )["id"]
        for year in (2027, 2025, 2026):
            response = client.post(
                "/resources/rates",
                json={
                    "cost_category_id": category_id,
                    "year": year,
                    "hourly_rate": "50",
                    "currency_code": "EUR",
                },
                headers=headers,
            )
            assert response.status_code == 201

        listed = cast(
            dict[str, Any],
            client.get(
                f"/resources/categories/{category_id}/rates?sort=-year&limit=2",
                headers=headers,
            ).json(),
        )
        assert listed["total"] == 3
        assert [r["year"] for r in listed["items"]] == [2027, 2026]


def test_rates_pagination() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        cost_type_id = cast(
            dict[str, Any],
            client.post(
                "/resources/cost-types",
                json={"code": "PAG-ALLRATE-CT", "name": "Rate", "kind": "other"},
                headers=headers,
            ).json(),
        )["id"]
        category_id = cast(
            dict[str, Any],
            client.post(
                "/resources/categories",
                json={
                    "cost_type_id": cost_type_id,
                    "accounting_code": "PAG-ALLRATE-CAT",
                    "name": "Rate category",
                },
                headers=headers,
            ).json(),
        )["id"]
        for year in (2030, 2031):
            response = client.post(
                "/resources/rates",
                json={
                    "cost_category_id": category_id,
                    "year": year,
                    "hourly_rate": "60",
                    "currency_code": "EUR",
                },
                headers=headers,
            )
            assert response.status_code == 201

        unpaginated = cast(dict[str, Any], client.get("/resources/rates", headers=headers).json())
        assert unpaginated["total"] == 2
        assert unpaginated["limit"] is None

        first_page = cast(
            dict[str, Any],
            client.get("/resources/rates?limit=1&sort=year", headers=headers).json(),
        )
        assert first_page["total"] == 2
        assert [r["year"] for r in first_page["items"]] == [2030]


def test_inflation_pagination_and_sort() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        for year in (2028, 2029, 2030):
            response = client.put(
                f"/resources/inflation/{year}",
                json={"coefficient": "1.02"},
                headers=headers,
            )
            assert response.status_code == 200

        descending = cast(
            dict[str, Any],
            client.get("/resources/inflation?sort=-year&limit=2", headers=headers).json(),
        )
        assert descending["total"] == 3
        assert [r["year"] for r in descending["items"]] == [2030, 2029]

        invalid_sort = client.get("/resources/inflation?sort=coefficient", headers=headers)
        assert invalid_sort.status_code == 400


def test_capacities_pagination_sort_and_role_filter() -> None:
    with TestClient(app) as client:
        headers = _admin_headers(client)
        context = _create_role_context(client, headers, "PAGCAP")
        role_ids: list[int] = []
        for suffix in ("1", "2"):
            role_response = client.post(
                "/resources/roles",
                json={
                    "name": f"Role {suffix}",
                    "node_id": context["node_id"],
                    "cost_category_id": context["cost_category_id"],
                },
                headers=headers,
            )
            assert role_response.status_code == 201
            role_id = cast(int, cast(dict[str, Any], role_response.json())["id"])
            role_ids.append(role_id)
            capacity_response = client.post(
                "/resources/capacities",
                json={"role_id": role_id, "person_count": "1", "available_hours": "1600"},
                headers=headers,
            )
            assert capacity_response.status_code == 201

        descending = cast(
            dict[str, Any],
            client.get("/resources/capacities?sort=-role_id", headers=headers).json(),
        )
        assert descending["total"] == 2
        assert [c["role_id"] for c in descending["items"]] == sorted(role_ids, reverse=True)

        filtered = cast(
            dict[str, Any],
            client.get(
                f"/resources/capacities?role_id={role_ids[0]}&limit=1", headers=headers
            ).json(),
        )
        assert filtered["total"] == 1
        assert [c["role_id"] for c in filtered["items"]] == [role_ids[0]]

        invalid_sort = client.get("/resources/capacities?sort=year", headers=headers)
        assert invalid_sort.status_code == 400


def test_resource_nodes_list_returns_complete_tree_without_truncation() -> None:
    """/resources/nodes is deliberately excluded from pagination (EPIC E7): the
    tree must always be returned whole. The new envelope shape still applies
    (`items`/`total`/`limit`/`offset`), but `limit` is always `null` and `total`
    always equals `len(items)` -- an unsupported `limit` query parameter passed by
    a caller must be silently ignored rather than truncating the tree."""
    with TestClient(app) as client:
        headers = _admin_headers(client)
        created_codes = [f"PAG-NODE-{i}" for i in range(12)]
        for code in created_codes:
            response = client.post(
                "/resources/nodes",
                json={"code": code, "name": f"Node {code}"},
                headers=headers,
            )
            assert response.status_code == 201

        payload = cast(dict[str, Any], client.get("/resources/nodes", headers=headers).json())
        assert payload["limit"] is None
        assert payload["offset"] == 0
        assert payload["total"] == len(payload["items"]) == len(created_codes)
        assert {node["code"] for node in payload["items"]} == set(created_codes)

        # An unsupported `limit` is ignored: FastAPI drops query params the
        # endpoint does not declare, so the full tree still comes back.
        ignored_limit = cast(
            dict[str, Any],
            client.get("/resources/nodes?limit=1", headers=headers).json(),
        )
        assert ignored_limit["total"] == len(created_codes)
