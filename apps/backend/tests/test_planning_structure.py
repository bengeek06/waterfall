from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from waterfall.api.routes import planning_support, plannings, tasks
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"planning.structure.{uuid4().hex}@example.com"
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
    return {"Authorization": f"Bearer {token_response.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Structured project"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _payload() -> dict[str, Any]:
    return {
        "posts": [
            {
                "key": "design",
                "name": "Design",
                "lots": [
                    {
                        "key": "specification",
                        "name": "Specification",
                        "deliverables": [
                            {"key": "requirements", "name": "Requirements"},
                            {"key": "architecture", "name": "Architecture"},
                        ],
                    },
                    {
                        "key": "validation",
                        "name": "Validation",
                        "deliverables": [{"key": "review", "name": "Review"}],
                    },
                ],
            }
        ]
    }


def test_save_planning_structure_draft_is_non_operational_and_generates_later() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        draft_path = f"/projects/{project_id}/planning-structure/draft"

        first = client.put(draft_path, json=_payload(), headers=headers)
        second = client.put(draft_path, json=_payload(), headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["planning_id"] == second.json()["planning_id"]
        assert client.get(f"/projects/{project_id}", headers=headers).json()["status"] == "cree"
        assert client.get(f"/projects/{project_id}/tasks", headers=headers).json() == []
        plannings = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        planning_items = cast(list[dict[str, Any]], plannings.json())
        assert len(planning_items) == 1
        assert planning_items[0]["status"] == "draft"

        generated = client.post(f"/projects/{project_id}/planning-structure", headers=headers)

        assert generated.status_code == 201
        generated_tasks = cast(list[dict[str, Any]], generated.json()["tasks"])
        assert len(generated_tasks) == 8
        project = client.get(f"/projects/{project_id}", headers=headers).json()
        assert project["status"] == "initialise"
        assert project["displayed_planning_id"] == first.json()["planning_id"]


def test_direct_planning_structure_writers_use_project_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    latest_draft_calls: list[int] = []
    displayed_planning_calls: list[int] = []
    original_lock = planning_support.get_mutable_project_lock
    original_latest_draft = plannings.get_mutable_project_with_latest_draft_lock
    original_displayed_planning = tasks.get_mutable_project_with_displayed_planning_lock

    def locked_project(db: Any, project_id: int, owner_id: int) -> MsProject:
        calls.append(project_id)
        return original_lock(db, project_id, owner_id)

    def locked_latest_draft(
        db: Any, project_id: int, owner_id: int, **kwargs: Any
    ) -> tuple[MsProject, Any]:
        latest_draft_calls.append(project_id)
        return original_latest_draft(db, project_id, owner_id, **kwargs)

    def locked_displayed_planning(db: Any, project_id: int, owner_id: int) -> tuple[MsProject, Any]:
        displayed_planning_calls.append(project_id)
        return original_displayed_planning(db, project_id, owner_id)

    monkeypatch.setattr(planning_support, "get_mutable_project_lock", locked_project)
    monkeypatch.setattr(
        plannings,
        "get_mutable_project_with_latest_draft_lock",
        locked_latest_draft,
    )
    monkeypatch.setattr(
        tasks,
        "get_mutable_project_with_displayed_planning_lock",
        locked_displayed_planning,
    )
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        draft_path = f"/projects/{project_id}/planning-structure/draft"

        saved = client.put(draft_path, json=_payload(), headers=headers)
        # Called while the project is still "cree" (before /planning-structure
        # flips it to "initialise") so it succeeds and reuses the draft just
        # saved above, exercising the same lock path as the other direct writers.
        skipped = client.post(f"/projects/{project_id}/planning-structure/skip", headers=headers)
        generated = client.post(f"/projects/{project_id}/planning-structure", headers=headers)
        updated = client.patch(
            f"/projects/{project_id}/tasks/{generated.json()['tasks'][0]['uid']}",
            json={"description": "Updated"},
            headers=headers,
        )
        reopened = client.post(f"/projects/{project_id}/planning-structure/reopen", headers=headers)

    assert saved.status_code == 200
    assert skipped.status_code == 200
    assert generated.status_code == 201
    assert updated.status_code == 200
    assert reopened.status_code == 200
    assert calls == [project_id] * 5
    assert latest_draft_calls == [project_id] * 4
    assert displayed_planning_calls == [project_id]


def test_save_planning_structure_draft_rejects_read_only_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "termine"
            session.commit()

        response = client.put(
            f"/projects/{project_id}/planning-structure/draft",
            json=_payload(),
            headers=headers,
        )

        assert response.status_code == 409


def test_skip_planning_structure_creates_empty_planning_and_initialises_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        response = client.post(f"/projects/{project_id}/planning-structure/skip", headers=headers)

        assert response.status_code == 200
        payload = cast(dict[str, Any], response.json())
        assert payload["status"] == "initialise"
        displayed_planning_id = payload["displayed_planning_id"]
        assert displayed_planning_id is not None

        plannings = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        planning_items = cast(list[dict[str, Any]], plannings.json())
        assert len(planning_items) == 1
        assert planning_items[0]["status"] == "draft"

        planning_detail = client.get(
            f"/projects/{project_id}/plannings/{displayed_planning_id}", headers=headers
        )
        assert planning_detail.status_code == 200
        assert planning_detail.json()["tasks"] == []


def test_skip_planning_structure_rejects_call_once_project_left_cree() -> None:
    """Skip is a "cree" -> "initialise" shortcut, not a repeatable reset.

    Calling it again once the project has left "cree" must be rejected
    instead of silently reusing/creating a draft planning, since that is
    exactly the path that could otherwise overwrite a validated reference
    (see the critical-bug regression test below).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure/skip"

        first = client.post(path, headers=headers)
        second = client.post(path, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 409
        assert (
            client.get(f"/projects/{project_id}", headers=headers).json()["displayed_planning_id"]
            == first.json()["displayed_planning_id"]
        )

        plannings = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        assert len(cast(list[dict[str, Any]], plannings.json())) == 1


def test_skip_planning_structure_does_not_overwrite_validated_reference() -> None:
    """Regression test for the critical bug reported during review of #130.

    Reproduction: generate the full skeleton, validate the planning, set it
    as the project reference, then call skip. Before the fix this returned
    200 and silently overwrote displayed_planning_id with a new empty draft
    even though project.status stayed "initialise". It must now be rejected
    with 409 and leave the project untouched.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        structure_path = f"/projects/{project_id}/planning-structure"

        generated = client.post(structure_path, json=_payload(), headers=headers)
        assert generated.status_code == 201
        assert len(cast(list[dict[str, Any]], generated.json()["tasks"])) == 8

        project_before = client.get(f"/projects/{project_id}", headers=headers).json()
        planning_id = project_before["displayed_planning_id"]
        assert planning_id is not None

        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/reference", headers=headers
            ).status_code
            == 200
        )

        project_referenced = client.get(f"/projects/{project_id}", headers=headers).json()
        assert project_referenced["planning_reference_id"] == planning_id
        assert project_referenced["displayed_planning_id"] == planning_id

        skip_response = client.post(
            f"/projects/{project_id}/planning-structure/skip", headers=headers
        )

        assert skip_response.status_code == 409

        project_after = client.get(f"/projects/{project_id}", headers=headers).json()
        assert project_after["planning_reference_id"] == planning_id
        assert project_after["displayed_planning_id"] == planning_id

        planning_detail = client.get(
            f"/projects/{project_id}/plannings/{planning_id}", headers=headers
        )
        assert planning_detail.status_code == 200
        assert len(cast(list[dict[str, Any]], planning_detail.json()["tasks"])) == 8


