"""The cost facet of a revision, over HTTP (E14-07, issue #333).

Every acceptance criterion of the issue is pinned here. The point of the module,
beyond the criteria themselves, is what it does *not* contain: no move endpoint, no
delete endpoint, no second error table, no second tree read. Moving a cost line and
deleting one are ``POST .../nodes/move`` and ``POST .../nodes/delete`` of #331,
facet-agnostic by construction, and reading one is ``GET .../nodes`` -- which is why
the "the bearing task changes, the chiffrage does not" criteria below are written
against those very endpoints.

The fixture follows ``test_revision_planning_api``'s: the project is created through
the API (so it has an owner the routes can check) and the revision straight into the
tables (so the tree under test owes nothing to the endpoints being tested).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from _revision_db_support import ReferenceData, insert_revision, insert_task
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.resources import Calendar, CostCategory, CostType, ResourceNode, ResourceRole
from waterfall.models.revision import ProjectRevision, RevisionCostFacet, RevisionPlanFacet

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "openapi" / "waterfall_v1.yaml"
GENERATED_CLIENT_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "api-client-ts"
    / "src"
    / "generated"
    / "api-types.ts"
)


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"revision.cost.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _seed_referential(session: Session, project_id: int, *, key: str) -> ReferenceData:
    calendar = Calendar(
        code=f"CAL-{key}", name="Standard", weeks_per_year=47, is_active=True, is_default=True
    )
    session.add(calendar)
    cost_type = CostType(code=f"SUP-{key}", name="Fourniture", kind="supply")
    session.add(cost_type)
    session.flush()
    category = CostCategory(
        cost_type_id=cost_type.id, accounting_code=f"SUP-{key}", name="Fournitures"
    )
    node = ResourceNode(code=f"IT-{key}", name="Informatique")
    session.add_all([category, node])
    session.flush()
    role = ResourceRole(
        node_id=node.id,
        cost_category_id=category.id,
        calendar_id=calendar.id,
        name="Developpeur",
    )
    session.add(role)
    session.flush()
    return ReferenceData(
        project_id=project_id,
        calendar_id=calendar.id,
        role_id=role.id,
        cost_type_id=cost_type.id,
        cost_category_id=category.id,
    )


class Fixture:
    """A project, a draft revision, and the two sibling tasks ``Alpha`` and ``Beta``."""

    def __init__(
        self, project_id: int, reference: ReferenceData, revision_id: int, nodes: dict[str, int]
    ) -> None:
        self.project_id = project_id
        self.reference = reference
        self.revision_id = revision_id
        self.nodes = nodes

    def url(self, suffix: str = "") -> str:
        return f"/projects/{self.project_id}/revisions/{self.revision_id}{suffix}"


def _seed(client: TestClient, headers: dict[str, str], *, status: str = "draft") -> Fixture:
    response = client.post("/projects", json={"name": "Revision cost API"}, headers=headers)
    assert response.status_code == 201
    project_id = cast(int, response.json()["id"])
    with get_session_factory()() as session:
        reference = _seed_referential(session, project_id, key=uuid4().hex[:8])
        revision = insert_revision(session, reference, status=status)
        alpha = insert_task(session, reference, revision, name="Alpha", position=1)
        beta = insert_task(session, reference, revision, name="Beta", position=2)
        milestone = insert_task(session, reference, revision, name="Jalon", position=3)
        session.flush()
        _mark_milestone(session, milestone.id)
        session.commit()
        return Fixture(
            project_id,
            reference,
            revision.id,
            {"alpha": alpha.id, "beta": beta.id, "milestone": milestone.id},
        )


def _mark_milestone(session: Session, node_id: int) -> None:
    """Flip a seeded task to a milestone, in the tables rather than through the API.

    ``insert_task`` has no ``is_milestone`` switch, and going through
    ``PATCH .../planning`` here would make the milestone guard's test depend on the
    planning facet's own write path.
    """
    facet = session.query(RevisionPlanFacet).filter(RevisionPlanFacet.node_id == node_id).one()
    facet.is_milestone = True
    session.flush()


def _lock_version(revision_id: int) -> int:
    with get_session_factory()() as session:
        revision = session.get(ProjectRevision, revision_id)
        assert revision is not None
        return revision.lock_version


def _stored_facet(node_id: int) -> RevisionCostFacet:
    with get_session_factory()() as session:
        facet = session.query(RevisionCostFacet).filter(RevisionCostFacet.node_id == node_id).one()
        session.expunge(facet)
        return facet


def _detail(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], response.json())["detail"]


def _node(client: TestClient, headers: dict[str, str], fixture: Fixture, node_id: int) -> Any:
    response = client.get(fixture.url("/nodes"), headers=headers)
    assert response.status_code == 200
    nodes = cast(list[dict[str, Any]], cast(dict[str, Any], response.json())["nodes"])
    return next(node for node in nodes if node["node_id"] == node_id)


def _create_non_labor(
    client: TestClient,
    headers: dict[str, str],
    fixture: Fixture,
    *,
    parent_id: int | None,
    lock_version: int = 0,
    label: str = "Cables",
    planned_date: str | None = None,
    cost_code_id: int | None = None,
    supply_status: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """The four optional attributes default to absent, and are supplied only where a
    test needs them *set* -- notably the move test, whose whole point is that none of
    them follows the bearing task (see ``RevisionCostFacet.planned_date``'s own
    "independent of the bearing task's dates"). Leaving them ``None`` by default keeps
    every other test's payload the minimal one its own subject needs."""
    payload: dict[str, Any] = {
        "expected_lock_version": lock_version,
        "nature": "non_labor",
        "label": label,
        "parent_id": parent_id,
        "quantity": "5.00",
        "cost_type_id": fixture.reference.cost_type_id,
        "cost_category_id": fixture.reference.cost_category_id,
        "unit_cost": "25.00",
    }
    for name, value in (
        ("planned_date", planned_date),
        ("cost_code_id", cost_code_id),
        ("supply_status", supply_status),
        ("comment", comment),
    ):
        if value is not None:
            payload[name] = value
    response = client.post(fixture.url("/cost-lines"), json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _root_cost_code_id(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    """The project's own auto-created root cost code (E6-01/#62's invariant).

    ``RevisionCostFacet.cost_code_id`` is a real foreign key, so a test that wants the
    field *set* needs an existing row, not an arbitrary integer.
    """
    response = client.get(f"/projects/{project_id}/cost-codes", headers=headers)
    assert response.status_code == 200, response.text
    items = cast(list[dict[str, Any]], cast(dict[str, Any], response.json())["items"])
    return cast(int, items[0]["id"])


def _create_labor(
    client: TestClient,
    headers: dict[str, str],
    fixture: Fixture,
    *,
    parent_id: int | None,
    lock_version: int = 0,
    hours: str = "12.00",
) -> dict[str, Any]:
    response = client.post(
        fixture.url("/cost-lines"),
        json={
            "expected_lock_version": lock_version,
            "nature": "labor",
            "label": "Developpement",
            "parent_id": parent_id,
            "role_id": fixture.reference.role_id,
            "hours": hours,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


# --------------------------------------------------------------------------------------
# Acceptance 1: moving a non-MO line changes its bearing task and nothing else
# --------------------------------------------------------------------------------------


def test_moving_a_non_labor_line_changes_its_bearing_task_and_no_chiffrage() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        created = _create_non_labor(
            client,
            headers,
            fixture,
            parent_id=fixture.nodes["alpha"],
            planned_date="2027-05-18",
            cost_code_id=_root_cost_code_id(client, headers, fixture.project_id),
            supply_status="ordered",
            comment="Devis fournisseur",
        )
        node_id = cast(int, created["node_id"])

        before = _node(client, headers, fixture, node_id)["cost"]
        assert before["bearing_task_node_id"] == fixture.nodes["alpha"]
        assert before["bearing_task_name"] == "Alpha"
        # Every field the assertion below compares is actually set, or "unchanged by
        # the move" would only ever be comparing nulls.
        assert before["planned_date"] == "2027-05-18"
        assert before["cost_code_id"] is not None
        assert before["supply_status"] == "ordered"
        assert before["comment"] == "Devis fournisseur"

        move = client.post(
            fixture.url("/nodes/move"),
            json={
                "expected_lock_version": created["lock_version"],
                "node_ids": [node_id],
                "target_parent_id": fixture.nodes["beta"],
            },
            headers=headers,
        )
        assert move.status_code == 200, move.text

        after = _node(client, headers, fixture, node_id)["cost"]
        assert after["bearing_task_node_id"] == fixture.nodes["beta"]
        assert after["bearing_task_name"] == "Beta"
        # The whole point of the single tree: the chiffrage is untouched by the move.
        # ``planned_date`` is named explicitly among them because it is the one field
        # a reader could plausibly expect to follow the bearing task -- it is a date,
        # and the task it now hangs under has its own -- whereas the facet declares it
        # "independent of the bearing task's dates, and the sole source of the ``year``
        # a frozen line carries once the revision is validated".
        for field in (
            "quantity",
            "unit_cost",
            "cost_category_id",
            "cost_type_id",
            "nature",
            "planned_date",
            "cost_code_id",
            "supply_status",
            "comment",
        ):
            assert after[field] == before[field], field


# --------------------------------------------------------------------------------------
# Acceptance 2: moving the bearing task leaves an MO line's role and hours alone
# --------------------------------------------------------------------------------------


def test_moving_the_bearing_task_leaves_a_labor_line_role_and_hours_untouched() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        created = _create_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])
        before = _node(client, headers, fixture, node_id)["cost"]
        assert before["bearing_task_node_id"] == fixture.nodes["alpha"]

        # ``Alpha`` itself moves under ``Beta``, carrying its subtree -- the cost node
        # is never named in the request.
        move = client.post(
            fixture.url("/nodes/move"),
            json={
                "expected_lock_version": created["lock_version"],
                "node_ids": [fixture.nodes["alpha"]],
                "target_parent_id": fixture.nodes["beta"],
            },
            headers=headers,
        )
        assert move.status_code == 200, move.text

        alpha = _node(client, headers, fixture, fixture.nodes["alpha"])
        assert alpha["parent_id"] == fixture.nodes["beta"]
        after = _node(client, headers, fixture, node_id)["cost"]
        assert after["bearing_task_node_id"] == fixture.nodes["alpha"]
        assert after["role_id"] == before["role_id"] == fixture.reference.role_id
        assert Decimal(cast(str, after["hours"])) == Decimal("12.00")


# --------------------------------------------------------------------------------------
# Acceptance 3: a cost line at the root is accepted (INV-01)
# --------------------------------------------------------------------------------------


def test_a_cost_line_at_the_root_is_accepted_and_has_no_bearing_task() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        created = _create_non_labor(
            client, headers, fixture, parent_id=None, label="Frais generaux"
        )

        cost = _node(client, headers, fixture, cast(int, created["node_id"]))["cost"]
        assert cost["bearing_task_node_id"] is None
        assert cost["bearing_task_name"] is None
        assert cost["label"] == "Frais generaux"


# --------------------------------------------------------------------------------------
# Acceptance 4: a validated revision refuses every cost write, with the planning code
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["validated", "superseded"])
def test_every_cost_write_on_a_frozen_revision_is_refused_as_revision_immutable(
    status: str,
) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        draft = _seed(client, headers)
        created = _create_non_labor(client, headers, draft, parent_id=draft.nodes["alpha"])
        node_id = cast(int, created["node_id"])
        with get_session_factory()() as session:
            revision = session.get(ProjectRevision, draft.revision_id)
            assert revision is not None
            revision.status = status
            session.commit()
        frozen_lock = _lock_version(draft.revision_id)

        create = client.post(
            draft.url("/cost-lines"),
            json={
                "expected_lock_version": frozen_lock,
                "nature": "labor",
                "label": "Refusee",
                "role_id": draft.reference.role_id,
                "hours": "1.00",
            },
            headers=headers,
        )
        assert create.status_code == 409, create.text
        assert _detail(create)["code"] == "REVISION_IMMUTABLE"

        patch = client.patch(
            draft.url(f"/nodes/{node_id}/cost"),
            json={"expected_lock_version": frozen_lock, "quantity": "9.00"},
            headers=headers,
        )
        assert patch.status_code == 409, patch.text
        assert _detail(patch)["code"] == "REVISION_IMMUTABLE"

        # INV-03 to the letter: nothing moved, counter included.
        assert _lock_version(draft.revision_id) == frozen_lock
        assert _stored_facet(node_id).quantity == Decimal("5.00")


# --------------------------------------------------------------------------------------
# Acceptance 5: the generated contract knows nothing of the devis grid any more
# --------------------------------------------------------------------------------------


def test_the_generated_contract_names_no_estimate_grid_schema() -> None:
    """The literal acceptance criterion of #333, on both generated artefacts.

    ``EstimateTaskRow``/``EstimateGridNode`` described the *structure* of a devis a
    second time; the revision node is now the only place a structure is described, so
    a schema named after either of them reappearing means a second tree came back.
    """
    for path in (OPENAPI_PATH, GENERATED_CLIENT_PATH):
        content = path.read_text(encoding="utf-8")
        assert "EstimateTaskRow" not in content, path
        assert "EstimateGridNode" not in content, path


# --------------------------------------------------------------------------------------
# The milestone guard is inherited from the domain, not restated here
# --------------------------------------------------------------------------------------


def test_a_cost_line_under_a_milestone_is_refused_by_the_domains_own_inv_27() -> None:
    """#333's third deliverable: one formulation of "a jalon holds no children".

    ``estimates.py`` still answers ``TASK_PARENT_IS_MILESTONE`` on the reconciliation
    import's own ``Tâches`` sheet; this path adds no second check of its own and the
    refusal therefore arrives as the domain's INV-27, under the code #343 published.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/cost-lines"),
            json={
                "expected_lock_version": 0,
                "nature": "labor",
                "label": "Sous un jalon",
                "parent_id": fixture.nodes["milestone"],
                "role_id": fixture.reference.role_id,
                "hours": "1.00",
            },
            headers=headers,
        )

    assert response.status_code == 400, response.text
    assert _detail(response)["code"] == "REVISION_MILESTONE_HAS_CHILDREN"


# --------------------------------------------------------------------------------------
# The shape contract (INV-19/INV-20) is the domain's too
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"nature": "labor", "label": "MO", "unit_cost": "10.00"}, "labor carrying a débours"),
        ({"nature": "labor", "label": "MO"}, "labor without role or hours"),
        ({"nature": "non_labor", "label": "Achat", "hours": "3.00"}, "non-labor carrying hours"),
    ],
)
def test_a_malformed_cost_shape_is_refused_as_a_facet_contract_not_a_422(
    payload: dict[str, Any], reason: str
) -> None:
    """400 and not 422: the shape rule is INV-19/INV-20, and it lives in the domain.

    Restating it as a ``model_validator`` would have answered 422 and put a second
    formulation of one rule on the wire -- the duplication EPIC #326 exists to remove.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/cost-lines"),
            json={"expected_lock_version": 0, **payload},
            headers=headers,
        )

    assert response.status_code == 400, (reason, response.text)
    assert _detail(response)["code"] == "REVISION_FACET_CONTRACT"


