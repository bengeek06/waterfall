from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
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
    email = f"planning.schedule.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Schedule mode"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _tasks_by_uid(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {task["uid"]: task for task in cast(list[dict[str, Any]], payload["tasks"])}


def _seed_hierarchy(project_id: int) -> int:
    """Seed a draft planning for E3-03 schedule-edit tests.

    uid=1 Root (summary) -> uid=2 Mid (summary) -> uid=3 Leaf (edited by most
    tests), uid=4 Leaf sibling (fixed dates, contributes to the summary
    min/max window). uid=5 is a milestone child of Root (no dates set,
    contributes nothing to the summary window). uid=6/7 are standalone tasks
    with fixed dates used as predecessors in the automatic-mode tests; they
    are not linked to uid=3 by default -- tests add their own
    ``WfPlanningLinkSnapshot`` rows as needed.
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
                    name="Root",
                    position=1,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=2,
                    name="Mid",
                    parent_uid=1,
                    position=1,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=3,
                    name="Leaf",
                    parent_uid=2,
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=4,
                    name="Leaf sibling",
                    parent_uid=2,
                    position=2,
                    start_at=datetime(2026, 1, 6, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 8, 8, 0, tzinfo=UTC),
                    duration_minutes=2880,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=5,
                    name="Milestone",
                    parent_uid=1,
                    position=2,
                    is_summary=False,
                    is_milestone=True,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=6,
                    name="Predecessor A",
                    position=3,
                    start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
                    duration_minutes=120,
                    is_summary=False,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=7,
                    name="Predecessor B",
                    position=4,
                    start_at=datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
                    duration_minutes=120,
                    is_summary=False,
                    is_milestone=False,
                ),
            ]
        )
        session.commit()
        return planning.id


def _add_link(
    planning_id: int, task_uid: int, predecessor_uid: int, link_type: int, lag_tenth_minute: int
) -> None:
    with get_session_factory()() as session:
        session.add(
            WfPlanningLinkSnapshot(
                planning_id=planning_id,
                task_uid=task_uid,
                predecessor_uid=predecessor_uid,
                link_type=link_type,
                lag_tenth_minute=lag_tenth_minute,
            )
        )
        session.commit()


def _schedule_path(project_id: int, planning_id: int, task_uid: int) -> str:
    return f"/projects/{project_id}/plannings/{planning_id}/tasks/{task_uid}"


def test_manual_task_stores_dates_verbatim_without_recalculation() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-01-09T08:00:00Z",
                "finish_at": "2026-01-11T08:00:00Z",
                "duration_minutes": 500,
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        leaf = tasks[3]
        assert leaf["is_manual"] is True
        assert leaf["start_at"] == "2026-01-09T08:00:00"
        assert leaf["finish_at"] == "2026-01-11T08:00:00"
        # Stored exactly as provided: a manually scheduled task is never
        # recalculated, even though its (nonexistent) calendar assignment
        # would have produced a different duration in automatic mode.
        assert leaf["duration_minutes"] == 500

        # Bottom-up recalculation of ancestor summaries.
        mid = tasks[2]
        assert mid["start_at"] == "2026-01-06T08:00:00"
        assert mid["finish_at"] == "2026-01-11T08:00:00"
        assert mid["duration_minutes"] == 7200  # wall-clock fallback: 5 days
        root = tasks[1]
        assert root["start_at"] == "2026-01-06T08:00:00"
        assert root["finish_at"] == "2026-01-11T08:00:00"
        assert root["duration_minutes"] == 7200


def test_manual_task_without_parent_skips_ancestor_recalculation() -> None:
    """A root-level task (no parent_uid) has no summary ancestor to
    recalculate; ``_recalculate_ancestor_summaries`` must return early
    instead of erroring."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-01T08:00:00Z",
                "finish_at": "2026-03-01T09:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        predecessor_a = _tasks_by_uid(cast(dict[str, Any], response.json()))[6]
        assert predecessor_a["start_at"] == "2026-03-01T08:00:00"
        assert predecessor_a["finish_at"] == "2026-03-01T09:00:00"


def test_manual_task_requires_start_at() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": True, "duration_minutes": 100},
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_manual_task_rejects_finish_before_start() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-01-10T08:00:00Z",
                "finish_at": "2026-01-09T08:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 400


def test_automatic_task_requires_positive_duration() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "start_at": "2026-01-05T08:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_automatic_task_without_predecessor_uses_payload_start_at() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": False,
                "start_at": "2026-01-20T08:00:00Z",
                "duration_minutes": 90,
            },
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        assert leaf["is_manual"] is False
        assert leaf["start_at"] == "2026-01-20T08:00:00"
        # Wall-clock fallback calendar (no Calendar rows exist in this test's
        # fresh schema): finish is simply start + duration.
        assert leaf["finish_at"] == "2026-01-20T09:30:00"
        assert leaf["duration_minutes"] == 90


