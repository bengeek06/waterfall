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

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from _revision_db_support import ReferenceData, insert_revision, insert_task, seed_annual_rate
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.resources import Calendar, CostCategory, CostType, ResourceNode, ResourceRole
from waterfall.models.revision import ProjectRevision, RevisionCostFacet, RevisionPlanFacet
from waterfall.services.estimate_calculation import UNASSIGNED_COST_CODE_LABEL, price_revision

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


def _accounting_code(fixture: Fixture) -> str:
    """The accounting code the aggregates key ``by_category`` on, read off the referential."""
    with get_session_factory()() as session:
        category = session.get(CostCategory, fixture.reference.cost_category_id)
        assert category is not None
        return category.accounting_code


def _date_task(node_id: int, *, year: int) -> None:
    """Give a seeded task a span inside one year, in the tables.

    A labour facet's hours are spread over the years of its **bearing task**, so a
    task with no dates prices nothing at all -- the legacy engine's behaviour, kept.
    Going through ``PATCH .../planning`` here would make a cost test depend on the
    planning facet's write path, exactly as ``_mark_milestone`` already avoids.
    """
    _span_task(
        node_id,
        start_at=datetime(year, 3, 2, tzinfo=UTC),
        finish_at=datetime(year, 6, 30, tzinfo=UTC),
    )


def _span_task(node_id: int, *, start_at: datetime, finish_at: datetime) -> None:
    """:func:`_date_task` for a span this API would not produce, in the tables.

    ``finish_at`` before ``start_at`` is one of them, and it is the point: nothing
    forbids that state -- no ``CheckConstraint`` on ``wf_revision_plan_facet``, no
    cross-field validator on the planning payloads, nothing in the MSPDI parser --
    so the engine, which is a read, has to answer on it.
    """
    with get_session_factory()() as session:
        facet = session.query(RevisionPlanFacet).filter(RevisionPlanFacet.node_id == node_id).one()
        facet.start_at = start_at
        facet.finish_at = finish_at
        session.commit()


