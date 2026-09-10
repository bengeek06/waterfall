"""E12-09 (#291): `row_number` on every devis grid read, plus `uid`/`parent_uid`/
`position` on `EstimateCostLineRead`/`EstimateRoleAssignmentRead`.

Covers `order_estimate_grid_depth_first` (`api/routes/planning_support.py`) and
`_load_estimate_grid_context` (`api/routes/estimates.py`) through the public
`GET/POST .../task-rows`, `GET/POST .../cost-lines` and `.../grid-nodes/move`
endpoints -- see #289 (E12-07)/#290 (E12-08) for the grid-node tree and the
live task display this issue merges together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateGridNode,
    InflationRate,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
)


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"estimate.grid.row.number.{uuid4().hex}@example.com"
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


def _current_user_id(client: TestClient, headers: dict[str, str]) -> int:
    response: Response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    return cast(int, response.json()["id"])


def _new_project(owner_id: int, *, name: str) -> MsProject:
    return MsProject(
        owner_id=owner_id,
        source_version=2016,
        save_version_out=16,
        name=name,
        schedule_from_start=True,
        start_date=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        finish_date=datetime(2026, 1, 20, 18, 0, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
        currency_code="EUR",
    )


def _seed_project(owner_id: int) -> int:
    """A bare project with its root cost code and no task."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project(owner_id, name="Estimate Grid Row Number Test")
        session.add(project)
        session.flush()
        session.add(
            ProjectCostCode(
                project_id=project.id, parent_id=None, code=f"PRJ-{project.id}", name=project.name
            )
        )
        session.commit()
        return project.id


def _seed_project_with_task(owner_id: int) -> tuple[int, int]:
    """A project with its root cost code and one undated root task."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project(owner_id, name="Estimate Grid Row Number Test")
        session.add(project)
        session.flush()
        session.add(
            ProjectCostCode(
                project_id=project.id, parent_id=None, code=f"PRJ-{project.id}", name=project.name
            )
        )
        task = MsTask(project_id=project.id, uid=1001, name="Task A")
        session.add(task)
        session.commit()
        return project.id, task.id


def _seed_project_with_dated_task(owner_id: int) -> tuple[int, int]:
    """A project with its root cost code and one dated root task (2026), so a
    labor role assignment against it can be created and the devis validated
    without tripping #175's CostRate/InflationRate coverage guard."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project(owner_id, name="Estimate Grid Row Number Validated Test")
        session.add(project)
        session.flush()
        session.add(
            ProjectCostCode(
                project_id=project.id, parent_id=None, code=f"PRJ-{project.id}", name=project.name
            )
        )
        task = MsTask(
            project_id=project.id,
            uid=1001,
            name="Task A",
            start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
            finish_at=datetime(2026, 1, 6, 18, 0, tzinfo=UTC),
        )
        session.add(task)
        session.commit()
        return project.id, task.id


def _seed_labor_role() -> int:
    """A labor role with 2026 CostRate/InflationRate coverage -- needed to
    validate a devis holding a role assignment against a dated task (#175)."""
    session_factory = get_session_factory()
    with session_factory() as session:
        node = ResourceNode(code=f"DIRECTION-{uuid4().hex[:8]}", name="Direction")
        session.add(node)
        session.flush()
        labor_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
        session.add(labor_type)
        session.flush()
        labor_category = CostCategory(
            cost_type_id=labor_type.id,
            accounting_code=f"MO-DEV-{uuid4().hex[:8]}",
            category_code="IDEX",
            name="Développement",
        )
        session.add(labor_category)
        session.flush()
        role = ResourceRole(node_id=node.id, cost_category_id=labor_category.id, name="Développeur")
        session.add(role)
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
        return role.id


