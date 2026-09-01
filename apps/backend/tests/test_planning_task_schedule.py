from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
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
from waterfall.services.planning_tree import (
    PlanningTaskScheduleError,
    _topological_cascade_order,  # pyright: ignore[reportPrivateUsage]
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


def test_automatic_task_sub_minute_lag_that_exactly_exhausts_a_days_capacity_rolls_over() -> None:
    """5th E3-03 PR review round, finding #1: a working-time lag whose whole-
    minute part exactly exhausts the last working day it touches -- plus a
    non-zero sub-minute remainder -- must roll the remainder over into the
    next working day, not strand it past that day's working window close.

    Predecessor A finishes on a Friday (2026-01-09 08:00, STANDARD 7h/day =
    420 min capacity). ``lag=420.5`` minutes: the whole-minute part (420)
    exactly matches Friday's full-day capacity, so a naive
    truncate-then-add-remainder implementation would return
    "Friday 15:00:00" (``compute_finish_at``'s exact-match, no-rollover
    instant) plus a raw 30-second ``timedelta`` on top, landing 30 seconds
    past Friday's working window close instead of rolling over the weekend
    into Monday.
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
        # 420.5 minutes = 4205 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=4205,
            lag_format=7,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Friday's 420 min capacity is fully consumed, the leftover 0.5
        # minutes roll over into Monday (Sat/Sun contribute nothing) ->
        # Monday 08:00:30, not Friday 15:00:30 (past the working window).
        assert leaf["start_at"] == "2026-01-12T08:00:30"
        assert leaf["finish_at"] == "2026-01-12T09:00:30"


def test_automatic_task_negative_sub_minute_lag_exhausting_a_days_capacity_rolls_over() -> None:
    """Symmetric (lead/advance) counterpart of
    ``test_automatic_task_sub_minute_lag_that_exactly_exhausts_a_days_capacity_rolls_over``:
    a negative working-time lag whose whole-minute part exactly exhausts the
    last working day it retreats through, plus a non-zero sub-minute
    remainder, must roll the remainder over into the preceding working day,
    not strand it past that day's working window open.

    Predecessor A finishes on a Monday (2026-01-12 08:00, STANDARD 7h/day =
    420 min capacity). ``lag=-420.5`` minutes: the whole-minute part (420)
    exactly matches Monday's full-day capacity, so a naive
    truncate-then-add-remainder implementation would return
    "Monday 01:00:00" (``compute_start_at``'s exact-match, no-rollover
    instant, using only Monday's own capacity) minus a raw 30-second
    ``timedelta`` on top, staying within Monday instead of rolling over the
    weekend into the preceding Friday.
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
        # -420.5 minutes = -4205 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=6,
            link_type=1,
            lag_tenth_minute=-4205,
            lag_format=7,
        )

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        # Monday's own 420 min capacity is fully consumed retreating
        # backward, the leftover 0.5 minutes roll over into the preceding
        # Friday (Sat/Sun contribute nothing) -> Friday 07:59:30, not
        # Monday 00:59:30 (past Monday's working window open).
        assert leaf["start_at"] == "2026-01-09T07:59:30"
        assert leaf["finish_at"] == "2026-01-09T08:59:30"


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


def test_automatic_task_finish_finish_predecessor_resolves_exact_calendar_aware_start() -> None:
    """6th/7th E3-03 PR review rounds: FF (link_type=0) is no longer
    approximated with raw wall-clock arithmetic. The successor's start is
    derived exactly: the predecessor's finish_at is offset by the (here
    zero, elapsed-format) lag via ``_resolve_lag_offset`` to get the
    successor's target finish date, which ``compute_start_at`` then converts
    into a start constraint given the successor's own duration -- see
    ``_resolve_predecessor_constraints`` in ``waterfall.services.planning_tree``.

    No ``Calendar`` rows exist in this test's fresh schema, so the task's
    calendar resolves to the wall-clock fallback (24h/day, every day
    working, see ``calendar_schedule.ResolvedCalendar``), which makes the new
    exact calendar-aware computation numerically coincide with the old raw
    wall-clock approximation it replaces -- this test's values are unchanged
    from before the fix, but for a different, now-exact, reason; the
    weekend-crossing test below is what actually exercises the fix's
    calendar-awareness.
    """
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
        # Predecessor A finishes at 10:00; target finish = 10:00 + 0 lag =
        # 10:00; compute_start_at(10:00, 240 min) = 06:00 under the 24h/day
        # wall-clock fallback calendar.
        assert leaf["start_at"] == "2026-01-05T06:00:00"
        assert leaf["finish_at"] == "2026-01-05T10:00:00"


def test_automatic_task_start_finish_predecessor_resolves_exact_calendar_aware_start() -> None:
    """SF (link_type=2) counterpart of the FF test above, anchored on the
    predecessor's start_at instead of its finish_at -- also now exact and
    calendar-aware rather than a raw wall-clock approximation."""
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
        # Predecessor B starts at 12:00; target finish = 12:00 + 30 min lag =
        # 12:30; compute_start_at(12:30, 240 min) = 08:30 under the 24h/day
        # wall-clock fallback calendar.
        assert leaf["start_at"] == "2026-01-05T08:30:00"
        assert leaf["finish_at"] == "2026-01-05T12:30:00"


def test_automatic_task_finish_finish_predecessor_resolves_through_calendar_skipping_weekend() -> (
    None
):
    """FF working-time lag now resolves through the applicable calendar,
    exactly mirroring
    ``test_automatic_task_working_day_lag_format_resolves_through_calendar_skipping_weekend``
    for FS: predecessor A is moved to finish on a Friday, and a 2-working-day
    lag (exceeding a single day's capacity) skips the weekend when computing
    the successor's target finish date.

    Manually verified: target finish = ``_resolve_lag_offset(Friday 08:00,
    840 min, lag_format=7)`` = Friday's 420 min capacity consumed first,
    Sat/Sun contribute nothing, the remaining 420 min consumed on Monday ->
    Monday 15:00:00 (identical to the FS test's predecessor-finish-derived
    constraint, since it is the exact same offset operation). The successor's
    60-minute duration is then walked *backward* from that target finish via
    ``compute_start_at`` -- entirely within Monday's own capacity -> start_at
    = Monday 14:00:00, finish_at = Monday 15:00:00 (round-trips back to the
    target finish, confirming ``compute_start_at`` is ``compute_finish_at``'s
    exact inverse here). The old raw wall-clock approximation
    (``predecessor.finish_at + lag - duration_minutes`` = Friday 08:00 + 840
    min - 60 min = Friday 21:00:00) would have landed on the same Friday,
    never touching the weekend at all -- demonstrating the fix.
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
            link_type=0,
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
        assert leaf["start_at"] == "2026-01-12T14:00:00"
        assert leaf["finish_at"] == "2026-01-12T15:00:00"


def test_automatic_task_start_finish_predecessor_resolves_through_calendar_skipping_weekend() -> (
    None
):
    """SF working-time lead (negative lag) counterpart of the FF weekend test
    above: predecessor B is moved to start on a Monday, and a -2-working-day
    lag retreats the target finish date backward across the weekend to the
    preceding Friday.

    Manually verified: target finish = ``_resolve_lag_offset(Monday 08:00,
    -840 min, lag_format=7)`` = Monday's own 420 min capacity consumed first
    retreating backward, Sat/Sun contribute nothing, the remaining 420 min
    consumed on the preceding Friday -> Friday 01:00:00 (identical to the
    negative-lag FS test's constraint, same offset operation). The
    successor's 60-minute duration is then walked backward from that target
    finish via ``compute_start_at`` -- entirely within Friday's own capacity
    -> start_at = Friday 00:00:00, finish_at = Friday 01:00:00. The old raw
    wall-clock approximation (``predecessor.start_at + lag -
    duration_minutes`` = Monday 08:00 - 840 min - 60 min = Sunday 17:00:00)
    would have landed on the weekend itself -- demonstrating the fix.
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
                .filter(WfPlanningTaskSnapshot.uid == 7)
                .one()
            )
            predecessor.start_at = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)  # Monday
            session.commit()
        # -2 working days = -840 min = -8400 tenths of a minute.
        _add_link(
            planning_id,
            task_uid=3,
            predecessor_uid=7,
            link_type=2,
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
        assert leaf["start_at"] == "2026-01-09T00:00:00"
        assert leaf["finish_at"] == "2026-01-09T01:00:00"


def test_automatic_task_finish_finish_target_on_non_working_day_falls_back_to_monday() -> None:
    """10th E3-03 PR review round: an FF link's target finish date is a lower
    bound ("finishes no earlier than"), not an equality -- exactly like an
    FS/SS link already bounds the successor's *start*. Before this fix, a
    ``target_finish`` landing on a day with zero working capacity made
    ``compute_start_at`` raise ``ValueError`` (no start can produce an exact
    finish on a non-working day), which was surfaced as a 400 even though
    the successor legitimately finishing on the next working day satisfies
    the FF constraint perfectly well.

    Predecessor A is moved to finish on a Friday, and a 1-*elapsed*-day lag
    (raw wall-clock, not calendar-aware -- see ``_is_elapsed_lag_format``)
    lands the target finish on the following Saturday, which has zero
    capacity under the Mon-Fri calendar. ``compute_start_at_for_finish_at_or_after``
    walks the target forward to Monday, where the successor's 60-minute
    duration resolves normally: start_at = Monday 07:00, finish_at = Monday
    08:00 (manually verified against ``compute_start_at_for_finish_at_or_after``
    directly, see ``test_calendar_schedule.py``'s counterpart for the pure
    calendar-primitive-level assertion).
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
        # 1 elapsed day = 1440 min = 14400 tenths of a minute; lag_format
        # omitted (None), which _is_elapsed_lag_format treats as elapsed raw
        # wall-clock -- it is NOT calendar-snapped, so it can (and here does)
        # land on a non-working day.
        _add_link(planning_id, task_uid=3, predecessor_uid=6, link_type=0, lag_tenth_minute=14400)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        assert leaf["start_at"] == "2026-01-12T07:00:00"
        assert leaf["finish_at"] == "2026-01-12T08:00:00"


def test_automatic_task_start_finish_target_on_non_working_day_falls_back_to_monday() -> None:
    """SF (link_type=2) counterpart of the FF non-working-day fallback test
    above -- same underlying bug (10th E3-03 PR review round), same fix,
    anchored on the predecessor's ``start_at`` instead of its ``finish_at``.
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
                .filter(WfPlanningTaskSnapshot.uid == 7)
                .one()
            )
            predecessor.start_at = datetime(2026, 1, 9, 8, 0, tzinfo=UTC)  # Friday
            session.commit()
        # 1 elapsed day = 1440 min = 14400 tenths of a minute, same as the FF
        # test above -- target_finish also lands on the following Saturday.
        _add_link(planning_id, task_uid=3, predecessor_uid=7, link_type=2, lag_tenth_minute=14400)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={"is_manual": False, "duration_minutes": 60},
            headers=headers,
        )

        assert response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], response.json()))[3]
        assert leaf["start_at"] == "2026-01-12T07:00:00"
        assert leaf["finish_at"] == "2026-01-12T08:00:00"


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


