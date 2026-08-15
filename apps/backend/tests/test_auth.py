import os
from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

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
        assert "refreshToken" in token_payload
        assert token_payload["token_type"] == "bearer"

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


def test_refresh_token_rotation_revokes_previous_refresh_token() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "rotate@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        login_response = _login(client, "rotate@example.com", "SuperSecret123")
        assert login_response.status_code == 200
        first_tokens: dict[str, Any] = login_response.json()

        refresh_response: Response = client.post(
            "/auth/refresh",
            json={"refreshToken": first_tokens["refreshToken"]},
        )
        assert refresh_response.status_code == 200
        second_tokens: dict[str, Any] = refresh_response.json()

        stale_refresh_response: Response = client.post(
            "/auth/refresh",
            json={"refreshToken": first_tokens["refreshToken"]},
        )
        assert stale_refresh_response.status_code == 401

        me_response: Response = client.get(
            "/auth/me",
            headers=_auth_header(cast(str, second_tokens["access_token"])),
        )
        assert me_response.status_code == 200


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
        users_payload = cast(list[dict[str, Any]], users_response.json())
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


def test_registration_can_be_disabled_outside_dev() -> None:
    login_rate_limiter.clear()
    os.environ["APP_ENV"] = "prod"
    os.environ["AUTH_ALLOW_PUBLIC_REGISTER"] = "false"
    os.environ["SECRET_KEY"] = "prod-secret-for-tests"
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


def test_login_rate_limit() -> None:
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


def test_login_lockout_after_failed_attempts() -> None:
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
