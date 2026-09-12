"""Backend guardrail for issue #137: raw-string (or raw-list) ``HTTPException.detail``
messages must never leak untranslated English text into API responses.

``waterfall.main._generic_http_exception_handler`` rewrites a string or
list ``detail`` into ``{"code": "GENERIC_ERROR"}`` while leaving already
structured (``dict``) details untouched, and preserving any ``headers``
(e.g. ``WWW-Authenticate``) carried by the original ``HTTPException``.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.main import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"error.handler.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_raw_string_detail_is_rewritten_to_generic_error_code() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "raw.detail@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        # Wrong password -> `HTTPException(status_code=401, detail="Incorrect
        # username or password", ...)`: a raw English string.
        response = client.post(
            "/auth/token",
            data={"username": "raw.detail@example.com", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "GENERIC_ERROR"}}


def test_www_authenticate_header_is_preserved_on_rewritten_401() -> None:
    with TestClient(app) as client:
        register_response: Response = client.post(
            "/auth/register",
            json={"email": "header.preserved@example.com", "password": "SuperSecret123"},
        )
        assert register_response.status_code == 201

        response = client.post(
            "/auth/token",
            data={"username": "header.preserved@example.com", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    # The body is still rewritten -- the header fix must not be a special
    # case that skips the generic rewrite.
    assert response.json() == {"detail": {"code": "GENERIC_ERROR"}}


def test_raw_list_detail_is_rewritten_to_generic_error_code() -> None:
    """Moyenne finding on the #137 review: ``_PlanningTaskBodyValidationRoute``
    (``api/routes/planning_support.py``) converts a request-body
    ``RequestValidationError`` into ``HTTPException(400, detail=exc.errors())``
    -- a ``list`` of raw Pydantic error dicts (``"Field required"``, etc.),
    the same class of untranslated-English leak as a bare string, just
    shaped as a list instead of a string.

    Aimed at ``PATCH /projects/{id}/tasks/{uid}`` since E14-05 (#331) removed the
    planning-snapshot endpoint this used to probe. The route class under test is
    the same one, applied to a route that still carries it; the behaviour this
    guards is the error handler's, not that of any particular endpoint.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)

        # A blank `name` fails `TaskUpdate`'s own validator: project/task existence
        # is never reached, since `_PlanningTaskBodyValidationRoute` converts the
        # body-validation failure before the endpoint runs.
        response = client.patch(
            "/projects/1/tasks/1",
            json={"name": "   "},
            headers=headers,
        )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "GENERIC_ERROR"}}


def test_structured_detail_is_left_untouched() -> None:
    """A ``dict`` detail carries a machine-readable code and must pass through as is.

    Probed on a revision endpoint since E14-05 (#331): every refusal of that API is
    structured by construction (``api/revision_errors.py``), which makes it the
    natural place to pin the "already structured details are not rewritten" half of
    the handler's contract.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_response = client.post(
            "/projects", json={"name": "Error handler fixture"}, headers=headers
        )
        assert project_response.status_code == 201
        project_id = cast(int, project_response.json()["id"])

        response = client.post(
            f"/projects/{project_id}/revisions/9999/nodes/delete",
            json={"node_ids": [1], "expected_lock_version": 0},
            headers=headers,
        )

    assert response.status_code == 404
    body = cast(dict[str, Any], response.json())
    assert body["detail"] == {"code": "REVISION_NOT_FOUND"}
