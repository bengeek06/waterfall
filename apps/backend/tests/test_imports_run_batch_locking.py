"""PostgreSQL concurrency regression test for issue #37 (imports.run_batch lock ordering).

Mirrors the pattern in test_projects_task_reference_locking.py (see that module's
docstring for the full rationale): proving this fix requires a real PostgreSQL
backend with two independent connections/transactions, since SQLite silently
drops `SELECT ... FOR UPDATE`, so the normal SQLite-backed TestClient test
session could never observe the row lock this issue is about.

`run_batch` now reads and parses the uploaded XML *before* acquiring the
project row lock, so slow file I/O and XML parsing never block other writers
serialized on it. This test proves the lock re-acquisition that follows (on
both the dry-run and confirmation paths) still correctly queues behind a
concurrently-held project lock, exactly like before the refactor.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
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

MINIMAL_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Project xmlns="http://schemas.microsoft.com/project">'
    b"<SaveVersion>14</SaveVersion><Name>minimal.xml</Name>"
    b"<ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate>"
    b"<MinutesPerDay>480</MinutesPerDay>"
    b"<Tasks><Task><UID>1</UID><ID>1</ID><Name>Task</Name>"
    b"<Duration>PT480M</Duration></Task></Tasks>"
    b"</Project>"
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


def _seed_project_with_pending_batch(session: Session, tmp_path: Path) -> tuple[int, int, int]:
    from waterfall.models.ms_core import MsProject
    from waterfall.models.user import User
    from waterfall.models.wf_core import WfImportBatch

    owner = User(
        email=f"import-lock-{uuid4().hex[:8]}@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(owner)
    session.flush()

    project = MsProject(
        owner_id=owner.id,
        source_version=2016,
        save_version_out=16,
        name="Import Lock Test",
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

    xml_path = tmp_path / f"batch-{uuid4().hex}.xml"
    xml_path.write_bytes(MINIMAL_XML)
    source_sha256 = hashlib.sha256(MINIMAL_XML).hexdigest()

    batch = WfImportBatch(
        project_id=project.id,
        import_mode="standard",
        source_filename="minimal.xml",
        source_storage_path=str(xml_path),
        source_sha256=source_sha256,
        started_at=datetime.now(UTC),
        status="pending",
        log_json=json.dumps({"uploaded_bytes": len(MINIMAL_XML)}),
    )
    session.add(batch)
    session.commit()

    return owner.id, project.id, batch.id


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_batch_queues_behind_project_lock(
    postgres_app_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    """Both paths must read and parse the XML before ever requesting the project lock."""
    import waterfall.api.routes.imports as imports_module
    from waterfall.api.routes.project_access import get_mutable_project_lock
    from waterfall.models.user import User
    from waterfall.models.wf_core import WfImportBatch
    from waterfall.schemas.imports import ImportRunRequest
    from waterfall.services.msproject_xml import ParsedProject

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            owner_id, project_id, batch_id = _seed_project_with_pending_batch(
                seed_session, tmp_path
            )

        session_a = session_factory()
        session_b = session_factory()
        try:
            locked_project = get_mutable_project_lock(session_a, project_id, owner_id)
            assert locked_project.id == project_id

            session_b.execute(text("SET LOCAL lock_timeout = '200ms'"))
            current_user = User(id=owner_id)

            completed = {"read": False, "parse": False}
            real_read_source_xml = imports_module._read_source_xml  # pyright: ignore[reportPrivateUsage]
            real_parse = imports_module.parse_msproject_xml

            def traced_read(batch: WfImportBatch) -> bytes:
                xml_bytes = real_read_source_xml(batch)
                completed["read"] = True
                return xml_bytes

            def traced_parse(xml_bytes: bytes) -> ParsedProject:
                parsed = real_parse(xml_bytes)
                completed["parse"] = True
                return parsed

            monkeypatch.setattr(imports_module, "_read_source_xml", traced_read)
            monkeypatch.setattr(imports_module, "parse_msproject_xml", traced_parse)

            with pytest.raises(OperationalError, match="lock timeout"):
                imports_module.run_batch(
                    batch_id,
                    ImportRunRequest(dryRun=dry_run, confirm=not dry_run),
                    db=session_b,
                    current_user=current_user,
                )

            assert completed["read"], "XML must be read before the project lock is requested"
            assert completed["parse"], "XML must be parsed before the project lock is requested"

            session_b.rollback()
            session_a.rollback()
        finally:
            session_a.close()
            session_b.close()
    finally:
        engine.dispose()


def test_run_batch_rejects_stale_source_after_concurrent_reupload(
    postgres_app_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent re-upload between the unlocked parse and the lock must 409."""
    from fastapi import HTTPException

    import waterfall.api.routes.imports as imports_module
    from waterfall.models.user import User
    from waterfall.models.wf_core import WfImportBatch
    from waterfall.schemas.imports import ImportRunRequest

    engine = create_engine(postgres_app_database_url, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with session_factory() as seed_session:
            owner_id, _project_id, batch_id = _seed_project_with_pending_batch(
                seed_session, tmp_path
            )

        session_b = session_factory()
        try:
            real_read_source_xml = imports_module._read_source_xml  # pyright: ignore[reportPrivateUsage]

            def read_then_race(batch: WfImportBatch) -> bytes:
                # Read the XML exactly like run_batch does, unlocked, then
                # simulate a concurrent upload_xml replacing the file and
                # source_sha256 before run_batch re-acquires the project lock.
                xml_bytes = real_read_source_xml(batch)
                with session_factory() as concurrent_session:
                    concurrent_batch = concurrent_session.get(WfImportBatch, batch_id)
                    assert concurrent_batch is not None
                    new_bytes = MINIMAL_XML.replace(b"minimal.xml", b"replaced.xml")
                    Path(str(concurrent_batch.source_storage_path)).write_bytes(new_bytes)
                    concurrent_batch.source_sha256 = hashlib.sha256(new_bytes).hexdigest()
                    concurrent_session.commit()
                return xml_bytes

            monkeypatch.setattr(imports_module, "_read_source_xml", read_then_race)

            current_user = User(id=owner_id)
            with pytest.raises(HTTPException) as excinfo:
                imports_module.run_batch(
                    batch_id,
                    ImportRunRequest(dryRun=True, confirm=False),
                    db=session_b,
                    current_user=current_user,
                )
            assert excinfo.value.status_code == 409
            assert excinfo.value.detail == "Uploaded XML changed concurrently; re-run the batch"
        finally:
            session_b.close()
    finally:
        engine.dispose()
