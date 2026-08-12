from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = "import.tester@example.com"
    password = "SuperSecret123!"

    register_response: Response = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert register_response.status_code == 201

    token_response: Response = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    )
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def test_import_batch_minimal_flow() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)

        create_response: Response = client.post(
            "/imports/v1/batches",
            json={"importMode": "standard", "sourceName": "planning_rain.xml"},
            headers=headers,
        )
        assert create_response.status_code == 201
        batch = create_response.json()
        assert batch["status"] == "pending"
        batch_id = batch["id"]

        upload_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/xml",
            files={
                "file": (
                    "planning_rain.xml",
                    '<Project xmlns="http://schemas.microsoft.com/project"></Project>',
                    "application/xml",
                )
            },
            headers=headers,
        )
        assert upload_response.status_code == 202
        assert upload_response.json()["sourceName"] == "planning_rain.xml"

        run_response: Response = client.post(
            f"/imports/v1/batches/{batch_id}/run",
            json={"dryRun": True, "failFast": True},
            headers=headers,
        )
        assert run_response.status_code == 202
        assert run_response.json()["status"] == "running"

        status_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["id"] == batch_id
        assert "counters" in status_payload
        assert "warnings" in status_payload

        errors_response: Response = client.get(
            f"/imports/v1/batches/{batch_id}/errors",
            headers=headers,
        )
        assert errors_response.status_code == 200
        assert isinstance(errors_response.json()["items"], list)
