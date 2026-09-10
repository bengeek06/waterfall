"""Shared helpers for tests that need a real Redis backend.

Mirrors _postgres_support.py's reachability policy: tests exercising the Redis-backed
login rate limiter run against a real Redis rather than a mock, so behaviour stays
honest with production, but skip cleanly with an actionable message when no Redis is
reachable locally.

Note this only spares *these* tests: the login rate limiter is fail-closed, so with no
Redis running every test that authenticates through POST /auth/token gets a 503. Running
the suite does require a reachable Redis; the skip here just keeps the failure mode of
the Redis-specific tests from being a confusing assertion error.

Deliberately not named test_*.py, for the same reason as _postgres_support.py: pytest's
default collection would otherwise try to import it as a test module.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit, urlunsplit

import pytest
import redis
from redis.exceptions import RedisError

# Matches the default REDIS_URL in waterfall.core.config.Settings: an unauthenticated
# local Redis. Unlike _postgres_support's default, this one does NOT match the
# docker-compose `redis` service, which requires a password (REDIS_PASSWORD) -- pointing
# at it needs TEST_REDIS_URL to carry that password. CI sets TEST_REDIS_URL explicitly.
DEFAULT_TEST_REDIS_URL = "redis://localhost:6379/0"

# Never let a reachability probe or test setup hang if Redis is down.
_REDIS_SOCKET_TIMEOUT_SECONDS = 2


def redis_test_url() -> str:
    return os.environ.get("TEST_REDIS_URL", DEFAULT_TEST_REDIS_URL)


def redis_test_url_and_password() -> tuple[str, str | None]:
    """Split the test Redis URL into a credential-free URL and its password.

    Lets a test exercise the shape docker-compose actually deploys -- REDIS_URL with no
    credentials plus a separate REDIS_PASSWORD -- regardless of how TEST_REDIS_URL is
    written (passwordless locally, password-in-URL in CI). The password is unquoted to
    match what redis-py's own from_url() would extract.
    """
    parsed = urlsplit(redis_test_url())
    password = unquote(parsed.password) if parsed.password else None
    netloc = parsed.hostname or "localhost"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return url, password


def _redact(url: str) -> str:
    """Strip any `user:password@` credentials before putting a URL in a skip message."""
    scheme, separator, remainder = url.partition("://")
    if not separator or "@" not in remainder:
        return url
    _credentials, _, host_part = remainder.rpartition("@")
    return f"{scheme}://***@{host_part}"


def redis_reachable(url: str) -> bool:
    client = redis.Redis.from_url(
        url,
        socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
    )
    try:
        return client.ping()
    except RedisError:
        return False
    finally:
        client.close()


@pytest.fixture
def require_redis() -> None:
    """Skip the requesting test if Redis is not reachable.

    Requested by name (unused return value) rather than for a yielded resource: the
    tests that need this just exercise the application's own login_rate_limiter
    singleton, which already reads REDIS_URL from settings.
    """
    url = redis_test_url()
    if not redis_reachable(url):
        pytest.skip(
            "Redis is not reachable at "
            f"{_redact(url)}. Run this test either against a passwordless local Redis "
            "(`docker run --rm -d -p 6379:6379 redis:7.4-alpine`), or against the "
            "docker-compose `redis` service -- which requires a password, so you must "
            "set TEST_REDIS_URL to include it: "
            "TEST_REDIS_URL=redis://:$REDIS_PASSWORD@localhost:6379/0 (percent-encode "
            "any /, + or @ in the password). Just starting the compose service without "
            "TEST_REDIS_URL is not enough: the connection is refused with "
            "AuthenticationError and this test skips again."
        )
