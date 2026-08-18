from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def test_metrics_endpoint() -> None:
    with TestClient(app) as client:
        _health: Response = client.get("/health")
        _project: Response = client.get("/projects/123456")
        metrics: Response = client.get("/metrics")

    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text
    assert "http_request_duration_seconds" in metrics.text
    assert 'path="/projects/{project_id}"' in metrics.text
    assert 'path="/projects/123456"' not in metrics.text
