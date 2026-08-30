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
    planning_id: int,
    task_uid: int,
    predecessor_uid: int,
    link_type: int,
    lag_tenth_minute: int,
    lag_format: int | None = None,
) -> None:
    with get_session_factory()() as session:
        session.add(
            WfPlanningLinkSnapshot(
                planning_id=planning_id,
                task_uid=task_uid,
                predecessor_uid=predecessor_uid,
                link_type=link_type,
                lag_tenth_minute=lag_tenth_minute,
                lag_format=lag_format,
            )
        )
        session.commit()


def _create_standard_calendar() -> None:
    """A Mon-Fri 7h/day calendar, matching STANDARD_HOURS in
    test_calendar_schedule.py, used by the lag_format regression tests below
    to demonstrate a working-time lag skipping a weekend."""
    with get_session_factory()() as session:
        calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=47)
        session.add(calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(
                calendar_id=calendar.id,
                day_type=day_type,
                hours_per_day=Decimal("0.00") if day_type in (1, 7) else Decimal("7.00"),
            )
            for day_type in range(1, 8)
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


def test_automatic_task_working_day_lag_format_resolves_through_calendar_skipping_weekend() -> None:
    """E3-03 PR review finding #2: a working-time ("d", lag_format=7) FS lag
    is resolved through the applicable calendar, like a task's own duration,
    instead of raw wall-clock arithmetic.

    Predecessor A is moved to finish on a Friday. A lag that fits within a
    single calendar day always resolves within that same date regardless of
    the anchor's time-of-day (identical to how ``compute_finish_at`` already
    behaves for a task's own duration -- see
    ``test_compute_finish_at_mono_day_fits_within_one_days_capacity`` in
    test_calendar_schedule.py), so the smallest lag that unambiguously
    demonstrates the weekend being skipped is one exceeding a single day's
    working capacity: 2 working days (2 * the STANDARD calendar's 7h/day
    capacity), mirroring test_compute_finish_at_skips_non_working_days.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _create_standard_calendar()
        with get_session_factory()() as session:
            predecessor = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 6)
                .one()
            )
            predecessor.finish_at = datetime(2026, 1, 9, 8, 0, tzinfo=UTC)  # Friday
            session.commit()
        # 2 working days = 2 * 7h * 60 min = 840 min = 8400 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=8400,
            lag_format=7,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Friday 08:00: Friday's 7h (420 min) is consumed first, Sat/Sun
        # contribute nothing, the remaining 420 min are consumed on Monday ->
        # 2026-01-12 (Monday) 15:00, not the naive Sunday a raw 840-minute
        # wall-clock addition would produce.
        assert leaf["start_at"] == "2026-01-12T15:00:00"
        assert leaf["finish_at"] == "2026-01-12T16:00:00"


def test_automatic_task_negative_working_day_lag_resolves_through_calendar_skipping_weekend() -> (
    None
):
    """2nd E3-03 PR review round, finding #1: a negative (lead/advance)
    working-time ("d", lag_format=7) FS lag must also be resolved through the
    applicable calendar, retreating to the preceding *working* day(s) across
    a weekend instead of falling back to raw wall-clock subtraction (which
    would have landed on a non-working weekend day).

    Predecessor A is moved to finish on a Monday. A lag exceeding a single
    day's working capacity is needed to unambiguously demonstrate the
    weekend being skipped (a lag that fits within the anchor's own day's
    capacity resolves within that same day -- see
    ``test_compute_start_at_mono_day_fits_within_the_anchors_own_days_capacity``
    in test_calendar_schedule.py -- and would not exercise the weekend-skip
    path at all), so this uses 2 working days (2 * the STANDARD calendar's
    7h/day capacity), mirroring
    ``test_automatic_task_working_day_lag_format_resolves_through_calendar_skipping_weekend``
    above.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _create_standard_calendar()
        with get_session_factory()() as session:
            predecessor = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 6)
                .one()
            )
            predecessor.finish_at = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)  # Monday
            session.commit()
        # -2 working days = -840 min = -8400 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=-8400,
            lag_format=7,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Monday 08:00 retreats: Monday's own 7h (420 min) is consumed
        # first, Sat/Sun contribute nothing, the remaining 420 min are
        # consumed on the preceding Friday -> 2026-01-09 (Friday) 01:00, not
        # the 2026-01-10 (Saturday) a naive 840-minute wall-clock
        # subtraction would produce.
        assert leaf["start_at"] == "2026-01-09T01:00:00"
        assert leaf["finish_at"] == "2026-01-09T02:00:00"


