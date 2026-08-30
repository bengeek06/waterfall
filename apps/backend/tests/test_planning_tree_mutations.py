from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from waterfall.api.routes import projects
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    Calendar,
    CalendarWeekday,
    CostCategory,
    CostType,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)


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


def test_mutable_draft_planning_locks_project_then_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = MagicMock(spec=MsProject)
    planning = MagicMock(spec=WfPlanning)
    planning.status = "draft"
    project_query = MagicMock()
    planning_query = MagicMock()
    project_query.filter.return_value = project_query
    project_query.populate_existing.return_value = project_query
    project_query.with_for_update.return_value = project_query
    project_query.first.return_value = project
    planning_query.filter.return_value = planning_query
    planning_query.populate_existing.return_value = planning_query
    planning_query.with_for_update.return_value = planning_query
    planning_query.first.return_value = planning
    db = MagicMock()
    db.query.side_effect = [project_query, planning_query]

    def assert_state_checks_follow_locks(_: MsProject) -> None:
        assert project_query.with_for_update.called
        assert planning_query.with_for_update.called

    monkeypatch.setattr(projects, "ensure_project_mutable", assert_state_checks_follow_locks)

    result = projects.get_mutable_draft_planning_with_locks(db, 10, 20, 30)

    assert result == (project, planning)
    assert db.query.call_args_list == [
        ((MsProject,),),
        ((WfPlanning,),),
    ]
    project_query.with_for_update.assert_called_once_with()
    planning_query.with_for_update.assert_called_once_with()


def test_displayed_planning_branch_is_selected_after_project_refresh_and_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    project = MagicMock(spec=MsProject)
    project.displayed_planning_id = 20
    planning = MagicMock(spec=WfPlanning)
    planning.status = "draft"
    project_query = MagicMock()
    planning_query = MagicMock()
    project_query.filter.return_value = project_query
    project_query.populate_existing.return_value = project_query
    project_query.with_for_update.return_value = project_query
    project_query.first.side_effect = lambda: (events.append("project_first"), project)[1]
    planning_query.filter.return_value = planning_query
    planning_query.populate_existing.return_value = planning_query
    planning_query.with_for_update.return_value = planning_query
    planning_query.first.side_effect = lambda: (events.append("planning_first"), planning)[1]
    db = MagicMock()
    db.query.side_effect = [project_query, planning_query]

    project_query.populate_existing.side_effect = lambda: (
        events.append("project_refresh"),
        project_query,
    )[1]
    project_query.with_for_update.side_effect = lambda: (
        events.append("project_lock"),
        project_query,
    )[1]
    planning_query.with_for_update.side_effect = lambda: (
        events.append("planning_lock"),
        planning_query,
    )[1]

    def check_project(_: MsProject) -> None:
        events.append("project_mutable")

    monkeypatch.setattr(projects, "ensure_project_mutable", check_project)

    result = projects.get_mutable_project_with_displayed_planning_lock(db, 10, 30)

    assert result == (project, planning)
    assert events == [
        "project_refresh",
        "project_lock",
        "project_first",
        "project_mutable",
        "planning_lock",
        "planning_first",
    ]


def test_mutable_displayed_draft_planning_locks_project_then_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = MagicMock(spec=MsProject)
    project.displayed_planning_id = 20
    planning = MagicMock(spec=WfPlanning)
    planning.status = "draft"
    project_query = MagicMock()
    planning_query = MagicMock()
    project_query.filter.return_value = project_query
    project_query.populate_existing.return_value = project_query
    project_query.with_for_update.return_value = project_query
    project_query.first.return_value = project
    planning_query.filter.return_value = planning_query
    planning_query.populate_existing.return_value = planning_query
    planning_query.with_for_update.return_value = planning_query
    planning_query.first.return_value = planning
    db = MagicMock()
    db.query.side_effect = [project_query, planning_query]

    def assert_project_check_follows_lock(_: MsProject) -> None:
        assert project_query.with_for_update.called

    monkeypatch.setattr(projects, "ensure_project_mutable", assert_project_check_follows_lock)

    result = projects.get_mutable_displayed_draft_planning_with_locks(db, 10, 30)

    assert result == (project, planning)
    assert db.query.call_args_list == [
        ((MsProject,),),
        ((WfPlanning,),),
    ]
    project_query.with_for_update.assert_called_once_with()
    planning_query.with_for_update.assert_called_once_with()


def test_snapshot_task_creation_uses_displayed_planning_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    original_helper = projects.get_mutable_project_with_displayed_planning_lock

    def locked_helper(
        db: Any, project_id: int, owner_id: int
    ) -> tuple[MsProject, WfPlanning | None]:
        calls.append((project_id, owner_id))
        return original_helper(db, project_id, owner_id)

    monkeypatch.setattr(projects, "get_mutable_project_with_displayed_planning_lock", locked_helper)
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.displayed_planning_id = planning_id
            session.commit()

        response = client.post(
            f"/projects/{project_id}/tasks", json={"name": "Locked snapshot task"}, headers=headers
        )

    assert response.status_code == 201
    assert len(calls) == 1
    assert calls[0][0] == project_id


