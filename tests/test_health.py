from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def test_liveness() -> None:
    with TestClient(app) as client:
        response: Response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness() -> None:
    with TestClient(app) as client:
        response: Response = client.get("/health/ready")
    assert response.status_code == 200
    payload: dict[str, str] = response.json()
    assert payload["status"] == "ready"
    assert "timestamp" in payload
