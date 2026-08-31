"""E3-05: create/delete tasks in a draft planning tree.

Covers the versioned ``POST .../plannings/{planningId}/tasks`` (create) and
``POST .../plannings/{planningId}/tasks/delete`` (delete) contract that
replaces the legacy ``POST``/``DELETE /projects/{projectId}/tasks[/{taskUid}]``
endpoints (see the acceptance-test checklist copied into each test's
docstring below).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

from waterfall.db.session import get_engine, get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostType,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.models.wf_core import WfChargeLine


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"planning.task.crud.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Task create/delete"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _tasks_by_uid(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {task["uid"]: task for task in cast(list[dict[str, Any]], payload["tasks"])}


def _seed_planning(project_id: int) -> int:
    """Seed a single draft planning: Group A(1) -> Leaf A(2), Leaf B(3);
    Group B(4) -> Leaf C(5); Root leaf(6).
    """
    with get_session_factory()() as session:
        planning = WfPlanning(project_id=project_id, version_number=1, status="draft")
        session.add(planning)
        session.flush()
        session.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=1,
                    name="Group A",
                    position=1,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=2,
                    name="Leaf A",
                    parent_uid=1,
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=3,
                    name="Leaf B",
                    parent_uid=1,
                    position=2,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=4,
                    name="Group B",
                    position=2,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=5,
                    name="Leaf C",
                    parent_uid=4,
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=6,
                    name="Root leaf",
                    position=3,
                    is_summary=False,
                    is_milestone=False,
                ),
            ]
        )
        session.commit()
        return planning.id


def _bridge_legacy_task(project_id: int, uid: int) -> int:
    """Insert a legacy MsTask row bridging a snapshot uid, as generate_planning_snapshot
    would if the planning had been created from legacy tasks. Estimate/assignment
    references key off ms_task.id, not the snapshot -- see is_task_referenced.
    """
    with get_session_factory()() as session:
        task = MsTask(project_id=project_id, uid=uid, name=f"Legacy bridge {uid}")
        session.add(task)
        session.commit()
        return task.id


# ---------------------------------------------------------------------------
# Create: explicit position (root, first child, after a given task)
# ---------------------------------------------------------------------------


def test_create_task_with_no_position_becomes_first_root() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "New root"},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        new_uid = next(uid for uid, task in tasks.items() if task["name"] == "New root")
        assert tasks[new_uid]["parent_uid"] is None
        assert tasks[new_uid]["outline_number"] == "1"
        assert tasks[1]["outline_number"] == "2"
        assert tasks[4]["outline_number"] == "3"
        assert tasks[6]["outline_number"] == "4"


def test_create_task_as_first_child_of_parent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "New leaf", "target_parent_uid": 1},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        new_uid = next(uid for uid, task in tasks.items() if task["name"] == "New leaf")
        assert tasks[new_uid]["parent_uid"] == 1
        assert tasks[new_uid]["outline_number"] == "1.1"
        assert tasks[2]["outline_number"] == "1.2"
        assert tasks[3]["outline_number"] == "1.3"


def test_create_task_after_given_sibling() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "New leaf", "target_parent_uid": 1, "insert_after_uid": 2},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        new_uid = next(uid for uid, task in tasks.items() if task["name"] == "New leaf")
        assert tasks[new_uid]["parent_uid"] == 1
        assert tasks[2]["outline_number"] == "1.1"
        assert tasks[new_uid]["outline_number"] == "1.2"
        assert tasks[3]["outline_number"] == "1.3"


def test_create_task_root_appended_after_given_sibling() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "New root", "insert_after_uid": 6},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        new_uid = next(uid for uid, task in tasks.items() if task["name"] == "New root")
        assert tasks[new_uid]["parent_uid"] is None
        assert tasks[6]["outline_number"] == "3"
        assert tasks[new_uid]["outline_number"] == "4"


def test_create_task_rejects_missing_target_parent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Orphan", "target_parent_uid": 999},
            headers=headers,
        )

        assert response.status_code == 404


def test_create_task_rejects_milestone_as_target_parent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        with get_session_factory()() as session:
            milestone = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 6)
                .one()
            )
            milestone.is_milestone = True
            session.commit()

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Under milestone", "target_parent_uid": 6},
            headers=headers,
        )

        assert response.status_code == 409


def test_create_task_rejects_insert_after_uid_not_a_sibling() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        # uid=5 (Leaf C, a child of Group B) is not a sibling of Group A's children.
        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Misplaced", "target_parent_uid": 1, "insert_after_uid": 5},
            headers=headers,
        )

        assert response.status_code == 400


def test_create_task_schema_validation_returns_bad_request() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        path = f"/projects/{project_id}/plannings/{planning_id}/tasks"

        for payload in (
            {"name": ""},
            {},
            {"name": "New leaf", "target_parent_uid": 0},
            {"name": "New leaf", "insert_after_uid": 0},
        ):
            response = client.post(path, json=payload, headers=headers)
            assert response.status_code == 400
            error_payload = cast(dict[str, Any], response.json())
            assert set(error_payload) == {"detail"}
            assert isinstance(error_payload["detail"], list)


def test_create_task_rejects_unknown_insert_after_uid() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Misplaced", "insert_after_uid": 999},
            headers=headers,
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete: simple selection, cascade confirmation, normalized selection
# ---------------------------------------------------------------------------


def test_delete_selection_without_children_renumbers_tree() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [6]},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        assert 6 not in tasks
        assert tasks[1]["outline_number"] == "1"
        assert tasks[4]["outline_number"] == "2"


def test_delete_task_with_children_without_confirm_cascade_is_refused_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [1]},
            headers=headers,
        )

        assert response.status_code == 409
        detail = cast(dict[str, Any], response.json())["detail"]
        assert detail["code"] == "CASCADE_CONFIRMATION_REQUIRED"
        assert sorted(detail["descendant_uids"]) == [2, 3]

        with get_session_factory()() as session:
            remaining_uids = {
                task.uid
                for task in session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .all()
            }
        assert remaining_uids == {1, 2, 3, 4, 5, 6}


def test_delete_task_with_children_confirm_cascade_deletes_subtree_and_renumbers() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [1], "confirm_cascade": True},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        assert {1, 2, 3}.isdisjoint(tasks)
        assert tasks[4]["outline_number"] == "1"
        assert tasks[4]["parent_uid"] is None
        assert tasks[6]["outline_number"] == "2"


def test_delete_selection_mixing_parent_and_descendant_normalizes_to_parent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [1, 2], "confirm_cascade": True},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        assert {1, 2, 3}.isdisjoint(tasks)
        assert set(tasks) == {4, 5, 6}


def test_delete_task_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [999]},
            headers=headers,
        )

        assert response.status_code == 404


def test_delete_task_schema_validation_returns_bad_request() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        path = f"/projects/{project_id}/plannings/{planning_id}/tasks/delete"

        for payload in (
            {"task_uids": []},
            {"task_uids": [0]},
        ):
            response = client.post(path, json=payload, headers=headers)
            assert response.status_code == 400
            error_payload = cast(dict[str, Any], response.json())
            assert set(error_payload) == {"detail"}
            assert isinstance(error_payload["detail"], list)


# ---------------------------------------------------------------------------
# Delete: task referenced by an estimate, an assignment, or a charge
# ---------------------------------------------------------------------------


def test_delete_task_referenced_by_charge_line_conflicts_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        _bridge_legacy_task(project_id, 6)
        with get_session_factory()() as session:
            session.add(WfChargeLine(project_id=project_id, task_uid=6, load_minutes=120))
            session.commit()

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [6]},
            headers=headers,
        )

        assert response.status_code == 409
        detail = cast(dict[str, Any], response.json())["detail"]
        assert detail["code"] == "TASK_REFERENCED"
        assert detail["task_uids"] == [6]

        with get_session_factory()() as session:
            remaining_uids = {
                task.uid
                for task in session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .all()
            }
        assert 6 in remaining_uids


def test_delete_task_referenced_by_role_assignment_in_cascade_conflicts_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        legacy_task_id = _bridge_legacy_task(project_id, 5)

        with get_session_factory()() as session:
            cost_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
            session.add(cost_type)
            session.flush()
            category = CostCategory(
                cost_type_id=cost_type.id,
                accounting_code=f"DEV-{uuid4().hex[:8]}",
                name="Developpement",
            )
            node = ResourceNode(code=f"IT-{uuid4().hex[:8]}", name="Informatique")
            session.add_all([category, node])
            session.flush()
            role = ResourceRole(
                node_id=node.id,
                cost_category_id=category.id,
                name="Developpeur",
            )
            session.add(role)
            session.flush()
            session.add(
                TaskRoleAssignment(
                    task_id=legacy_task_id,
                    role_id=role.id,
                    quantity=Decimal("1.00"),
                    hours=Decimal("10.00"),
                )
            )
            session.commit()

        # uid=4 (Group B) is the parent of uid=5 (Leaf C, referenced above); a
        # cascade delete of the whole subtree must be refused, not just the
        # leaf, and nothing may be partially deleted.
        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [4], "confirm_cascade": True},
            headers=headers,
        )

        assert response.status_code == 409
        detail = cast(dict[str, Any], response.json())["detail"]
        assert detail["code"] == "TASK_REFERENCED"
        assert detail["task_uids"] == [5]

        with get_session_factory()() as session:
            remaining_uids = {
                task.uid
                for task in session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .all()
            }
        assert remaining_uids == {1, 2, 3, 4, 5, 6}


# ---------------------------------------------------------------------------
# Large cascade: reference checks must be batched, not one query set per task
# ---------------------------------------------------------------------------


def test_delete_large_cascade_batches_reference_checks_instead_of_per_task_queries() -> None:
    """delete_planning_tasks must not turn a large cascade into an N+1 sequence.

    Before find_referenced_task_uids batched the reference lookups, deleting a
    cascade of N tasks ran is_task_referenced once per task uid (up to 5
    SELECTs each) while the route already holds a row lock on
    ms_project/wf_planning -- for a 60-task subtree that alone would be up to
    ~300 sequential queries blocking every other writer on the project.
    Asserting the whole request's statement count stays a small, roughly
    constant number (independent of the 60-task selection size) catches a
    regression back to the per-task loop.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        leaf_count = 60
        with get_session_factory()() as session:
            planning = WfPlanning(project_id=project_id, version_number=1, status="draft")
            session.add(planning)
            session.flush()
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=1,
                    name="Root",
                    position=1,
                    is_summary=True,
                    is_milestone=False,
                )
            )
            session.add_all(
                [
                    WfPlanningTaskSnapshot(
                        planning_id=planning.id,
                        uid=uid,
                        name=f"Leaf {uid}",
                        parent_uid=1,
                        position=uid - 1,
                        is_summary=False,
                        is_milestone=False,
                    )
                    for uid in range(2, leaf_count + 2)
                ]
            )
            session.commit()
            planning_id = planning.id

        engine = get_engine()
        statement_count = 0

        def _count_statement(*_args: object, **_kwargs: object) -> None:
            nonlocal statement_count
            statement_count += 1

        event.listen(engine, "before_cursor_execute", _count_statement)
        try:
            response = client.post(
                f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
                json={"task_uids": [1], "confirm_cascade": True},
                headers=headers,
            )
        finally:
            event.remove(engine, "before_cursor_execute", _count_statement)

    assert response.status_code == 200
    tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
    assert not tasks

    # A per-task loop would have run on the order of 60 * 5 = 300+ reference
    # queries alone; the batched version issues a small, fixed number of
    # IN (...) queries regardless of the selection size, plus the handful of
    # queries the rest of the request (auth, locks, tree load/renumber,
    # response read) always needs.
    assert statement_count < 50