def test_skip_then_generate_structure_reuses_same_empty_planning() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        skip_response = client.post(
            f"/projects/{project_id}/planning-structure/skip", headers=headers
        )
        assert skip_response.status_code == 200
        skip_payload = cast(dict[str, Any], skip_response.json())
        assert skip_payload["status"] == "initialise"
        skip_planning_id = skip_payload["displayed_planning_id"]
        assert skip_planning_id is not None

        generated = client.post(
            f"/projects/{project_id}/planning-structure", json=_payload(), headers=headers
        )

        assert generated.status_code == 201
        generated_tasks = cast(list[dict[str, Any]], generated.json()["tasks"])
        assert len(generated_tasks) == 8

        project_after = client.get(f"/projects/{project_id}", headers=headers).json()
        assert project_after["displayed_planning_id"] == skip_planning_id

        plannings = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        assert len(cast(list[dict[str, Any]], plannings.json())) == 1


def test_skip_planning_structure_rejects_read_only_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "perdu"
            session.commit()

        response = client.post(f"/projects/{project_id}/planning-structure/skip", headers=headers)

        assert response.status_code == 409


def test_reopen_without_draft_or_reference_creates_empty_planning() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        response = client.post(f"/projects/{project_id}/planning-structure/reopen", headers=headers)

        assert response.status_code == 200
        payload = cast(dict[str, Any], response.json())
        assert payload["status"] == "initialise"
        displayed_planning_id = payload["displayed_planning_id"]
        assert displayed_planning_id is not None

        planning_detail = client.get(
            f"/projects/{project_id}/plannings/{displayed_planning_id}", headers=headers
        )
        assert planning_detail.status_code == 200
        assert planning_detail.json()["tasks"] == []