def test_editing_predecessor_reschedules_automatic_successor() -> None:
    """Issue #73 ("Automatic-mode successors are not rescheduled when their
    predecessor's dates change"): editing a task now cascades forward to
    every automatic-mode successor transitively affected by it (see
    ``_cascade_successor_schedules``), not just its summary *ancestors*.

    uid=3 (Leaf) is first put in automatic mode with an FS link on uid=6
    (Predecessor A), landing on dates consistent with its constraint.
    Predecessor A is then edited (as a manual task) to finish much later, in
    the same request/response uid=3 must be rescheduled to respect its own
    FS constraint against the new date -- this replaces the previous
    "Known v1 limitation" regression test that froze the non-cascading
    behaviour.
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

        # uid=3 is rescheduled by the same request: it now respects its FS
        # constraint against uid=6's new finish_at (09:00 + 30 min lag).
        leaf_after = _tasks_by_uid(cast(dict[str, Any], predecessor_response.json()))[3]
        assert leaf_after["start_at"] == "2026-02-01T09:30:00"
        assert leaf_after["finish_at"] == "2026-02-01T13:30:00"
        assert leaf_after["is_manual"] is False


def test_automatic_task_schedule_cascades_across_a_chain() -> None:
    """A -> B -> C (uid=6 -> uid=8 -> uid=9), all automatic via FS: editing A
    alone cascades across the whole chain in a single request, proving the
    cascade is not limited to A's immediate successors.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add_all(
                [
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=8,
                        name="B",
                        position=5,
                        start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
                        duration_minutes=180,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=False,
                    ),
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=9,
                        name="C",
                        position=6,
                        start_at=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
                        duration_minutes=60,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=False,
                    ),
                ]
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)
        _add_link(planning_id, task_uid=9, predecessor_uid=8, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        # B: FS from A, lag 0 => starts exactly when A finishes.
        assert tasks[8]["is_manual"] is False
        assert tasks[8]["start_at"] == "2026-03-02T10:00:00"
        assert tasks[8]["finish_at"] == "2026-03-02T13:00:00"
        # C: FS from B, lag 0 => starts exactly when B (already rescheduled) finishes.
        assert tasks[9]["is_manual"] is False
        assert tasks[9]["start_at"] == "2026-03-02T13:00:00"
        assert tasks[9]["finish_at"] == "2026-03-02T14:00:00"


def test_automatic_task_schedule_cascades_diamond_using_both_updated_predecessors() -> None:
    """A -> {B, C}, {B, C} -> D (uid=6 -> {uid=8, uid=9} -> uid=10): a single
    edit to A must recompute D exactly once, using both B's and C's already
    -updated dates. B and C use different link types (FS/SS) so getting the
    recompute order wrong (D recomputed against a stale B or C) produces a
    detectably different result than getting it right.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add_all(
                [
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=8,
                        name="B",
                        position=5,
                        start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
                        duration_minutes=60,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=False,
                    ),
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=9,
                        name="C",
                        position=6,
                        start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
                        duration_minutes=360,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=False,
                    ),
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=10,
                        name="D",
                        position=7,
                        start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 5, 8, 30, tzinfo=UTC),
                        duration_minutes=30,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=False,
                    ),
                ]
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)
        _add_link(planning_id, task_uid=9, predecessor_uid=6, link_type=3, lag_tenth_minute=0)
        _add_link(planning_id, task_uid=10, predecessor_uid=8, link_type=1, lag_tenth_minute=0)
        _add_link(planning_id, task_uid=10, predecessor_uid=9, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        # B: FS from A, lag 0 => starts when A finishes (10:00), 60 min duration.
        assert tasks[8]["is_manual"] is False
        assert tasks[8]["start_at"] == "2026-03-02T10:00:00"
        assert tasks[8]["finish_at"] == "2026-03-02T11:00:00"
        # C: SS from A, lag 0 => starts when A starts (08:00), 360 min duration.
        assert tasks[9]["is_manual"] is False
        assert tasks[9]["start_at"] == "2026-03-02T08:00:00"
        assert tasks[9]["finish_at"] == "2026-03-02T14:00:00"
        # D: FS from both B (finishes 11:00) and C (finishes 14:00) -- the
        # max of the two, which requires both to already carry their updated
        # (not stale, pre-cascade) finish_at when D is recomputed.
        assert tasks[10]["is_manual"] is False
        assert tasks[10]["start_at"] == "2026-03-02T14:00:00"
        assert tasks[10]["finish_at"] == "2026-03-02T14:30:00"


def test_manual_successor_is_never_rescheduled_when_predecessor_changes() -> None:
    """A manual task's dates are frozen: they must stay verbatim even when an
    automatic predecessor it references moves as part of the same request.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)
        _add_link(planning_id, task_uid=3, predecessor_uid=6, link_type=1, lag_tenth_minute=0)

        manual_response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-01-10T08:00:00Z",
                "finish_at": "2026-01-10T09:00:00Z",
            },
            headers=headers,
        )
        assert manual_response.status_code == 200

        predecessor_response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert predecessor_response.status_code == 200
        leaf = _tasks_by_uid(cast(dict[str, Any], predecessor_response.json()))[3]
        assert leaf["is_manual"] is True
        assert leaf["start_at"] == "2026-01-10T08:00:00"
        assert leaf["finish_at"] == "2026-01-10T09:00:00"