def test_snapshot_task_deletion_uses_displayed_planning_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    original_helper = projects.get_mutable_project_with_displayed_planning_lock

    def locked_helper(
        db: Any, project_id: int, owner_id: int
    ) -> tuple[MsProject, WfPlanning | None]:
        calls.append((project_id, owner_id))
        return original_helper(db, project_id, owner_id)

    monkeypatch.setattr(projects, "get_mutable_project_with_displayed_planning_lock", locked_helper)
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
        with get_session_factory()() as session:
            project = session.get(MsProject, project_id)
            assert project is not None
            project.displayed_planning_id = planning_id
            session.commit()

        response = client.delete(f"/projects/{project_id}/tasks/2", headers=headers)

    assert response.status_code == 204
    assert len(calls) == 1
    assert calls[0][0] == project_id


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


def test_move_recalculates_summary_duration_from_assigned_resource_role_calendar() -> None:
    """E5-04: a summary task's duration is derived from its own assigned
    resource role's working calendar, and children staffed on a different
    (or no) calendar must not corrupt that resolution."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)

        with get_session_factory()() as session:
            # PARTTIME: 4h/day Mon-Fri, 0h on the weekend -- deliberately
            # different from STANDARD's 7h/day so the test can distinguish
            # "calendar-aware" from "wall-clock" or "STANDARD" arithmetic.
            calendar = Calendar(code="PARTTIME", name="Temps partiel", weeks_per_year=47)
            session.add(calendar)
            session.flush()
            session.add_all(
                CalendarWeekday(
                    calendar_id=calendar.id,
                    day_type=day_type,
                    hours_per_day=Decimal("0.00") if day_type in (1, 7) else Decimal("4.00"),
                )
                for day_type in range(1, 8)
            )

            cost_type = CostType(code="MO", name="Main d'oeuvre", kind="labor")
            session.add(cost_type)
            session.flush()
            category = CostCategory(
                cost_type_id=cost_type.id,
                accounting_code="DEV",
                category_code="IDEX",
                name="Developpement",
            )
            node = ResourceNode(code="IT", name="Departement informatique")
            session.add_all([category, node])
            session.flush()
            role = ResourceRole(
                node_id=node.id,
                cost_category_id=category.id,
                calendar_id=calendar.id,
                code="DEV-PARTTIME",
                name="Developpeur temps partiel",
            )
            session.add(role)
            session.flush()

            # wf_task_role_assignment references ms_task.id, never a
            # planning snapshot row, so a live MsTask row bridging uid=4
            # (Group B, the summary whose duration this test locks in) has
            # to exist -- same bridging pattern the E5-02 export code uses.
            summary_task = MsTask(project_id=project_id, uid=4, name="Group B")
            session.add(summary_task)
            session.flush()
            session.add(
                TaskRoleAssignment(
                    task_id=summary_task.id,
                    role_id=role.id,
                    quantity=Decimal("1.00"),
                    hours=Decimal("10.00"),
                )
            )

            # uid=5 (Leaf C) is a child of the summary with dates that do not
            # dominate the min/max window and no calendar of its own -- it
            # resolves to the wall-clock fallback tier, distinct from the
            # summary's own PARTTIME calendar, and must not influence the
            # summary's duration calculation.
            leaf_c = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 5)
                .one()
            )
            leaf_c.start_at = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
            leaf_c.finish_at = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
            session.commit()

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={"task_uids": [3], "target_parent_uid": 4, "position": 2},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        assert tasks[4]["is_summary"] is True
        assert tasks[4]["start_at"] == "2026-01-01T08:00:00"
        assert tasks[4]["finish_at"] == "2026-01-10T08:00:00"

        with get_session_factory()() as session:
            group_b = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 4)
                .one()
            )
            # 7 working weekdays (Mon-Fri) at 4h/day between 2026-01-01T08:00
            # and 2026-01-10T08:00 under PARTTIME: not the wall-clock diff
            # (12960 minutes) nor a STANDARD-calendar figure.
            assert group_b.duration_minutes == 1680


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


def test_move_recalculating_summary_with_near_date_max_child_returns_400_not_500() -> None:
    """Round-4 E3-03 PR review finding: ``compute_working_minutes_between``
    (used by ``_recalculate_summary_fields`` to derive a summary task's
    ``duration_minutes`` from its children) walks the calendar day by day,
    exactly like ``compute_finish_at``/``compute_start_at``, but -- unlike
    those two -- had no iteration ceiling of its own. Any move recalculates
    the *whole* tree's summary durations (not just the moved subtree), so a
    task that already carries an unreasonably far ``finish_at`` (e.g. from a
    prior manual-mode edit, which has no server-side range validation, see
    ``_apply_manual_schedule``) makes an otherwise unrelated move trip the
    same unbounded walk. This must surface as the 400 already documented for
    an invalid move, not leak as an uncaught 500, and must return promptly
    rather than looping for an unreasonable number of iterations.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _, planning_id = _seed_plannings(project_id)
        with get_session_factory()() as session:
            leaf = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 3)
                .one()
            )
            # uid=3 is a child of Group A (uid=1, summary): its finish_at
            # feeds directly into Group A's max(finish_dates) recalculation.
            leaf.finish_at = datetime(9999, 12, 31, 0, 0, tzinfo=UTC)
            session.commit()

        # An unrelated move (uid=6 has no relationship to Group A) still
        # recalculates every summary task's duration in the whole tree.
        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/move",
            json={"task_uids": [6], "target_parent_uid": 4, "position": 1},
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


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
