"""E12-01 (#273): estimate-scoped labor role assignments.

Covers `GET/POST /projects/{projectId}/estimates/{estimateId}/role-assignments`
and `PATCH/DELETE .../role-assignments/{assignmentId}` -- the devis-version-scoped
replacement for the removed project-wide `/tasks/{taskUid}/role-assignments`
routes (`api/routes/tasks.py`). `TaskRoleAssignment` itself (project-wide,
feeding the reconciliation export and planning calendar resolution) is
untouched by this issue and is not exercised here -- see
`test_estimate_reconciliation_import.py`/`test_export_api.py` for that.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    CostType,
    EstimateLine,
    EstimateRoleAssignment,
    InflationRate,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)


def _auth_headers(client: TestClient, email: str | None = None) -> dict[str, str]:
    email = email or f"estimate.role.assignment.{uuid4().hex}@example.com"
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
    return cast(int, response.json()["id"])


def _seed_project_and_task(owner_id: int, *, dated: bool = True) -> tuple[int, int]:
    """A project with one root task (uid 1001), plus the project's root cost code
    (this helper bypasses `POST /projects`, which auto-creates it -- see #62/E6-01)."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=owner_id,
            source_version=2016,
            save_version_out=16,
            name="Estimate Role Assignment Test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
            finish_date=datetime(2026, 1, 20, 18, 0, tzinfo=UTC),
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()

        session.add(
            ProjectCostCode(
                project_id=project.id,
                parent_id=None,
                code=f"PRJ-{project.id}",
                name=project.name,
            )
        )

        task = MsTask(
            project_id=project.id,
            uid=1001,
            name="Task One",
            task_type=0,
            outline_number="1",
            outline_level=1,
            wbs="1",
            start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC) if dated else None,
            finish_at=datetime(2026, 1, 6, 18, 0, tzinfo=UTC) if dated else None,
            is_summary=False,
            is_milestone=False,
        )
        session.add(task)
        session.commit()
        return project.id, task.id


def _seed_roles() -> tuple[int, int]:
    """A labor role (with 2026 CostRate/InflationRate coverage, needed for #175)
    and a supply role, returning `(labor_role_id, supply_role_id)`."""
    session_factory = get_session_factory()
    with session_factory() as session:
        node = ResourceNode(code=f"DIRECTION-{uuid4().hex[:8]}", name="Direction")
        session.add(node)
        session.flush()

        labor_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
        supply_type = CostType(code=f"FOURN-{uuid4().hex[:8]}", name="Fourniture", kind="supply")
        session.add_all([labor_type, supply_type])
        session.flush()

        labor_category = CostCategory(
            cost_type_id=labor_type.id,
            accounting_code=f"MO-DEV-{uuid4().hex[:8]}",
            category_code="IDEX",
            name="Développement",
        )
        supply_category = CostCategory(
            cost_type_id=supply_type.id,
            accounting_code=f"FO-CABLE-{uuid4().hex[:8]}",
            category_code="ACHAT",
            name="Câbles",
        )
        session.add_all([labor_category, supply_category])
        session.flush()

        labor_role = ResourceRole(
            node_id=node.id, cost_category_id=labor_category.id, name="Développeur"
        )
        supply_role = ResourceRole(
            node_id=node.id, cost_category_id=supply_category.id, name="Câble"
        )
        session.add_all([labor_role, supply_role])
        session.flush()

        session.add(
            CostRate(
                cost_category_id=labor_category.id,
                year=2026,
                hourly_rate=Decimal("100.00"),
                currency_code="EUR",
            )
        )
        session.add(InflationRate(year=2026, coefficient=Decimal("1.0")))
        session.commit()
        return labor_role.id, supply_role.id


def _seed_second_labor_role(existing_labor_role_id: int, name: str) -> int:
    """A second active labor role sharing `existing_labor_role_id`'s node/category
    (and therefore its already-seeded CostRate/InflationRate coverage)."""
    session_factory = get_session_factory()
    with session_factory() as session:
        existing = (
            session.query(ResourceRole).filter(ResourceRole.id == existing_labor_role_id).one()
        )
        role = ResourceRole(
            node_id=existing.node_id, cost_category_id=existing.cost_category_id, name=name
        )
        session.add(role)
        session.commit()
        return role.id


def _cost_category_id_for_role(role_id: int) -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        return session.query(ResourceRole).filter(ResourceRole.id == role_id).one().cost_category_id


