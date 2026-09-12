"""Issue #176: calendar-mismatch diagnostic in build_import_diff.

Exercises services.import_diff.build_import_diff directly against a
hand-built ParsedProject/ParsedTask, rather than round-tripping through a
real MS Project XML file, so each scenario can pin exact start_at/finish_at/
duration_minutes combinations without fighting the XML schema.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject
from waterfall.models.resources import Calendar, CalendarWeekday
from waterfall.schemas.imports import ImportDiffItem
from waterfall.services.import_diff import build_import_diff
from waterfall.services.msproject_xml import ParsedProject, ParsedTask

# Standard Mon-Fri 8h/day calendar, flagged as the org-wide default.
_STANDARD_HOURS = {
    day_type: Decimal("0.00") if day_type in (1, 7) else Decimal("8.00") for day_type in range(1, 8)
}


def _create_default_calendar() -> None:
    with get_session_factory()() as session:
        calendar = Calendar(code="STANDARD", name="Standard", weeks_per_year=52, is_default=True)
        session.add(calendar)
        session.flush()
        session.add_all(
            CalendarWeekday(calendar_id=calendar.id, day_type=day_type, hours_per_day=hours)
            for day_type, hours in _STANDARD_HOURS.items()
        )
        session.commit()


def _create_project() -> int:
    with get_session_factory()() as session:
        project = MsProject(
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Calendar mismatch diagnostic test",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, 8, tzinfo=UTC),
            finish_date=datetime(2026, 1, 31, 18, tzinfo=UTC),
            calendar_uid=None,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.commit()
        return project.id


def _task(
    uid: int,
    *,
    name: str = "Task",
    outline_number: str | None = None,
    is_summary: bool = False,
    is_manual: bool | None = False,
    start_at: datetime | None = None,
    finish_at: datetime | None = None,
    duration_minutes: int | None = None,
) -> ParsedTask:
    return ParsedTask(
        uid=uid,
        id_display=uid,
        name=name,
        task_type=1,
        outline_number=outline_number,
        outline_level=outline_number.count(".") + 1 if outline_number else None,
        wbs=None,
        start_at=start_at,
        finish_at=finish_at,
        duration_minutes=duration_minutes,
        duration_format=None,
        percent_complete=0,
        is_summary=is_summary,
        is_milestone=False,
        is_manual=is_manual,
        calendar_uid=None,
        notes=None,
    )


def _parsed_project(tasks: tuple[ParsedTask, ...]) -> ParsedProject:
    return ParsedProject(
        namespace="http://schemas.microsoft.com/project/2007",
        save_version=16,
        source_version=2016,
        external_uid=None,
        name="Calendar mismatch diagnostic test",
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, 8, tzinfo=UTC),
        finish_date=None,
        calendar_uid=None,
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
        currency_code="EUR",
        tasks=tasks,
        links=(),
    )


def _mismatch_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [item for item in items if item["kind"] == "calendar_mismatch"]


def test_automatic_leaf_task_duration_mismatch_is_flagged() -> None:
    _create_default_calendar()
    project_id = _create_project()
    monday_08 = datetime(2026, 1, 5, 8, 0)
    # duration_minutes (480 = one working day) is inconsistent with the
    # file's own finish_at, which spans two working days under the standard
    # calendar (Monday 08:00 -> Tuesday 16:00).
    tasks = (
        _task(
            uid=1,
            outline_number="1",
            start_at=monday_08,
            finish_at=datetime(2026, 1, 6, 16, 0),
            duration_minutes=480,
        ),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    mismatches = _mismatch_items(items)
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert mismatch["uid"] == 1
    assert mismatch["fields"] == ["duration_minutes"]
    payload = cast(dict[str, Any], mismatch["calendar_mismatch"])
    assert payload["task_uid"] == 1
    assert payload["file_duration_minutes"] == 480
    assert payload["expected_duration_minutes"] == 960

    # Round-trips through the actual response schema (issue #176 also fixed
    # ImportDiffItem's populate_by_name so this payload is not silently
    # dropped, the same latent bug link_changes already had).
    validated = ImportDiffItem(**cast(dict[str, Any], mismatch))
    assert validated.calendar_mismatch is not None
    assert validated.calendar_mismatch.file_duration_minutes == 480
    assert validated.calendar_mismatch.expected_duration_minutes == 960


def test_summary_task_duration_mismatch_uses_children_span_from_file() -> None:
    _create_default_calendar()
    project_id = _create_project()
    tasks = (
        _task(
            uid=1,
            outline_number="1",
            is_summary=True,
            duration_minutes=500,  # wrong: real span below is 960 minutes
        ),
        _task(
            uid=2,
            outline_number="1.1",
            start_at=datetime(2026, 1, 5, 8, 0),
            finish_at=datetime(2026, 1, 5, 16, 0),
            duration_minutes=480,
        ),
        _task(
            uid=3,
            outline_number="1.2",
            start_at=datetime(2026, 1, 6, 8, 0),
            finish_at=datetime(2026, 1, 6, 16, 0),
            duration_minutes=480,
        ),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    mismatches = _mismatch_items(items)
    assert [item["uid"] for item in mismatches] == [1]
    payload = cast(dict[str, Any], mismatches[0]["calendar_mismatch"])
    assert payload["file_duration_minutes"] == 500
    assert payload["expected_duration_minutes"] == 960

    validated = ImportDiffItem(**cast(dict[str, Any], mismatches[0]))
    assert validated.calendar_mismatch is not None
    assert validated.calendar_mismatch.expected_duration_minutes == 960


def test_summary_task_child_without_dates_is_ignored_not_excluded() -> None:
    """One child lacking dates does not disqualify the summary task -- only
    the aggregate span ending up empty (no child with dates at all) does, per
    _recalculate_summary_dates's own guard."""
    _create_default_calendar()
    project_id = _create_project()
    tasks = (
        _task(uid=1, outline_number="1", is_summary=True, duration_minutes=500),
        _task(
            uid=2,
            outline_number="1.1",
            start_at=datetime(2026, 1, 5, 8, 0),
            finish_at=datetime(2026, 1, 5, 16, 0),
            duration_minutes=480,
        ),
        # No start_at/finish_at at all -- must not exclude the summary task.
        _task(uid=3, outline_number="1.2", duration_minutes=None),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    mismatches = _mismatch_items(items)
    assert [item["uid"] for item in mismatches] == [1]
    payload = cast(dict[str, Any], mismatches[0]["calendar_mismatch"])
    # Span collapses to the single dated child: 480 minutes expected.
    assert payload["expected_duration_minutes"] == 480


def test_manually_scheduled_task_is_never_flagged() -> None:
    _create_default_calendar()
    project_id = _create_project()
    tasks = (
        _task(
            uid=1,
            outline_number="1",
            is_manual=True,
            start_at=datetime(2026, 1, 5, 8, 0),
            finish_at=datetime(2026, 1, 6, 16, 0),
            duration_minutes=480,
        ),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    assert _mismatch_items(items) == []


def test_task_with_undecided_is_manual_is_treated_like_manual() -> None:
    """is_manual=None (MS Project never wrote a <Manual> element at all) must
    be treated exactly like True, not falsy-coerced into "automatic"."""
    _create_default_calendar()
    project_id = _create_project()
    tasks = (
        _task(
            uid=1,
            outline_number="1",
            is_manual=None,
            start_at=datetime(2026, 1, 5, 8, 0),
            finish_at=datetime(2026, 1, 6, 16, 0),
            duration_minutes=480,
        ),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    assert _mismatch_items(items) == []


def test_task_without_resolvable_calendar_is_omitted_without_raising() -> None:
    # Deliberately no default calendar at all in the system.
    project_id = _create_project()
    tasks = (
        _task(
            uid=1,
            outline_number="1",
            start_at=datetime(2026, 1, 5, 8, 0),
            finish_at=datetime(2026, 1, 6, 16, 0),
            duration_minutes=480,
        ),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    assert _mismatch_items(items) == []
    # The import itself is unaffected: the task still shows up as "added".
    assert {(item["kind"], item["uid"]) for item in items} == {("added", 1)}


def test_consistent_file_produces_no_calendar_mismatch_items() -> None:
    _create_default_calendar()
    project_id = _create_project()
    tasks = (
        _task(
            uid=1,
            outline_number="1",
            is_summary=True,
            duration_minutes=960,
        ),
        _task(
            uid=2,
            outline_number="1.1",
            start_at=datetime(2026, 1, 5, 8, 0),
            finish_at=datetime(2026, 1, 5, 16, 0),
            duration_minutes=480,
        ),
        _task(
            uid=3,
            outline_number="1.2",
            start_at=datetime(2026, 1, 6, 8, 0),
            finish_at=datetime(2026, 1, 6, 16, 0),
            duration_minutes=480,
        ),
    )

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        items = build_import_diff(session, project, _parsed_project(tasks))

    assert _mismatch_items(items) == []


def test_a_cost_loss_with_no_removed_item_to_appear_on_is_still_served(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#332 review, M1 and its round-3 correction: degrade, do not answer 500.

    The safeguard joins two sources of truth by an external uid: the losses are
    computed against the **revision** the confirmed run writes into, the ``removed``
    items against the **displayed legacy planning**. A uid the first knows and the
    second does not has no item of its own to hang its warning on.

    An earlier version of this test claimed the state was unreachable through the
    API. It is not: ``POST /projects/{id}/plannings/{planning_id}/display`` puts back
    any planning of the project, older uid set included, and
    ``test_a_loss_the_displayed_planning_cannot_attribute_is_degraded_not_five_hundred``
    in ``test_revision_import.py`` walks the whole sequence through endpoints
    answering 200/202 only.

    What is pinned here is the *shape* of the degradation on the function's own
    seam: the loss is attributed to a synthesised ``removed`` item instead of being
    dropped, nothing raises, and a WARNING names the uids for whoever has to fix the
    join -- #333 is the issue that rebuilds it.
    """
    _create_default_calendar()
    project_id = _create_project()
    tasks = (_task(uid=1, outline_number="1"),)
    orphaned_losses: dict[int, list[dict[str, object]]] = {
        7: [
            {
                "node_id": 42,
                "work_item_id": 7,
                "label": "Cables",
                "nature": "non_labor",
                "amount": Decimal("300.00"),
                "bearing_task_name": "T7",
            }
        ]
    }

    with get_session_factory()() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        with caplog.at_level(logging.WARNING, logger="waterfall.services.import_diff"):
            items = build_import_diff(
                session, project, _parsed_project(tasks), cost_losses=orphaned_losses
            )

    removed = [item for item in items if item["kind"] == "removed"]
    assert [item["uid"] for item in removed] == [7]
    assert removed[0]["cost_losses"] == orphaned_losses[7]
    assert "displayed planning does not carry it" in cast(str, removed[0]["message"])
    # WARNING, not ERROR (#332 review, B-2): the condition is reached by a supported
    # user action (redisplaying an older planning), so it must not trip an
    # ERROR-keyed alerting rule. The level is asserted, not just the message, so a
    # future promotion back to ERROR fails here rather than in production alerting.
    assert [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ] == ["import_diff.cost_loss_unattributed uids=[7]"]
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