# ---------------------------------------------------------------------------
# uid uniqueness spans every version of the project, not just the current draft
# ---------------------------------------------------------------------------


def test_create_task_after_delete_does_not_collide_with_uid_alive_in_another_version() -> None:
    """A recreated uid must stay unique across every version of the project.

    ``uid`` is a stable identity reused across planning versions (see
    ``task_references.py``): deleting the highest-uid task from the current
    draft and immediately creating a new one must not reuse a uid that is
    still alive in another version of the same project, even though that
    version isn't the one being mutated here.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        # A second, already-validated version of the same project still has a
        # live task at uid=6, the highest uid in the seeded draft.
        with get_session_factory()() as session:
            other_planning = WfPlanning(project_id=project_id, version_number=2, status="validated")
            session.add(other_planning)
            session.flush()
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=other_planning.id,
                    uid=6,
                    name="Root leaf (validated copy)",
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                )
            )
            session.commit()

        deleted = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [6]},
            headers=headers,
        )
        assert deleted.status_code == 200

        created = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "New root"},
            headers=headers,
        )
        assert created.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], created.json()))
        new_uid = next(uid for uid, task in tasks.items() if task["name"] == "New root")
        assert new_uid != 6


# ---------------------------------------------------------------------------
# Renumbering after delete then create (inverse of the legacy gap-preserving behaviour)
# ---------------------------------------------------------------------------


def test_delete_then_create_fully_renumbers_the_tree_without_gaps() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        # Delete the middle child of Group A (uid=3, "Leaf B" is a sibling of
        # uid=2 under uid=1) -- unlike the legacy endpoint, which preserved
        # numbering gaps, this must renumber the remaining sibling(s).
        deleted = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [3]},
            headers=headers,
        )
        assert deleted.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], deleted.json()))
        assert tasks[2]["outline_number"] == "1.1"

        recreated = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Leaf D", "target_parent_uid": 1},
            headers=headers,
        )
        assert recreated.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], recreated.json()))
        new_uid = next(uid for uid, task in tasks.items() if task["name"] == "Leaf D")

        with get_session_factory()() as session:
            children = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.parent_uid == 1)
                .all()
            )
        outline_numbers = sorted(cast(str, child.outline_number) for child in children)
        positions = sorted(cast(int, child.position) for child in children)
        assert outline_numbers == ["1.1", "1.2"]
        assert positions == [1, 2]
        assert new_uid in {child.uid for child in children}


# ---------------------------------------------------------------------------
# Guardrails: validated planning / read-only project reject without mutation
# ---------------------------------------------------------------------------


def test_create_and_delete_reject_validated_planning_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
            ).status_code
            == 200
        )

        create = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Refused"},
            headers=headers,
        )
        delete = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [6]},
            headers=headers,
        )

        assert create.status_code == 409
        assert delete.status_code == 409
        with get_session_factory()() as session:
            remaining = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .count()
            )
        assert remaining == 6


def test_create_and_delete_reject_read_only_project_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "termine"
            session.commit()

        create = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Refused"},
            headers=headers,
        )
        delete = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [6]},
            headers=headers,
        )

        assert create.status_code == 409
        assert delete.status_code == 409


# ---------------------------------------------------------------------------
# The legacy generic-project task endpoints no longer exist
# ---------------------------------------------------------------------------


def test_legacy_project_task_create_and_delete_endpoints_are_gone() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/display", headers=headers
            ).status_code
            == 200
        )

        create = client.post(
            f"/projects/{project_id}/tasks", json={"name": "Should not work"}, headers=headers
        )
        delete = client.delete(f"/projects/{project_id}/tasks/1", headers=headers)

        assert create.status_code == 405
        assert delete.status_code == 405

        # GET (list) and PATCH (description) on the same path prefix are unaffected.
        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        patched = client.patch(
            f"/projects/{project_id}/tasks/1",
            json={"description": "Still works"},
            headers=headers,
        )
        assert patched.status_code == 200
