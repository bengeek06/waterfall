"""Liveness and readiness probes (E13-03).

Every outage below is simulated in-process -- an engine pointed at an unopenable file, a
Redis client pointed at a refused port, an object storage endpoint pointed at the same --
so the suite never needs a dependency to be *stopped* to prove the failure path. The one
thing it does need is the same reachable Redis the rest of the suite already needs (see
_redis_support), and only for the all-green case, which skips cleanly without it.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any, cast

import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.pool import QueuePool

from _object_storage_support import TEST_ENDPOINT_URL, new_s3_client
from waterfall.api.routes import health
from waterfall.api.routes.auth import LoginRateLimiter
from waterfall.core import object_storage as object_storage_module
from waterfall.core.config import Settings, get_settings
from waterfall.core.object_storage import ObjectStorageUnavailableError, import_object_storage
from waterfall.db.session import get_engine
from waterfall.main import app

if TYPE_CHECKING:  # pragma: no cover - typing-only import (boto3-stubs is a dev dep)
    from mypy_boto3_s3.client import S3Client

# Port 1 is privileged: nothing an unprivileged process can bind, so the connection is
# always refused instead of hanging (same rationale as test_imports_api's constant).
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"
UNREACHABLE_ENDPOINT_URL = "http://127.0.0.1:1"
UNOPENABLE_DATABASE_URL = "sqlite+pysqlite:////nonexistent-directory/waterfall.db"

# SQLAlchemy's QueuePool defaults, which get_engine() does not override: pool_size=5 plus
# max_overflow=10. One probe past that capacity is what used to leave the API permanently
# unable to serve a single request.
_PROBES_PAST_POOL_CAPACITY = 16


def _readiness(client: TestClient) -> tuple[int, dict[str, Any]]:
    response: Response = client.get("/health/ready")
    return response.status_code, cast(dict[str, Any], response.json())


def _assert_liveness_still_ok(client: TestClient) -> None:
    """Liveness must stay green while a dependency is down.

    The whole point of the split: a failing liveness probe gets the container *restarted*,
    so a Redis or Garage outage leaking into /health would escalate a degraded API into a
    restart loop.
    """
    response: Response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness() -> None:
    with TestClient(app) as client:
        response: Response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_every_dependency_when_all_are_up() -> None:
    with TestClient(app) as client:
        status_code, payload = _readiness(client)

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}
    assert "timestamp" in payload


def test_readiness_reports_the_database_as_the_failing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A real driver on an unopenable path, reached through the settings rather than by
    # patching an engine in: the probe builds its own engine (health._probe_engine), and
    # that construction is part of what has to work. The failure then comes out of the
    # driver, through SQLAlchemy, exactly as a refused Postgres connection would.
    monkeypatch.setenv("DATABASE_URL", UNOPENABLE_DATABASE_URL)
    get_settings.cache_clear()
    health.reset_probe_engine()
    try:
        with TestClient(app) as client:
            status_code, payload = _readiness(client)
            _assert_liveness_still_ok(client)
    finally:
        get_settings.cache_clear()
        health.reset_probe_engine()

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"] == {"database": "unavailable", "redis": "ok", "storage": "ok"}


def test_readiness_reports_redis_as_the_failing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", UNREACHABLE_REDIS_URL)
    get_settings.cache_clear()
    try:
        # A fresh limiter rather than the module singleton: it connects lazily, so it
        # picks up the unreachable URL above, and the application-wide instance every
        # other test shares is left untouched.
        monkeypatch.setattr(health, "login_rate_limiter", LoginRateLimiter())

        with TestClient(app) as client:
            status_code, payload = _readiness(client)
            _assert_liveness_still_ok(client)
    finally:
        get_settings.cache_clear()

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"] == {"database": "ok", "redis": "unavailable", "storage": "ok"}


@pytest.mark.no_object_storage_mock
def test_readiness_reports_object_storage_as_the_failing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GARAGE_ENDPOINT_URL", UNREACHABLE_ENDPOINT_URL)
    get_settings.cache_clear()
    import_object_storage.reset()
    try:
        with TestClient(app) as client:
            status_code, payload = _readiness(client)
            _assert_liveness_still_ok(client)
    finally:
        get_settings.cache_clear()
        import_object_storage.reset()

    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"] == {"database": "ok", "redis": "ok", "storage": "unavailable"}


@pytest.mark.no_object_storage_mock
def test_readiness_reports_a_missing_bucket_as_a_storage_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reachable store without the configured bucket is not "ready" either.

    HEAD on an absent bucket answers a bodiless 404, which `check_bucket` deliberately
    does not treat as the "missing object" case -- the API cannot serve imports without
    that bucket, so the probe must stay red until garage-init has created it.
    """
    from moto import mock_aws  # local import: only this test needs a bucket-less backend

    monkeypatch.setenv("GARAGE_BUCKET", "bucket-that-was-never-created")
    get_settings.cache_clear()
    import_object_storage.reset()
    try:
        # TEST_ENDPOINT_URL is only safe to point at while moto is intercepting it (it is
        # the real AWS endpoint otherwise); the surrounding context manager is what makes
        # that true, and _object_storage_support's guard enforces the rule.
        monkeypatch.setenv("GARAGE_ENDPOINT_URL", TEST_ENDPOINT_URL)
        get_settings.cache_clear()
        with mock_aws(), TestClient(app) as client:
            status_code, payload = _readiness(client)
    finally:
        get_settings.cache_clear()
        import_object_storage.reset()

    assert status_code == 503
    assert payload["checks"]["storage"] == "unavailable"