def test_manual_successor_interrupts_cascade_but_a_second_live_predecessor_still_reschedules() -> (
    None
):
    """A (automatic, uid=6) -> B (manual, uid=8) -> C (automatic, uid=9), all
    FS links. Editing A must NOT recompute B (manual, frozen) and must NOT
    recompute C *through* B (B never moved, nothing to propagate through
    it). But C also has an independent, second automatic predecessor -- A
    itself, uid=6 -- so C must still be recomputed, via that other live
    edge, not via B.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add_all(
                [
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=8,
                        name="B",
                        position=5,
                        start_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
                        duration_minutes=60,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=True,
                    ),
                    WfPlanningTaskSnapshot(
                        planning_id=planning_id,
                        uid=9,
                        name="C",
                        position=6,
                        start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                        finish_at=datetime(2026, 1, 5, 9, 30, tzinfo=UTC),
                        duration_minutes=90,
                        is_summary=False,
                        is_milestone=False,
                        is_manual=False,
                    ),
                ]
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)
        _add_link(planning_id, task_uid=9, predecessor_uid=8, link_type=1, lag_tenth_minute=0)
        # C's second, independent predecessor: A itself, with a 180 min lag.
        _add_link(planning_id, task_uid=9, predecessor_uid=6, link_type=1, lag_tenth_minute=1800)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        # B (manual) is untouched.
        assert tasks[8]["is_manual"] is True
        assert tasks[8]["start_at"] == "2026-01-10T08:00:00"
        assert tasks[8]["finish_at"] == "2026-01-10T09:00:00"
        # C is rescheduled via its direct link to A (10:00 + 180 min lag =
        # 13:00), not via B's stale constraint (09:00, via B's own FS lag 0)
        # -- the max of the two is 13:00, which can only come from A.
        assert tasks[9]["start_at"] == "2026-03-02T13:00:00"
        assert tasks[9]["finish_at"] == "2026-03-02T14:30:00"


def test_cascade_leaves_a_successor_with_unset_is_manual_untouched() -> None:
    """Reviewer finding #1: ``is_manual`` is nullable (``WfPlanningTaskSnapshot.is_manual:
    Mapped[bool | None]``) and genuinely ``NULL`` in real data (MS Project XML
    import leaves it unset when the ``<Manual>`` element is absent -- see
    ``_seed_hierarchy``'s own uid=4 fixture above, which never sets it
    either). A falsy check (``successor.is_manual``) would wrongly treat
    ``None`` the same as ``False`` (confirmed automatic) and pull an
    undecided task into the cascade. uid=8 here is seeded exactly like
    uid=4 -- ``is_manual`` simply never passed -- linked as an FS successor
    of uid=6, which is then edited; uid=8 must stay a dead end: its stored
    dates untouched and ``is_manual`` still ``None`` in the response.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning_id,
                    uid=8,
                    name="Undecided successor",
                    position=5,
                    start_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
                    duration_minutes=60,
                    is_summary=False,
                    is_milestone=False,
                    # is_manual deliberately omitted -- stays NULL, matching
                    # _seed_hierarchy's own uid=4 fixture pattern.
                )
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        successor = tasks[8]
        assert successor["is_manual"] is None
        assert successor["start_at"] == "2026-01-10T08:00:00"
        assert successor["finish_at"] == "2026-01-10T09:00:00"
        # An unrelated fixture task not reachable by any added link stays
        # completely untouched too.
        assert tasks[4]["start_at"] == "2026-01-06T08:00:00"
        assert tasks[4]["finish_at"] == "2026-01-08T08:00:00"


