from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsProject
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot


def _project() -> MsProject:
    return MsProject(
        source_version=2016,
        save_version_out=16,
        name="Planning lifecycle test",
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        finish_date=datetime(2026, 1, 2, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
    )


def test_project_and_planning_defaults_and_snapshot_references() -> None:
    with get_session_factory()() as session:
        project = _project()
        session.add(project)
        session.flush()
        planning = WfPlanning(project_id=project.id, version_number=1, status="validated")
        session.add(planning)
        session.flush()
        task = WfPlanningTaskSnapshot(
            planning_id=planning.id,
            uid=1,
            name="Task",
            is_summary=False,
            is_milestone=False,
        )
        session.add(task)
        session.flush()
        project.planning_reference_id = planning.id
        project.displayed_planning_id = planning.id
        session.add(
            WfPlanningLinkSnapshot(
                planning_id=planning.id,
                task_uid=1,
                predecessor_uid=1,
                link_type=1,
            )
        )
        session.commit()

        assert project.status == "cree"
        assert planning.status == "validated"
        session.refresh(project)
        assert project.planning_reference_id == planning.id
        assert project.displayed_planning_id == planning.id
        assert session.query(WfPlanningTaskSnapshot).count() == 1
        assert session.query(WfPlanningLinkSnapshot).count() == 1


def test_planning_version_and_snapshot_uid_are_unique_per_parent() -> None:
    with get_session_factory()() as session:
        project = _project()
        session.add(project)
        session.flush()
        session.add_all(
            [
                WfPlanning(project_id=project.id, version_number=1),
                WfPlanning(project_id=project.id, version_number=1),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_planning_status_constraint_rejects_unknown_status() -> None:
    with get_session_factory()() as session:
        project = _project()
        session.add(project)
        session.flush()
        session.add(WfPlanning(project_id=project.id, version_number=1, status="active"))
        with pytest.raises(IntegrityError):
            session.commit()