# --------------------------------------------------------------------------------------
# Editing the facet
# --------------------------------------------------------------------------------------


def test_editing_several_attributes_at_once_advances_the_lock_version_by_one() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])

        response = client.patch(
            fixture.url(f"/nodes/{node_id}/cost"),
            json={
                "expected_lock_version": created["lock_version"],
                "quantity": "9.00",
                "unit_cost": "12.50",
                "label": "  Cables revises  ",
                "supply_status": "ordered",
                "planned_date": "2027-03-01",
                "comment": "Devis fournisseur",
            },
            headers=headers,
        )

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    assert body["lock_version"] == cast(int, created["lock_version"]) + 1
    facet = _stored_facet(node_id)
    assert facet.quantity == Decimal("9.00")
    assert facet.unit_cost == Decimal("12.50")
    assert facet.label == "Cables revises"
    assert facet.supply_status == "ordered"
    assert facet.comment == "Devis fournisseur"


def test_an_omitted_field_is_left_alone_while_an_explicit_null_clears_it() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])
        dated = client.patch(
            fixture.url(f"/nodes/{node_id}/cost"),
            json={
                "expected_lock_version": created["lock_version"],
                "planned_date": "2027-03-01",
                "comment": "A revoir",
            },
            headers=headers,
        )
        assert dated.status_code == 200, dated.text

        cleared = client.patch(
            fixture.url(f"/nodes/{node_id}/cost"),
            json={
                "expected_lock_version": cast(dict[str, Any], dated.json())["lock_version"],
                "planned_date": None,
            },
            headers=headers,
        )

    assert cleared.status_code == 200, cleared.text
    facet = _stored_facet(node_id)
    assert facet.planned_date is None
    # ``comment`` was not supplied at all, so it kept the value the previous write set.
    assert facet.comment == "A revoir"


