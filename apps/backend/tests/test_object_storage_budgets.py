"""Per-call-site timeout budgets of the object storage client (E13-02 review follow-up).

The one storage call that runs *inside* the `ms_project` row lock is the staging-to-final
`copy` in `imports.upload_xml`, and it has to stay there: it is what makes the switchover
atomic with respect to that handler's `status != "pending"` re-check. Its timeout budget is
therefore the maximum time every other writer on the project is blocked -- and nothing else
bounds that wait, since `db/session.get_engine` sets no `lock_timeout`.

These tests pin that budget, because nothing else can: the failure they guard against is a
two-minute project-wide freeze under a black-holed store (TCP accepted, nothing answered),
which no functional test can reproduce without actually waiting it out.

Chosen over the behavioural test the review suggested (monkeypatch `import_object_storage.
copy` to sleep, then prove from a second session that the project lock is released within
the budget): a monkeypatched sleep has no timeout of its own, so such a test can only
re-assert that the copy happens under the lock -- which test_imports_run_batch_locking.py
already covers for the sibling path -- never that the budget bounds it. Driving a real
black-holed endpoint would assert the budget, at the cost of ~25s of wall clock per run. So
the budget is asserted where it is decided: on the effective botocore `Config` of the client
each operation actually uses.
"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

import pytest

from _object_storage_support import TEST_BUCKET
from waterfall.core import object_storage as object_storage_module
from waterfall.core.config import Settings
from waterfall.core.object_storage import ObjectStorage, import_object_storage

if TYPE_CHECKING:  # pragma: no cover - typing-only import (boto3-stubs is a dev dep)
    from mypy_boto3_s3.client import S3Client

# Ceiling, not an equality: the point is that no future retuning may let one copy hold a
# project frozen for minutes. 30s leaves room for the 24s of timeouts plus botocore's
# jittered backoff, and still fails loudly on a slip back to the data-path budget (140s).
_MAX_LOCKED_SWITCHOVER_SECONDS = 30

_SOURCE_KEY = "imports/budget-source.xml"


def _effective_budget(client: S3Client) -> tuple[int, int, int]:
    """(connect_timeout, read_timeout, attempts) as botocore resolved them.

    Read off `meta.config` rather than the module constants: `Config(retries=...)` accepts
    both `max_attempts` (a retry count, resolved to one *more* request than it names) and
    `total_max_attempts` (requests, initial one included). Only the resolved value says how
    many round trips the caller is really signed up for.
    """
    # `cast` because botocore builds `Config`'s attributes dynamically from OPTION_DEFAULTS,
    # so botocore-stubs declares none of them and pyright rejects every access.
    config = cast(Any, client.meta.config)
    return (
        int(config.connect_timeout),
        int(config.read_timeout),
        int(config.retries["total_max_attempts"]),
    )


def test_switchover_client_budget_bounds_the_project_lock_window() -> None:
    """~25s worst case, not the data path's ~140s."""
    storage = ObjectStorage()
    try:
        client, _ = storage._connect_switchover()  # pyright: ignore[reportPrivateUsage]
        connect_timeout, read_timeout, attempts = _effective_budget(client)

        assert (connect_timeout, read_timeout, attempts) == (2, 10, 2)
        assert attempts * (connect_timeout + read_timeout) <= _MAX_LOCKED_SWITCHOVER_SECONDS
    finally:
        storage.reset()


def test_data_path_keeps_its_own_wider_budget() -> None:
    """The upload budget is deliberately not the switchover one.

    A 25 MB PUT over a slow link needs the 30s read timeout that a server-side copy -- which
    transfers no object data at all -- has no use for. Collapsing the two budgets into one
    would sacrifice one of those two properties; this test states which pair of numbers
    belongs to which call site, so a future "simplification" has to be deliberate.
    """
    storage = ObjectStorage()
    try:
        client, _ = storage._connect()  # pyright: ignore[reportPrivateUsage]
        assert _effective_budget(client) == (5, 30, 4)
    finally:
        storage.reset()


def test_probe_client_makes_exactly_one_attempt() -> None:
    """The readiness probe runs behind a ~2s deadline in api/routes/health.py.

    One request, one second each way: a retry would push the probe past that deadline and
    leave a socket-holding thread behind on every poll.
    """
    storage = ObjectStorage()
    try:
        client, _ = storage._connect_probe()  # pyright: ignore[reportPrivateUsage]
        assert _effective_budget(client) == (1, 1, 1)
    finally:
        storage.reset()


@pytest.mark.parametrize(
    ("operation", "expected_budget"),
    [
        ("copy", (2, 10, 2)),
        ("upload", (5, 30, 4)),
        ("download", (5, 30, 4)),
        ("delete", (5, 30, 4)),
    ],
)
def test_each_operation_uses_the_client_its_budget_was_written_for(
    object_storage: S3Client,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_budget: tuple[int, int, int],
) -> None:
    """Routing, not just values: `copy` must not drift back onto the data-path client.

    That drift is invisible -- every test still passes against a responsive store -- and
    silently restores the ~140s project freeze, so it is checked at the only point where it
    shows: which client the operation builds.
    """
    # Seeded through the fixture's own client, so the operation under test is the first (and
    # only) thing to build an application client.
    object_storage.put_object(Bucket=TEST_BUCKET, Key=_SOURCE_KEY, Body=b"<Project/>")

    built: list[tuple[int, int, int]] = []
    real_new_client = object_storage_module._new_client  # pyright: ignore[reportPrivateUsage]

    def recording_new_client(
        settings: Settings, *, connect_timeout: int, read_timeout: int, total_max_attempts: int
    ) -> S3Client:
        built.append((connect_timeout, read_timeout, total_max_attempts))
        return real_new_client(
            settings,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            total_max_attempts=total_max_attempts,
        )

    monkeypatch.setattr(object_storage_module, "_new_client", recording_new_client)
    import_object_storage.reset()

    if operation == "copy":
        import_object_storage.copy(_SOURCE_KEY, "imports/budget-final.xml")
    elif operation == "upload":
        import_object_storage.upload("imports/budget-upload.xml", BytesIO(b"<Project/>"))
    elif operation == "download":
        import_object_storage.download(_SOURCE_KEY)
    else:
        import_object_storage.delete(_SOURCE_KEY)

    assert built == [expected_budget]
