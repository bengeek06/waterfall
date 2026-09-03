from datetime import UTC, datetime
from pathlib import Path

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.services.msproject_xml_import import import_tasks_and_links

EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"


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
