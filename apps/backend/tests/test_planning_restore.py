"""E4-01 (#18 PR 3/3): full-snapshot restore driving frontend undo/redo.

``PUT .../plannings/{planningId}/tasks/restore`` replaces every task and link
of a draft planning with an exact prior snapshot (verbatim values, no
recalculation), so undo/redo can restore precisely what a previous response
already contained, including a whole cascade-deleted subtree.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"planning.restore.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Planning restore"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _tasks_by_uid(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {task["uid"]: task for task in cast(list[dict[str, Any]], payload["tasks"])}


def _links(payload: dict[str, Any]) -> list[tuple[int, int, int]]:
    return [
        (link["task_uid"], link["predecessor_uid"], link["link_type"])
        for link in cast(list[dict[str, Any]], payload["links"])
    ]


def _seed_planning(project_id: int) -> int:
    """Group A(1, summary) -> Leaf A(2), Leaf B(3); Root leaf(4); link 3->2 (FS)."""
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
                    name="Root leaf",
                    position=2,
                    is_summary=False,
                    is_milestone=False,
                ),
            ]
        )
        session.flush()
        session.add(
            WfPlanningLinkSnapshot(
                planning_id=planning.id, task_uid=3, predecessor_uid=2, link_type=1
            )
        )
        session.commit()
        return planning.id


def _restore_path(project_id: int, planning_id: int) -> str:
    return f"/projects/{project_id}/plannings/{planning_id}/tasks/restore"


def test_restore_recreates_a_cascade_deleted_subtree_exactly() -> None:
    """The core use case: undo of a cascade delete."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        before = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert before.status_code == 200
        before_payload = cast(dict[str, Any], before.json())
        before_tasks = _tasks_by_uid(before_payload)
        before_links = _links(before_payload)

        deleted = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [1], "confirm_cascade": True, "expected_revision": 0},
            headers=headers,
        )
        assert deleted.status_code == 200
        deleted_payload = cast(dict[str, Any], deleted.json())
        assert 1 not in _tasks_by_uid(deleted_payload)
        assert 2 not in _tasks_by_uid(deleted_payload)

        restored = client.put(
            _restore_path(project_id, planning_id),
            json={
                "tasks": [
                    {
                        "uid": task["uid"],
                        "id_display": task["id_display"],
                        "structure_key": task["structure_key"],
                        "structure_kind": task["structure_kind"],
                        "parent_uid": task["parent_uid"],
                        "position": task["position"],
                        "name": task["name"],
                        "outline_number": task["outline_number"],
                        "outline_level": task["outline_level"],
                        "wbs": task["wbs"],
                        "start_at": task["start_at"],
                        "finish_at": task["finish_at"],
                        "duration_minutes": task["duration_minutes"],
                        "duration_format": task["duration_format"],
                        "work_minutes": task["work_minutes"],
                        "percent_complete": task["percent_complete"],
                        "is_summary": task["is_summary"],
                        "is_milestone": task["is_milestone"],
                        "is_manual": task["is_manual"],
                        "calendar_uid": task["calendar_uid"],
                        "notes": task["description"],
                    }
                    for task in before_tasks.values()
                ],
                "links": [
                    {
                        "task_uid": task_uid,
                        "predecessor_uid": predecessor_uid,
                        "link_type": link_type,
                    }
                    for task_uid, predecessor_uid, link_type in before_links
                ],
                "expected_revision": 1,
            },
            headers=headers,
        )

        assert restored.status_code == 200
        restored_payload = cast(dict[str, Any], restored.json())
        assert restored_payload["revision"] == 2
        assert _tasks_by_uid(restored_payload).keys() == before_tasks.keys()
        for uid, task in before_tasks.items():
            restored_task = _tasks_by_uid(restored_payload)[uid]
            for field in ("name", "parent_uid", "position", "outline_number", "is_summary"):
                assert restored_task[field] == task[field], field
        assert sorted(_links(restored_payload)) == sorted(before_links)


def test_restore_rejects_stale_revision_without_mutating() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.put(
            _restore_path(project_id, planning_id),
            json={"tasks": [], "links": [], "expected_revision": 5},
            headers=headers,
        )

        assert response.status_code == 409
        assert cast(dict[str, Any], response.json())["detail"] == {
            "code": "PLANNING_REVISION_CONFLICT",
            "project_id": project_id,
            "planning_id": planning_id,
            "expected_revision": 5,
            "current_revision": 0,
        }
        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert detail.json()["revision"] == 0
        assert 1 in _tasks_by_uid(cast(dict[str, Any], detail.json()))


