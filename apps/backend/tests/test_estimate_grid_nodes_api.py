"""E12-07 (#289): the devis grid node tree and its move endpoint.

Covers `POST /projects/{projectId}/estimates/{estimateId}/grid-nodes/move`, the
default "last child of the devis root" placement of a newly created
`EstimateCostLine`/`EstimateRoleAssignment`, and `task_id` recalculation after a
move -- see `services/estimate_grid.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    CostCategory,
    CostType,
    Estimate,
    EstimateCostLine,
    EstimateGridNode,
    EstimateRoleAssignment,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
)


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"estimate.grid.node.{uuid4().hex}@example.com"
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


def _seed_project_with_two_tasks(owner_id: int) -> tuple[int, int, int]:
    """A project with its root cost code and two undated root tasks (task_a, task_b)."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=owner_id,
            source_version=2016,
            save_version_out=16,
            name="Estimate Grid Node Test",
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

        task_a = MsTask(project_id=project.id, uid=1001, name="Task A")
        task_b = MsTask(project_id=project.id, uid=1002, name="Task B")
        session.add_all([task_a, task_b])
        session.commit()
        return project.id, task_a.id, task_b.id


def _seed_labor_role() -> int:
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
        session.commit()
        return role.id


def _create_draft_estimate(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response: Response = client.post(
        f"/projects/{project_id}/estimates",
        json={"kind": "initial", "currency_code": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _create_cost_category(kind: str = "supply") -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        cost_type = CostType(code=f"{kind.upper()}-{uuid4().hex[:8]}", name=kind, kind=kind)
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


def _create_role_assignment(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    estimate_id: int,
    task_id: int,
    role_id: int,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "task_id": task_id,
        "role_id": role_id,
        "quantity": "1",
        "hours": "1",
        **extra,
    }
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _node_for_cost_line(line_id: int) -> EstimateGridNode:
    session_factory = get_session_factory()
    with session_factory() as session:
        line = session.query(EstimateCostLine).filter(EstimateCostLine.id == line_id).one()
        return session.query(EstimateGridNode).filter(EstimateGridNode.id == line.node_id).one()


def _node_for_assignment(assignment_id: int) -> EstimateGridNode:
    session_factory = get_session_factory()
    with session_factory() as session:
        assignment = (
            session.query(EstimateRoleAssignment)
            .filter(EstimateRoleAssignment.id == assignment_id)
            .one()
        )
        return (
            session.query(EstimateGridNode).filter(EstimateGridNode.id == assignment.node_id).one()
        )


def _assignment_task_id(assignment_id: int) -> int | None:
    session_factory = get_session_factory()
    with session_factory() as session:
        return (
            session.query(EstimateRoleAssignment.task_id)
            .filter(EstimateRoleAssignment.id == assignment_id)
            .scalar()
        )


def _estimate_revision(estimate_id: int) -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        return session.query(Estimate.revision).filter(Estimate.id == estimate_id).scalar()


def test_create_cost_line_without_position_becomes_last_root_child() -> None:
    """Acceptance: creating a cost line without a position places it last among
    the devis root's children."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _, _ = _seed_project_with_two_tasks(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        first = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        second = _create_cost_line(client, headers, project_id, estimate_id, category_id)

        first_node = _node_for_cost_line(cast(int, first["id"]))
        second_node = _node_for_cost_line(cast(int, second["id"]))

        assert first_node.parent_uid is None
        assert second_node.parent_uid is None
        assert first_node.position == 1
        assert second_node.position == 2


def test_create_and_delete_cost_line_bump_estimate_revision() -> None:
    """Finding Haute (#289 review): creating/deleting a cost line mutates the
    devis grid node tree exactly like grid-nodes/move does, so it must bump
    estimate.revision too -- otherwise a concurrent move's expected_revision
    optimistic lock can pass against a tree that already changed underneath it."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _, _ = _seed_project_with_two_tasks(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        assert _estimate_revision(estimate_id) == 0

        line = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        assert _estimate_revision(estimate_id) == 1

        delete_response = client.delete(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines/{line['id']}",
            headers=headers,
        )
        assert delete_response.status_code == 204
        assert _estimate_revision(estimate_id) == 2


def test_create_and_delete_role_assignment_bump_estimate_revision() -> None:
    """Same Finding Haute obligation as the cost-line test above, for
    role-assignment create/delete."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_a_id, _ = _seed_project_with_two_tasks(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        role_id = _seed_labor_role()

        assert _estimate_revision(estimate_id) == 0

        assignment = _create_role_assignment(
            client, headers, project_id, estimate_id, task_a_id, role_id
        )
        assert _estimate_revision(estimate_id) == 1

        delete_response = client.delete(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments/{assignment['id']}",
            headers=headers,
        )
        assert delete_response.status_code == 204
        assert _estimate_revision(estimate_id) == 2


def test_move_labor_line_to_another_task_updates_node_and_recalculates_task_id() -> None:
    """Acceptance: moving a labor line to attach it to another task updates its
    node's parent_uid and its own recalculated task_id, without touching any
    other line of the same estimate."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_a_id, task_b_id = _seed_project_with_two_tasks(
            _current_user_id(client, headers)
        )
        estimate_id = _create_draft_estimate(client, headers, project_id)
        role_id = _seed_labor_role()
        category_id = _create_cost_category()

        moved = _create_role_assignment(
            client,
            headers,
            project_id,
            estimate_id,
            task_a_id,
            role_id,
            target_parent_uid=task_a_id,
        )
        # An unrelated cost line, untouched by the move below.
        untouched = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        untouched_node_before = _node_for_cost_line(cast(int, untouched["id"]))

        moved_node = _node_for_assignment(cast(int, moved["id"]))
        assert moved_node.parent_uid == task_a_id

        # Issue #289 review (Finding Haute): both creates above already bumped
        # estimate.revision, so expected_revision must reflect that, not the
        # estimate's initial 0.
        revision_before = _estimate_revision(estimate_id)
        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [moved_node.uid],
                "target_parent_uid": task_b_id,
                "position": 1,
                "expected_revision": revision_before,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["revision"] == revision_before + 1

        moved_node_after = _node_for_assignment(cast(int, moved["id"]))
        assert moved_node_after.parent_uid == task_b_id
        assert _assignment_task_id(cast(int, moved["id"])) == task_b_id

        untouched_node_after = _node_for_cost_line(cast(int, untouched["id"]))
        assert untouched_node_after.parent_uid == untouched_node_before.parent_uid
        assert untouched_node_after.position == untouched_node_before.position


def test_unindent_line_to_root_clears_task_id_without_error() -> None:
    """Acceptance: unindenting a line all the way to the devis root (no ancestor
    task left) sets its task_id to NULL without error."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_a_id, _ = _seed_project_with_two_tasks(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        role_id = _seed_labor_role()

        assignment = _create_role_assignment(
            client,
            headers,
            project_id,
            estimate_id,
            task_a_id,
            role_id,
            target_parent_uid=task_a_id,
        )
        node = _node_for_assignment(cast(int, assignment["id"]))
        assert node.parent_uid == task_a_id

        # Issue #289 review (Finding Haute): the create above already bumped
        # estimate.revision.
        revision_before = _estimate_revision(estimate_id)
        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [node.uid],
                "target_parent_uid": None,
                "position": 1,
                "expected_revision": revision_before,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

        node_after = _node_for_assignment(cast(int, assignment["id"]))
        assert node_after.parent_uid is None
        assert _assignment_task_id(cast(int, assignment["id"])) is None


def test_move_with_stale_expected_revision_returns_409_without_mutating_tree() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_a_id, task_b_id = _seed_project_with_two_tasks(
            _current_user_id(client, headers)
        )
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        line = _create_cost_line(
            client, headers, project_id, estimate_id, category_id, target_parent_uid=task_a_id
        )
        node_before = _node_for_cost_line(cast(int, line["id"]))
        # Issue #289 review (Finding Haute): the create above already bumped
        # estimate.revision away from 0.
        revision_before = _estimate_revision(estimate_id)

        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [node_before.uid],
                "target_parent_uid": task_b_id,
                "position": 1,
                "expected_revision": 999,
            },
            headers=headers,
        )
        assert response.status_code == 409
        detail = cast(dict[str, Any], response.json())["detail"]
        assert detail["code"] == "ESTIMATE_REVISION_CONFLICT"
        assert detail["expected_revision"] == 999
        assert detail["current_revision"] == revision_before

        node_after = _node_for_cost_line(cast(int, line["id"]))
        assert node_after.parent_uid == task_a_id
        assert _estimate_revision(estimate_id) == revision_before


def test_move_rejects_target_parent_task_outside_estimate_scope() -> None:
    """A positive target_parent_uid that isn't one of this estimate's own
    EstimateTaskRow tasks is refused with 404 (not a bare FK/500)."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        project_id, _, _ = _seed_project_with_two_tasks(owner_id)
        # A second, unrelated project: create_project_estimate below snapshots every
        # MsTask of *its own* project_id into EstimateTaskRow (see its own
        # docstring/legacy_tasks fallback) -- a task from a different project is
        # never a member of this estimate's own task-rows, unlike a task of the
        # *same* project (which the fallback would auto-include).
        other_project_id, other_task_id, _ = _seed_project_with_two_tasks(owner_id)
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        line = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        node = _node_for_cost_line(cast(int, line["id"]))

        # Issue #289 review (Finding Haute): the create above already bumped
        # estimate.revision.
        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [node.uid],
                "target_parent_uid": other_task_id,
                "position": 1,
                "expected_revision": _estimate_revision(estimate_id),
            },
            headers=headers,
        )
        assert response.status_code == 404
        assert other_project_id != project_id


def test_move_rejects_node_under_itself_or_its_descendant() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, _, _ = _seed_project_with_two_tasks(_current_user_id(client, headers))
        estimate_id = _create_draft_estimate(client, headers, project_id)
        category_id = _create_cost_category()

        parent_line = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        parent_node = _node_for_cost_line(cast(int, parent_line["id"]))

        # Issue #289 review (Finding Haute): the create above already bumped
        # estimate.revision, so every expected_revision below is fetched fresh
        # rather than hardcoded, to genuinely exercise each invariant instead of
        # tripping an unrelated stale-revision 409.
        under_itself = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [parent_node.uid],
                "target_parent_uid": parent_node.uid,
                "position": 1,
                "expected_revision": _estimate_revision(estimate_id),
            },
            headers=headers,
        )
        assert under_itself.status_code == 409

        child_line = _create_cost_line(client, headers, project_id, estimate_id, category_id)
        child_node = _node_for_cost_line(cast(int, child_line["id"]))

        # First make child_node a real child of parent_node...
        first_move = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [child_node.uid],
                "target_parent_uid": parent_node.uid,
                "position": 1,
                "expected_revision": _estimate_revision(estimate_id),
            },
            headers=headers,
        )
        assert first_move.status_code == 200

        # ...then attempt to move the parent under its own now-descendant.
        under_descendant = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [parent_node.uid],
                "target_parent_uid": child_node.uid,
                "position": 1,
                "expected_revision": _estimate_revision(estimate_id),
            },
            headers=headers,
        )
        assert under_descendant.status_code == 409


