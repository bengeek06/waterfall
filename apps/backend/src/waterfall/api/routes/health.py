"""Liveness and readiness probes.

The split is deliberate (E13-03):

- `GET /health` is *liveness*: "is this process alive?". It checks nothing else, on
  purpose. An orchestrator restarts a container that fails its liveness probe, so wiring
  a dependency check in here would make a Redis blip restart every API container --
  turning a partial outage into a full one.
- `GET /health/ready` is *readiness*: "can this process serve traffic right now?". It
  really contacts Postgres, Redis and the object store, and answers 503 when any of them
  is unreachable, so Compose (and later any orchestrator) can sequence what depends on
  the API and take an instance out of rotation instead of killing it.

The check logic lives here, next to the route that owns it, for the same reason
`LoginRateLimiter` lives in `auth.py`: it is infrastructure plumbing owned by one
endpoint, and it needs that endpoint's own Redis client -- a `core/` or `services/`
module importing `api.routes.auth` would invert the layering (and risk an import cycle,
since `auth` imports `waterfall.services`). `check_dependencies()` is nonetheless a
standalone, argument-free function returning a per-dependency mapping, which is what
E13-04's `dependency_up` gauge is fed from -- the readiness handler publishes the result
it already has, so the metric never costs a probe of its own.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from time import monotonic
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.pool import NullPool

from waterfall.api.routes.auth import login_rate_limiter
from waterfall.core.config import get_settings
from waterfall.core.object_storage import import_object_storage
from waterfall.core.observability import set_dependency_up
from waterfall.schemas.health import DependencyState, ReadinessChecks, ReadinessStatus

router = APIRouter(prefix="/health")
logger = logging.getLogger(__name__)

# Per-dependency wall-clock budget, enforced here and not left to each client library:
# every client already has its own timeouts, but they are tuned for the data path (the
# object storage one alone can spend 3 x 5s connecting), and a probe that inherits them
# would hang far past the point where the answer is still useful.
#
# 2s x 3 dependencies = 6s worst case, which must stay *under* the Docker healthcheck's
# own `timeout:` (10s in infra/docker/docker-compose.yml, with an 8s client-side timeout
# on the urllib call itself): if Docker gave up first, the probe would be reported as a
# flat failure and the one thing it exists to produce -- which dependency is down --
# would be lost.
_CHECK_TIMEOUT_SECONDS = 2.0

# How long one probe round is reused. The deadline above bounds a single round; this
# bounds how many rounds a burst of callers can start. `/health/ready` is anonymous and
# not rate limited, and every round spawns one thread per dependency, so without this a
# few dozen concurrent requests against a down dependency would pin every worker of the
# anyio threadpool that all `def` handlers share -- freezing the rest of the API for as
# long as the outage lasts. Sized against the 15s Docker `interval:`: an answer is at
# worst this TTL plus one round old (5s + 6s), i.e. under one poll period, and Docker
# needs 6 consecutive failures before flipping the container to unhealthy. E13-04's
# `dependency_up` gauge reads this same memoised result rather than probing again.
_RESULT_TTL_SECONDS = 5.0

# libpq parameters for the probe connection (see `_probe_engine`). `connect_timeout` is
# the one that matters against a host that accepts TCP and then says nothing -- the
# classic silent partition -- because it bounds the whole startup handshake, not just the
# SYN. `tcp_user_timeout` covers the other shape, a peer that disappears mid-query and
# stops acknowledging, which no application-level timeout can see. `statement_timeout` is
# a server-side GUC and only helps when the server is alive but slow; it is the least
# useful of the three here, and is set anyway so a probe can never outlive its budget on
# a responsive-but-overloaded database.
_PROBE_CONNECT_TIMEOUT_SECONDS = 2
_PROBE_TCP_USER_TIMEOUT_MS = 2000
_PROBE_STATEMENT_TIMEOUT_MS = 2000

_result_lock = threading.Lock()
_last_result: tuple[float, dict[Dependency, bool]] | None = None


class Dependency(StrEnum):
    """The backing services `GET /health/ready` reports on.

    The values are the response body keys, and will be the `dependency` label values of
    E13-04's gauge -- one spelling, shared.
    """

    DATABASE = "database"
    REDIS = "redis"
    STORAGE = "storage"


@router.get("")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    response_model=ReadinessStatus,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessStatus,
            "description": "Au moins une dépendance est injoignable",
        }
    },
)
def readiness(response: Response) -> ReadinessStatus:
    states = check_dependencies()
    # E13-04: mirror the answer onto `dependency_up` for /metrics. Fed from the result
    # this handler already holds -- which may be memoised -- so observability never costs
    # an extra probe, and so a scrape of /metrics costs none at all. The metric stays out
    # of the response body: /health/ready answers orchestrators, /metrics answers
    # Prometheus, and the two payloads are deliberately not merged.
    for dependency, is_up in states.items():
        set_dependency_up(dependency.value, is_up)
    is_ready = all(states.values())
    # Same body either way, only the status code differs: a caller that gets a 503 needs
    # the per-dependency breakdown even more than one that gets a 200.
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(
        status="ready" if is_ready else "unavailable",
        checks=ReadinessChecks(
            database=_state(states[Dependency.DATABASE]),
            redis=_state(states[Dependency.REDIS]),
            storage=_state(states[Dependency.STORAGE]),
        ),
        timestamp=datetime.now(UTC),
    )


def check_dependencies() -> dict[Dependency, bool]:
    """Probe every backing service and report whether each one answered.

    Sequential, not concurrent: three probes are cheap, and running them one after the
    other keeps the worst case a plain sum that can be reasoned about against the Docker
    healthcheck timeout (see `_CHECK_TIMEOUT_SECONDS`). Never raises -- a dependency that
    fails, times out, or blows up in an unexpected way is simply reported as `False`.

    Memoised for `_RESULT_TTL_SECONDS`, with at most one probe round in flight. This is
    the back-pressure the endpoint would otherwise have none of -- it is anonymous and
    not rate limited, and every round spawns a thread per dependency -- and it also
    spares the dependencies, which during an outage are by hypothesis already struggling.
    Tests that simulate an outage must call `reset_dependency_cache()` first.
    """
    cached = _last_result
    if cached is not None and monotonic() - cached[0] < _RESULT_TTL_SECONDS:
        # A copy: the mapping is handed to callers (the route, E13-04's gauge) that must
        # not be able to mutate what the next caller reads.
        return dict(cached[1])

    if cached is None:
        # Nothing to serve yet: the very first caller has to wait for a real answer.
        with _result_lock:
            return dict(_probe_round())

    # Stale result in hand, round already in flight: answer now rather than queue behind
    # it. `readiness` is a `def` handler, so every waiter would hold one of the anyio
    # threadpool's workers that all `def` routes share -- blocking 40 of them for the 6s
    # a down dependency costs is precisely the API-wide freeze this guards against. The
    # answer served is at worst one TTL plus one round old, well inside the 15s Docker
    # polls at and the 6 retries it needs before flipping the container to unhealthy.
    if not _result_lock.acquire(blocking=False):
        return dict(cached[1])
    try:
        return dict(_probe_round())
    finally:
        _result_lock.release()


def _probe_round() -> dict[Dependency, bool]:
    """Probe all three dependencies and memoise the outcome. Call holding `_result_lock`.

    Re-reads the memo first: between the unlocked read in `check_dependencies` and the
    lock being granted, another caller may have just finished a round.
    """
    global _last_result
    cached = _last_result
    if cached is not None and monotonic() - cached[0] < _RESULT_TTL_SECONDS:
        return cached[1]
    states = {
        Dependency.DATABASE: _probe(Dependency.DATABASE, _check_database),
        Dependency.REDIS: _probe(Dependency.REDIS, _check_redis),
        Dependency.STORAGE: _probe(Dependency.STORAGE, _check_storage),
    }
    # Stamped after the probes, not before: a round that spent its full 6s budget would
    # otherwise be born almost expired and the next caller would re-probe immediately.
    _last_result = (monotonic(), states)
    return states


def reset_dependency_cache() -> None:
    """Forget the memoised probe result. Test utility -- no production caller.

    The suite simulates outages by repointing settings in-process, within a single test,
    far faster than `_RESULT_TTL_SECONDS`; without this a test would assert against the
    previous test's answer. Called from conftest's autouse fixture, so no individual test
    has to remember.
    """
    global _last_result
    with _result_lock:
        _last_result = None


def _probe(dependency: Dependency, check: Callable[[], None]) -> bool:
    """Run `check` under a hard deadline; anything but a clean return means "down".

    A daemon thread joined with a timeout, rather than `concurrent.futures`: a hung probe
    must not hold the request *nor* the process. `ThreadPoolExecutor` registers an atexit
    hook that joins its workers, so a thread stuck on an unresponsive dependency would
    also stall interpreter shutdown -- i.e. make the container slow to stop precisely
    when something is already broken. A daemon thread is abandoned instead.

    What an abandoned thread actually costs, since the join only bounds the *request*:

    - Database: ~2s, from libpq's own `connect_timeout`/`tcp_user_timeout` on the probe
      engine, which is also pool-less -- see `_probe_engine` for why both matter.
    - Redis: ~4s, not the 2s `_REDIS_SOCKET_TIMEOUT_SECONDS` suggests. `auth.py` builds
      the client with `Retry(ExponentialBackoff(), 1)`, so a refused or silent server
      costs two 2s attempts plus the backoff between them.
    - Object storage: ~2s, one attempt with a 1s connect and a 1s read timeout
      (`_PROBE_*` in core/object_storage.py).

    None of these bound *name resolution*: `socket.getaddrinfo` is a blocking libc call
    that neither botocore's `connect_timeout` nor redis-py's `socket_connect_timeout`
    can interrupt, so with a slow or flapping DNS (a Compose service being recreated) a
    probe thread lives for the resolver's own budget -- on the order of 20s with default
    `resolv.conf` timeouts across A and AAAA -- whatever the numbers above say. That is
    survivable for Redis and object storage, whose clients release their pooled socket in
    their own `finally`, and is precisely why the database probe must not be able to hold
    a slot of the application's connection pool.
    """
    outcome: list[bool] = []

    def run() -> None:
        try:
            check()
        # Intentionally broad: the probe's contract is "never raise". A dependency client
        # raising something unforeseen (a driver-level TypeError on a malformed setting,
        # say) must still be reported as that dependency being down, not bubble up as a
        # 500 from an endpoint whose entire job is to diagnose outages.
        except Exception as exc:
            # The underlying cause, like auth.py does for the same class of failure: the
            # wrapper messages (`ObjectStorageUnavailableError`,
            # `RateLimiterUnavailableError`) say *what* failed but not *why*, and "could
            # not connect to endpoint X" is the whole diagnostic value of this line.
            # Message only -- no traceback, no settings dump: redis-py, botocore and the
            # DB drivers all report host, port and endpoint, never a credential. In
            # particular redis-py never puts the URL (nor a password carried in it) in an
            # exception message -- `parse_url` raises on the malformed *component*, and
            # connection errors are formatted from host/port. The guarantee is that
            # property of the library, not a configuration convention: REDIS_URL may well
            # carry a password, which auth.py's `_get_client` explicitly supports.
            logger.warning(
                "health.readiness.dependency_unavailable",
                extra={"dependency": dependency.value, "error": str(exc.__cause__ or exc)},
            )
            outcome.append(False)
        else:
            outcome.append(True)

    thread = threading.Thread(target=run, name=f"readiness-{dependency.value}", daemon=True)
    thread.start()
    thread.join(_CHECK_TIMEOUT_SECONDS)
    if not outcome:
        logger.warning(
            "health.readiness.dependency_timeout",
            extra={"dependency": dependency.value, "timeout_seconds": _CHECK_TIMEOUT_SECONDS},
        )
        return False
    return outcome[0]


def _check_database() -> None:
    # The cheapest possible round trip: this must prove the server answers, not just that
    # a `Connection` object could be built.
    with _probe_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


@lru_cache(maxsize=1)
def _probe_engine() -> Engine:
    """The engine the readiness probe connects with -- deliberately not `get_engine()`.

    Two properties the application engine cannot give:

    - `NullPool`. `_probe` abandons a thread that overruns its deadline, and an abandoned
      thread keeps whatever it checked out. Borrowing from the shared `QueuePool` means a
      hung probe permanently burns a slot: at one poll every 15s a silent partition
      exhausts `pool_size + max_overflow` in under four minutes, after which every real
      request waits `pool_timeout` and then fails -- and the checkouts never come back,
      so the API stays broken after the database recovers. Worse, the stuck threads are
      the anyio workers that `/health/ready` itself (a `def` handler) needs, so the probe
      stops answering and the diagnosis is lost exactly when it is needed. With no pool,
      a hung probe leaks at most one socket, which its own timeouts then close.
    - Real driver timeouts. `get_engine()` passes no `connect_args`, so libpq will wait
      indefinitely on a host that accepts TCP and never completes the handshake; the
      2s join would then abandon a thread that never dies. The parameters below make the
      thread actually terminate, with `_probe` left as the belt to their braces.

    Hardening `get_engine()` itself (pool_pre_ping, an application-wide connect_timeout)
    is a separate concern and deliberately out of scope here: those values have to be
    chosen against the data path's latency profile, not the probe's.

    Cached like `get_engine()`; `reset_probe_engine()` drops it for tests.
    """
    url = make_url(get_settings().database_url)
    kwargs: dict[str, Any] = {"poolclass": NullPool}
    if url.get_backend_name() == "postgresql":
        kwargs["connect_args"] = {
            "connect_timeout": _PROBE_CONNECT_TIMEOUT_SECONDS,
            "tcp_user_timeout": _PROBE_TCP_USER_TIMEOUT_MS,
            "options": f"-c statement_timeout={_PROBE_STATEMENT_TIMEOUT_MS}",
        }
    return create_engine(url, **kwargs)


def reset_probe_engine() -> None:
    """Dispose the cached probe engine and re-read the settings on the next probe.

    Test utility, like `ObjectStorage.reset()`: the suite repoints DATABASE_URL in-process
    to simulate an unreachable database, and an engine built from the previous value would
    keep answering for it.
    """
    if _probe_engine.cache_info().currsize:
        _probe_engine().dispose()
    _probe_engine.cache_clear()


def _check_redis() -> None:
    # Through the login rate limiter's own client: that is the only Redis this app uses,
    # and reporting on any other connection would risk a green probe next to a login path
    # that fails closed.
    login_rate_limiter.ping()


def _check_storage() -> None:
    import_object_storage.check_bucket()


def _state(is_up: bool) -> DependencyState:
    return "ok" if is_up else "unavailable"
