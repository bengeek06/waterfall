from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"planning.tree.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _seed_plannings(project_id: int) -> tuple[int, int]:
    with get_session_factory()() as session:
        first = WfPlanning(project_id=project_id, version_number=1, status="draft")
        second = WfPlanning(project_id=project_id, version_number=2, status="draft")
        session.add_all([first, second])
        session.flush()
        for planning in (first, second):
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
                        start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 7, 8, 0, tzinfo=UTC),
                        duration_minutes=2880,
                        is_summary=False,
                        is_milestone=False,
                    ),
                    WfPlanningTaskSnapshot(
                        planning_id=planning.id,
                        uid=3,
                        name="Leaf B",
                        parent_uid=1,
                        position=2,
                        start_at=datetime(2026, 1, 8, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                        duration_minutes=2880,
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
        return first.id, second.id


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Tree mutations"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _tasks_by_uid(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {task["uid"]: task for task in cast(list[dict[str, Any]], payload["tasks"])}


def test_move_leaf_targets_explicit_planning_and_recalculates_tree() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        first_planning_id, second_planning_id = _seed_plannings(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{second_planning_id}/tasks/move",
            json={"task_uids": [3], "target_parent_uid": 4, "position": 1},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        assert tasks[3]["parent_uid"] == 4
        assert tasks[3]["outline_number"] == "2.1"
        assert tasks[5]["outline_number"] == "2.2"
        first = client.get(f"/projects/{project_id}/plannings/{first_planning_id}", headers=headers)
        assert _tasks_by_uid(cast(dict[str, Any], first.json()))[3]["parent_uid"] == 1


def test_move_group_normalizes_selected_descendant_and_preserves_subtree_order() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={"task_uids": [1, 2], "target_parent_uid": None, "position": 2},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = cast(list[dict[str, Any]], response.json()["tasks"])
        assert [task["uid"] for task in tasks] == [4, 5, 1, 2, 3, 6]
        by_uid = {task["uid"]: task for task in tasks}
        assert by_uid[2]["parent_uid"] == 1
        assert by_uid[2]["outline_number"] == "2.1"
        assert by_uid[3]["outline_number"] == "2.2"


def test_move_multiple_roots_preserves_current_depth_first_order() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={"task_uids": [3, 5], "target_parent_uid": None, "position": 2},
            headers=headers,
        )

        assert response.status_code == 200
        assert [task["uid"] for task in response.json()["tasks"]] == [1, 2, 3, 5, 4, 6]


def test_move_task_to_root() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={"task_uids": [3], "target_parent_uid": None, "position": 1},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        assert tasks[3]["parent_uid"] is None
        assert tasks[3]["outline_number"] == "1"
        assert tasks[1]["outline_number"] == "2"


def test_invalid_move_rolls_back_tree() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
        path = f"/projects/{project_id}/plannings/{planning_id}/tasks/move"

        cycle = client.post(
            path, json={"task_uids": [1], "target_parent_uid": 2, "position": 1}, headers=headers
        )
        missing = client.post(
            path, json={"task_uids": [3], "target_parent_uid": 999, "position": 1}, headers=headers
        )
        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)

        assert cycle.status_code == 409
        cycle_payload = cast(dict[str, Any], cycle.json())
        assert set(cycle_payload) == {"detail"}
        assert isinstance(cycle_payload["detail"], str)
        assert missing.status_code == 404
        missing_payload = cast(dict[str, Any], missing.json())
        assert set(missing_payload) == {"detail"}
        assert isinstance(missing_payload["detail"], str)
        assert _tasks_by_uid(cast(dict[str, Any], detail.json()))[3]["parent_uid"] == 1


def test_move_schema_validation_returns_bad_request() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
        path = f"/projects/{project_id}/plannings/{planning_id}/tasks/move"

        for payload in (
            {"task_uids": [], "target_parent_uid": None, "position": 1},
            {"task_uids": [0], "target_parent_uid": None, "position": 1},
            {"task_uids": [-1], "target_parent_uid": None, "position": 1},
            {"task_uids": [2], "target_parent_uid": 0, "position": 1},
            {"task_uids": [2], "target_parent_uid": None, "position": 0},
        ):
            response = client.post(path, json=payload, headers=headers)
            assert response.status_code == 400
            error_payload = cast(dict[str, Any], response.json())
            assert set(error_payload) == {"detail"}
            assert isinstance(error_payload["detail"], list)


def test_move_recalculates_summary_invariants() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
        path = f"/projects/{project_id}/plannings/{planning_id}/tasks/move"

        promoted = client.post(
            path,
            json={"task_uids": [2], "target_parent_uid": 6, "position": 1},
            headers=headers,
        )

        assert promoted.status_code == 200
        promoted_tasks = _tasks_by_uid(cast(dict[str, Any], promoted.json()))
        assert promoted_tasks[6]["is_summary"] is True
        assert promoted_tasks[6]["start_at"] == "2026-01-05T08:00:00"
        assert promoted_tasks[6]["finish_at"] == "2026-01-07T08:00:00"

        demoted = client.post(
            path,
            json={"task_uids": [3], "target_parent_uid": 4, "position": 2},
            headers=headers,
        )

        assert demoted.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], demoted.json()))
        assert tasks[1]["is_summary"] is False
        assert tasks[1]["start_at"] is None
        assert tasks[1]["finish_at"] is None
        assert tasks[4]["is_summary"] is True
        assert tasks[4]["start_at"] == "2026-01-08T08:00:00"
        assert tasks[4]["finish_at"] == "2026-01-10T08:00:00"
        with get_session_factory()() as session:
            snapshots = {
                task.uid: task
                for task in session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .all()
            }
        assert snapshots[1].duration_minutes is None
        assert snapshots[4].duration_minutes == 2880
        assert snapshots[6].duration_minutes == 2880


def test_move_rejects_milestone_as_target_parent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
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
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={"task_uids": [2], "target_parent_uid": 6, "position": 1},
            headers=headers,
        )

        assert response.status_code == 409


def test_move_rejects_validated_planning_and_read_only_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        first_planning_id, second_planning_id = _seed_plannings(project_id)
        move = {"task_uids": [3], "target_parent_uid": None, "position": 1}
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{first_planning_id}/validate", headers=headers
            ).status_code
            == 200
        )

        validated = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/tasks/move",
            json=move,
            headers=headers,
        )
        assert validated.status_code == 409
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "termine"
            session.commit()
        read_only = client.post(
            f"/projects/{project_id}/plannings/{second_planning_id}/tasks/move",
            json=move,
            headers=headers,
        )
        assert read_only.status_code == 409