def test_create_planning_structure_generates_hierarchy_and_links() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        response = client.post(
            f"/projects/{project_id}/planning-structure",
            json=_payload(),
            headers=headers,
        )

        assert response.status_code == 201
        tasks = cast(list[dict[str, Any]], response.json()["tasks"])
        assert [task["structure_kind"] for task in tasks] == [
            "poste",
            "lot",
            "livrable",
            "livrable",
            "milestone",
            "lot",
            "livrable",
            "milestone",
        ]
        assert tasks[0]["outline_number"] == "1"
        assert tasks[1]["outline_number"] == "1.1"
        assert tasks[2]["parent_uid"] == tasks[1]["uid"]
        assert tasks[4]["is_milestone"] is True

        links_response = client.get(
            f"/projects/{project_id}/export.xml",
            headers=headers,
        )
        assert links_response.status_code == 200
        assert links_response.content.count(b"<PredecessorLink>") == 3

        tree_response = client.get(
            f"/projects/{project_id}/planning-tree",
            headers=headers,
        )
        assert tree_response.status_code == 200
        roots = cast(list[dict[str, Any]], tree_response.json()["tasks"])
        assert len(roots) == 1
        assert len(roots[0]["children"]) == 2
        assert len(roots[0]["children"][0]["children"]) == 3


def test_create_planning_structure_is_idempotent() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        second = client.post(path, json=_payload(), headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        first_tasks = cast(list[dict[str, Any]], first.json()["tasks"])
        second_tasks = cast(list[dict[str, Any]], second.json()["tasks"])
        assert [task["uid"] for task in second_tasks] == [task["uid"] for task in first_tasks]

        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        listed_tasks = cast(list[dict[str, Any]], listed.json())
        assert len(listed_tasks) == len(first_tasks)


def test_create_planning_structure_resynchronizes_names() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 201
        payload = _payload()
        payload["posts"][0]["lots"][0]["deliverables"][0]["name"] = "Updated requirements"

        second = client.post(path, json=payload, headers=headers)

        assert second.status_code == 201
        tasks = cast(list[dict[str, Any]], second.json()["tasks"])
        assert tasks[2]["name"] == "Updated requirements"


def test_create_planning_structure_reconciles_removed_lots() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 201
        payload = _payload()
        payload["posts"][0]["lots"] = payload["posts"][0]["lots"][:1]

        second = client.post(path, json=payload, headers=headers)

        assert second.status_code == 201
        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        tasks = cast(list[dict[str, Any]], listed.json())
        assert len(tasks) == 5
        assert all(task["structure_key"] != "design/validation" for task in tasks)


def test_create_planning_structure_rejects_duplicate_keys_without_mutation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        payload = _payload()
        payload["posts"][0]["lots"][1]["key"] = "specification"

        response = client.post(
            f"/projects/{project_id}/planning-structure",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 422
        listed = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert listed.status_code == 200
        assert listed.json() == []


def test_task_mutations_target_displayed_draft_snapshot() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        generated = client.post(
            f"/projects/{project_id}/planning-structure",
            json=_payload(),
            headers=headers,
        )
        assert generated.status_code == 201
        summary_uid = generated.json()["tasks"][0]["uid"]

        # create_planning_structure sets the generated draft as the project's
        # displayed planning; the E3-05 create/delete contract is scoped by
        # planning id, so it is resolved from there.
        planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]

        create = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Draft task", "expected_revision": 0},
            headers=headers,
        )
        assert create.status_code == 200
        create_payload = cast(dict[str, Any], create.json())
        new_uid = next(
            task["uid"]
            for task in cast(list[dict[str, Any]], create_payload["tasks"])
            if task["name"] == "Draft task"
        )

        # A summary task that still has children cannot be removed without
        # confirming the cascade.
        summary_delete = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [summary_uid], "expected_revision": 1},
            headers=headers,
        )
        assert summary_delete.status_code == 409
        assert summary_delete.json()["detail"]["code"] == "CASCADE_CONFIRMATION_REQUIRED"

        # A leaf task added to the displayed draft snapshot can be removed.
        leaf_delete = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [new_uid], "expected_revision": 1},
            headers=headers,
        )
        assert leaf_delete.status_code == 200
        remaining = client.get(f"/projects/{project_id}/tasks", headers=headers).json()
        assert new_uid not in [task["uid"] for task in remaining]