def test_automatic_task_short_negative_lag_stays_within_the_anchors_own_day() -> None:
    """Round-3 E3-03 PR review finding #1: a negative (lead/advance)
    working-time lag short enough to fit within the predecessor's own
    calendar day must resolve to earlier that *same* day, not retreat an
    entire extra working day (and, in this case, an entire weekend) before
    it starts counting down -- see
    ``test_compute_start_at_short_lead_fits_within_the_anchors_own_day`` in
    test_calendar_schedule.py for the underlying unit-level regression.

    Predecessor A is moved to finish on a Monday. A 1-hour lead must resolve
    to 1 hour earlier that same Monday.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _create_standard_calendar()
        with get_session_factory()() as session:
            predecessor = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 6)
                .one()
            )
            predecessor.finish_at = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)  # Monday
            session.commit()
        # -1 hour = -60 min = -600 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=-600,
            lag_format=7,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Monday 08:00 - 1h fits entirely within Monday's own capacity ->
        # Monday 07:00, not the preceding Friday.
        assert leaf["start_at"] == "2026-01-12T07:00:00"
        assert leaf["finish_at"] == "2026-01-12T08:00:00"


def test_automatic_task_negative_elapsed_lag_format_keeps_raw_wall_clock_arithmetic() -> None:
    """The elapsed ("ed", lag_format=8) counterpart of the negative-lag test
    above must keep the pre-existing raw wall-clock behaviour unchanged for a
    negative lag too: subtracted directly with no calendar involved, landing
    on the weekend instead of being pushed back to the preceding working
    day."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _create_standard_calendar()
        with get_session_factory()() as session:
            predecessor = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 6)
                .one()
            )
            predecessor.finish_at = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)  # Monday
            session.commit()
        # -1 elapsed day = -1440 min = -14400 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=-14400,
            lag_format=8,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Monday 08:00 - 24h raw wall-clock = Sunday 08:00 (unchanged).
        assert leaf["start_at"] == "2026-01-11T08:00:00"


def test_automatic_task_sub_minute_lag_preserves_fractional_offset() -> None:
    """2nd E3-03 PR review round, finding #2: ``lag_tenth_minute=5`` (0.5
    minutes) in a working-time format must resolve to a 30-second offset, not
    silently vanish to a zero offset -- which is what ``round(0.5)`` (Python
    banker's rounding rounds halves to even) previously produced."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _create_standard_calendar()
        # 0.5 minutes = 5 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=5,
            lag_format=7,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Predecessor A finishes at 2026-01-05T10:00:00; a vanished (rounded
        # to zero) lag would incorrectly also produce 10:00:00.
        assert leaf["start_at"] == "2026-01-05T10:00:30"
        assert leaf["finish_at"] == "2026-01-05T11:00:30"


def test_automatic_task_elapsed_lag_format_keeps_raw_wall_clock_arithmetic() -> None:
    """The elapsed ("ed", lag_format=8) counterpart of the test above must
    keep the pre-existing raw wall-clock behaviour unchanged: the lag is
    added directly with no calendar involved, landing on the weekend instead
    of being pushed to the next working day."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _create_standard_calendar()
        with get_session_factory()() as session:
            predecessor = (
                session.query(WfPlanningTaskSnapshot)
                .filter(WfPlanningTaskSnapshot.planning_id == planning_id)
                .filter(WfPlanningTaskSnapshot.uid == 6)
                .one()
            )
            predecessor.finish_at = datetime(2026, 1, 9, 8, 0, tzinfo=UTC)  # Friday
            session.commit()
        # 1 elapsed day = 1440 min = 14400 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=14400,
            lag_format=8,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Friday 08:00 + 24h raw wall-clock = Saturday 08:00 (unchanged).
        assert leaf["start_at"] == "2026-01-10T08:00:00"
        # The task's own duration is unaffected by this fix and stays
        # calendar-aware regardless of the lag_format used to reach start_at.
        assert leaf["finish_at"] == "2026-01-12T09:00:00"


def test_automatic_task_missing_lag_format_keeps_raw_wall_clock_arithmetic() -> None:
    """An absent ``<LagFormat>`` (legal per the MSPDI schema) must preserve
    the pre-existing raw wall-clock lag arithmetic -- the only behaviour
    available before lag_format was read at all -- rather than silently
    defaulting untagged data to the new calendar-aware path."""
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
        # Predecessor A finishes at 10:00, +30 min lag => 10:30 (unchanged).
        assert leaf["start_at"] == "2026-01-05T10:30:00"
        assert leaf["finish_at"] == "2026-01-05T14:30:00"


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