def test_cascade_successor_with_out_of_range_stored_duration_returns_400_not_500() -> None:
    """Reviewer finding #2: constructing the synthetic
    ``PlanningTaskScheduleUpdate`` for a cascade successor reads
    ``duration_minutes`` straight from the database, which has no
    upper-bound CHECK constraint and can exceed the schema's
    ``le=7_884_000`` bound (e.g. data imported before that bound existed, or
    via ``msproject_xml.parse_duration``, which has no equivalent limit).
    uid=8 here stores a duration far above that bound; linking it as an FS
    successor of uid=6 and then editing uid=6 must surface the module's own
    documented 400 (``PlanningTaskScheduleError``), never an uncaught
    ``pydantic.ValidationError`` 500.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning_id,
                    uid=8,
                    name="Out-of-range successor",
                    position=5,
                    start_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
                    duration_minutes=8_000_000,
                    is_summary=False,
                    is_milestone=False,
                    is_manual=False,
                )
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        assert "8" in body["detail"]


def test_cascade_milestone_successor_ignores_stray_stored_duration() -> None:
    """Reviewer finding #3: a milestone's synthetic payload used to always
    include ``duration_minutes=candidate.duration_minutes``, which puts
    ``"duration_minutes"`` in ``payload.model_fields_set`` and makes
    ``_check_milestone_duration_and_finish_consistency`` reject the whole
    cascade whenever a milestone successor happens to carry a stray non-zero
    stored value (e.g. drifted import data) -- even though the caller never
    touched that milestone and a milestone's duration is always
    definitionally 0. uid=8 here is an automatic-mode milestone successor of
    uid=6 with a stray ``duration_minutes=45`` left over from prior data;
    editing uid=6 must still succeed and land the milestone at duration 0.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning_id,
                    uid=8,
                    name="Drifted milestone successor",
                    position=5,
                    start_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    duration_minutes=45,
                    is_summary=False,
                    is_milestone=True,
                    is_manual=False,
                )
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        milestone = tasks[8]
        assert milestone["is_manual"] is False
        assert milestone["duration_minutes"] == 0
        assert milestone["start_at"] == milestone["finish_at"] == "2026-03-02T10:00:00"