def _seed_project_with_dangling_ancestor(owner_id: int) -> tuple[int, int, int]:
    """A project with a draft planning holding 3 tasks: `task_r` (an unrelated,
    ordinary root), `task_p` (a root with no legacy `MsTask` twin -- the
    "ancestor" that left the devis's scope, mirroring
    `_resolve_legacy_parent_task`'s own documented degenerate case) and
    `task_c` (a real, twinned task whose snapshot's `parent_uid` points at
    `task_p`). `WfPlanningTaskSnapshot.parent_uid` carries its own DB-level FK
    to another snapshot of the *same* planning, so a snapshot can never
    reference an ancestor that was never part of the tree at all -- the
    reachable "ancestor out of scope" case is a real, FK-valid ancestor
    snapshot whose legacy `MsTask` twin (the identity
    `resolve_task_uid_by_id`/`resolve_live_task_display` actually key off) is
    simply absent (E12-09/#291's third acceptance test).

    Returns `(project_id, task_r_id, task_c_id)` (`MsTask.id`, not `uid`).
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project(owner_id, name="Estimate Grid Dangling Ancestor Test")
        session.add(project)
        session.flush()
        session.add(
            ProjectCostCode(
                project_id=project.id, parent_id=None, code=f"PRJ-{project.id}", name=project.name
            )
        )

        planning = WfPlanning(project_id=project.id, version_number=1, status="draft")
        session.add(planning)
        session.flush()

        # task_p deliberately has no MsTask twin (only a snapshot).
        task_r = MsTask(project_id=project.id, uid=10, name="Root")
        task_c = MsTask(project_id=project.id, uid=30, name="Child of a vanished ancestor")
        session.add_all([task_r, task_c])
        session.flush()

        session.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=10,
                    name="Root",
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=20,
                    name="Vanished ancestor",
                    position=2,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=30,
                    parent_uid=20,
                    name="Child of a vanished ancestor",
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
            ]
        )
        project.displayed_planning_id = planning.id
        session.add(project)
        session.commit()
        return project.id, task_r.id, task_c.id


def _create_draft_estimate(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response: Response = client.post(
        f"/projects/{project_id}/estimates",
        json={"kind": "initial", "currency_code": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast(int, response.json()["id"])


def _create_cost_category() -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        cost_type = CostType(code=f"SUPPLY-{uuid4().hex[:8]}", name="Fourniture", kind="supply")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"ACC-{uuid4().hex[:8]}",
            category_code="ACHAT",
            name="Cables",
        )
        session.add(category)
        session.commit()
        return category.id


def _create_cost_line(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    estimate_id: int,
    cost_category_id: int,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "cost_category_id": cost_category_id,
        "label": f"Line {uuid4().hex[:6]}",
        "quantity": "1",
        "unit_cost": "10",
        **extra,
    }
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _list_cost_lines(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int, **params: Any
) -> dict[str, Any]:
    response = client.get(
        f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
        params=params,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def _list_task_rows(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int
) -> list[dict[str, Any]]:
    response = client.get(
        f"/projects/{project_id}/estimates/{estimate_id}/task-rows",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json()["items"])


def _create_role_assignment(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    estimate_id: int,
    task_id: int,
    role_id: int,
    **extra: Any,
) -> dict[str, Any]:
    payload = {"task_id": task_id, "role_id": role_id, "quantity": "1", "hours": "1", **extra}
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _list_role_assignments(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int
) -> list[dict[str, Any]]:
    response = client.get(
        f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json()["items"])


def _validate_estimate(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int
) -> None:
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/validate",
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _node_for_cost_line(line_id: int) -> EstimateGridNode:
    session_factory = get_session_factory()
    with session_factory() as session:
        line = session.query(EstimateCostLine).filter(EstimateCostLine.id == line_id).one()
        return session.query(EstimateGridNode).filter(EstimateGridNode.id == line.node_id).one()


def _estimate_revision(estimate_id: int) -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        return session.query(Estimate.revision).filter(Estimate.id == estimate_id).scalar()


def test_task_followed_by_two_cost_lines_gets_sequential_row_numbers() -> None:
    """Acceptance (#291): a task followed by 2 cost lines attached to it gets
    row_number 1, 2, 3 in that order."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_with_task(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        task_rows = _list_task_rows(client, headers, project_id, estimate_id)
        assert len(task_rows) == 1
        assert task_rows[0]["row_number"] == 1

        first = _create_cost_line(
            client, headers, project_id, estimate_id, category_id, target_parent_uid=task_id
        )
        second = _create_cost_line(
            client, headers, project_id, estimate_id, category_id, target_parent_uid=task_id
        )
        assert first["row_number"] == 2
        assert second["row_number"] == 3
        assert first["uid"] < 0
        assert first["parent_uid"] == task_id

        # A fresh read (not just the create responses) reports the same ranks.
        lines = _list_cost_lines(client, headers, project_id, estimate_id)["items"]
        row_number_by_id = {line["id"]: line["row_number"] for line in lines}
        assert row_number_by_id[first["id"]] == 2
        assert row_number_by_id[second["id"]] == 3
        task_rows_after = _list_task_rows(client, headers, project_id, estimate_id)
        assert task_rows_after[0]["row_number"] == 1


def test_move_cost_line_changes_row_number_for_it_and_its_new_siblings() -> None:
    """Acceptance (#291): moving a cost line (E12-07's grid-nodes/move) changes
    its own row_number and that of the lines around it, on the very next read
    -- no extra action needed."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _seed_project(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        first = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        second = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        third = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        assert [first["row_number"], second["row_number"], third["row_number"]] == [1, 2, 3]

        first_node = _node_for_cost_line(cast(int, first["id"]))
        move_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [first_node.uid],
                "target_parent_uid": None,
                "position": 2,
                "expected_revision": _estimate_revision(estimate_id),
            },
            headers=headers,
        )
        assert move_response.status_code == 200, move_response.text

        # New order: second, first, third.
        lines = _list_cost_lines(client, headers, project_id, estimate_id)["items"]
        row_number_by_id = {line["id"]: line["row_number"] for line in lines}
        assert row_number_by_id[second["id"]] == 1
        assert row_number_by_id[first["id"]] == 2
        assert row_number_by_id[third["id"]] == 3


def test_task_rows_pagination_reports_row_number_from_the_full_devis_not_the_page() -> None:
    """Regression guard for the exact scoping bug E12-08 (#290) hit: a page's
    row_number must be its true rank in the whole devis, not a rank restarted
    at 1 for each page."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _seed_project(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        first = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        second = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        third = _create_cost_line(client, headers, project_id, estimate_id, category_id)

        second_page = _list_cost_lines(client, headers, project_id, estimate_id, limit=1, offset=1)
        assert second_page["total"] == 3
        assert len(second_page["items"]) == 1
        assert second_page["items"][0]["id"] == second["id"]
        # Not 1: the item is the *second* row of the whole devis, even though
        # it is the *first* (only) row of this page.
        assert second_page["items"][0]["row_number"] == 2

        third_page = _list_cost_lines(client, headers, project_id, estimate_id, limit=1, offset=2)
        assert third_page["items"][0]["id"] == third["id"]
        assert third_page["items"][0]["row_number"] == 3
        assert first["row_number"] == 1


def test_task_with_out_of_scope_ancestor_degrades_to_root_without_blocking_the_rest() -> None:
    """Acceptance (#291): a task whose ancestor left the devis's planning scope
    after the estimate was created does not prevent computing row_number for
    the rest of the tree -- it degrades gracefully to the devis root."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_r_id, _task_c_id = _seed_project_with_dangling_ancestor(
            _current_user_id(client, headers)
        )
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        # 3 rows: task_r, the vanished ancestor itself (no MsTask twin, so its
        # own task_uid/row_number stay None -- a separate, pre-existing
        # degenerate case, see resolve_live_task_display's own docstring),
        # and task_c.
        task_rows = _list_task_rows(client, headers, project_id, estimate_id)
        assert len(task_rows) == 3
        by_task_id = {row["task_id"]: row for row in task_rows}
        # task_c itself still resolves and gets a row_number -- it just has no
        # parent left (degraded to root) since its ancestor's MsTask twin is
        # gone.
        child_row = next(
            row for row in task_rows if row["task_name"] == "Child of a vanished ancestor"
        )
        assert child_row["parent_task_id"] is None
        assert child_row["row_number"] is not None

        # The rest of the tree -- the unrelated root task and its own cost
        # line -- computes a perfectly normal row_number.
        line = _create_cost_line(
            client, headers, project_id, estimate_id, category_id, target_parent_uid=task_r_id
        )
        root_row_number = by_task_id[task_r_id]["row_number"]
        assert root_row_number is not None
        assert line["row_number"] == root_row_number + 1


def test_row_number_uid_parent_uid_position_stay_correct_after_validation() -> None:
    """Moyenne finding (#291 review): row_number/uid/parent_uid/position on
    cost-lines, role-assignments and task-rows must stay correct and stable
    once the devis is validated, not just for a draft. `_load_estimate_grid_context`
    deliberately computes them from the grid's frozen shape for a validated
    estimate exactly like a draft one (see its own docstring) -- this guards
    that a fresh read after validation neither crashes nor silently drops
    those values."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_id = _seed_project_with_dated_task(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()
        labor_role_id = _seed_labor_role()

        task_rows_before = _list_task_rows(client, headers, project_id, estimate_id)
        assert len(task_rows_before) == 1
        assert task_rows_before[0]["row_number"] == 1

        line = _create_cost_line(
            client, headers, project_id, estimate_id, category_id, target_parent_uid=task_id
        )
        assignment = _create_role_assignment(
            client,
            headers,
            project_id,
            estimate_id,
            task_id,
            labor_role_id,
            target_parent_uid=task_id,
        )
        assert line["row_number"] == 2
        assert assignment["row_number"] == 3
        assert line["parent_uid"] == task_id
        assert assignment["parent_uid"] == task_id

        _validate_estimate(client, headers, project_id, estimate_id)

        # Fresh reads (not the create responses) on the now-validated devis.
        task_rows_after = _list_task_rows(client, headers, project_id, estimate_id)
        lines_after = _list_cost_lines(client, headers, project_id, estimate_id)["items"]
        assignments_after = _list_role_assignments(client, headers, project_id, estimate_id)

        assert len(task_rows_after) == 1
        assert task_rows_after[0]["row_number"] == 1
        assert len(lines_after) == 1
        assert len(assignments_after) == 1

        line_after = lines_after[0]
        assert line_after["id"] == line["id"]
        assert line_after["row_number"] == 2
        assert line_after["uid"] == line["uid"]
        assert line_after["parent_uid"] == task_id
        assert line_after["position"] == line["position"]

        assignment_after = assignments_after[0]
        assert assignment_after["id"] == assignment["id"]
        assert assignment_after["row_number"] == 3
        assert assignment_after["uid"] == assignment["uid"]
        assert assignment_after["parent_uid"] == task_id
        assert assignment_after["position"] == assignment["position"]