def test_reopen_and_regenerate_preserves_uids() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        assert client.post(path, json=_payload(), headers=headers).status_code == 201
        initial_tasks = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/tasks", headers=headers).json(),
        )
        uid_by_key = {task["structure_key"]: task["uid"] for task in initial_tasks}
        previous_max_uid = max(uid_by_key.values())

        reopened = client.post(f"/projects/{project_id}/planning-structure/reopen", headers=headers)
        assert reopened.status_code == 200

        extended = _payload()
        extended["posts"][0]["lots"][0]["deliverables"].append(
            {"key": "deployment", "name": "Deployment"}
        )
        assert client.post(path, json=extended, headers=headers).status_code == 201
        regenerated_tasks = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/tasks", headers=headers).json(),
        )
        regenerated_uid_by_key = {task["structure_key"]: task["uid"] for task in regenerated_tasks}

        for key, uid in uid_by_key.items():
            assert regenerated_uid_by_key[key] == uid

        new_key = "design/specification/deployment"
        assert regenerated_uid_by_key[new_key] > previous_max_uid


def test_regenerate_structure_preserves_manual_tasks() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        assert client.post(path, json=_payload(), headers=headers).status_code == 201
        structured_tasks = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/tasks", headers=headers).json(),
        )
        uid_by_key = {
            task["structure_key"]: task["uid"]
            for task in structured_tasks
            if task["structure_key"] is not None
        }

        planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]
        created = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Manual task", "expected_revision": 0},
            headers=headers,
        )
        assert created.status_code == 200
        created_payload = cast(dict[str, Any], created.json())
        manual_task = next(
            task
            for task in cast(list[dict[str, Any]], created_payload["tasks"])
            if task["name"] == "Manual task"
        )
        manual_uid = manual_task["uid"]
        assert manual_task["structure_key"] is None

        assert client.post(path, json=_payload(), headers=headers).status_code == 201

        regenerated = cast(
            list[dict[str, Any]],
            client.get(f"/projects/{project_id}/tasks", headers=headers).json(),
        )
        assert manual_uid in [task["uid"] for task in regenerated]
        regenerated_uid_by_key = {
            task["structure_key"]: task["uid"]
            for task in regenerated
            if task["structure_key"] is not None
        }
        for key, uid in uid_by_key.items():
            assert regenerated_uid_by_key[key] == uid


def test_regenerate_structure_preserves_nested_manual_task_hierarchy() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"
        tasks_url = f"/projects/{project_id}/tasks"

        assert client.post(path, json=_payload(), headers=headers).status_code == 201
        planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]

        parent_created = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={"name": "Manual parent", "expected_revision": 0},
            headers=headers,
        )
        assert parent_created.status_code == 200
        parent_payload = cast(dict[str, Any], parent_created.json())
        manual_parent = next(
            task
            for task in cast(list[dict[str, Any]], parent_payload["tasks"])
            if task["name"] == "Manual parent"
        )
        parent_uid = manual_parent["uid"]

        child_created = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={
                "name": "Manual child",
                "target_parent_uid": parent_uid,
                "expected_revision": parent_payload["revision"],
            },
            headers=headers,
        )
        assert child_created.status_code == 200
        child_payload = cast(dict[str, Any], child_created.json())
        manual_child = next(
            task
            for task in cast(list[dict[str, Any]], child_payload["tasks"])
            if task["name"] == "Manual child"
        )
        child_uid = manual_child["uid"]
        assert manual_child["parent_uid"] == parent_uid

        before_regeneration = cast(
            list[dict[str, Any]], client.get(tasks_url, headers=headers).json()
        )
        manual_child_before = next(task for task in before_regeneration if task["uid"] == child_uid)
        assert manual_child_before["parent_uid"] == parent_uid

        # Regenerate the skeleton over the same structure: this must not disturb the
        # nested manual hierarchy created above (Copilot review finding, issue #130).
        assert client.post(path, json=_payload(), headers=headers).status_code == 201

        after_regeneration = cast(
            list[dict[str, Any]], client.get(tasks_url, headers=headers).json()
        )
        manual_parent_after = next(task for task in after_regeneration if task["uid"] == parent_uid)
        manual_child_after = next(task for task in after_regeneration if task["uid"] == child_uid)
        assert manual_parent_after["parent_uid"] is None
        assert manual_child_after["parent_uid"] == parent_uid


