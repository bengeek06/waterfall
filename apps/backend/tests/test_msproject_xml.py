import pytest

from waterfall.services.msproject_xml import MsProjectValidationError, parse_msproject_xml


def _xml(tasks: str, namespace: str = "http://schemas.microsoft.com/project") -> bytes:
    return f"""<Project xmlns=\"{namespace}\"><SaveVersion>16</SaveVersion><MinutesPerDay>480</MinutesPerDay><Tasks>{tasks}</Tasks></Project>""".encode()


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
        _xml(
            "<Task><UID>1</UID><ID>1</ID><Name>A</Name><Duration>PT8H</Duration></Task>"
        )
    )
    assert parsed.tasks[0].duration_minutes == 480