def test_readiness_fails_a_dependency_that_does_not_answer_in_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hanging dependency must produce a 503, not a request that never returns."""
    release = threading.Event()
    monkeypatch.setattr(health, "_CHECK_TIMEOUT_SECONDS", 0.1)

    def hangs() -> None:
        # Far longer than any plausible probe deadline: if the request waited for this,
        # the elapsed assertion below would catch it.
        release.wait(30)

    monkeypatch.setattr(health, "_check_storage", hangs)
    try:
        with TestClient(app) as client:
            started = perf_counter()
            status_code, payload = _readiness(client)
            elapsed = perf_counter() - started
            _assert_liveness_still_ok(client)
    finally:
        release.set()

    assert status_code == 503
    assert payload["checks"] == {"database": "ok", "redis": "ok", "storage": "unavailable"}
    assert elapsed < 5


@contextmanager
def _tcp_tarpit() -> Generator[int]:
    """Listen on an ephemeral port, accept every connection, and answer nothing, ever.

    The shape of a silent partition -- a frozen VM, a dropped conntrack entry, a network
    that blackholes without an RST -- and the only shape that exercises this code path: a
    *refused* port (UNREACHABLE_REDIS_URL above) fails in microseconds and would never
    leave a probe hanging. Here libpq completes the TCP handshake and then waits for a
    server that never speaks a byte of the startup protocol.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(64)
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept_forever() -> None:
        while not stop.is_set():
            try:
                connection, _ = server.accept()
            except OSError:  # the socket was closed by the exit path below
                return
            # Kept referenced, deliberately: letting it be garbage collected would close
            # it and give the client an EOF, i.e. a prompt failure instead of a hang.
            accepted.append(connection)

    threading.Thread(target=accept_forever, name="tarpit", daemon=True).start()
    try:
        yield cast(int, server.getsockname()[1])
    finally:
        stop.set()
        server.close()
        for connection in accepted:
            connection.close()


