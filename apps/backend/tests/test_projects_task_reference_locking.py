"""Concurrency regression test for issue #79 (task deletion vs. reference creation race).

Mirrors the pattern in test_resources_calendar_locking.py (see that module's
docstring for the full rationale): proving this fix requires a real PostgreSQL
backend with two independent connections/transactions, since SQLite silently
drops `SELECT ... FOR UPDATE` (SQLAlchemy's sqlite dialect no-ops the clause),
so the normal SQLite-backed TestClient test session could never observe the
row lock this issue is about. This module therefore drives the guarded route
function directly against two independent `Session` objects on a real
`create_engine(postgres_app_database_url)`, instead of going through the
FastAPI `Depends(get_db)` request lifecycle.

`delete_planning_tasks` checks task references while holding the project's row
lock. These tests prove every route that creates such references takes the same
lock and therefore queues behind a concurrent deletion.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from _postgres_support import (
    ephemeral_postgres_database,
    postgres_admin_url,
    postgres_reachable,
)


@pytest.fixture
def postgres_app_database_url() -> Generator[str]:
    admin_url = postgres_admin_url()
    if not postgres_reachable(admin_url):
        pytest.skip(
            "PostgreSQL is not reachable; set TEST_POSTGRES_URL or start the "
            "docker-compose postgres service to run this test."
        )
    with ephemeral_postgres_database(admin_url) as database_url:
        # Same registration trick as test_resources_calendar_locking.py: importing
        # the models package registers every mapped class on Base.metadata, so
        # create_all below produces the full application schema.
        from waterfall.models import User

        _ = User.__tablename__
        from waterfall.db.base import Base

        engine = create_engine(database_url, future=True)
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
        yield database_url


def _seed_project_and_draft_estimate(
    session: Session,
) -> tuple[int, int, int, int, int, int, int]:
    from waterfall.models.ms_core import MsProject, MsTask
    from waterfall.models.planning import WfPlanning
    from waterfall.models.resources import CostCategory, CostType, Estimate
    from waterfall.models.user import User

    owner = User(
        email=f"locking-{uuid4().hex[:8]}@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(owner)
    session.flush()

    project = MsProject(
        owner_id=owner.id,
        source_version=2016,
        save_version_out=16,
        name="Task Reference Locking Test",
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        finish_date=datetime(2026, 12, 31, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
        currency_code="EUR",
    )
    session.add(project)
    session.flush()

    task = MsTask(project_id=project.id, uid=1, name="Referenced task")
    session.add(task)
    session.flush()

    planning = WfPlanning(project_id=project.id, version_number=1, status="draft")
    session.add(planning)
    session.flush()

    estimate = Estimate(
        project_id=project.id,
        planning_id=None,
        version_number=1,
        kind="initial",
        status="draft",
        currency_code="EUR",
    )
    session.add(estimate)

    cost_type = CostType(code=f"MAT-{uuid4().hex[:8]}", name="Materiel", kind="other")
    session.add(cost_type)
    session.flush()
    cost_category = CostCategory(
        cost_type_id=cost_type.id,
        accounting_code=f"MATCAT-{uuid4().hex[:8]}",
        name="Materiel",
    )
    session.add(cost_category)
    session.commit()

    return (
        owner.id,
        project.id,
        planning.id,
        estimate.id,
        cost_category.id,
        task.id,
        task.uid,
    )


@pytest.mark.parametrize(
    "operation",
    [
        "create_project_estimate",
        "validate_project_estimate",
        "create_estimate_cost_line",
        "update_estimate_cost_line",
        "create_task_role_assignment",
    ],
)
def test_project_lock_blocks_every_task_reference_creator(
    postgres_app_database_url: str,
    operation: str,
) -> None:
    """Every reference creator must queue behind task deletion's project lock."""
    from waterfall.api.routes.projects import (
        create_estimate_cost_line,
        create_project_estimate,
        create_task_role_assignment,
        get_mutable_draft_planning_with_locks,
        update_estimate_cost_line,
        validate_project_estimate,
    )
    from waterfall.models.user import User
    from waterfall.schemas.projects import (
        EstimateCostLineCreate,
        EstimateCostLineUpdate,
        ProjectEstimateCreate,
        TaskRoleAssignmentCreate,
    )

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            (
                owner_id,
                project_id,
                planning_id,
                estimate_id,
                cost_category_id,
                task_id,
                task_uid,
            ) = _seed_project_and_draft_estimate(seed_session)

        session_a = session_factory()
        session_b = session_factory()
        try:
            locked_project, locked_planning = get_mutable_draft_planning_with_locks(
                session_a, project_id, planning_id, owner_id
            )
            assert locked_project.id == project_id
            assert locked_planning.id == planning_id

            session_b.execute(text("SET LOCAL lock_timeout = '200ms'"))
            current_user = User(id=owner_id)

            def run_operation() -> object:
                if operation == "create_project_estimate":
                    return create_project_estimate(
                        project_id,
                        ProjectEstimateCreate(kind="initial", currency_code="EUR"),
                        db=session_b,
                        current_user=current_user,
                    )
                if operation == "validate_project_estimate":
                    return validate_project_estimate(
                        project_id, estimate_id, db=session_b, current_user=current_user
                    )
                if operation == "create_estimate_cost_line":
                    return create_estimate_cost_line(
                        project_id,
                        estimate_id,
                        EstimateCostLineCreate(
                            task_id=task_id,
                            cost_category_id=cost_category_id,
                            label="Concurrent material",
                            quantity=Decimal("1"),
                            unit_cost=Decimal("100"),
                        ),
                        db=session_b,
                        current_user=current_user,
                    )
                if operation == "update_estimate_cost_line":
                    return update_estimate_cost_line(
                        project_id,
                        estimate_id,
                        1,
                        EstimateCostLineUpdate(task_id=task_id),
                        db=session_b,
                        current_user=current_user,
                    )
                return create_task_role_assignment(
                    project_id,
                    task_uid,
                    TaskRoleAssignmentCreate(role_id=1, quantity=Decimal("1"), hours=Decimal("1")),
                    db=session_b,
                    current_user=current_user,
                )

            with pytest.raises(OperationalError, match="lock timeout"):
                run_operation()
            session_b.rollback()

            if operation == "create_estimate_cost_line":
                session_a.commit()
                created = create_estimate_cost_line(
                    project_id,
                    estimate_id,
                    EstimateCostLineCreate(
                        task_id=task_id,
                        cost_category_id=cost_category_id,
                        label="Material after deletion lock",
                        quantity=Decimal("1"),
                        unit_cost=Decimal("100"),
                    ),
                    db=session_b,
                    current_user=current_user,
                )
                assert created.task_id == task_id
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine.dispose()