def test_automatic_task_without_predecessor_falls_back_to_stored_start_at() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        with get_session_factory()() as session:
            leaf = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 3)
                .one()
            )
            leaf.start_at = datetime(2026, 1, 12, 9, 0, tzinfo=UTC)
            session.commit()

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        assert leaf["start_at"] == "2026-01-12T09:00:00"
        assert leaf["finish_at"] == "2026-01-12T10:00:00"


def test_automatic_task_without_predecessor_or_any_start_at_is_rejected() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_automatic_task_finish_start_predecessor_sets_start_after_predecessor_finish() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _add_link(planning_id, task_uid=3, predecessor_uid=6, link_type=1, lag_tenth_minute=300)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 240},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Predecessor A finishes at 10:00, +30 min lag => 10:30.
        assert leaf["start_at"] == "2026-01-05T10:30:00"
        assert leaf["finish_at"] == "2026-01-05T14:30:00"


def test_automatic_task_multiple_predecessors_uses_latest_constraint() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        # FS on predecessor A => 10:30 constraint.
        _add_link(planning_id, task_uid=3, predecessor_uid=6, link_type=1, lag_tenth_minute=300)
        # SS on predecessor B => 12:00 constraint (later, must win).
        _add_link(planning_id, task_uid=3, predecessor_uid=7, link_type=3, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 240},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        assert leaf["start_at"] == "2026-01-05T12:00:00"
        assert leaf["finish_at"] == "2026-01-05T16:00:00"


def test_automatic_task_finish_finish_predecessor_uses_documented_raw_minute_approximation() -> (
    None
):
    """FF (link_type=0) known v1 limitation: the successor's start is derived
    from the predecessor's finish date using raw wall-clock minute
    arithmetic (predecessor.finish_at + lag - duration_minutes), not a true
    calendar-aware backward walk. This test freezes that documented
    behaviour, see ``_resolve_predecessor_constraints`` in
    ``waterfall.services.planning_tree``."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _add_link(planning_id, task_uid=3, predecessor_uid=6, link_type=0, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 240},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Predecessor A finishes at 10:00; 10:00 + 0 lag - 240 min = 06:00.
        assert leaf["start_at"] == "2026-01-05T06:00:00"
        assert leaf["finish_at"] == "2026-01-05T10:00:00"


def test_automatic_task_start_finish_predecessor_uses_documented_raw_minute_approximation() -> None:
    """SF (link_type=2) known v1 limitation, mirroring the FF test above but
    anchored on the predecessor's start_at instead of its finish_at."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _add_link(planning_id, task_uid=3, predecessor_uid=7, link_type=2, lag_tenth_minute=300)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 240},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Predecessor B starts at 12:00; 12:00 + 30 min lag - 240 min = 08:30.
        assert leaf["start_at"] == "2026-01-05T08:30:00"
        assert leaf["finish_at"] == "2026-01-05T12:30:00"