def _create_draft_estimate(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response: Response = client.post(
        f"/projects/{project_id}/estimates",
        json={"kind": "initial", "currency_code": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _list_cost_codes(
    client: TestClient, headers: dict[str, str], project_id: int
) -> list[dict[str, Any]]:
    response: Response = client.get(f"/projects/{project_id}/cost-codes", headers=headers)
    assert response.status_code == 200
    return cast(list[dict[str, Any]], response.json()["items"])


def _root_cost_code_id(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    root = next(
        item for item in _list_cost_codes(client, headers, project_id) if item["parent_id"] is None
    )
    return cast(int, root["id"])


def test_create_role_assignment_defaults_to_project_root_cost_code() -> None:
    """Acceptance: creating without `cost_code_id` attaches to the project's root."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)
        root_id = _root_cost_code_id(client, headers, project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert response.status_code == 201
        payload = cast(dict[str, Any], response.json())
        assert payload["cost_code_id"] == root_id
        assert payload["estimate_id"] == estimate_id
        assert payload["task_id"] == task_id
        assert payload["role_code"] == "Développeur"


def test_two_draft_estimates_can_each_hold_a_different_role_for_the_same_task() -> None:
    """Acceptance: the whole point of E12-01 -- two coexisting draft estimates of
    the same project can each carry their own role assignment for the same task,
    without colliding on the (estimate_id, task_id, role_id) unique constraint --
    including the SAME role assigned independently on each, since uniqueness is
    scoped per-estimate, never project-wide."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        engineer_role_id, _ = _seed_roles()
        technician_role_id = _seed_second_labor_role(engineer_role_id, "Technicien")
        estimate_v1_id = _create_draft_estimate(client, headers, project_id)
        estimate_v2_id = _create_draft_estimate(client, headers, project_id)
        assert estimate_v1_id != estimate_v2_id

        v1_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_v1_id}/role-assignments",
            json={"task_id": task_id, "role_id": engineer_role_id, "quantity": "1", "hours": "10"},
            headers=headers,
        )
        assert v1_response.status_code == 201

        # A different role (technician) on the other draft, for the same task.
        v2_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_v2_id}/role-assignments",
            json={
                "task_id": task_id,
                "role_id": technician_role_id,
                "quantity": "1",
                "hours": "1",
            },
            headers=headers,
        )
        assert v2_response.status_code == 201

        # The SAME role (engineer) is also fine on the second estimate: uniqueness
        # is scoped per-estimate, not project-wide -- this is the exact
        # (task_id, role_id) pair already used on estimate_v1_id.
        v2_same_role_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_v2_id}/role-assignments",
            json={"task_id": task_id, "role_id": engineer_role_id, "quantity": "2", "hours": "20"},
            headers=headers,
        )
        assert v2_same_role_response.status_code == 201

        # But a genuine duplicate WITHIN the same estimate is still rejected.
        duplicate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_v1_id}/role-assignments",
            json={"task_id": task_id, "role_id": engineer_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert duplicate_response.status_code == 409

        # Independently editable: updating v1's copy must not affect v2's copy.
        v1_id = cast(int, v1_response.json()["id"])
        update_response = client.patch(
            f"/projects/{project_id}/estimates/{estimate_v1_id}/role-assignments/{v1_id}",
            json={"hours": "99"},
            headers=headers,
        )
        assert update_response.status_code == 200
        v2_same_role_id = cast(int, v2_same_role_response.json()["id"])
        v2_get = client.get(
            f"/projects/{project_id}/estimates/{estimate_v2_id}/role-assignments",
            headers=headers,
        )
        v2_items = {item["id"]: item for item in v2_get.json()["items"]}
        assert v2_items[v2_same_role_id]["hours"] == "20.00"


def test_create_and_update_reject_non_draft_estimate() -> None:
    """Acceptance: create/update on a validated estimate is refused with 409."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert create_response.status_code == 201
        assignment_id = cast(int, create_response.json()["id"])

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate", headers=headers
        )
        assert validate_response.status_code == 200

        rejected_create = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert rejected_create.status_code == 409

        rejected_update = client.patch(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
            json={"hours": "5"},
            headers=headers,
        )
        assert rejected_update.status_code == 409


def test_role_assignment_lifecycle() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, supply_role_id = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        rejected_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": supply_role_id, "quantity": "1", "hours": "7.4"},
            headers=headers,
        )
        assert rejected_response.status_code == 400

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "2", "hours": "7.4"},
            headers=headers,
        )
        assert create_response.status_code == 201
        assignment = cast(dict[str, Any], create_response.json())
        assignment_id = cast(int, assignment["id"])
        assert assignment["role_code"] == "Développeur"

        list_response = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            headers=headers,
        )
        assert list_response.status_code == 200
        assignments = cast(list[dict[str, Any]], list_response.json()["items"])
        assert len(assignments) == 1

        update_response = client.patch(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
            json={"hours": "14.8"},
            headers=headers,
        )
        assert update_response.status_code == 200
        # The response is built before commit (no commit-then-refresh, tech debt
        # #262), so it reflects the value exactly as validated by the request
        # payload -- unlike a DB round-trip, it is not re-quantized to the
        # column's Numeric(14, 2) scale.
        updated_hours = cast(str, update_response.json()["hours"])
        assert Decimal(updated_hours) == Decimal("14.8")

        delete_response = client.delete(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
            headers=headers,
        )
        assert delete_response.status_code == 204

        empty_list_response = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            headers=headers,
        )
        assert empty_list_response.json()["items"] == []


def test_list_role_assignments_pagination_sort_and_search() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        session_factory = get_session_factory()
        with session_factory() as session:
            labor_role = session.query(ResourceRole).filter(ResourceRole.id == labor_role_id).one()
            second_role = ResourceRole(
                node_id=labor_role.node_id,
                cost_category_id=labor_role.cost_category_id,
                name="Analyste",
            )
            session.add(second_role)
            session.commit()
            second_role_id = second_role.id

        first_assignment = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert first_assignment.status_code == 201
        second_assignment = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": second_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert second_assignment.status_code == 201

        listed = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments", headers=headers
        )
        assert listed.status_code == 200
        body = cast(dict[str, Any], listed.json())
        assert body["limit"] is None
        assert body["total"] == len(body["items"]) == 2
        assert [item["role_name"] for item in body["items"]] == ["Analyste", "Développeur"]

        descending = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments?sort=-role_name",
            headers=headers,
        )
        assert descending.status_code == 200
        assert [item["role_name"] for item in descending.json()["items"]] == [
            "Développeur",
            "Analyste",
        ]

        invalid_sort = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments?sort=unknown_column",
            headers=headers,
        )
        assert invalid_sort.status_code == 400

        searched = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments?q=analyste",
            headers=headers,
        )
        assert searched.status_code == 200
        assert [item["role_name"] for item in searched.json()["items"]] == ["Analyste"]


def test_create_rejects_role_outside_active_labor_category() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        _, supply_role_id = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": supply_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert response.status_code == 400


def test_create_rejects_task_outside_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_project_and_task(_current_user_id(client, headers))
        other_project_id, other_task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": other_task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
            },
            headers=headers,
        )
        assert response.status_code == 400
        assert other_project_id != project_id


def test_create_accepts_explicit_sub_cost_code_and_rejects_foreign_one() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)
        root_id = _root_cost_code_id(client, headers, project_id)

        sub_code_response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT-MO", "name": "Lot main d'oeuvre", "parent_id": root_id},
            headers=headers,
        )
        assert sub_code_response.status_code == 201
        sub_code_id = cast(int, sub_code_response.json()["id"])

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
                "cost_code_id": sub_code_id,
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        assignment_id = cast(int, create_response.json()["id"])
        assert create_response.json()["cost_code_id"] == sub_code_id

        other_project_id, _ = _seed_project_and_task(_current_user_id(client, headers))
        other_root_id = _root_cost_code_id(client, headers, other_project_id)

        # A second task on the *same* project, so this rejection check exercises
        # the cost_code_id/project-membership rule in isolation, without also
        # tripping the (estimate_id, task_id, role_id) uniqueness constraint.
        session_factory = get_session_factory()
        with session_factory() as session:
            second_task = MsTask(project_id=project_id, uid=1002, name="Task Two")
            session.add(second_task)
            session.commit()
            second_task_id = second_task.id

        rejected_create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": second_task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
                "cost_code_id": other_root_id,
            },
            headers=headers,
        )
        assert rejected_create_response.status_code == 400

        rejected_update_response = client.patch(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
            json={"cost_code_id": other_root_id},
            headers=headers,
        )
        assert rejected_update_response.status_code == 400

        accepted_update_response = client.patch(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
            json={"cost_code_id": root_id},
            headers=headers,
        )
        assert accepted_update_response.status_code == 200
        assert accepted_update_response.json()["cost_code_id"] == root_id


def test_update_explicit_null_cost_code_id_resolves_to_root_not_cleared() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)
        root_id = _root_cost_code_id(client, headers, project_id)

        sub_code_response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT-MO-NULL", "name": "Lot", "parent_id": root_id},
            headers=headers,
        )
        sub_code_id = cast(int, sub_code_response.json()["id"])

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
                "cost_code_id": sub_code_id,
            },
            headers=headers,
        )
        assignment_id = cast(int, create_response.json()["id"])

        null_update_response = client.patch(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment_id}",
            json={"cost_code_id": None},
            headers=headers,
        )
        assert null_update_response.status_code == 200
        assert null_update_response.json()["cost_code_id"] == root_id


def test_create_rejects_a_deactivated_cost_code() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)
        root_id = _root_cost_code_id(client, headers, project_id)

        sub_code_response = client.post(
            f"/projects/{project_id}/cost-codes",
            json={"code": "LOT-MO-INACTIVE", "name": "Lot", "parent_id": root_id},
            headers=headers,
        )
        sub_code_id = cast(int, sub_code_response.json()["id"])

        deactivate_response = client.delete(
            f"/projects/{project_id}/cost-codes/{sub_code_id}", headers=headers
        )
        assert deactivate_response.status_code == 204

        rejected_create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
                "cost_code_id": sub_code_id,
            },
            headers=headers,
        )
        assert rejected_create_response.status_code == 400


def test_create_on_dated_task_rejects_missing_cost_rate_coverage() -> None:
    """Issue #175 (E6-11): identical guard as the removed `create_task_role_assignment`."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        project_id, _ = _seed_project_and_task(owner_id, dated=False)
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        session_factory = get_session_factory()
        with session_factory() as session:
            # `_seed_roles` only seeds a CostRate for year 2026; this task spans a
            # year with no rate for that same labor category at all.
            uncovered_task = MsTask(
                project_id=project_id,
                uid=1006,
                name="Uncovered rate task",
                task_type=0,
                outline_number="6",
                outline_level=1,
                start_at=datetime(2029, 3, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2029, 3, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
            )
            session.add(uncovered_task)
            session.commit()
            uncovered_task_id = uncovered_task.id

        labor_category_id = _cost_category_id_for_role(labor_role_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": uncovered_task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
            },
            headers=headers,
        )
        assert response.status_code == 400
        detail = cast(dict[str, Any], response.json())["detail"]
        assert detail["code"] == "MISSING_RATE_COVERAGE"
        assert detail["missing_cost_rates"] == [
            {
                "category_id": labor_category_id,
                "category_name": "Développement",
                "accounting_code": _cost_category_accounting_code(labor_category_id),
                "year": 2029,
            }
        ]
        assert detail["missing_inflation_years"] == [2029]


def _cost_category_accounting_code(category_id: int) -> str:
    session_factory = get_session_factory()
    with session_factory() as session:
        return (
            session.query(CostCategory).filter(CostCategory.id == category_id).one().accounting_code
        )


def test_create_on_dated_task_rejects_missing_inflation_rate_coverage() -> None:
    """Issue #175 (E6-11): even when the category has a `CostRate` for the task's
    year, a missing `InflationRate` for that same year must refuse the assignment
    too -- inflation coverage is checked independently of the cost-rate coverage.
    Ported from the removed `test_task_role_assignment_on_dated_task_rejects_
    missing_inflation_rate_coverage` (test_projects_api.py) onto the new
    estimate-scoped route (E12-01/#273 review finding)."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _ = _seed_project_and_task(_current_user_id(client, headers), dated=False)
        labor_role_id, _ = _seed_roles()
        labor_category_id = _cost_category_id_for_role(labor_role_id)
        estimate_id = _create_draft_estimate(client, headers, project_id)

        session_factory = get_session_factory()
        with session_factory() as session:
            # A CostRate exists for 2030, but no InflationRate does.
            session.add(
                CostRate(
                    cost_category_id=labor_category_id,
                    year=2030,
                    hourly_rate=Decimal("120.00"),
                    currency_code="EUR",
                )
            )
            rate_only_task = MsTask(
                project_id=project_id,
                uid=1007,
                name="Rate-only task",
                task_type=0,
                outline_number="7",
                outline_level=1,
                start_at=datetime(2030, 3, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2030, 3, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
            )
            session.add(rate_only_task)
            session.commit()
            rate_only_task_id = rate_only_task.id

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": rate_only_task_id,
                "role_id": labor_role_id,
                "quantity": "1",
                "hours": "1",
            },
            headers=headers,
        )
        assert response.status_code == 400
        # Review finding (E6-11/#175): assert on the JSON a real HTTP client
        # actually receives. The `CostRate` for 2030 exists, so only the
        # `InflationRate` gap is reported.
        detail = cast(dict[str, Any], response.json())["detail"]
        assert detail["code"] == "MISSING_RATE_COVERAGE"
        assert detail["missing_cost_rates"] == []
        assert detail["missing_inflation_years"] == [2030]


def test_create_reports_a_clean_error_if_project_has_no_active_root() -> None:
    """Review finding on #63 (originally `test_task_role_assignment_reports_a_
    clean_error_if_project_has_no_active_root`, test_projects_api.py, ported to the
    new estimate-scoped route by the E12-01/#273 review): the #62/E6-01 invariant
    (every project always has an active root cost code) is guaranteed by
    application logic, not a DB constraint -- if it were ever violated,
    resolve_cost_code_id must surface a clean, documented error rather than a bare,
    unhandled NoResultFound. Deactivating the root directly at the ORM layer
    (bypassing the API, which always refuses this) is the only way to construct
    that state for this test."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)
        root_id = _root_cost_code_id(client, headers, project_id)

        session_factory = get_session_factory()
        with session_factory() as session:
            root = session.query(ProjectCostCode).filter(ProjectCostCode.id == root_id).one()
            root.is_active = False
            session.add(root)
            session.commit()

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert response.status_code == 500


def test_create_without_dates_skips_rate_coverage_check() -> None:
    """Issue #175 (E6-11): an undated task has no known years to check, so the
    guard must not apply -- creation succeeds like before this issue."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers), dated=False)
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert response.status_code == 201


def test_estimate_role_assignment_used_by_labor_calculation_on_validation() -> None:
    """E12-02 (#274): `calculate_estimate_lines` now reads this estimate's own
    `EstimateRoleAssignment` rows (E12-01/#273 review finding, high #2, tracked
    the transitional gap this closes -- see the docstring of migration
    20260909_0012_estimate_role_assignment.py). Creating one and validating the
    devis must produce a matching `EstimateLine`, and synchronize a
    project-wide `TaskRoleAssignment` for the same (task, role) pair (full
    sync/replacement semantics and calendar resolution are covered end-to-end
    in `test_estimate_calculation.py`)."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert create_response.status_code == 201

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate", headers=headers
        )
        assert validate_response.status_code == 200

        session_factory = get_session_factory()
        with session_factory() as session:
            matching_lines = (
                session.query(EstimateLine)
                .filter(EstimateLine.estimate_id == estimate_id)
                .filter(EstimateLine.task_id == task_id)
                .filter(EstimateLine.role_id == labor_role_id)
                .count()
            )
            assert matching_lines == 1

            synced = (
                session.query(TaskRoleAssignment)
                .filter(TaskRoleAssignment.task_id == task_id)
                .filter(TaskRoleAssignment.role_id == labor_role_id)
                .one()
            )
            assert synced.quantity == Decimal("1")
            assert synced.hours == Decimal("1")


def test_delete_project_purges_its_estimate_role_assignments() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_and_task(_current_user_id(client, headers))
        labor_role_id, _ = _seed_roles()
        estimate_id = _create_draft_estimate(client, headers, project_id)

        create_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={"task_id": task_id, "role_id": labor_role_id, "quantity": "1", "hours": "1"},
            headers=headers,
        )
        assert create_response.status_code == 201
        assignment_id = cast(int, create_response.json()["id"])

        delete_response = client.delete(f"/projects/{project_id}", headers=headers)
        assert delete_response.status_code == 204

        session_factory = get_session_factory()
        with session_factory() as session:
            assert (
                session.query(EstimateRoleAssignment)
                .filter(EstimateRoleAssignment.id == assignment_id)
                .count()
                == 0
            )