def test_regenerate_structure_still_orphans_manual_task_under_removed_deliverable() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"
        tasks_url = f"/projects/{project_id}/tasks"

        assert client.post(path, json=_payload(), headers=headers).status_code == 201
        planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]
        structured_tasks = cast(list[dict[str, Any]], client.get(tasks_url, headers=headers).json())
        uid_by_key = {
            task["structure_key"]: task["uid"]
            for task in structured_tasks
            if task["structure_key"] is not None
        }
        removed_deliverable_uid = uid_by_key["design/specification/architecture"]

        manual_created = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks",
            json={
                "name": "Manual note",
                "target_parent_uid": removed_deliverable_uid,
                "expected_revision": 0,
            },
            headers=headers,
        )
        assert manual_created.status_code == 200
        manual_payload = cast(dict[str, Any], manual_created.json())
        manual_task = next(
            task
            for task in cast(list[dict[str, Any]], manual_payload["tasks"])
            if task["name"] == "Manual note"
        )
        manual_uid = manual_task["uid"]
        assert manual_task["parent_uid"] == removed_deliverable_uid

        payload_without_architecture = _payload()
        payload_without_architecture["posts"][0]["lots"][0]["deliverables"] = [
            {"key": "requirements", "name": "Requirements"}
        ]
        assert (
            client.post(path, json=payload_without_architecture, headers=headers).status_code == 201
        )

        regenerated = cast(list[dict[str, Any]], client.get(tasks_url, headers=headers).json())
        manual_after = next(task for task in regenerated if task["uid"] == manual_uid)
        assert manual_after["parent_uid"] is None


def test_structure_versions_validated_planning_is_immutable_and_reopenable() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"

        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 201
        project = client.get(f"/projects/{project_id}", headers=headers).json()
        assert project["status"] == "initialise"
        first_planning_id = project["displayed_planning_id"]
        assert first_planning_id is not None

        assert (
            client.post(
                f"/projects/{project_id}/plannings/{first_planning_id}/validate",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{first_planning_id}/reference",
                headers=headers,
            ).status_code
            == 200
        )

        reopened_from_validated = client.post(
            f"/projects/{project_id}/planning-structure/reopen", headers=headers
        )
        assert reopened_from_validated.status_code == 200
        reopened_planning_id = reopened_from_validated.json()["displayed_planning_id"]
        assert reopened_planning_id not in {first_planning_id, None}

        changed = _payload()
        changed["posts"][0]["lots"] = changed["posts"][0]["lots"][:1]
        second = client.post(path, json=changed, headers=headers)
        assert second.status_code == 201
        second_planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]
        assert second_planning_id != first_planning_id
        second_tasks = cast(list[dict[str, Any]], second.json()["tasks"])
        assert len(second_tasks) == 5

        original = client.get(
            f"/projects/{project_id}/plannings/{first_planning_id}", headers=headers
        )
        assert original.status_code == 200
        original_tasks = cast(list[dict[str, Any]], original.json()["tasks"])
        assert len(original_tasks) == 8

        default_tasks = client.get(f"/projects/{project_id}/tasks", headers=headers)
        assert default_tasks.status_code == 200
        default_task_items = cast(list[dict[str, Any]], default_tasks.json())
        assert len(default_task_items) == 5
        selected_original = client.get(
            f"/projects/{project_id}/tasks?planning_id={first_planning_id}", headers=headers
        )
        assert selected_original.status_code == 200
        selected_original_items = cast(list[dict[str, Any]], selected_original.json())
        assert len(selected_original_items) == 8
        paged_original = client.get(
            f"/projects/{project_id}/plannings/{first_planning_id}?limit=1&offset=1",
            headers=headers,
        )
        assert paged_original.status_code == 200
        paged_original_payload = cast(dict[str, Any], paged_original.json())
        assert len(cast(list[dict[str, Any]], paged_original_payload["tasks"])) == 1

        plannings = client.get(f"/projects/{project_id}/plannings", headers=headers)
        assert plannings.status_code == 200
        planning_items = cast(list[dict[str, Any]], plannings.json())
        assert all(
            set(item)
            == {
                "id",
                "project_id",
                "version_number",
                "status",
                "revision",
                "note",
                "created_at",
                "validated_at",
            }
            for item in planning_items
        )

        reopened = client.post(f"/projects/{project_id}/planning-structure/reopen", headers=headers)
        assert reopened.status_code == 200
        reopened_payload = cast(dict[str, Any], reopened.json())
        assert reopened_payload["status"] == "initialise"
        assert reopened_payload["displayed_planning_id"] == second_planning_id

        first_export = client.get(
            f"/projects/{project_id}/export.xml?planning_id={first_planning_id}",
            headers=headers,
        )
        second_export = client.get(
            f"/projects/{project_id}/export.xml?planning_id={second_planning_id}",
            headers=headers,
        )
        assert first_export.status_code == 200
        assert second_export.status_code == 200
        assert b"Validation" in first_export.content
        assert b"Validation" not in second_export.content