@pytest.mark.parametrize("field", ["label", "quantity"])
def test_an_explicit_null_on_a_field_with_no_cleared_state_is_a_422(field: str) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])

        response = client.patch(
            fixture.url(f"/nodes/{cast(int, created['node_id'])}/cost"),
            json={"expected_lock_version": created["lock_version"], field: None},
            headers=headers,
        )

    assert response.status_code == 422, response.text


def test_an_edit_breaking_the_shape_contract_leaves_the_facet_untouched() -> None:
    """Refused *before* the first assignment, so a rejected patch is not half applied."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])

        response = client.patch(
            fixture.url(f"/nodes/{node_id}/cost"),
            json={
                "expected_lock_version": created["lock_version"],
                "label": "Ne doit pas passer",
                "unit_cost": "10.00",
            },
            headers=headers,
        )

    assert response.status_code == 400, response.text
    assert _detail(response)["code"] == "REVISION_FACET_CONTRACT"
    facet = _stored_facet(node_id)
    assert facet.label == "Developpement"
    assert facet.unit_cost is None
    assert _lock_version(fixture.revision_id) == cast(int, created["lock_version"])


def test_changing_a_labor_lines_role_resynchronises_the_calendar_above_it() -> None:
    """Règle 1 carried to its end: a role decides the calendar of the tasks above it.

    ``assign_role`` already resynchronised from the node up; the composite edit has to
    do the same, or editing a role through this endpoint would leave the ancestors
    pointing at the previous role's calendar.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])

        with get_session_factory()() as session:
            other_calendar = Calendar(
                code=f"CAL-ALT-{uuid4().hex[:8]}",
                name="Alternatif",
                weeks_per_year=45,
                is_active=True,
            )
            session.add(other_calendar)
            session.flush()
            other_role = ResourceRole(
                node_id=(
                    session.query(ResourceRole)
                    .filter(ResourceRole.id == fixture.reference.role_id)
                    .one()
                    .node_id
                ),
                cost_category_id=fixture.reference.cost_category_id,
                calendar_id=other_calendar.id,
                name="Chef de projet",
            )
            session.add(other_role)
            session.commit()
            other_role_id = other_role.id
            other_calendar_id = other_calendar.id

        response = client.patch(
            fixture.url(f"/nodes/{node_id}/cost"),
            json={"expected_lock_version": created["lock_version"], "role_id": other_role_id},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert _stored_facet(node_id).role_id == other_role_id
    with get_session_factory()() as session:
        alpha = (
            session.query(RevisionPlanFacet)
            .filter(RevisionPlanFacet.node_id == fixture.nodes["alpha"])
            .one()
        )
        assert alpha.calendar_id == other_calendar_id
        assert alpha.calendar_source == "role"


def test_a_stale_expected_lock_version_is_refused_on_both_cost_writes() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])

        stale_create = client.post(
            fixture.url("/cost-lines"),
            json={
                "expected_lock_version": 0,
                "nature": "labor",
                "label": "Trop tard",
                "role_id": fixture.reference.role_id,
                "hours": "1.00",
            },
            headers=headers,
        )
        assert stale_create.status_code == 409, stale_create.text
        assert _detail(stale_create)["code"] == "REVISION_LOCK_CONFLICT"

        stale_patch = client.patch(
            fixture.url(f"/nodes/{node_id}/cost"),
            json={"expected_lock_version": 0, "quantity": "3.00"},
            headers=headers,
        )
        assert stale_patch.status_code == 409, stale_patch.text
        assert _detail(stale_patch)["code"] == "REVISION_LOCK_CONFLICT"


