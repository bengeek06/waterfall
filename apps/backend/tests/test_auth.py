import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine

from _redis_support import redis_test_url_and_password
from waterfall.api.routes import auth as auth_module
from waterfall.api.routes.auth import login_rate_limiter
from waterfall.core.config import get_settings
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.user import User


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def _login(client: TestClient, email: str, password: str) -> Response:
    return client.post(
        "/auth/token",
        data={"username": email, "password": password},
    )


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _admin_headers(client: TestClient) -> dict[str, str]:
    email = "admin.helper@example.com"
    password = "SuperSecret123"
    register_response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert register_response.status_code == 201

    session_factory = get_session_factory()
    with session_factory() as session:
        user = session.query(User).filter(User.email == email).one()
        user.is_admin = True
        session.add(user)
        session.commit()

    login_response = _login(client, email, password)
    assert login_response.status_code == 200
    return _auth_header(cast(str, login_response.json()["access_token"]))


def test_register_login_and_me() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        token_response = _login(client, "alice@example.com", "SuperSecret123")
        assert token_response.status_code == 200
        token_payload: dict[str, Any] = token_response.json()
        token = cast(str, token_payload["access_token"])
        assert "refreshToken" not in token_payload
        assert token_payload["token_type"] == "bearer"
        assert "HttpOnly" in token_response.headers["set-cookie"]

        me_response: Response = client.get(
            "/auth/me",
            headers=_auth_header(token),
        )
        assert me_response.status_code == 200
        me_payload: dict[str, str | int | bool] = me_response.json()
        assert me_payload["email"] == "alice@example.com"
        assert me_payload["is_active"] is True


def test_register_duplicate_email() -> None:
    with TestClient(app) as client:
        _first: Response = client.post(
            "/auth/register",
            json={"email": "bob@example.com", "password": "SuperSecret123"},
        )
        second: Response = client.post(
            "/auth/register",
            json={"email": "bob@example.com", "password": "SuperSecret123"},
        )
        assert second.status_code == 409


def test_user_creation_rejects_password_outside_policy() -> None:
    with TestClient(app) as client:
        register_response = client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "short"},
        )
        assert register_response.status_code == 422

        admin_headers = _admin_headers(client)
        admin_create_response = client.post(
            "/auth/users",
            json={"email": "admin-short@example.com", "password": "short"},
            headers=admin_headers,
        )
        assert admin_create_response.status_code == 422