def test_cascade_successor_with_zero_stored_duration_returns_400_attributed_to_candidate() -> None:
    """Cross-cutting review finding (Haute): a cascade candidate's own
    pre-existing degenerate stored data must not surface as an unattributed
    400 that looks like it is about the caller's own (perfectly valid)
    request. uid=8 here is an automatic-mode FS successor of uid=6 with
    ``duration_minutes=0`` -- realistic imported data, since MS Project XML
    import writes ``duration_minutes=None`` (and, by the same mechanism, can
    round-trip to 0) whenever the ``<Duration>`` element is absent, with
    ``is_manual`` set independently and no cross-check. That value passes the
    request schema's own ``Field(ge=0, ...)`` validation cleanly (0 is
    in-range), so it is never caught by the ``ValidationError`` branch in
    ``_cascade_successor_schedules`` -- it only trips
    ``_apply_automatic_schedule``'s own internal
    ``duration_minutes<=0`` check. Editing uid=6 (an otherwise-valid,
    unrelated manual-mode edit) must surface a 400 whose message identifies
    uid=8 as the source, not a bare, unattributed
    "An automatically scheduled task requires a positive duration_minutes".
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning_id,
                    uid=8,
                    name="Degenerate-duration successor",
                    position=5,
                    start_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    duration_minutes=0,
                    is_summary=False,
                    is_milestone=False,
                    is_manual=False,
                )
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=6, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 6),
            json={
                "is_manual": True,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-02T10:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body
        # Must identify uid=8 as the source of the failure, not a bare,
        # unattributed message that looks like it is about the caller's own
        # (valid) request against uid=6.
        assert "8" in body["detail"]
        assert "positive duration_minutes" in body["detail"]


def test_cascade_does_not_propagate_through_a_summary_task_acting_as_a_predecessor() -> None:
    """Cross-cutting review finding (Moyenne, documented known limitation,
    NOT a defect fixed by this ticket): the issue #73 cascade only walks
    forward from the edited task's own uid via direct
    ``WfPlanningLinkSnapshot`` edges (see ``_discover_cascade_candidates``).
    It does not reach a task whose ``predecessor_uid`` points at a
    *summary* task, even when the edit changes that summary's own aggregate
    ``start_at``/``finish_at`` via ``_recalculate_ancestor_summaries`` (which
    runs after the cascade). Nothing in ``planning_links.py``'s validation
    prevents a predecessor link from referencing a summary task.

    uid=2 (Mid) is a summary task with children uid=3 (Leaf) and uid=4 (Leaf
    sibling, fixed dates). uid=8 (Y) is a separate automatic-mode task with
    an FS link whose ``predecessor_uid`` is uid=2 (Mid) directly. Editing
    uid=3 (X) moves Mid's aggregate ``finish_at`` forward, but Y is NOT
    rescheduled by this request -- this test freezes that known gap rather
    than leaving it silently unverified, matching this repo's established
    convention (e.g. the original
    ``test_editing_predecessor_does_not_reschedule_automatic_successor``
    before issue #73 closed the direct-predecessor case). Closing this gap
    is a materially larger, separate change (cascading through
    summary-derived date changes) and is left as a candidate follow-up.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning_id,
                    uid=8,
                    name="Y",
                    position=5,
                    start_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 10, 9, 0, tzinfo=UTC),
                    duration_minutes=60,
                    is_summary=False,
                    is_milestone=False,
                    is_manual=False,
                )
            )
            session.commit()
        # Y's predecessor link points directly at uid=2 (Mid), a summary
        # task -- not at any of Mid's individual children.
        _add_link(planning_id, task_uid=8, predecessor_uid=2, link_type=1, lag_tenth_minute=0)

        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-02-01T08:00:00Z",
                "finish_at": "2026-02-01T09:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        # Mid's aggregate finish_at did move, past uid=4's own 2026-01-08
        # finish_at, because uid=3 now finishes later.
        assert tasks[2]["finish_at"] == "2026-02-01T09:00:00"
        # But Y -- whose predecessor link points at Mid, not at uid=3
        # directly -- is left completely untouched by this cascade.
        assert tasks[8]["is_manual"] is False
        assert tasks[8]["start_at"] == "2026-01-10T08:00:00"
        assert tasks[8]["finish_at"] == "2026-01-10T09:00:00"


