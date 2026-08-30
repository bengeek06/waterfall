import pytest

from waterfall.services.msproject_xml import (
    MsProjectValidationError,
    parse_msproject_xml,
    validate_canonical_xml,
)


def _xml(tasks: str, namespace: str = "http://schemas.microsoft.com/project") -> bytes:
    return (
        f'<Project xmlns="{namespace}"><SaveVersion>16</SaveVersion>'
        f"<MinutesPerDay>480</MinutesPerDay><Tasks>{tasks}</Tasks></Project>"
    ).encode()


def test_validator_rejects_duplicate_uid_and_orphan_link() -> None:
    task = """
    <Task><UID>1</UID><ID>1</ID><Name>A</Name><OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel>
      <PredecessorLink><PredecessorUID>9</PredecessorUID><Type>1</Type></PredecessorLink>
    </Task>
    <Task><UID>1</UID><ID>2</ID><Name>B</Name></Task>
    """
    with pytest.raises(MsProjectValidationError) as error:
        parse_msproject_xml(_xml(task))
    codes = {issue["code"] for issue in error.value.issues}
    assert {"DUPLICATE_UID", "ORPHAN_LINK"} <= codes


def test_validator_rejects_cycles_and_bad_namespace() -> None:
    task = """
    <Task><UID>1</UID><ID>1</ID><Name>A</Name><PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type></PredecessorLink></Task>
    <Task><UID>2</UID><ID>2</ID><Name>B</Name><PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type></PredecessorLink></Task>
    """
    with pytest.raises(MsProjectValidationError) as error:
        parse_msproject_xml(_xml(task, "https://invalid.example/project"))
    codes = {issue["code"] for issue in error.value.issues}
    assert {"UNSUPPORTED_NAMESPACE", "DEPENDENCY_CYCLE"} <= codes


def test_validator_parses_iso_duration() -> None:
    parsed = parse_msproject_xml(
        b'<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><ID>1</ID><Name>A</Name><Duration>PT8H</Duration></Task></Tasks></Project>'
    )
    assert parsed.tasks[0].duration_minutes == 480


def test_canonical_schema_accepts_minimal_project() -> None:
    xml = b'<Project xmlns="http://schemas.microsoft.com/project/2007"><SaveVersion>16</SaveVersion><ScheduleFromStart>true</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate><Tasks><Task><UID>1</UID><Name>One</Name><Duration>PT480M</Duration></Task></Tasks></Project>'
    validate_canonical_xml(xml)


def test_parser_reports_non_blocking_warning_for_custom_calendars() -> None:
    task = "<Task><UID>1</UID><ID>1</ID><Name>A</Name></Task>"
    xml = (
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart>"
        "<StartDate>2026-01-01T08:00:00</StartDate><MinutesPerDay>480</MinutesPerDay>"
        "<Calendars>"
        "<Calendar><UID>999</UID><Name>Source calendar</Name></Calendar>"
        "</Calendars>"
        f"<Tasks>{task}</Tasks></Project>"
    ).encode()

    parsed = parse_msproject_xml(xml)

    assert len(parsed.warnings) == 1
    assert parsed.warnings[0]["code"] == "CUSTOM_CALENDARS_IGNORED"


def test_parser_accepts_realistic_calendar_exception_day_and_warns() -> None:
    # Regression test for a real MS Project export: a "country" calendar
    # almost always encodes public holidays as a DayType=0 exception WeekDay
    # with a TimePeriod, and the calendar itself commonly carries
    # IsBaseCalendar/BaseCalendarUID. The canonical XSD must tolerate this
    # shape structurally (E5-02 does not read these fields) so the file is
    # never rejected before the non-blocking CUSTOM_CALENDARS_IGNORED
    # diagnostic can be raised.
    task = "<Task><UID>1</UID><ID>1</ID><Name>A</Name></Task>"
    xml = (
        '<Project xmlns="http://schemas.microsoft.com/project/2007">'
        "<SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart>"
        "<StartDate>2026-01-01T08:00:00</StartDate><MinutesPerDay>480</MinutesPerDay>"
        "<Calendars>"
        "<Calendar>"
        "<UID>999</UID><Name>Calendrier France</Name>"
        "<IsBaseCalendar>1</IsBaseCalendar>"
        "<WeekDays>"
        "<WeekDay>"
        "<DayType>0</DayType><DayWorking>0</DayWorking>"
        "<TimePeriod><FromDate>2026-01-01T00:00:00</FromDate>"
        "<ToDate>2026-01-01T00:00:00</ToDate></TimePeriod>"
        "</WeekDay>"
        "</WeekDays>"
        "</Calendar>"
        "</Calendars>"
        f"<Tasks>{task}</Tasks></Project>"
    ).encode()

    parsed = parse_msproject_xml(xml)

    assert len(parsed.warnings) == 1
    assert parsed.warnings[0]["code"] == "CUSTOM_CALENDARS_IGNORED"


def test_parser_reports_no_warning_without_calendars_block() -> None:
    task = "<Task><UID>1</UID><ID>1</ID><Name>A</Name></Task>"
    xml = (
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<SaveVersion>16</SaveVersion><ScheduleFromStart>1</ScheduleFromStart>"
        "<StartDate>2026-01-01T08:00:00</StartDate><MinutesPerDay>480</MinutesPerDay>"
        f"<Tasks>{task}</Tasks></Project>"
    ).encode()

    parsed = parse_msproject_xml(xml)

    assert parsed.warnings == ()
