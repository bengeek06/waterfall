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

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.wf_core import WfChargeLine


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
    (``api/routes/planning_support.py``, applied to 6 ``plannings.py``
    endpoints, including ``tasks/move`` below) converts a request-body
    ``RequestValidationError`` into ``HTTPException(400, detail=exc.errors())``
    -- a ``list`` of raw Pydantic error dicts (``"Field required"``, etc.),
    the same class of untranslated-English leak as a bare string, just
    shaped as a list instead of a string.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)

        # An empty body is missing every required field of `PlanningTaskMove`
        # (`task_uids`, `position`, `expected_revision`): project/planning
        # existence is never reached, since `_PlanningTaskBodyValidationRoute`
        # converts the body-validation failure before the endpoint runs.
        response = client.post(
            "/projects/1/plannings/1/tasks/move",
            json={},
            headers=headers,
        )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "GENERIC_ERROR"}}


def _seed_planning_with_parent_and_child(project_id: int) -> int:
    with get_session_factory()() as session:
        planning = WfPlanning(project_id=project_id, version_number=1, status="draft")
        session.add(planning)
        session.flush()
        session.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=1,
                    name="Root",
                    position=1,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=2,
                    name="Child",
                    parent_uid=1,
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
            ]
        )
        session.commit()
        return planning.id


def test_structured_detail_is_left_untouched() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_response = client.post(
            "/projects", json={"name": "Error handler fixture"}, headers=headers
        )
        assert project_response.status_code == 201
        project_id = cast(int, project_response.json()["id"])
        planning_id = _seed_planning_with_parent_and_child(project_id)

        with get_session_factory()() as session:
            session.add(MsTask(project_id=project_id, uid=2, name="Legacy bridge"))
            session.flush()
            session.add(WfChargeLine(project_id=project_id, task_uid=2, load_minutes=60))
            session.commit()

        # Deleting uid=2 (referenced by a charge line) raises
        # `HTTPException(detail={"code": "TASK_REFERENCED", "task_uids": [...]})`:
        # an already structured detail.
        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [2], "expected_revision": 0},
            headers=headers,
        )

    assert response.status_code == 409
    body = cast(dict[str, Any], response.json())
    assert body["detail"]["code"] == "TASK_REFERENCED"
    assert body["detail"]["task_uids"] == [2]
