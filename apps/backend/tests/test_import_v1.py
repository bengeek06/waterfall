from datetime import UTC, datetime
from pathlib import Path

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject, MsTask, MsTaskLink
from waterfall.models.wf_core import WfTaskEnrichment
from waterfall.services.import_v1 import import_tasks_and_links

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

        task_count, link_count = import_tasks_and_links(
            session,
            EXAMPLE_XML.read_bytes(),
            project,
        )
        session.commit()

        assert task_count == 2
        assert link_count == 1
        assert session.query(MsTask).filter(MsTask.project_id == project.id).count() == 2
        assert session.query(MsTaskLink).filter(MsTaskLink.project_id == project.id).count() == 1
        enrichment = (
            session.query(WfTaskEnrichment)
            .filter(WfTaskEnrichment.project_id == project.id)
            .filter(WfTaskEnrichment.task_uid == 1)
            .one()
        )
        assert enrichment.description == "description de l'étude"