def test_editing_a_milestone_cascades_to_its_own_automatic_successor() -> None:
    """Basse-severity gap: every existing cascade test edits a plain task as
    the predecessor that triggers the cascade; none edit a *milestone* as
    the edited task itself. uid=5 (Milestone, seeded by ``_seed_hierarchy``
    with no dates) is scheduled manually, then a separate automatic-mode FS
    successor (uid=8) must cascade to respect the milestone's new date in
    the same request.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        with get_session_factory()() as session:
            session.add(
                WfPlanningTaskSnapshot(
                    planning_id=planning_id,
                    uid=8,
                    name="Milestone successor",
                    position=5,
                    start_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
                    finish_at=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
                    duration_minutes=60,
                    is_summary=False,
                    is_milestone=False,
                    is_manual=False,
                )
            )
            session.commit()
        _add_link(planning_id, task_uid=8, predecessor_uid=5, link_type=1, lag_tenth_minute=300)

        response = client.patch(
            _schedule_path(project_id, planning_id, 5),
            json={"is_manual": True, "start_at": "2026-03-02T08:00:00Z"},
            headers=headers,
        )

        assert response.status_code == 200
        tasks = _tasks_by_uid(cast(dict[str, Any], response.json()))
        milestone = tasks[5]
        assert milestone["is_manual"] is True
        assert milestone["start_at"] == milestone["finish_at"] == "2026-03-02T08:00:00"
        # uid=8: FS from the milestone, +30 min lag => starts at 08:30,
        # 60 min duration => finishes at 09:30, rescheduled in the same
        # request as the milestone's own edit.
        successor = tasks[8]
        assert successor["is_manual"] is False
        assert successor["start_at"] == "2026-03-02T08:30:00"
        assert successor["finish_at"] == "2026-03-02T09:30:00"


def test_topological_cascade_order_detects_residual_cycle_without_hanging() -> None:
    """Focused unit test of the Kahn's-algorithm helper extracted for issue
    #73's cascade (``_topological_cascade_order``), bypassing the public API
    -- which can never itself produce a cyclic predecessor graph, since
    ``planning_links._validate_no_cycles`` already rejects that at
    link-write time. Feeds a synthetic 2-cycle directly to confirm the
    helper terminates (rather than hanging) and raises a
    ``PlanningTaskScheduleError`` naming the unresolved tasks, instead of
    silently dropping them from the cascade.
    """
    link_100_from_101 = WfPlanningLinkSnapshot(
        planning_id=1, task_uid=100, predecessor_uid=101, link_type=1, lag_tenth_minute=0
    )
    link_101_from_100 = WfPlanningLinkSnapshot(
        planning_id=1, task_uid=101, predecessor_uid=100, link_type=1, lag_tenth_minute=0
    )
    links_by_task = {100: [link_100_from_101], 101: [link_101_from_100]}

    with pytest.raises(PlanningTaskScheduleError, match="cycle"):
        _topological_cascade_order(
            edited_task_uid=1, candidates={100, 101}, links_by_task=links_by_task
        )


def test_topological_cascade_order_detects_residual_cycle_back_to_edited_task() -> None:
    """PR #81 Copilot review finding: a residual cycle that loops back to
    ``edited_task_uid`` itself (rather than being fully contained within
    ``candidates``) must also be caught, not silently treated as resolved.

    Reproduces ``edited -> B -> edited``: task ``B`` (uid 200) has a
    predecessor link on the edited task (uid 1), and the edited task has its
    own predecessor link on B. Before this fix, ``B``'s in-degree was 1
    (from the edited task), got released unconditionally by
    ``_release(edited_task_uid)``, and the function returned ``[200]``
    successfully -- even though the edited task's own already-applied
    schedule was computed against B's stale, pre-cascade dates, and B's edge
    back to the edited task was never inspected at all.
    """
    link_200_from_edited = WfPlanningLinkSnapshot(
        planning_id=1, task_uid=200, predecessor_uid=1, link_type=1, lag_tenth_minute=0
    )
    link_edited_from_200 = WfPlanningLinkSnapshot(
        planning_id=1, task_uid=1, predecessor_uid=200, link_type=1, lag_tenth_minute=0
    )
    links_by_task = {200: [link_200_from_edited], 1: [link_edited_from_200]}

    with pytest.raises(PlanningTaskScheduleError, match="cycle"):
        _topological_cascade_order(edited_task_uid=1, candidates={200}, links_by_task=links_by_task)


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


def test_manual_task_near_date_max_recalculating_ancestor_summary_returns_400_not_500() -> None:
    """Round-4 E3-03 PR review finding: ``compute_working_minutes_between``
    (used by ``_recalculate_summary_fields``, which
    ``_recalculate_ancestor_summaries`` reuses to keep a summary ancestor's
    ``duration_minutes`` in sync after a schedule edit) walks the calendar
    day by day exactly like ``compute_finish_at``/``compute_start_at``, but
    -- unlike those two -- had no iteration ceiling of its own. A manually
    scheduled task's ``start_at``/``finish_at`` is stored verbatim with no
    server-side range validation (see ``_apply_manual_schedule``), so a
    child dated near ``date.max`` under a summary parent makes this
    unbounded walk reachable through the ordinary schedule-edit endpoint.
    This must surface as the 400 already documented for an invalid
    schedule, not leak as an uncaught 500, and must return promptly rather
    than looping for an unreasonable number of iterations.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_hierarchy(project_id)

        # uid=3 (Leaf) is a child of uid=2 (Mid, summary), itself a child of
        # uid=1 (Root, summary): its finish_at feeds directly into both
        # ancestors' max(finish_dates) recalculation.
        response = client.patch(
            _schedule_path(project_id, planning_id, 3),
            json={
                "is_manual": True,
                "start_at": "2026-01-05T08:00:00Z",
                "finish_at": "9999-12-31T00:00:00Z",
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
