"""Non-blocking PostgreSQL baseline for issue #14 planning performance."""

from __future__ import annotations

import statistics
import time
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from _postgres_support import ephemeral_postgres_database, postgres_admin_url, postgres_reachable


@pytest.fixture
def postgres_benchmark_database() -> Generator[str]:
    admin_url = postgres_admin_url()
    if not postgres_reachable(admin_url):
        pytest.skip(
            "PostgreSQL is not reachable; start the Compose postgres service to run the benchmark."
        )
    with ephemeral_postgres_database(admin_url) as database_url:
        from waterfall.db.base import Base
        from waterfall.models import User

        _ = User.__tablename__
        engine = create_engine(database_url, future=True)
        try:
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()
        yield database_url


def _seed_planning(
    database_url: str,
) -> tuple[sessionmaker[Session], int, int, int, Engine]:
    from waterfall.models.ms_core import MsProject
    from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
    from waterfall.models.user import User

    engine = create_engine(database_url, future=True)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with sessions() as session:
        owner = User(
            email=f"benchmark-{uuid4().hex}@example.com",
            hashed_password="not-a-real-hash",
            is_active=True,
        )
        session.add(owner)
        session.flush()
        project = MsProject(
            owner_id=owner.id,
            source_version=2016,
            save_version_out=16,
            name="Planning benchmark",
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
        planning = WfPlanning(project_id=project.id, version_number=1, status="draft")
        session.add(planning)
        session.flush()
        session.add_all(
            WfPlanningTaskSnapshot(
                planning_id=planning.id,
                uid=uid,
                name=f"Task {uid}",
                position=uid,
                outline_number=str(uid),
                outline_level=1,
                is_summary=False,
                is_milestone=False,
            )
            for uid in range(1, 1001)
        )
        project.displayed_planning_id = planning.id
        session.commit()
        return sessions, owner.id, project.id, planning.id, engine


def _percentile(values: list[float], percentile: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[int(percentile) - 1]


def test_planning_1000_task_postgres_baseline(postgres_benchmark_database: str) -> None:
    from waterfall.api.routes.plannings import get_planning_tree, move_planning_tasks_route
    from waterfall.models.user import User
    from waterfall.schemas.projects import PlanningTaskMove

    sessions, owner_id, project_id, planning_id, engine = _seed_planning(
        postgres_benchmark_database
    )
    try:
        read_times: list[float] = []
        warmup_mutations = 5
        for _ in range(warmup_mutations):
            with sessions() as session:
                get_planning_tree(project_id, planning_id, session, User(id=owner_id))
        for _ in range(30):
            started = time.perf_counter()
            with sessions() as session:
                get_planning_tree(project_id, planning_id, session, User(id=owner_id))
            read_times.append((time.perf_counter() - started) * 1000)

        mutation_times: list[float] = []
        for revision in range(warmup_mutations):
            with sessions() as session:
                move_planning_tasks_route(
                    project_id,
                    planning_id,
                    PlanningTaskMove(
                        task_uids=[1000],
                        target_parent_uid=None,
                        position=1 if revision % 2 == 0 else 1000,
                        expected_revision=revision,
                    ),
                    db=session,
                    current_user=User(id=owner_id),
                )
        for revision in range(warmup_mutations, warmup_mutations + 30):
            started = time.perf_counter()
            with sessions() as session:
                move_planning_tasks_route(
                    project_id,
                    planning_id,
                    PlanningTaskMove(
                        task_uids=[1000],
                        target_parent_uid=None,
                        position=1 if revision % 2 == 0 else 1000,
                        expected_revision=revision,
                    ),
                    db=session,
                    current_user=User(id=owner_id),
                )
            mutation_times.append((time.perf_counter() - started) * 1000)

        print(
            "planning_1000_tasks_ms "
            f"read_p50={statistics.median(read_times):.2f} "
            f"read_p95={_percentile(read_times, 95):.2f} "
            f"mutation_p50={statistics.median(mutation_times):.2f} "
            f"mutation_p95={_percentile(mutation_times, 95):.2f}"
        )
    finally:
        engine.dispose()
