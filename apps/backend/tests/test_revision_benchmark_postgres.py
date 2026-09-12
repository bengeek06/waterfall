"""Non-blocking PostgreSQL baseline for issue #14 planning performance.

Moved onto the revision tree by E14-05 (#331), which removed the two endpoints it
used to time. Same shape and same purpose -- print a read/mutation percentile
baseline on a 1000-node tree, assert nothing -- so that the cost of the new model
is observable rather than discovered in production.
"""

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


def _seed_revision(
    database_url: str,
) -> tuple[sessionmaker[Session], int, int, int, int, Engine]:
    from waterfall.models.ms_core import MsProject
    from waterfall.models.resources import Calendar
    from waterfall.models.revision import (
        ProjectRevision,
        RevisionNode,
        RevisionPlanFacet,
        WorkItem,
    )
    from waterfall.models.user import User

    engine = create_engine(database_url, future=True)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with sessions() as session:
        owner = User(
            email=f"benchmark-{uuid4().hex}@example.com",
            hashed_password="not-a-real-hash",
            is_active=True,
        )
        calendar = Calendar(
            code=f"CAL-{uuid4().hex[:8]}",
            name="Standard",
            weeks_per_year=47,
            is_active=True,
            is_default=True,
        )
        session.add_all([owner, calendar])
        session.flush()
        project = MsProject(
            owner_id=owner.id,
            source_version=2016,
            save_version_out=16,
            name="Revision benchmark",
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
        revision = ProjectRevision(
            project_id=project.id, version_number=1, status="draft", lock_version=0
        )
        session.add(revision)
        session.flush()
        work_items = [WorkItem(project_id=project.id, kind="task") for _ in range(1000)]
        session.add_all(work_items)
        session.flush()
        nodes = [
            RevisionNode(
                revision_id=revision.id,
                work_item_id=work_item.id,
                kind="task",
                parent_id=None,
                position=position,
            )
            for position, work_item in enumerate(work_items, start=1)
        ]
        session.add_all(nodes)
        session.flush()
        session.add_all(
            RevisionPlanFacet(
                node_id=node.id,
                node_kind="task",
                name=f"Task {node.position}",
                calendar_id=calendar.id,
                calendar_source="project",
            )
            for node in nodes
        )
        session.commit()
        return sessions, owner.id, project.id, revision.id, nodes[-1].id, engine


def _percentile(values: list[float], percentile: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[int(percentile) - 1]


def test_revision_1000_node_postgres_baseline(postgres_benchmark_database: str) -> None:
    from waterfall.api.routes.revisions import move_revision_nodes, read_revision_nodes
    from waterfall.models.user import User
    from waterfall.schemas.revisions import RevisionNodeMove

    sessions, owner_id, project_id, revision_id, last_node_id, engine = _seed_revision(
        postgres_benchmark_database
    )

    def _move(session: Session, lock_version: int) -> None:
        move_revision_nodes(
            project_id,
            revision_id,
            RevisionNodeMove(
                node_ids=[last_node_id],
                mode="to_parent",
                target_parent_id=None,
                position=1 if lock_version % 2 == 0 else 1000,
                expected_lock_version=lock_version,
            ),
            db=session,
            current_user=User(id=owner_id),
        )

    try:
        read_times: list[float] = []
        warmup_mutations = 5
        for _ in range(warmup_mutations):
            with sessions() as session:
                read_revision_nodes(project_id, revision_id, session, User(id=owner_id))
        for _ in range(30):
            started = time.perf_counter()
            with sessions() as session:
                read_revision_nodes(project_id, revision_id, session, User(id=owner_id))
            read_times.append((time.perf_counter() - started) * 1000)

        mutation_times: list[float] = []
        for lock_version in range(warmup_mutations):
            with sessions() as session:
                _move(session, lock_version)
        for lock_version in range(warmup_mutations, warmup_mutations + 30):
            started = time.perf_counter()
            with sessions() as session:
                _move(session, lock_version)
            mutation_times.append((time.perf_counter() - started) * 1000)

        print(
            "revision_1000_nodes_ms "
            f"read_p50={statistics.median(read_times):.2f} "
            f"read_p95={_percentile(read_times, 95):.2f} "
            f"mutation_p50={statistics.median(mutation_times):.2f} "
            f"mutation_p95={_percentile(mutation_times, 95):.2f}"
        )
    finally:
        engine.dispose()