def test_editing_predecessor_does_not_reschedule_automatic_successor() -> None:
    """E3-03 PR review finding #3, documented "Known v1 limitation": editing a
    task only recalculates its summary *ancestors* (see
    ``_recalculate_ancestor_summaries``), never its *successors* -- other
    tasks whose ``WfPlanningLinkSnapshot`` references it as
    ``predecessor_uid`` -- even when a successor is in automatic mode.

    This test freezes that current (non-cascading) behaviour: uid=3 (Leaf) is
    first put in automatic mode with an FS link on uid=6 (Predecessor A),
    landing on dates consistent with its constraint. Predecessor A is then
    edited to finish much later. Per issue #73 ("Automatic-mode successors
    are not rescheduled when their predecessor's dates change"), uid=3 is
    *not* revisited and keeps its now-constraint-violating dates -- this test
    must be replaced with a positive cascade assertion once #73 is
    implemented, not just deleted.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _add_link(planning_id, task_uid=3, predecessor_uid=6, link_type=1, lag_tenth_minute=300)

        automatic_response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 240},
            headers=headers,
        )
        assert automatic_response.status_code == 200
        leaf_before = _tasks_by_uid(cast(dict[str, Any], automatic_response.json()))[3]
        # Predecessor A finishes at 10:00, +30 min lag => 10:30 (same math as
        # test_automatic_task_finish_start_predecessor_sets_start_after_predecessor_finish).
        assert leaf_before["start_at"] == "2026-01-05T10:30:00"
        assert leaf_before["finish_at"] == "2026-01-05T14:30:00"

        predecessor_response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-02-01T08:00:00Z",
                "finish_at": "2026-02-01T09:00:00Z",
            },
            headers=headers,
        )
        assert predecessor_response.status_code == 200
        predecessor = _tasks_by_uid(cast(dict[str, Any], predecessor_response.json()))[6]
        assert predecessor["finish_at"] == "2026-02-01T09:00:00"

        # uid=3 is untouched by this request: it keeps its pre-edit dates,
        # which now violate its own FS constraint against uid=6 -- the
        # documented v1 gap tracked by issue #73.
        leaf_after = _tasks_by_uid(cast(dict[str, Any], predecessor_response.json()))[3]
        assert leaf_after["start_at"] == leaf_before["start_at"]
        assert leaf_after["finish_at"] == leaf_before["finish_at"]


def test_automatic_task_start_at_near_datetime_max_returns_400_not_500() -> None:
    """Round-3 E3-03 PR review finding #2: ``compute_finish_at`` walks the
    calendar day by day and can raise ``OverflowError`` (not just
    ``ValueError``) when that walk is pushed past ``date.max``
    (``9999-12-31``). This is a schema-valid request (``start_at`` is just a
    very late, but legal, ``datetime``), so it must surface as the 400
    already documented for an invalid schedule, not leak as an uncaught 500.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        # No Calendar rows exist in this test's fresh schema, so the
        # wall-clock fallback calendar applies: every day has a 1440
        # min/day (24h) capacity. A duration exceeding a single day's
        # capacity forces the forward walk to step past 9999-12-31
        # (date.max), which raises OverflowError.
        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": False,
                "start_at": "9999-12-31T00:00:00Z",
                "duration_minutes": 1441,
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)


def test_automatic_task_sparse_calendar_duration_rejected_without_hanging() -> None:
    """Round-3 E3-03 PR review finding #3: ``duration_minutes``'s schema-level
    upper bound (15 years of *working* minutes) does not by itself cap how
    many calendar days ``compute_finish_at`` walks: a calendar with only a
    sliver of capacity on a single weekday per week needs a huge number of
    day-by-day loop iterations to absorb even a fraction of the maximum
    allowed duration. This must be rejected by the hard iteration ceiling in
    ``calendar_schedule.py`` (surfaced as a 400) rather than hang the
    request. Deliberately does not assert on wall-clock timing -- only that
    the expected error response comes back at all -- since a slow-but-
    eventually-successful loop would also be an unacceptable outcome for
    this test to silently tolerate under a stopwatch.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        with get_session_factory()() as session:
            calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=1)
            session.add(calendar)
            session.flush()
            # Every day has 0 capacity except Monday, which has the DB's
            # minimum legal non-zero capacity (0.01h = 1 min once rounded).
            session.add_all(
                CalendarWeekday(
                    calendar_id=calendar.id,
                    day_type=day_type,
                    hours_per_day=Decimal("0.01") if day_type == 2 else Decimal("0.00"),
                )
                for day_type in range(1, 8)
            )
            session.commit()

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": False,
                "start_at": "2026-01-05T08:00:00Z",
                # Near the schema's own upper bound (le=7_884_000): far more
                # working minutes than a 1 min/day, 1 day/week calendar
                # could ever plausibly absorb within the iteration ceiling.
                "duration_minutes": 7_000_000,
            },
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


def test_schedule_update_rejects_duration_minutes_above_upper_bound() -> None:
    """2nd E3-03 PR review round, finding #3: an unbounded ``duration_minutes``
    could drive ``compute_finish_at``'s day-stepping loop for a very long
    time, overflow past ``datetime.max``, or exceed the PostgreSQL
    ``INTEGER`` column's range. Rejected at the Pydantic validation layer,
    surfaced as a 400 (not FastAPI's default 422) by
    ``_PlanningTaskBodyValidationRoute``, which this endpoint shares with the
    tree-move endpoint precisely so a malformed request body is reported the
    same way as any other business-rule violation on this resource -- before
    it ever reaches ``update_planning_task_schedule``."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-01-05T08:00:00Z",
                "duration_minutes": 7_884_001,
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert isinstance(response.json()["detail"], list)


def test_schedule_update_accepts_duration_minutes_at_upper_bound() -> None:
    """The boundary value itself (exactly 15 years in minutes) must still be
    accepted -- the bound is inclusive, only values strictly above it are
    rejected."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-01-05T08:00:00Z",
                "duration_minutes": 7_884_000,
            },
            headers=headers,
        )

        assert response.status_code == 200


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
