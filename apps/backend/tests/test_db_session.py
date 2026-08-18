from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from waterfall.db.session import get_session_factory
from waterfall.models.ms_core import MsTask


def test_sqlite_enforces_foreign_keys() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        session.add(
            MsTask(
                project_id=999999,
                uid=1,
                id_display=1,
                name="Orphan task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
                finish_at=datetime(2026, 1, 1, tzinfo=UTC),
                duration_minutes=None,
                duration_format=None,
                work_minutes=None,
                percent_complete=0,
                is_summary=False,
                is_milestone=False,
                calendar_uid=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
