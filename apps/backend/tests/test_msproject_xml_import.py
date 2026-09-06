from datetime import UTC, datetime
from pathlib import Path

import pytest

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.msproject_xml import MsProjectValidationError
from waterfall.services.msproject_xml_import import import_tasks_and_links

EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"


def _new_project(name: str) -> MsProject:
    return MsProject(
        owner_id=None,
        source_version=2016,
        save_version_out=16,
        name=name,
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        finish_date=datetime(2026, 1, 1, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
    )


_PROJECT_SUMMARY_TASK = """
<Task><UID>0</UID><ID>0</ID><Name>Project</Name>
  <OutlineNumber>0</OutlineNumber><OutlineLevel>0</OutlineLevel><Summary>1</Summary>
</Task>
"""


def _xml_with_tasks(tasks: str) -> bytes:
    return (
        '<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion>'
        "<ScheduleFromStart>true</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate>"
        f"<MinutesPerDay>480</MinutesPerDay><Tasks>{tasks}</Tasks></Project>"
    ).encode()


def test_import_service_persists_tasks_links_and_notes() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=None,
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Import service target",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            finish_date=datetime(2026, 1, 1, tzinfo=UTC),
            calendar_uid=None,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()

        task_count, link_count, warnings = import_tasks_and_links(
            session,
            EXAMPLE_XML.read_bytes(),
            project,
        )
        session.commit()

        assert task_count == 2
        assert link_count == 1
        assert warnings == ()
        planning = session.query(WfPlanning).filter(WfPlanning.project_id == project.id).one()
        assert planning.status == "draft"
        assert project.displayed_planning_id == planning.id
        assert session.query(MsTask).filter(MsTask.project_id == project.id).count() == 0
        assert (
            session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .count()
            == 2
        )
        assert (
            session.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
            .count()
            == 1
        )
        task = (
            session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .filter(WfPlanningTaskSnapshot.uid == 1)
            .one()
        )
        assert task.notes == "description de l'étude"


def test_import_service_replaces_draft_and_preserves_validated_history() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=None,
            source_version=2016,
            save_version_out=16,
            name="Sync target",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            finish_date=datetime(2026, 1, 1, tzinfo=UTC),
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
        )
        session.add(project)
        session.flush()

        source = EXAMPLE_XML.read_bytes()
        import_tasks_and_links(session, source, project)
        first_planning_id = project.displayed_planning_id
        changed = source.replace(b"Etude documentaire", b"Etude documentaire v2")
        import_tasks_and_links(session, changed, project)
        assert project.displayed_planning_id == first_planning_id
        draft = session.get(WfPlanning, first_planning_id)
        assert draft is not None
        assert session.query(WfPlanning).filter(WfPlanning.project_id == project.id).count() == 1
        assert (
            session.query(WfPlanningTaskSnapshot)
            .filter(
                WfPlanningTaskSnapshot.planning_id == first_planning_id,
                WfPlanningTaskSnapshot.name == "Etude documentaire v2",
            )
            .count()
            == 1
        )

        draft.status = "validated"
        session.flush()
        import_tasks_and_links(session, source, project)
        session.commit()

        assert session.query(MsTask).filter(MsTask.project_id == project.id).count() == 0
        assert session.query(WfPlanning).filter(WfPlanning.project_id == project.id).count() == 2
        validated = session.get(WfPlanning, first_planning_id)
        assert validated is not None
        assert validated.status == "validated"
        assert project.displayed_planning_id != first_planning_id
        displayed = session.get(WfPlanning, project.displayed_planning_id)
        assert displayed is not None
        assert displayed.status == "draft"


def test_import_service_persists_only_real_tasks_dropping_project_summary() -> None:
    task = (
        _PROJECT_SUMMARY_TASK
        + """
        <Task><UID>1</UID><ID>1</ID><Name>A</Name>
          <OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel>
        </Task>
        <Task><UID>2</UID><ID>2</ID><Name>B</Name>
          <OutlineNumber>2</OutlineNumber><OutlineLevel>1</OutlineLevel>
          <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type></PredecessorLink>
        </Task>
        """
    )
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("Summary task dropped")
        session.add(project)
        session.flush()

        task_count, link_count, warnings = import_tasks_and_links(
            session, _xml_with_tasks(task), project
        )
        session.commit()

        assert (task_count, link_count, warnings) == (2, 1, ())
        planning = session.query(WfPlanning).filter(WfPlanning.project_id == project.id).one()
        snapshots = (
            session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .all()
        )
        assert {snapshot.uid for snapshot in snapshots} == {1, 2}
        assert all(
            snapshot.position is not None and snapshot.position > 0 for snapshot in snapshots
        )
        links = (
            session.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
            .all()
        )
        assert {link.predecessor_uid for link in links} == {1}


def test_import_service_rejects_link_to_omitted_project_summary_before_persisting() -> None:
    task = (
        _PROJECT_SUMMARY_TASK
        + """
        <Task><UID>1</UID><ID>1</ID><Name>A</Name>
          <OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel>
          <PredecessorLink><PredecessorUID>0</PredecessorUID><Type>1</Type></PredecessorLink>
        </Task>
        """
    )
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("Dangling link to summary")
        session.add(project)
        session.flush()

        with pytest.raises(MsProjectValidationError) as error:
            import_tasks_and_links(session, _xml_with_tasks(task), project)
        assert {issue["code"] for issue in error.value.issues} == {"ORPHAN_LINK"}

        session.rollback()
        assert session.query(WfPlanning).filter(WfPlanning.project_id == project.id).count() == 0
        assert session.query(WfPlanningTaskSnapshot).count() == 0
        assert session.query(WfPlanningLinkSnapshot).count() == 0