def test_password_change_rejects_password_outside_policy() -> None:
    with TestClient(app) as client:
        register_response = client.post(
            "/auth/register",
            json={"email": "password-policy@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201
        login_response = _login(client, "password-policy@example.com", "SuperSecret123")
        assert login_response.status_code == 200

        response = client.post(
            "/auth/me/password",
            json={"current_password": "SuperSecret123", "new_password": "short"},
            headers=_auth_header(cast(str, login_response.json()["access_token"])),
        )
        assert response.status_code == 422


def test_inactive_user_cannot_login() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "inactive@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        session_factory = get_session_factory()
        with session_factory() as session:
            user = session.query(User).filter(User.email == "inactive@example.com").first()
            assert user is not None
            user.is_active = False
            session.add(user)
            session.commit()

        login_response = _login(client, "inactive@example.com", "SuperSecret123")
        assert login_response.status_code == 403


def test_refresh_token_does_not_revoke_existing_access_tokens() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "rotate@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        login_response = _login(client, "rotate@example.com", "SuperSecret123")
        assert login_response.status_code == 200
        first_tokens: dict[str, Any] = login_response.json()

        refresh_response: Response = client.post("/auth/refresh")
        assert refresh_response.status_code == 200
        second_tokens: dict[str, Any] = refresh_response.json()

        me_response: Response = client.get(
            "/auth/me",
            headers=_auth_header(cast(str, second_tokens["access_token"])),
        )
        assert me_response.status_code == 200

        # Previous access token remains valid until explicit revocation events.
        me_with_first_access_token = client.get(
            "/auth/me",
            headers=_auth_header(cast(str, first_tokens["access_token"])),
        )
        assert me_with_first_access_token.status_code == 200


def test_logout_clears_refresh_cookie() -> None:
    with TestClient(app) as client:
        register_response = client.post(
            "/auth/register",
            json={"email": "logout@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201
        login_response = _login(client, "logout@example.com", "SuperSecret123")
        assert login_response.status_code == 200

        logout_response = client.post("/auth/logout")
        assert logout_response.status_code == 204
        assert "Max-Age=0" in logout_response.headers["set-cookie"]

        refresh_response = client.post("/auth/refresh")
        assert refresh_response.status_code == 401


def test_change_password_invalidates_previous_credentials() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "password-change@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        login_response = _login(client, "password-change@example.com", "SuperSecret123")
        assert login_response.status_code == 200
        access_token = cast(str, login_response.json()["access_token"])

        change_response: Response = client.post(
            "/auth/me/password",
            json={
                "current_password": "SuperSecret123",
                "new_password": "NewSecret123",
            },
            headers=_auth_header(access_token),
        )
        assert change_response.status_code == 204

        old_password_login = _login(client, "password-change@example.com", "SuperSecret123")
        assert old_password_login.status_code == 401

        new_password_login = _login(client, "password-change@example.com", "NewSecret123")
        assert new_password_login.status_code == 200


def test_admin_can_manage_users() -> None:
    with TestClient(app) as client:
        admin_register = client.post(
            "/auth/register",
            json={"email": "admin@example.com", "password": "SuperSecret123"},
        )
        user_register = client.post(
            "/auth/register",
            json={"email": "user@example.com", "password": "SuperSecret123"},
        )
        assert admin_register.status_code == 201
        assert user_register.status_code == 201

        session_factory = get_session_factory()
        with session_factory() as session:
            admin = session.query(User).filter(User.email == "admin@example.com").first()
            assert admin is not None
            admin.is_admin = True
            session.add(admin)
            session.commit()

            managed_user = session.query(User).filter(User.email == "user@example.com").first()
            assert managed_user is not None
            managed_user_id = managed_user.id

        admin_login = _login(client, "admin@example.com", "SuperSecret123")
        assert admin_login.status_code == 200
        admin_token = cast(str, admin_login.json()["access_token"])

        users_response = client.get("/auth/users", headers=_auth_header(admin_token))
        assert users_response.status_code == 200
        users_body = cast(dict[str, Any], users_response.json())
        users_payload = cast(list[dict[str, Any]], users_body["items"])
        assert users_body["total"] == len(users_payload)
        assert any(item["email"] == "user@example.com" for item in users_payload)

        disable_response = client.patch(
            f"/auth/users/{managed_user_id}/status",
            json={"is_active": False},
            headers=_auth_header(admin_token),
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["is_active"] is False

        role_response = client.patch(
            f"/auth/users/{managed_user_id}/role",
            json={"is_admin": True},
            headers=_auth_header(admin_token),
        )
        assert role_response.status_code == 200
        assert role_response.json()["is_admin"] is True


def test_admin_can_create_and_delete_user() -> None:
    with TestClient(app) as client:
        admin_headers = _admin_headers(client)

        create_response = client.post(
            "/auth/users",
            json={"email": "new.user@example.com", "password": "NewSecret123!"},
            headers=admin_headers,
        )
        assert create_response.status_code == 201
        created_user = cast(dict[str, Any], create_response.json())
        assert created_user["email"] == "new.user@example.com"
        user_id = cast(int, created_user["id"])

        duplicate_response = client.post(
            "/auth/users",
            json={"email": "new.user@example.com", "password": "NewSecret123!"},
            headers=admin_headers,
        )
        assert duplicate_response.status_code == 409

        delete_response = client.delete(f"/auth/users/{user_id}", headers=admin_headers)
        assert delete_response.status_code == 204

        missing_response = client.delete(f"/auth/users/{user_id}", headers=admin_headers)
        assert missing_response.status_code == 404


def test_admin_can_list_users_with_sort_and_search_and_rejects_unknown_sort() -> None:
    with TestClient(app) as client:
        admin_headers = _admin_headers(client)

        for email in ("zeta.user@example.com", "alpha.user@example.com"):
            created = client.post(
                "/auth/register", json={"email": email, "password": "SuperSecret123"}
            )
            assert created.status_code == 201

        listed = client.get("/auth/users", headers=admin_headers)
        assert listed.status_code == 200
        body = cast(dict[str, Any], listed.json())
        assert body["limit"] is None
        assert body["total"] == len(body["items"])

        ascending = client.get("/auth/users?sort=email", headers=admin_headers)
        assert ascending.status_code == 200
        emails = cast(list[str], [item["email"] for item in ascending.json()["items"]])
        assert emails == sorted(emails)

        searched = client.get("/auth/users?q=alpha.user", headers=admin_headers)
        assert searched.status_code == 200
        searched_emails = [item["email"] for item in searched.json()["items"]]
        assert searched_emails == ["alpha.user@example.com"]

        invalid_sort = client.get("/auth/users?sort=unknown_column", headers=admin_headers)
        assert invalid_sort.status_code == 400


def test_admin_cannot_delete_self() -> None:
    with TestClient(app) as client:
        admin_headers = _admin_headers(client)
        me_response = client.get("/auth/me", headers=admin_headers)
        assert me_response.status_code == 200
        me_payload = cast(dict[str, Any], me_response.json())
        me_id = cast(int, me_payload["id"])

        delete_response = client.delete(
            f"/auth/users/{me_id}",
            headers=admin_headers,
        )
        assert delete_response.status_code == 400


def test_non_admin_cannot_manage_users() -> None:
    with TestClient(app) as client:
        register_response = client.post(
            "/auth/register",
            json={"email": "simple.user@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        login_response = _login(client, "simple.user@example.com", "SuperSecret123")
        assert login_response.status_code == 200
        token = cast(str, login_response.json()["access_token"])

        users_response = client.get("/auth/users", headers=_auth_header(token))
        assert users_response.status_code == 403


def test_registration_can_be_disabled_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    from waterfall import main as main_module

    def accept_schema_revision(_engine: Engine) -> None:
        return None

    login_rate_limiter.clear()
    os.environ["APP_ENV"] = "prod"
    os.environ["AUTH_ALLOW_PUBLIC_REGISTER"] = "false"
    os.environ["SECRET_KEY"] = "prod-secret-for-tests"
    monkeypatch.setattr(main_module, "assert_database_schema_current", accept_schema_revision)
    _clear_settings_cache()

    try:
        with TestClient(app) as client:
            register_response = client.post(
                "/auth/register",
                json={"email": "blocked@example.com", "password": "SuperSecret123"},
            )
            assert register_response.status_code == 403
    finally:
        os.environ["APP_ENV"] = "test"
        os.environ.pop("AUTH_ALLOW_PUBLIC_REGISTER", None)
        os.environ["SECRET_KEY"] = "test-secret"
        _clear_settings_cache()


def test_login_rate_limit(require_redis: None) -> None:
    login_rate_limiter.clear()
    os.environ["AUTH_RATE_LIMIT_ATTEMPTS"] = "2"
    os.environ["AUTH_RATE_LIMIT_WINDOW_SECONDS"] = "60"
    _clear_settings_cache()

    try:
        with TestClient(app) as client:
            for _ in range(2):
                response = _login(client, "ratelimit@example.com", "bad-password")
                assert response.status_code == 401

            limited_response = _login(client, "ratelimit@example.com", "bad-password")
            assert limited_response.status_code == 429
    finally:
        os.environ.pop("AUTH_RATE_LIMIT_ATTEMPTS", None)
        os.environ.pop("AUTH_RATE_LIMIT_WINDOW_SECONDS", None)
        login_rate_limiter.clear()
        _clear_settings_cache()


def test_login_lockout_after_failed_attempts(require_redis: None) -> None:
    login_rate_limiter.clear()
    os.environ["AUTH_MAX_FAILED_ATTEMPTS"] = "2"
    os.environ["AUTH_LOCKOUT_MINUTES"] = "15"
    os.environ["AUTH_RATE_LIMIT_ATTEMPTS"] = "50"
    _clear_settings_cache()

    try:
        with TestClient(app) as client:
            register_response = client.post(
                "/auth/register",
                json={"email": "lockout@example.com", "password": "SuperSecret123"},
            )
            assert register_response.status_code == 201

            first_fail = _login(client, "lockout@example.com", "bad-password")
            second_fail = _login(client, "lockout@example.com", "bad-password")
            assert first_fail.status_code == 401
            assert second_fail.status_code == 401

            locked_response = _login(client, "lockout@example.com", "SuperSecret123")
            assert locked_response.status_code == 423
    finally:
        os.environ.pop("AUTH_MAX_FAILED_ATTEMPTS", None)
        os.environ.pop("AUTH_LOCKOUT_MINUTES", None)
        os.environ.pop("AUTH_RATE_LIMIT_ATTEMPTS", None)
        login_rate_limiter.clear()
        _clear_settings_cache()


def test_login_fails_closed_when_rate_limiter_redis_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A login attempt must be rejected (503), never accepted, if the rate limiter's
    Redis backend can't be reached -- fail-closed, not fail-open."""
    # A fresh LoginRateLimiter so this test's bad REDIS_URL isn't shadowed by a Redis
    # connection the shared singleton may have already opened against a working host.
    monkeypatch.setattr(auth_module, "login_rate_limiter", auth_module.LoginRateLimiter())
    # Port 1 is a privileged port nothing listens on; the connection is refused
    # immediately rather than waiting out the client's socket_connect_timeout.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    _clear_settings_cache()

    try:
        with TestClient(app) as client:
            response = _login(client, "unreachable-redis@example.com", "bad-password")
            assert response.status_code == 503
            # The body matters as much as the status: it is what the frontend surfaces,
            # and it must not leak the Redis URL (which may embed a password). The raw
            # English `detail="Login temporarily unavailable"` never reaches the client:
            # main.py's _generic_http_exception_handler rewrites every string detail into
            # this translatable code, exactly as it does for the neighbouring 423/429.
            assert response.json() == {"detail": {"code": "GENERIC_ERROR"}}
    finally:
        _clear_settings_cache()


@pytest.mark.parametrize(
    "redis_url",
    [
        # Nothing listens on privileged port 1: connection refused (a RedisError).
        pytest.param("redis://127.0.0.1:1/0", id="unreachable"),
        # No scheme -- the most banal misconfiguration. redis-py raises ValueError, not
        # RedisError, from from_url(); if it escaped, allow() would 500 instead of the
        # 503 the OpenAPI contract documents, and clear() would break the autouse
        # fixture that calls it before all ~280 tests of the suite.
        pytest.param("localhost:6379", id="malformed"),
    ],
)
def test_rate_limiter_allow_fails_closed_while_clear_stays_silent(
    monkeypatch: pytest.MonkeyPatch, redis_url: str
) -> None:
    """Locks the deliberate asymmetry between the limiter's two methods.

    Direct unit test, no TestClient: now that CI provisions a Redis, `clear()`'s
    error-swallowing branch is never exercised by the rest of the suite, so a regression
    -- someone "harmonising" the two methods -- would otherwise go unnoticed.
    """
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    _clear_settings_cache()

    try:
        limiter = auth_module.LoginRateLimiter()
        limiter.clear()
        with pytest.raises(auth_module.RateLimiterUnavailableError):
            limiter.allow("unreachable-key", max_attempts=5, window_seconds=60)
    finally:
        _clear_settings_cache()


def test_rate_limiter_authenticates_with_redis_password_outside_the_url(
    require_redis: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REDIS_PASSWORD is a setting of its own, not a fragment interpolated into REDIS_URL.

    docker-compose deploys exactly this shape, because a password from
    `openssl rand -base64 24` routinely contains `/`, `+` or `@` and would silently
    corrupt URL parsing. Skipped-but-meaningful locally (passwordless Redis, password
    None); against CI's password-protected Redis this is the authenticated path.
    """
    url, password = redis_test_url_and_password()
    monkeypatch.setenv("REDIS_URL", url)
    if password is None:
        monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("REDIS_PASSWORD", password)
    _clear_settings_cache()

    try:
        limiter = auth_module.LoginRateLimiter()
        assert limiter.allow(f"split-password-{uuid4().hex}", max_attempts=1, window_seconds=60)
    finally:
        _clear_settings_cache()


def test_login_rate_limiter_grants_exactly_max_attempts_under_concurrency(
    require_redis: None,
) -> None:
    """The prune/count/record sequence must be atomic.

    Run as three separate round-trips it is a read-modify-write: concurrent attempts on
    the same key all read the same pre-increment count and are all admitted (measured
    against a real Redis 7.4: 16 grants for a limit of 5 over 40 concurrent calls). The
    limit is a security control, so overshooting it by 3x is not acceptable slack.
    """
    limiter = auth_module.LoginRateLimiter()
    key = f"atomic-{uuid4().hex}"
    max_attempts = 5
    concurrency = 40
    # Release every thread at once, so they genuinely interleave inside the limiter
    # instead of finishing one after another as the pool warms up.
    barrier = threading.Barrier(concurrency)

    def attempt() -> bool:
        barrier.wait(timeout=30)
        return limiter.allow(key, max_attempts=max_attempts, window_seconds=60)

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(attempt) for _ in range(concurrency)]
            granted = sum(future.result() for future in futures)
        assert granted == max_attempts
    finally:
        limiter.clear()


def test_login_rate_limiter_sets_a_ttl_on_the_key(require_redis: None) -> None:
    """The window key must never be left without an expiry.

    With ZADD and EXPIRE issued as two separate commands, a process dying in between
    leaks the key forever; the Lua script makes them one step.
    """
    limiter = auth_module.LoginRateLimiter()
    key = f"ttl-{uuid4().hex}"

    try:
        assert limiter.allow(key, max_attempts=5, window_seconds=60)
        client = limiter._get_client()  # pyright: ignore[reportPrivateUsage]
        ttl = client.ttl(f"login_rate_limit:{key}")
        assert 0 < ttl <= 61
    finally:
        limiter.clear()