def test_two_root_role_assignments_with_same_role_do_not_conflict() -> None:
    """Finding Moyenne (#289 review): `uq_wf_estimate_role_assignment` is on
    (estimate_id, task_id, role_id) and task_id is nullable -- two root-level
    assignments (task_id IS NULL, unindented all the way to the devis root)
    with the same role_id do NOT collide, because SQL unique constraints treat
    every NULL as distinct from any other NULL. This is accepted, intentional
    product behaviour (a root assignment behaves like a free-floating
    EstimateCostLine, which has never had a uniqueness constraint either), so
    this test locks it in rather than guarding against a regression."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, task_a_id, task_b_id = _seed_project_with_two_tasks(
            _current_user_id(client, headers)
        )
        estimate_id = _create_draft_estimate(client, headers, project_id)
        role_id = _seed_labor_role()

        # Attached to two different tasks so the constraint doesn't already
        # reject them at creation time.
        first = _create_role_assignment(
            client, headers, project_id, estimate_id, task_a_id, role_id
        )
        second = _create_role_assignment(
            client, headers, project_id, estimate_id, task_b_id, role_id
        )
        first_node = _node_for_assignment(cast(int, first["id"]))
        second_node = _node_for_assignment(cast(int, second["id"]))

        # Unindent both to the devis root in one move: task_id is recalculated
        # to NULL for both, so both now share (estimate_id, NULL, role_id).
        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/grid-nodes/move",
            json={
                "node_uids": [first_node.uid, second_node.uid],
                "target_parent_uid": None,
                "position": 1,
                "expected_revision": _estimate_revision(estimate_id),
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

        assert _assignment_task_id(cast(int, first["id"])) is None
        assert _assignment_task_id(cast(int, second["id"])) is None