@pytest.mark.parametrize("project_status", ["en_reponse_appel_offre", "en_cours"])
def test_reopen_from_validated_reference_preserves_engaged_project_status(
    project_status: str,
) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        path = f"/projects/{project_id}/planning-structure"
        created = client.post(path, json=_payload(), headers=headers)
        assert created.status_code == 201
        planning_id = client.get(f"/projects/{project_id}", headers=headers).json()[
            "displayed_planning_id"
        ]
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/reference", headers=headers
            ).status_code
            == 200
        )
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = project_status
            session.commit()

        reopened = client.post(f"/projects/{project_id}/planning-structure/reopen", headers=headers)

        assert reopened.status_code == 200
        assert reopened.json()["status"] == project_status


def test_planning_tree_returns_complete_tree_without_pagination() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        response = client.post(
            f"/projects/{project_id}/planning-structure", json=_payload(), headers=headers
        )
        assert response.status_code == 201

        tree = client.get(f"/projects/{project_id}/planning-tree?limit=1", headers=headers)

        assert tree.status_code == 200
        tree_payload = cast(dict[str, Any], tree.json())
        roots = cast(list[dict[str, Any]], tree_payload["tasks"])
        lots = cast(list[dict[str, Any]], roots[0]["children"])
        assert len(lots) == 2
        assert len(cast(list[dict[str, Any]], lots[0]["children"])) == 3


@pytest.mark.parametrize(
    ("project_status", "expected_status"),
    [
        ("cree", "initialise"),
        ("initialise", "initialise"),
        ("en_reponse_appel_offre", "en_reponse_appel_offre"),
        ("en_cours", "en_cours"),
    ],
)
def test_reopen_existing_draft_preserves_engaged_project_status(
    project_status: str, expected_status: str
) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert (
            client.post(
                f"/projects/{project_id}/planning-structure",
                json=_payload(),
                headers=headers,
            ).status_code
            == 201
        )

        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = project_status
            session.commit()

        response = client.post(f"/projects/{project_id}/planning-structure/reopen", headers=headers)

        assert response.status_code == 200
        assert response.json()["status"] == expected_status


@pytest.mark.parametrize("project_status", ["en_reponse_appel_offre", "en_cours"])
def test_reopen_status_transition_back_to_initialise_is_rejected(project_status: str) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert (
            client.post(
                f"/projects/{project_id}/planning-structure",
                json=_payload(),
                headers=headers,
            ).status_code
            == 201
        )

        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = project_status
            session.commit()

        response = client.patch(
            f"/projects/{project_id}/status",
            json={"status": "initialise"},
            headers=headers,
        )

        assert response.status_code == 409