def test_a_hung_database_never_consumes_the_application_connection_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database that hangs must cost the probe a socket, never a pool slot.

    The regression this pins down: when the probe borrowed `get_engine()`, every poll
    against a silently partitioned host abandoned a thread still holding its checkout.
    With Docker polling every 15s, `pool_size + max_overflow` checkouts leaked in under
    four minutes, after which every real request waited `pool_timeout` and then failed --
    permanently, since the leaked checkouts never return, not even once the database is
    back. The probe's own engine is pool-less, so the loop below leaks nothing at all.
    """
    application_pool = get_engine().pool
    assert isinstance(application_pool, QueuePool)
    assert application_pool.checkedout() == 0

    # The watchdog under test, shortened: it is what abandons the threads (2s each here
    # would make this a 32s test for no extra coverage).
    monkeypatch.setattr(health, "_CHECK_TIMEOUT_SECONDS", 0.1)

    with _tcp_tarpit() as port:
        monkeypatch.setenv(
            "DATABASE_URL", f"postgresql+psycopg://probe:probe@127.0.0.1:{port}/probe"
        )
        get_settings.cache_clear()
        health.reset_probe_engine()
        try:
            for _ in range(_PROBES_PAST_POOL_CAPACITY):
                # The memoised result would otherwise turn this into a single probe.
                health.reset_dependency_cache()
                assert health.check_dependencies()[health.Dependency.DATABASE] is False

            assert application_pool.checkedout() == 0
            # And the application really still serves: 401 means the login path opened a
            # session, queried the user table and came back -- no pool timeout, no 500.
            with TestClient(app) as client:
                response: Response = client.post(
                    "/auth/token",
                    data={"username": "nobody@example.test", "password": "wrong-password"},
                )
            assert response.status_code == 401
            assert application_pool.checkedout() == 0
        finally:
            get_settings.cache_clear()
            health.reset_probe_engine()


def test_a_burst_of_readiness_calls_shares_one_probe_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """/health/ready is anonymous and unthrottled, so it must not probe per request.

    Without the memoised result, a burst of callers during an outage spawns three threads
    each and pins the anyio worker pool that every `def` handler in the API shares.
    """
    probe_rounds = 0

    def counted() -> None:
        nonlocal probe_rounds
        probe_rounds += 1

    monkeypatch.setattr(health, "_check_storage", counted)

    with TestClient(app) as client:
        for _ in range(5):
            status_code, payload = _readiness(client)
            assert status_code == 200
            assert payload["checks"]["storage"] == "ok"

    assert probe_rounds == 1

    # ... and the memo is droppable, which is what keeps the rest of the suite honest.
    health.reset_dependency_cache()
    with TestClient(app) as client:
        _readiness(client)
    assert probe_rounds == 2


def test_a_probe_round_in_flight_never_blocks_another_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller arriving during a slow round serves the last answer, it does not queue.

    Queueing would undo the point of memoising: `readiness` is a `def` handler, so every
    waiter holds one of the anyio threadpool workers that all `def` routes in the API
    share, and a down dependency costs the round 6s.
    """
    # A real, all-green round first: stale-but-known is what a later caller serves.
    assert all(health.check_dependencies().values())
    # Expire it immediately, so the next call really starts a round rather than hitting
    # the memo -- without clearing it, which would send both callers down the cold-start
    # path where waiting is the only correct behaviour.
    monkeypatch.setattr(health, "_RESULT_TTL_SECONDS", 0.0)

    entered = threading.Event()
    release = threading.Event()

    def hangs() -> None:
        entered.set()
        release.wait(30)

    monkeypatch.setattr(health, "_CHECK_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(health, "_check_storage", hangs)

    slow_round = threading.Thread(target=health.check_dependencies, daemon=True)
    slow_round.start()
    try:
        assert entered.wait(10), "the background round never reached the storage probe"
        started = perf_counter()
        states = health.check_dependencies()
        elapsed = perf_counter() - started
    finally:
        release.set()
        slow_round.join(15)

    assert elapsed < 1
    assert states == {
        health.Dependency.DATABASE: True,
        health.Dependency.REDIS: True,
        health.Dependency.STORAGE: True,
    }


def test_two_cold_callers_share_a_single_probe_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold start is the one case where a caller legitimately waits -- once, not twice.

    With no previous answer to serve there is nothing to do but wait for the round in
    flight; the second caller must then pick up its result rather than probe again, which
    is what would turn a restart under load into a thundering herd on every dependency.
    """
    health.reset_dependency_cache()
    rounds = 0
    entered = threading.Event()
    release = threading.Event()

    def counted_and_slow() -> None:
        nonlocal rounds
        rounds += 1
        entered.set()
        release.wait(10)

    monkeypatch.setattr(health, "_CHECK_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(health, "_check_storage", counted_and_slow)

    results: list[dict[health.Dependency, bool]] = []

    def call() -> None:
        results.append(health.check_dependencies())

    first = threading.Thread(target=call, daemon=True)
    second = threading.Thread(target=call, daemon=True)
    first.start()
    try:
        assert entered.wait(10), "the first round never reached the storage probe"
        second.start()
        # Long enough for the second caller to reach the lock the first one holds.
        sleep(0.2)
    finally:
        release.set()
        first.join(15)
        second.join(15)

    assert rounds == 1
    assert results == [results[0], results[0]]


def test_check_bucket_reports_a_forbidden_bucket_as_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """403 is the other half of `check_bucket`'s thesis, next to the bodiless 404.

    A bucket the credentials cannot see answers 403, and that is infrastructure not in the
    state the API needs -- an outage, never the "missing object" case. Stubbed rather than
    served, because no in-memory backend produces an authorization failure on demand; this
    is the exact branch a refactor that routed `check_bucket` through `_NOT_FOUND_CODES`
    (or that started treating any 4xx as "not found") would break.
    """
    client = new_s3_client()
    stubber = Stubber(client)
    stubber.add_client_error("head_bucket", service_error_code="403", http_status_code=403)

    def stubbed_client(
        settings: Settings, *, connect_timeout: int, read_timeout: int, total_max_attempts: int
    ) -> S3Client:
        return client

    monkeypatch.setattr(object_storage_module, "_new_client", stubbed_client)
    import_object_storage.reset()

    with stubber, pytest.raises(ObjectStorageUnavailableError):
        import_object_storage.check_bucket()
    stubber.assert_no_pending_responses()


def test_readiness_body_never_leaks_dependency_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """/health/ready is unauthenticated: an outage must not describe the backend."""
    monkeypatch.setenv("REDIS_URL", UNREACHABLE_REDIS_URL)
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(health, "login_rate_limiter", LoginRateLimiter())
        with TestClient(app) as client:
            _, payload = _readiness(client)
    finally:
        get_settings.cache_clear()

    serialized = str(payload)
    assert set(payload) == {"status", "checks", "timestamp"}
    assert "127.0.0.1" not in serialized
    assert "redis://" not in serialized
    assert get_settings().garage_access_key_id not in serialized