def test_restore_rejects_duplicate_uid_without_mutating() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.put(
            _restore_path(project_id, planning_id),
            json={
                "tasks": [
                    {"uid": 10, "name": "A"},
                    {"uid": 10, "name": "B"},
                ],
                "links": [],
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert response.status_code == 400
        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert detail.json()["revision"] == 0
        assert 10 not in _tasks_by_uid(cast(dict[str, Any], detail.json()))


def test_restore_rejects_cycle_without_mutating() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.put(
            _restore_path(project_id, planning_id),
            json={
                "tasks": [
                    {"uid": 10, "name": "A", "parent_uid": 11},
                    {"uid": 11, "name": "B", "parent_uid": 10},
                ],
                "links": [],
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert response.status_code == 409
        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert detail.json()["revision"] == 0
        assert 10 not in _tasks_by_uid(cast(dict[str, Any], detail.json()))


def test_restore_rejects_link_referencing_unknown_task() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.put(
            _restore_path(project_id, planning_id),
            json={
                "tasks": [{"uid": 10, "name": "A"}],
                "links": [{"task_uid": 10, "predecessor_uid": 999, "link_type": 1}],
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert response.status_code == 400
        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert detail.json()["revision"] == 0


def test_restore_rejects_milestone_with_children() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        response = client.put(
            _restore_path(project_id, planning_id),
            json={
                "tasks": [
                    {"uid": 10, "name": "Milestone", "is_milestone": True},
                    {"uid": 11, "name": "Child", "parent_uid": 10},
                ],
                "links": [],
                "expected_revision": 0,
            },
            headers=headers,
        )

        assert response.status_code == 409
        detail = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        assert detail.json()["revision"] == 0


def test_restore_rejects_non_draft_planning_and_read_only_project() -> None:
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

        response = client.put(
            _restore_path(project_id, planning_id),
            json={"tasks": [], "links": [], "expected_revision": 0},
            headers=headers,
        )

        assert response.status_code == 409


def test_redo_reapplies_a_move_after_undo() -> None:
    """A full undo(before-snapshot)/redo(after-snapshot) round trip via restore."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning(project_id)

        before = client.get(f"/projects/{project_id}/plannings/{planning_id}", headers=headers)
        before_payload = cast(dict[str, Any], before.json())

        moved = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={
                "task_uids": [4],
                "target_parent_uid": None,
                "position": 1,
                "expected_revision": 0,
            },
            headers=headers,
        )
        assert moved.status_code == 200
        after_payload = cast(dict[str, Any], moved.json())
        assert after_payload["revision"] == 1

        def _restore_payload(payload: dict[str, Any], expected_revision: int) -> dict[str, Any]:
            return {
                "tasks": [
                    {
                        "uid": task["uid"],
                        "name": task["name"],
                        "parent_uid": task["parent_uid"],
                        "position": task["position"],
                        "outline_number": task["outline_number"],
                        "outline_level": task["outline_level"],
                        "is_summary": task["is_summary"],
                        "is_milestone": task["is_milestone"],
                    }
                    for task in _tasks_by_uid(payload).values()
                ],
                "links": [
                    {"task_uid": t, "predecessor_uid": p, "link_type": lt}
                    for t, p, lt in _links(payload)
                ],
                "expected_revision": expected_revision,
            }

        undone = client.put(
            _restore_path(project_id, planning_id),
            json=_restore_payload(before_payload, 1),
            headers=headers,
        )
        assert undone.status_code == 200
        undone_payload = cast(dict[str, Any], undone.json())
        assert _tasks_by_uid(undone_payload)[4]["parent_uid"] is None
        assert _tasks_by_uid(undone_payload)[4]["position"] == 2

        redone = client.put(
            _restore_path(project_id, planning_id),
            json=_restore_payload(after_payload, 2),
            headers=headers,
        )
        assert redone.status_code == 200
        assert _tasks_by_uid(cast(dict[str, Any], redone.json()))[4]["position"] == 1