def test_automatic_task_uses_assigned_role_calendar_for_duration() -> None:
    """E5-04's calendar resolution is reused: a non-standard calendar
    assigned via the task's resource role produces a different finish_at
    than the wall-clock fallback would."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
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

            # wf_task_role_assignment references ms_task.id, never a planning
            # snapshot row directly, so a live MsTask row bridging uid=3 has
            # to exist (same bridging pattern as E5-04's tests).
            leaf_task = MsTask(project_id=project_id, uid=3, name="Leaf")
            session.add(leaf_task)
            session.flush()
            session.add(
                TaskRoleAssignment(
                    task_id=leaf_task.id,
                    role_id=role.id,
                    quantity=Decimal("1.00"),
                    hours=Decimal("10.00"),
                )
            )
            session.commit()

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": False,
                "start_at": "2026-01-05T08:00:00Z",
                "duration_minutes": 1200,
            },
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        assert leaf["start_at"] == "2026-01-05T08:00:00"
        # 1200 minutes at 4h (240 min)/weekday from Monday 2026-01-05 08:00
        # consumes Mon-Fri fully, finishing at 2026-01-09T12:00 -- not the
        # 2026-01-06T04:00 a naive 24h/day wall-clock diff would produce.
        assert leaf["finish_at"] == "2026-01-09T12:00:00"


def test_summary_task_rejects_direct_schedule_edit() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 2),
            json={"is_manual": True, "start_at": "2026-01-05T08:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_milestone_forces_zero_duration_and_matching_finish_at() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": True, "start_at": "2026-02-01T09:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 200
        milestone = _tasks_by_uid(cast(dict[str, Any], response.json()))[5]
        assert milestone["start_at"] == "2026-02-01T09:00:00"
        assert milestone["finish_at"] == "2026-02-01T09:00:00"
        assert milestone["duration_minutes"] == 0


def test_milestone_rejects_explicit_nonzero_duration() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={
                "is_manual": True,
                "start_at": "2026-02-01T09:00:00Z",
                "duration_minutes": 120,
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_milestone_rejects_explicit_finish_at_different_from_start_at() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={
                "is_manual": True,
                "start_at": "2026-02-01T09:00:00Z",
                "finish_at": "2026-02-02T09:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 400


def test_milestone_without_any_start_at_is_rejected() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": True},
            headers=headers,
        )

        assert response.status_code == 400


def test_automatic_milestone_without_predecessor_uses_payload_start_at() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": False, "start_at": "2026-02-01T09:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 200
        milestone = _tasks_by_uid(cast(dict[str, Any], response.json()))[5]
        assert milestone["is_manual"] is False
        assert milestone["start_at"] == "2026-02-01T09:00:00"
        assert milestone["finish_at"] == "2026-02-01T09:00:00"
        assert milestone["duration_minutes"] == 0


def test_automatic_milestone_finish_start_predecessor_sets_start_after_predecessor_finish() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _add_link(planning_id, task_uid=5, predecessor_uid=6, link_type=1, lag_tenth_minute=300)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": False},
            headers=headers,
        )

        assert response.status_code == 200
        milestone = _tasks_by_uid(cast(dict[str, Any], response.json()))[5]
        # Predecessor A finishes at 10:00, +30 min lag => 10:30.
        assert milestone["start_at"] == "2026-01-05T10:30:00"
        assert milestone["finish_at"] == "2026-01-05T10:30:00"
        assert milestone["duration_minutes"] == 0


def test_automatic_milestone_multiple_predecessors_uses_latest_constraint() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        # FS on predecessor A => 10:30 constraint.
        _add_link(planning_id, task_uid=5, predecessor_uid=6, link_type=1, lag_tenth_minute=300)
        # SS on predecessor B => 12:00 constraint (later, must win).
        _add_link(planning_id, task_uid=5, predecessor_uid=7, link_type=3, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": False},
            headers=headers,
        )

        assert response.status_code == 200
        milestone = _tasks_by_uid(cast(dict[str, Any], response.json()))[5]
        assert milestone["start_at"] == "2026-01-05T12:00:00"
        assert milestone["finish_at"] == "2026-01-05T12:00:00"


def test_automatic_milestone_without_predecessor_or_any_start_at_is_rejected() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": False},
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_schedule_update_rejects_validated_planning_and_read_only_project() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        payload = {"is_manual": True, "start_at": "2026-01-05T08:00:00Z"}

        assert (
            client.post(
                f"/projects/{project_id}/plannings/{planning_id}/validate", headers=headers
            ).status_code
            == 200
        )

        validated = client.patch(
            _schedule_path(project_id, planning_id, 3), json=payload, headers=headers
        )
        assert validated.status_code == 409

        with get_session_factory()() as session:
            second_planning = WfPlanning(project_id=project_id, version_number=2, status="draft")
            session.add(second_planning)
            session.flush()
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=second_planning.id,
                    uid=3,
                    name="Leaf",
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                )
            )
            session.commit()
            second_planning_id = second_planning.id

            project = session.get(MsProject, project_id)
            assert project is not None
            project.status = "termine"
            session.commit()

        read_only = client.patch(
            _schedule_path(project_id, second_planning_id, 3), json=payload, headers=headers
        )
        assert read_only.status_code == 409


def test_schedule_update_returns_404_for_unknown_task() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 999),
            json={"is_manual": True, "start_at": "2026-01-05T08:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 404