def _seed_rate(
    fixture: Fixture, *, year: int, hourly_rate: Decimal, inflation: Decimal = Decimal("1.00000000")
) -> None:
    """The ``(category, year)`` hourly rate and the year's inflation coefficient.

    What turns an MO line from "priced at 0 because nothing covers it" into a real
    figure: a rate is annual and per cost category, which is exactly why
    ``Role.hourly_rate`` is never loaded and the engine is injected as the domain's
    ``AmountResolver`` instead.
    """
    with get_session_factory()() as session:
        seed_annual_rate(
            session, fixture.reference, year=year, hourly_rate=hourly_rate, inflation=inflation
        )
        session.commit()


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
    quantity: str = "5.00",
    unit_cost: str = "25.00",
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
        "quantity": quantity,
        "cost_type_id": fixture.reference.cost_type_id,
        "cost_category_id": fixture.reference.cost_category_id,
        "unit_cost": unit_cost,
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

    Both natures are deleted in the same call, and for one reason: the amount Règle 3
    quotes comes from the **calculation engine**, injected as the domain's
    ``AmountResolver`` (E14-07b, #364), and only an MO line proves it. Left to
    ``pricing.default_amount``, a non-MO line would still be reported at ``125.00``
    -- its two operands sit on the facet -- while the MO line would be announced as
    costing ``0``, because ``Role.hourly_rate`` is deliberately never loaded. That is
    the same figure, from the same resolver, that ``POST /imports/v1/batches/{id}/run``
    quotes for the same rule (``tests/test_revision_import.py``): two routes, one
    answer.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        created = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        node_id = cast(int, created["node_id"])
        _date_task(fixture.nodes["beta"], year=2030)
        _seed_rate(
            fixture, year=2030, hourly_rate=Decimal("100.00"), inflation=Decimal("1.05000000")
        )
        labor = _create_labor(
            client,
            headers,
            fixture,
            parent_id=fixture.nodes["beta"],
            lock_version=cast(int, created["lock_version"]),
            hours="12.00",
        )
        labor_node_id = cast(int, labor["node_id"])

        response = client.post(
            fixture.url("/nodes/delete"),
            json={
                "expected_lock_version": labor["lock_version"],
                "node_ids": [node_id, labor_node_id],
            },
            headers=headers,
        )

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    assert sorted(cast(list[int], body["removed_node_ids"])) == sorted([node_id, labor_node_id])
    losses = cast(list[dict[str, Any]], body["cost_losses"])
    assert {
        cast(str, loss["label"]): (
            loss["nature"],
            Decimal(cast(str, loss["amount"])),
            loss["bearing_task_name"],
        )
        for loss in losses
    } == {
        "Cables": ("non_labor", Decimal("125.00"), "Alpha"),
        # 1 x 12 h spread over Beta's single year, at 100.00/h and 1.05 of inflation.
        "Developpement": ("labor", Decimal("1260.00"), "Beta"),
    }
    with get_session_factory()() as session:
        assert (
            session.query(RevisionCostFacet)
            .filter(RevisionCostFacet.node_id.in_([node_id, labor_node_id]))
            .first()
            is None
        )


# --------------------------------------------------------------------------------------
# The totals of the revision (E14-07b, #364)
# --------------------------------------------------------------------------------------


def test_the_aggregates_endpoint_totals_the_cost_facets_of_a_draft() -> None:
    """``GET .../revisions/{id}/aggregates``, and the reason it replaces the devis one.

    ``GET .../estimates/{id}/aggregates`` summed the `wf_estimate_line` rows a
    validation had written, so a **draft** reported nothing at all. Here both lines
    are created through the cost-facet route on a draft, and the totals answer.

    The second line sits at the **root**, with no bearing task -- INV-01's
    project-wide global cost -- and counts like the first: nothing in the aggregate
    filters on a bearing task.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        under_alpha = _create_non_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        _create_non_labor(
            client,
            headers,
            fixture,
            parent_id=None,
            lock_version=cast(int, under_alpha["lock_version"]),
            label="Frais transverses",
        )

        response = client.get(fixture.url("/aggregates"), headers=headers)

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    assert body["revision_id"] == fixture.revision_id
    # 5.00 x 25.00, twice.
    assert Decimal(cast(str, body["total_purchase_cost"])) == Decimal("250.00")
    assert Decimal(cast(str, body["total_labor_cost"])) == Decimal("0")
    assert Decimal(cast(str, body["total_unburdened_cost"])) == Decimal("250.00")
    by_category = cast(dict[str, str], body["by_category"])
    assert {code: Decimal(amount) for code, amount in by_category.items()} == {
        _accounting_code(fixture): Decimal("250.00")
    }
    # Neither line carries a cost code, so both fall under the shared placeholder the
    # Excel export uses as well.
    by_cost_code = cast(dict[str, str], body["by_cost_code"])
    assert {label: Decimal(amount) for label, amount in by_cost_code.items()} == {
        UNASSIGNED_COST_CODE_LABEL: Decimal("250.00")
    }
    assert body["missing_cost_rates"] == []
    assert body["missing_inflation_years"] == []


def test_the_aggregates_endpoint_names_a_missing_rate_instead_of_failing() -> None:
    """A read has to answer, even when the rate table does not cover the year.

    The legacy engine refuses the whole **validation** with a 400
    ``MISSING_RATE_COVERAGE``, which is right for a validation. Reading the totals of
    a draft is not a validation: the MO line is priced at a zero rate and the gap is
    named in the same 200, so nothing about it is silent. Turning it back into a
    refusal at validation time is E14-08's (#334).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _date_task(fixture.nodes["alpha"], year=2031)
        response = client.post(
            fixture.url("/cost-lines"),
            json={
                "expected_lock_version": 0,
                "nature": "labor",
                "label": "Etude",
                "parent_id": fixture.nodes["alpha"],
                "quantity": "1.00",
                "role_id": fixture.reference.role_id,
                "hours": "10.00",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text

        aggregates = client.get(fixture.url("/aggregates"), headers=headers)

    assert aggregates.status_code == 200, aggregates.text
    body = cast(dict[str, Any], aggregates.json())
    assert Decimal(cast(str, body["total_labor_cost"])) == Decimal("0")
    assert body["missing_cost_rates"] == [
        {
            "category_id": fixture.reference.cost_category_id,
            "category_name": "Fournitures",
            "accounting_code": _accounting_code(fixture),
            "year": 2031,
        }
    ]
    assert body["missing_inflation_years"] == [2031]


def test_a_bearing_task_whose_dates_are_inverted_prices_nothing_instead_of_failing() -> None:
    """The engine is a **read**: it refuses no stored state, however odd.

    ``finish_at`` before ``start_at`` is a state nothing forbids today -- no
    ``CheckConstraint`` on ``wf_revision_plan_facet``, no cross-field validator on
    ``RevisionTaskCreate``/``RevisionPlanFacetUpdate``, no domain invariant, nothing
    in the MSPDI parser. The years a labour facet spreads its hours over are then an
    **empty** range, and dividing the hours by it raises ``decimal.DivisionByZero``
    -- which is in neither ``revision_errors``' table nor ``RevisionFailure``, so it
    would surface as a 500 with no rollback, here and on every caller that prices
    unconditionally (the import diff of #336 included).

    So an empty range is treated as "no dates at all": the facet prices nothing, as a
    dateless bearing task's already did. Forbidding the state on the **write** side is
    a different question, and not this endpoint's.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _span_task(
            fixture.nodes["alpha"],
            start_at=datetime(2031, 1, 1, tzinfo=UTC),
            finish_at=datetime(2030, 12, 31, tzinfo=UTC),
        )
        created = _create_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"])
        response = client.get(fixture.url("/aggregates"), headers=headers)

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    assert Decimal(cast(str, body["total_labor_cost"])) == Decimal("0")
    assert body["by_category"] == {}
    # Not a gap in the rate table either: the line covers no year, so there is no
    # (category, year) combination for the rate table to be missing.
    assert body["missing_cost_rates"] == []
    assert body["missing_inflation_years"] == []
    with get_session_factory()() as session:
        pricing = price_revision(session, fixture.revision_id)
    assert [line for line in pricing.lines if line.node_id == created["node_id"]] == []


def test_the_aggregates_endpoint_publishes_every_amount_at_the_cent() -> None:
    """A euro figure is published at the cent, and the rounding happens per line.

    ``GET .../estimates/{id}/aggregates`` answered two decimals because every amount
    it summed had been through a ``Numeric(16, 2)`` column -- one line at a time,
    *before* anything was added up. ``calculate_revision_aggregates`` restates that
    rule where the column stood: each priced line at the cent, then the sum. Ten
    hours spread over three years at a flat rate are three lines of ``333.33...``,
    so the published total is ``999.99`` -- the very figure the endpoint this
    replaces answered on the same figures, which is #364's criterion.

    Summing the products at full precision and rounding the total instead would
    publish ``1000.00`` here, and would stop the five figures adding up at all: see
    ``test_the_published_totals_add_up_when_an_hourly_rate_has_four_decimals``.

    The engine underneath rounds nothing, and that is asserted too: it is also the
    resolver the pure domain calls, and a rounding rule invented there would be a
    rule the domain does not have.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _span_task(
            fixture.nodes["alpha"],
            start_at=datetime(2030, 10, 1, tzinfo=UTC),
            finish_at=datetime(2032, 2, 28, tzinfo=UTC),
        )
        for year in (2030, 2031, 2032):
            _seed_rate(fixture, year=year, hourly_rate=Decimal("100.00"))
        _create_labor(client, headers, fixture, parent_id=fixture.nodes["alpha"], hours="10.00")
        response = client.get(fixture.url("/aggregates"), headers=headers)

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    assert body["total_labor_cost"] == "999.99"
    assert body["total_unburdened_cost"] == "999.99"
    assert body["by_category"] == {_accounting_code(fixture): "999.99"}
    assert body["by_cost_code"] == {UNASSIGNED_COST_CODE_LABEL: "999.99"}
    # And the engine itself keeps every digit: rounding the sum of these products
    # would have published a cent more, which is the rule that was not retained.
    with get_session_factory()() as session:
        pricing = price_revision(session, fixture.revision_id)
    assert sum((line.amount for line in pricing.lines), Decimal("0")) == Decimal(
        "999.9999999999999999999999999"
    )


def test_the_published_totals_add_up_when_an_hourly_rate_has_four_decimals() -> None:
    """The five published figures are five partitions of the same lines, and they add up.

    ``CostRate.hourly_rate`` is a ``Numeric(14, 4)`` precisely so that a rate can
    carry four decimals, and a débours carries two operands whose product need not
    fit two either. One line of each is enough: ``1 x 1.00 h x 100.0040 EUR/h`` is
    ``100.0040`` and ``0.02 x 0.20 EUR`` is ``0.0040``. Rounding each of the five
    totals on its own would publish ``MO 100.00`` and ``Achats 0.00`` under a
    ``Total 100.01`` -- three figures ``analytics-tab.tsx`` puts side by side, one of
    them visibly not the sum of the other two.

    Rounding each *line* to the cent first makes that impossible by construction: a
    sum of amounts already at the cent is additive over any partition of the lines.
    So the three totals agree, and so does either breakdown.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _date_task(fixture.nodes["alpha"], year=2030)
        _seed_rate(fixture, year=2030, hourly_rate=Decimal("100.0040"))
        created = _create_labor(
            client, headers, fixture, parent_id=fixture.nodes["alpha"], hours="1.00"
        )
        _create_non_labor(
            client,
            headers,
            fixture,
            parent_id=fixture.nodes["alpha"],
            lock_version=cast(int, created["lock_version"]),
            label="Visserie",
            quantity="0.02",
            unit_cost="0.20",
        )
        response = client.get(fixture.url("/aggregates"), headers=headers)

    assert response.status_code == 200, response.text
    body = cast(dict[str, Any], response.json())
    labor = Decimal(cast(str, body["total_labor_cost"]))
    purchase = Decimal(cast(str, body["total_purchase_cost"]))
    unburdened = Decimal(cast(str, body["total_unburdened_cost"]))
    by_category = {
        code: Decimal(amount) for code, amount in cast(dict[str, str], body["by_category"]).items()
    }
    by_cost_code = {
        label: Decimal(amount)
        for label, amount in cast(dict[str, str], body["by_cost_code"]).items()
    }

    assert labor == Decimal("100.00")
    assert purchase == Decimal("0.00")
    assert unburdened == Decimal("100.00")
    assert labor + purchase == unburdened
    assert sum(by_category.values(), Decimal("0")) == unburdened
    assert sum(by_cost_code.values(), Decimal("0")) == unburdened


def test_the_aggregates_of_somebody_elses_project_are_not_found() -> None:
    """Same ownership guard as every other revision read, on the newest endpoint."""
    with TestClient(app) as client:
        owner_headers = _auth_headers(client)
        fixture = _seed(client, owner_headers)
        intruder_headers = _auth_headers(client)

        response = client.get(fixture.url("/aggregates"), headers=intruder_headers)
        unknown = client.get(
            f"/projects/{fixture.project_id}/revisions/{fixture.revision_id + 10_000}/aggregates",
            headers=owner_headers,
        )

    assert response.status_code == 404
    assert _detail(response) == {"code": "PROJECT_NOT_FOUND"}
    assert unknown.status_code == 404
    assert _detail(unknown) == {"code": "REVISION_NOT_FOUND"}
