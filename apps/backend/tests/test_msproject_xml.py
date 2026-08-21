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
