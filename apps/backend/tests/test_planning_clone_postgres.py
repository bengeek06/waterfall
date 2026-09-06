"""PostgreSQL regression for cloning a hierarchical planning (#103).

test_projects_api.py::test_creates_new_version_from_a_hierarchical_validated_planning
covers this same defect through the HTTP layer, but TestClient is wired to a single
SQLite database for the whole test session (see tests/conftest.py). That sibling test
reproduces the bug with a small, hand-built hierarchy tuned to how *SQLite* happens to
plan an unordered `SELECT ... WHERE planning_id = X` on a tiny table (it favours the
(planning_id, uid) index, returning rows in ascending-uid order). PostgreSQL plans the
same query differently for a table that size (a sequential/heap scan, returning rows in
physical/insertion order instead) and did not reproduce the bug through that same
hand-built hierarchy -- confirmed empirically while writing this test.

What *does* reproduce it on PostgreSQL is the exact flow #103 describes: a real
`generate_planning_structure`-created hierarchy (posts/lots/deliverables/milestones,
several tasks deep), validated and set as the project's reference, then cloned via
`source_planning_id`. This test drives that same real flow -- `create_planning_structure`
then `create_planning` -- directly against a disposable PostgreSQL database, proving the
fix holds there too rather than only against SQLite's own query-planning quirks.

`postgres_app_database_url` (below) is registered as a fixture for the whole test
session via `pytest_plugins` in tests/conftest.py, not imported here by name --
importing a `@pytest.fixture`-decorated callable into a module that also takes it as a
test parameter trips ruff's F811.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_STRUCTURE_PAYLOAD = {
    "posts": [
        {
            "key": "design",
            "name": "Design",
            "lots": [
                {
                    "key": "specification",
                    "name": "Specification",
                    "deliverables": [
                        {"key": "requirements", "name": "Requirements"},
                        {"key": "architecture", "name": "Architecture"},
                    ],
                },
                {
                    "key": "validation",
                    "name": "Validation",
                    "deliverables": [{"key": "review", "name": "Review"}],
                },
            ],
        },
    ],
}


def test_clones_a_hierarchical_validated_planning_on_postgresql(
    postgres_app_database_url: str,
) -> None:
    from waterfall.api.routes.plannings import (
        create_planning,
        create_planning_structure,
        set_planning_reference,
        validate_planning,
    )
    from waterfall.models.ms_core import MsProject
    from waterfall.models.planning import WfPlanning
    from waterfall.models.user import User
    from waterfall.schemas.projects import PlanningCreate, PlanningStructureCreate

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    try:
        with session_factory() as session:
            user = User(email="pg-clone@example.com", hashed_password="not-checked")
            session.add(user)
            session.flush()

            project = MsProject(
                owner_id=user.id,
                source_version=2016,
                save_version_out=16,
                name="Hierarchical clone source (PostgreSQL)",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 5, tzinfo=UTC),
                finish_date=datetime(2026, 1, 20, tzinfo=UTC),
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                status="cree",
            )
            session.add(project)
            session.flush()
            session.commit()

            generated = create_planning_structure(
                project_id=project.id,
                payload=PlanningStructureCreate.model_validate(_STRUCTURE_PAYLOAD),
                db=session,
                current_user=user,
            )
            assert len(generated.tasks) == 8
            generated_planning = (
                session.query(WfPlanning)
                .filter(WfPlanning.project_id == project.id)
                .order_by(WfPlanning.id.desc())
                .first()
            )
            assert generated_planning is not None
            planning_id = generated_planning.id

            validate_planning(
                project_id=project.id, planning_id=planning_id, db=session, current_user=user
            )
            set_planning_reference(
                project_id=project.id, planning_id=planning_id, db=session, current_user=user
            )

            result = create_planning(
                project_id=project.id,
                payload=PlanningCreate(source_planning_id=planning_id),
                db=session,
                current_user=user,
            )

            assert len(result.tasks) == 8
            root_lot = next(task for task in result.tasks if task.name == "Specification")
            child_deliverable = next(task for task in result.tasks if task.name == "Requirements")
            assert child_deliverable.parent_uid == root_lot.uid
    finally:
        engine.dispose()
