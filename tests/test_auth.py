from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def test_register_login_and_me() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        token_response: Response = client.post(
            "/auth/token",
            data={"username": "alice@example.com", "password": "SuperSecret123"},
        )
        assert token_response.status_code == 200
        token_payload: dict[str, str] = token_response.json()
        token = token_payload["access_token"]

        me_response: Response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
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