def test_editing_the_cost_facet_of_a_task_node_is_a_node_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.patch(
            fixture.url(f"/nodes/{fixture.nodes['alpha']}/cost"),
            json={"expected_lock_version": 0, "quantity": "2.00"},
            headers=headers,
        )

    assert response.status_code == 404, response.text
    assert _detail(response)["code"] == "REVISION_NODE_NOT_FOUND"


@pytest.mark.parametrize("route", ["create", "patch"])
@pytest.mark.parametrize(
    "payload",
    [
        {"quantity": "1234567890123.00"},
        {"unit_cost": "123456789012345.00"},
        {"hours": "1234567890123.00"},
    ],
)
def test_a_numeric_value_wider_than_its_column_is_a_422_not_a_500(
    payload: dict[str, Any],
    route: str,
) -> None:
    """The bound is the guard, and it is only visible here.

    PostgreSQL answers ``DataError`` -- not an ``IntegrityError``, so not a 409 -- on a
    value with more integer digits than ``Numeric(14, 2)``/``Numeric(16, 2)`` holds,
    and SQLite stores it happily. The payload bound is what keeps that from being a 500
    on production, so it is asserted rather than left to the backend under test.

    Both routes, because both payloads declare the bound: ``RevisionCostLineCreate``
    and ``RevisionCostFacetUpdate`` are two classes restating the same four
    ``Field(max_digits=...)``, and it is the *creation* path that runs all the way to
    an ``INSERT``. Testing only the patch would leave the ``INSERT`` -- the one that
    would actually surface a ``DataError`` as a 500 -- unguarded by any test.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        if route == "create":
            labor = "hours" in payload
            base: dict[str, Any] = {
                "expected_lock_version": 0,
                "label": "Trop large",
                "parent_id": fixture.nodes["alpha"],
            }
            base.update(
                {"nature": "labor", "role_id": fixture.reference.role_id, "hours": "1.00"}
                if labor
                else {
                    "nature": "non_labor",
                    "cost_type_id": fixture.reference.cost_type_id,
                    "cost_category_id": fixture.reference.cost_category_id,
                    "unit_cost": "25.00",
                }
            )
            response = client.post(
                fixture.url("/cost-lines"), json={**base, **payload}, headers=headers
            )
        else:
            created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
            response = client.patch(
                fixture.url(f"/nodes/{cast(int, created['node_id'])}/cost"),
                json={"expected_lock_version": created["lock_version"], **payload},
                headers=headers,
            )

    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------------------
# Deleting: `POST .../nodes/delete` already does it, so nothing was added
# --------------------------------------------------------------------------------------


def test_deleting_the_node_removes_the_cost_facet_and_names_the_chiffrage_it_took() -> None:
    """Why #333 added no ``DELETE .../cost-lines/{id}``.

    ``POST .../nodes/delete`` of #331 removes the node, its subtree and *both* facets
    (INV-02), and reports the chiffrage it took away (Règle 3). A cost-specific delete
    would have been that same operation under a second name, on the same table, with a
    second chance to diverge.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])

        response = client.post(
            fixture.url("/nodes/delete"),
            json={"expected_lock_version": created["lock_version"], "node_ids": [node_id]},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    assert body["removed_node_ids"] == [node_id]
    losses = cast(list[dict[str, Any]], body["cost_losses"])
    assert len(losses) == 1
    assert losses[0]["label"] == "Cables"
    assert losses[0]["nature"] == "non_labor"
    assert Decimal(cast(str, losses[0]["amount"])) == Decimal("125.00")
    assert losses[0]["bearing_task_name"] == "Alpha"
    with get_session_factory()() as session:
        assert (
            session.query(RevisionCostFacet).filter(RevisionCostFacet.node_id == node_id).first()
            is None
        )
