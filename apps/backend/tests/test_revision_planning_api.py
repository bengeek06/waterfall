"""The planning facet of a revision, over HTTP (E14-05, issue #331).

Every acceptance criterion of the issue is pinned here, plus the error table the
issue makes the point of the work: one code per refusal, and the *same* code for
INV-03 whichever class the refusal came out of -- which is what makes E14-07
(#333) able to reuse :mod:`waterfall.api.revision_errors` rather than restate it.

The fixture builds its project through the API (so it has an owner the routes can
check) and its revision straight into the tables (so the tree under test owes
nothing to the endpoints being tested).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from _revision_db_support import ReferenceData, insert_revision, insert_task
from waterfall.api import revision_errors
from waterfall.api.revision_errors import (
    _TRANSLATIONS,  # pyright: ignore[reportPrivateUsage]
    REVISION_IMMUTABLE,
    revision_http_exception,
    revision_operation,
)
from waterfall.db.session import get_session_factory
from waterfall.domain import revision as domain
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    Calendar,
    CostCategory,
    CostType,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.models.revision import ProjectRevision, RevisionNode, RevisionPlanFacet
from waterfall.services import revision_tree
from waterfall.services.calendar_schedule import resolve_task_calendar_ids
from waterfall.services.revision_store import FrozenRevisionError, RevisionStoreError

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "openapi" / "waterfall_v1.yaml"


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"revision.api.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "Revision API"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _seed_referential(session: Session, project_id: int, *, key: str) -> ReferenceData:
    """A default calendar, a cost type/category and a role, hung off an existing project.

    ``_revision_db_support.seed_reference_data`` creates its own project; these
    routes need one the API created, so that it carries an ``owner_id`` the
    ownership check can match.
    """
    calendar = Calendar(
        code=f"CAL-{key}", name="Standard", weeks_per_year=47, is_active=True, is_default=True
    )
    session.add(calendar)
    cost_type = CostType(code=f"MO-{key}", name="Main d'oeuvre", kind="labor")
    session.add(cost_type)
    session.flush()
    category = CostCategory(
        cost_type_id=cost_type.id, accounting_code=f"DEV-{key}", name="Developpement"
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
    """A project, a draft revision and the tree ``Alpha > {Design > Sub, Build}``, ``Beta``."""

    def __init__(
        self,
        project_id: int,
        reference: ReferenceData,
        revision_id: int,
        nodes: dict[str, int],
    ) -> None:
        self.project_id = project_id
        self.reference = reference
        self.revision_id = revision_id
        self.nodes = nodes

    def url(self, suffix: str = "") -> str:
        return f"/projects/{self.project_id}/revisions/{self.revision_id}{suffix}"


def _seed(client: TestClient, headers: dict[str, str], *, status: str = "draft") -> Fixture:
    project_id = _create_project(client, headers)
    with get_session_factory()() as session:
        reference = _seed_referential(session, project_id, key=uuid4().hex[:8])
        revision = insert_revision(session, reference, status=status)
        alpha = insert_task(session, reference, revision, name="Alpha", position=1)
        design = insert_task(
            session, reference, revision, name="Design", parent_id=alpha.id, position=1
        )
        sub = insert_task(session, reference, revision, name="Sub", parent_id=design.id, position=1)
        build = insert_task(
            session, reference, revision, name="Build", parent_id=alpha.id, position=2
        )
        beta = insert_task(session, reference, revision, name="Beta", position=2)
        session.commit()
        return Fixture(
            project_id,
            reference,
            revision.id,
            {
                "alpha": alpha.id,
                "design": design.id,
                "sub": sub.id,
                "build": build.id,
                "beta": beta.id,
            },
        )


def _lock_version(revision_id: int) -> int:
    with get_session_factory()() as session:
        revision = session.get(ProjectRevision, revision_id)
        assert revision is not None
        return revision.lock_version


def _facet(node_id: int) -> RevisionPlanFacet:
    with get_session_factory()() as session:
        facet = session.query(RevisionPlanFacet).filter(RevisionPlanFacet.node_id == node_id).one()
        session.expunge(facet)
        return facet


def _detail(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], response.json())["detail"]


# --------------------------------------------------------------------------------------
# Reading the tree (acceptance criterion 1)
# --------------------------------------------------------------------------------------


def test_reading_a_revision_lists_its_nodes_depth_first_with_row_number_level_and_facet() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.get(fixture.url("/nodes"), headers=headers)

    assert response.status_code == 200
    body = cast(dict[str, Any], response.json())
    assert body["revision_id"] == fixture.revision_id
    assert body["project_id"] == fixture.project_id
    assert body["status"] == "draft"
    assert body["lock_version"] == 0

    nodes = cast(list[dict[str, Any]], body["nodes"])
    assert [node["planning"]["name"] for node in nodes] == [
        "Alpha",
        "Design",
        "Sub",
        "Build",
        "Beta",
    ]
    # row_number is the rank in that very walk, level the depth (roots at 1). Both
    # are computed on read: no column carries either.
    assert [node["row_number"] for node in nodes] == [1, 2, 3, 4, 5]
    assert [node["level"] for node in nodes] == [1, 2, 3, 2, 1]
    assert [node["node_id"] for node in nodes] == [
        fixture.nodes["alpha"],
        fixture.nodes["design"],
        fixture.nodes["sub"],
        fixture.nodes["build"],
        fixture.nodes["beta"],
    ]
    assert all(node["kind"] == "task" for node in nodes)
    assert all(node["cost"] is None for node in nodes)
    assert nodes[0]["planning"]["calendar_id"] == fixture.reference.calendar_id
    assert nodes[0]["planning"]["calendar_source"] == "project"


def test_row_number_follows_a_move_rather_than_being_stored() -> None:
    """The E9 principle, made structural: nothing is renumbered in base, ever."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        moved = client.post(
            fixture.url("/nodes/move"),
            json={
                "node_ids": [fixture.nodes["beta"]],
                "mode": "to_parent",
                "target_parent_id": None,
                "position": 1,
                "expected_lock_version": 0,
            },
            headers=headers,
        )
        assert moved.status_code == 200
        response = client.get(fixture.url("/nodes"), headers=headers)

    nodes = cast(list[dict[str, Any]], cast(dict[str, Any], response.json())["nodes"])
    assert [(node["planning"]["name"], node["row_number"]) for node in nodes] == [
        ("Beta", 1),
        ("Alpha", 2),
        ("Design", 3),
        ("Sub", 4),
        ("Build", 5),
    ]


def test_the_tree_read_is_never_truncated_by_a_stray_limit_or_offset() -> None:
    """EPIC E7 (#115), carried over: a truncated tree is orphaned parents and wrong
    row numbers, so a caller's stray pagination must be ignored rather than obeyed.

    Moved here from
    ``test_projects_api.test_project_pagination_reports_total_and_task_listing_is_never_truncated``
    with the endpoint it guarded.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.get(fixture.url("/nodes?limit=1&offset=1"), headers=headers)

    assert response.status_code == 200
    assert len(cast(list[dict[str, Any]], cast(dict[str, Any], response.json())["nodes"])) == 5


def test_reading_a_revision_of_another_project_is_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        other_project_id = _create_project(client, headers)

        response = client.get(
            f"/projects/{other_project_id}/revisions/{fixture.revision_id}/nodes", headers=headers
        )

    assert response.status_code == 404
    assert _detail(response) == {"code": "REVISION_NOT_FOUND"}


# --------------------------------------------------------------------------------------
# The optimistic lock (acceptance criterion 2)
# --------------------------------------------------------------------------------------


def test_editing_a_duration_with_a_stale_lock_version_conflicts_and_changes_nothing() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]

        first = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={"duration_minutes": 480, "expected_lock_version": 0},
            headers=headers,
        )
        assert first.status_code == 200
        assert first.json() == {"revision_id": fixture.revision_id, "lock_version": 1}

        stale = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={"duration_minutes": 960, "expected_lock_version": 0},
            headers=headers,
        )

    assert stale.status_code == 409
    assert _detail(stale) == {
        "code": "REVISION_LOCK_CONFLICT",
        "revision_id": fixture.revision_id,
        "expected_lock_version": 0,
        "current_lock_version": 1,
    }
    # Nothing was written by the refused call: the duration is still the first one,
    # and the counter did not move a second time.
    assert _facet(design).duration_minutes == 480
    assert _lock_version(fixture.revision_id) == 1


def test_one_request_advances_the_lock_version_by_exactly_one_whatever_it_edits() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]

        response = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={
                "name": "Design revu",
                "duration_minutes": 240,
                "percent_complete": 25,
                "start_at": "2026-03-02T08:00:00Z",
                "finish_at": "2026-03-03T17:00:00Z",
                "is_milestone": False,
                "expected_lock_version": 0,
            },
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["lock_version"] == 1
    facet = _facet(design)
    assert facet.name == "Design revu"
    assert facet.duration_minutes == 240
    assert facet.percent_complete == 25
    assert facet.start_at is not None and facet.finish_at is not None


def test_an_absent_field_is_left_alone_and_an_explicit_null_clears_it() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]

        assert (
            client.patch(
                fixture.url(f"/nodes/{design}/planning"),
                json={"duration_minutes": 480, "percent_complete": 40, "expected_lock_version": 0},
                headers=headers,
            ).status_code
            == 200
        )
        # percent_complete is not mentioned: it must survive untouched.
        assert (
            client.patch(
                fixture.url(f"/nodes/{design}/planning"),
                json={"duration_minutes": None, "expected_lock_version": 1},
                headers=headers,
            ).status_code
            == 200
        )

    facet = _facet(design)
    assert facet.duration_minutes is None
    assert facet.percent_complete == 40


def test_pinning_and_unpinning_a_calendar_follows_regle_1() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]
        with get_session_factory()() as session:
            other = Calendar(
                code=f"ALT-{uuid4().hex[:8]}",
                name="Alternatif",
                weeks_per_year=47,
                is_active=True,
                is_default=False,
            )
            session.add(other)
            session.commit()
            other_calendar_id = other.id

        pinned = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={"calendar_id": other_calendar_id, "expected_lock_version": 0},
            headers=headers,
        )
        assert pinned.status_code == 200
        assert _facet(design).calendar_id == other_calendar_id
        assert _facet(design).calendar_source == "manual"

        cleared = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={"calendar_id": None, "expected_lock_version": 1},
            headers=headers,
        )

    assert cleared.status_code == 200
    facet = _facet(design)
    assert facet.calendar_id == fixture.reference.calendar_id
    assert facet.calendar_source == "project"


# --------------------------------------------------------------------------------------
# Predecessors (acceptance criterion 3)
# --------------------------------------------------------------------------------------


def test_replacing_the_predecessors_of_a_node_installs_exactly_the_given_list() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        build, sub, beta = (
            fixture.nodes["build"],
            fixture.nodes["sub"],
            fixture.nodes["beta"],
        )

        first = client.put(
            fixture.url(f"/nodes/{build}/predecessors"),
            json={
                "predecessors": [
                    {"predecessor_node_id": sub, "link_type": 1, "lag_tenth_minute": 600},
                    {"predecessor_node_id": beta, "link_type": 0},
                ],
                "expected_lock_version": 0,
            },
            headers=headers,
        )
        assert first.status_code == 200

        replaced = client.put(
            fixture.url(f"/nodes/{build}/predecessors"),
            json={
                "predecessors": [{"predecessor_node_id": beta, "link_type": 0}],
                "expected_lock_version": 1,
            },
            headers=headers,
        )
        assert replaced.status_code == 200

        cleared_read = client.get(fixture.url("/nodes"), headers=headers)

    nodes = {
        node["node_id"]: node
        for node in cast(list[dict[str, Any]], cast(dict[str, Any], cleared_read.json())["nodes"])
    }
    assert nodes[build]["predecessors"] == [
        {
            "predecessor_node_id": beta,
            "link_type": 0,
            "lag_tenth_minute": 0,
            "lag_format": None,
        }
    ]


def test_a_lag_format_the_mspdi_schema_allows_survives_a_read_modify_write() -> None:
    """#331 review, M1: 53 is legal MSPDI and used to be a 422 on the way back in.

    ``LagFormat`` 53 ("null", no unit displayed) is in the ``xsd:enumeration`` of the
    bundled schema but missing from the ``xsd:documentation`` beside it, and the
    enumeration this payload inherited had been derived from the prose. An MSPDI
    import carrying it (#332) would therefore have produced a link that ``GET
    .../nodes`` returns -- ``RevisionPredecessorRead.lag_format`` is an unbounded
    ``int | None``, rightly -- and that ``PUT .../predecessors`` refuses to take back,
    so any later edit of the node's predecessors would have had to drop the format
    silently. The read-modify-write cycle below is exactly that scenario.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        build, beta = fixture.nodes["build"], fixture.nodes["beta"]

        installed = client.put(
            fixture.url(f"/nodes/{build}/predecessors"),
            json={
                "predecessors": [{"predecessor_node_id": beta, "link_type": 1, "lag_format": 53}],
                "expected_lock_version": 0,
            },
            headers=headers,
        )
        assert installed.status_code == 200, installed.text

        read_back = client.get(fixture.url("/nodes"), headers=headers)
        nodes = {
            node["node_id"]: node
            for node in cast(list[dict[str, Any]], cast(dict[str, Any], read_back.json())["nodes"])
        }
        predecessors = cast(list[dict[str, Any]], nodes[build]["predecessors"])
        assert predecessors[0]["lag_format"] == 53

        # The list, unchanged, sent straight back: what a client editing anything else
        # on this node does, and what used to be a 422.
        replayed = client.put(
            fixture.url(f"/nodes/{build}/predecessors"),
            json={"predecessors": predecessors, "expected_lock_version": 1},
            headers=headers,
        )

    assert replayed.status_code == 200, replayed.text


def test_adding_a_predecessor_from_another_revision_is_refused() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        with get_session_factory()() as session:
            other_revision = insert_revision(session, fixture.reference, version_number=2)
            foreign = insert_task(
                session, fixture.reference, other_revision, name="Etranger", position=1
            )
            session.commit()
            foreign_node_id = foreign.id

        response = client.put(
            fixture.url(f"/nodes/{fixture.nodes['build']}/predecessors"),
            json={
                "predecessors": [{"predecessor_node_id": foreign_node_id, "link_type": 1}],
                "expected_lock_version": 0,
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert _detail(response) == {"code": "REVISION_CROSS_REVISION"}
    # A refused write leaves the counter exactly where it was.
    assert _lock_version(fixture.revision_id) == 0


def test_a_predecessor_cycle_is_refused() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        build, beta = fixture.nodes["build"], fixture.nodes["beta"]

        assert (
            client.put(
                fixture.url(f"/nodes/{build}/predecessors"),
                json={
                    "predecessors": [{"predecessor_node_id": beta, "link_type": 1}],
                    "expected_lock_version": 0,
                },
                headers=headers,
            ).status_code
            == 200
        )
        response = client.put(
            fixture.url(f"/nodes/{beta}/predecessors"),
            json={
                "predecessors": [{"predecessor_node_id": build, "link_type": 1}],
                "expected_lock_version": 1,
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert _detail(response) == {"code": "REVISION_LINK_INVALID"}


# --------------------------------------------------------------------------------------
# Immutability of a validated revision (acceptance criterion 4)
# --------------------------------------------------------------------------------------


def _writes(fixture: Fixture) -> list[tuple[str, str, dict[str, Any]]]:
    """Every write this API exposes, with a payload that would otherwise succeed."""
    design = fixture.nodes["design"]
    return [
        ("post", fixture.url("/tasks"), {"name": "Nouvelle", "expected_lock_version": 0}),
        (
            "post",
            fixture.url("/nodes/move"),
            {
                "node_ids": [fixture.nodes["beta"]],
                "mode": "to_parent",
                "position": 1,
                "expected_lock_version": 0,
            },
        ),
        (
            "post",
            fixture.url("/nodes/delete"),
            {"node_ids": [fixture.nodes["beta"]], "expected_lock_version": 0},
        ),
        (
            "patch",
            fixture.url(f"/nodes/{design}/planning"),
            {"duration_minutes": 60, "expected_lock_version": 0},
        ),
        (
            "put",
            fixture.url(f"/nodes/{design}/predecessors"),
            {"predecessors": [], "expected_lock_version": 0},
        ),
    ]


@pytest.mark.parametrize("status", ["validated", "superseded"])
def test_every_write_on_a_frozen_revision_is_refused_with_the_same_error(status: str) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers, status=status)

        responses = [
            (url, getattr(client, method)(url, json=payload, headers=headers))
            for method, url, payload in _writes(fixture)
        ]

    assert len(responses) == 5
    for url, response in responses:
        assert response.status_code == 409, url
        assert _detail(response) == {"code": "REVISION_IMMUTABLE"}, url
    assert _lock_version(fixture.revision_id) == 0


def test_inv_03_carries_one_code_whichever_class_the_refusal_came_out_of() -> None:
    """The hazard the review of #330 named, closed in one place.

    INV-03 reaches a route as a domain ``ImmutableRevisionError`` (the guard of
    ``revision_tree`` and the domain's own ``require_draft``) *or* as the store's
    ``FrozenRevisionError``. Both have to answer the same thing -- that is the
    acceptance criterion #333 inherits -- and the sibling ``RevisionStoreError``
    refusals that have nothing to do with INV-03 must **not** borrow that code.
    """
    domain_side = revision_http_exception(domain.ImmutableRevisionError("frozen"))
    store_side = revision_http_exception(FrozenRevisionError("frozen in the database"))

    assert domain_side.status_code == store_side.status_code == 409
    assert domain_side.detail == store_side.detail == {"code": REVISION_IMMUTABLE}


def test_a_bare_store_error_is_an_incident_rather_than_a_conflict() -> None:
    """#331 review, M5: ``REVISION_STATE_CONFLICT`` is gone, and deliberately.

    The seven sites raising a bare ``RevisionStoreError`` describe a stored state a
    client can neither provoke nor repair (an unreachable node, an orphaned facet, a
    link whose endpoint is gone). A 409 would tell that client "re-read and replay",
    and replaying would fail forever -- an infinite retry loop on a permanent
    condition, invisible as an incident. So the translation table does not name the
    base class, and the exception travels on to the 500 handler.

    What it does *not* skip is the rollback: ``revision_operation`` keeps it in
    ``RevisionFailure``, because the ``FOR UPDATE`` row lock has to be released
    whether or not the failure has a client-facing translation. That second half is
    the load-bearing one, so it is asserted rather than described (#331 review, B4):
    the session is put *in* a transaction before the raise, and has to be out of it
    after -- which on PostgreSQL is precisely what lets go of the lock.
    """
    unrelated = RevisionStoreError("a node the tree cannot reach")

    with pytest.raises(RevisionStoreError):
        revision_http_exception(unrelated)

    session = get_session_factory()()
    try:
        with pytest.raises(RevisionStoreError), revision_operation(session):
            # A real refusal surfaces mid-transaction, with the revision row claimed
            # and whatever `save_revision` already flushed still open. This query puts
            # the session in that same state, so the assertion below has something to
            # say: on a never-used session `in_transaction()` is False to begin with.
            session.execute(select(ProjectRevision.id)).first()
            assert session.in_transaction()
            raise unrelated

        assert not session.in_transaction()
    finally:
        session.close()


def test_a_data_error_is_rolled_back_without_being_translated() -> None:
    """#331 review, B3: in the rollback scope, deliberately absent from the table.

    A ``DataError`` means a write payload reached ``flush()`` carrying a value its
    column cannot hold -- i.e. that one of the bounds of ``schemas/revisions.py`` is
    missing. That is a bug of this repository, not a condition to publish, so there is
    no code for it and it travels on to the 500 handler like a bare store error. But
    it travels on *after* a rollback: a bug must not also strand the ``FOR UPDATE``
    lock the write took. ``test_revision_bounds_postgres`` pins the other half -- that
    PostgreSQL really answers ``DataError``, and that it is not an ``IntegrityError``.
    """
    out_of_range = DataError("UPDATE ...", params=None, orig=Exception("smallint out of range"))

    with pytest.raises(DataError):
        revision_http_exception(out_of_range)

    session = get_session_factory()()
    try:
        with pytest.raises(DataError), revision_operation(session):
            session.execute(select(ProjectRevision.id)).first()
            assert session.in_transaction()
            raise out_of_range

        assert not session.in_transaction()
    finally:
        session.close()


def test_an_integrity_error_is_answered_as_a_conflict() -> None:
    """B2: the fallback the OpenAPI description publishes, exercised rather than assumed.

    A constraint this layer does not restate (a foreign key, a unique index) refuses
    the write at ``flush()``. That is a conflict with stored data, not a malformed
    request, so it is a 409 carrying its own code -- and it is a *listed* entry of
    the table, not a catch-all, which is what lets an unrecognised exception be an
    incident instead of borrowing this code.
    """
    translated = revision_http_exception(
        IntegrityError("INSERT ...", params=None, orig=Exception("unique violation"))
    )

    assert translated.status_code == 409
    assert translated.detail == {"code": "REVISION_INTEGRITY_CONFLICT"}


# --------------------------------------------------------------------------------------
# Structure: create, move, delete
# --------------------------------------------------------------------------------------


def test_creating_a_task_node_inserts_it_and_bumps_the_lock_version() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/tasks"),
            json={
                "name": "Recette",
                "parent_id": fixture.nodes["alpha"],
                "position": 1,
                "description": "Campagne de recette",
                "duration_minutes": 960,
                "expected_lock_version": 0,
            },
            headers=headers,
        )
        assert response.status_code == 201
        created = cast(dict[str, Any], response.json())
        read = client.get(fixture.url("/nodes"), headers=headers)

    assert created["lock_version"] == 1
    assert created["node_id"] > 0
    assert created["work_item_id"] > 0
    nodes = cast(list[dict[str, Any]], cast(dict[str, Any], read.json())["nodes"])
    assert [node["planning"]["name"] for node in nodes] == [
        "Alpha",
        "Recette",
        "Design",
        "Sub",
        "Build",
        "Beta",
    ]
    recette = next(node for node in nodes if node["node_id"] == created["node_id"])
    assert recette["description"] == "Campagne de recette"
    assert recette["planning"]["duration_minutes"] == 960
    # Règle 1, INV-15: a task created without a named calendar inherits the
    # project's, recorded as inherited rather than pinned.
    assert recette["planning"]["calendar_source"] == "project"
    assert recette["planning"]["calendar_id"] == fixture.reference.calendar_id


def test_creating_a_task_under_an_unknown_parent_is_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/tasks"),
            json={"name": "Orpheline", "parent_id": 999_999, "expected_lock_version": 0},
            headers=headers,
        )

    assert response.status_code == 404
    assert _detail(response) == {"code": "REVISION_NODE_NOT_FOUND"}


def test_indenting_and_outdenting_a_selection() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        indented = client.post(
            fixture.url("/nodes/move"),
            json={
                "node_ids": [fixture.nodes["build"]],
                "mode": "indent",
                "expected_lock_version": 0,
            },
            headers=headers,
        )
        assert indented.status_code == 200
        read = client.get(fixture.url("/nodes"), headers=headers)

    nodes = {
        node["node_id"]: node
        for node in cast(list[dict[str, Any]], cast(dict[str, Any], read.json())["nodes"])
    }
    assert nodes[fixture.nodes["build"]]["parent_id"] == fixture.nodes["design"]
    assert nodes[fixture.nodes["build"]]["level"] == 3


def test_moving_a_node_under_its_own_descendant_is_refused_as_a_cycle() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/nodes/move"),
            json={
                "node_ids": [fixture.nodes["alpha"]],
                "mode": "to_parent",
                "target_parent_id": fixture.nodes["sub"],
                "expected_lock_version": 0,
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert _detail(response) == {"code": "REVISION_TREE_CYCLE"}


def test_outdenting_a_root_node_is_refused_as_an_invalid_selection() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/nodes/move"),
            json={
                "node_ids": [fixture.nodes["alpha"]],
                "mode": "outdent",
                "expected_lock_version": 0,
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert _detail(response) == {"code": "REVISION_SELECTION_INVALID"}


def test_deleting_a_node_removes_its_whole_subtree_and_names_the_chiffrage_it_takes() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        with get_session_factory()() as session:
            revision_tree.add_cost_line(
                session,
                fixture.revision_id,
                expected_lock_version=0,
                nature=domain.CostNature.LABOR,
                label="Etude",
                parent_id=fixture.nodes["sub"],
                role_id=fixture.reference.role_id,
                hours=Decimal("12"),
            )
            session.commit()

        response = client.post(
            fixture.url("/nodes/delete"),
            json={"node_ids": [fixture.nodes["design"]], "expected_lock_version": 1},
            headers=headers,
        )

    assert response.status_code == 200
    body = cast(dict[str, Any], response.json())
    assert body["lock_version"] == 2
    assert set(cast(list[int], body["removed_node_ids"])) >= {
        fixture.nodes["design"],
        fixture.nodes["sub"],
    }
    losses = cast(list[dict[str, Any]], body["cost_losses"])
    assert [loss["label"] for loss in losses] == ["Etude"]
    assert losses[0]["nature"] == "labor"
    assert losses[0]["bearing_task_name"] == "Sub"

    with get_session_factory()() as session:
        remaining = {
            row.id
            for row in session.query(RevisionNode).filter(
                RevisionNode.revision_id == fixture.revision_id
            )
        }
    assert remaining == {fixture.nodes["alpha"], fixture.nodes["build"], fixture.nodes["beta"]}


def test_deleting_an_unknown_node_is_not_found() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/nodes/delete"),
            json={"node_ids": [999_999], "expected_lock_version": 0},
            headers=headers,
        )

    assert response.status_code == 404
    assert _detail(response) == {"code": "REVISION_NODE_NOT_FOUND"}


def test_an_empty_selection_is_refused_by_the_schema_before_the_domain_sees_it() -> None:
    """FastAPI's own 422 keeps one meaning on this API: the body did not parse.

    Deliberately *not* converted into a 400 the way the legacy planning routes do
    (``_PlanningTaskBodyValidationRoute``): the refusals of the domain are the ones
    that answer 400 here, so a malformed body stays distinguishable from a refused
    operation without reading the body shape.

    The body is asserted, not only the status: ``RevisionUnprocessable`` publishes
    ``type``/``loc``/``msg`` as the shape of this response, and ``msg`` is documented
    as untranslated English a frontend must not display -- which only holds if
    ``type`` and ``loc`` really are there to act on instead.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/nodes/delete"),
            json={"node_ids": [], "expected_lock_version": 0},
            headers=headers,
        )

    assert response.status_code == 422
    errors = cast(list[dict[str, Any]], cast(dict[str, Any], response.json())["detail"])
    assert [(error["type"], error["loc"]) for error in errors] == [
        ("too_short", ["body", "node_ids"])
    ]
    assert isinstance(errors[0]["msg"], str)
    assert _lock_version(fixture.revision_id) == 0


# --------------------------------------------------------------------------------------
# Calendar parity with the legacy resolution (acceptance criterion 5)
# --------------------------------------------------------------------------------------


class CalendarScenario:
    """One staffing configuration, and what each of the two resolutions should answer.

    ``role_calendars`` lists the MO cost lines to hang under the task, in the order
    they are created -- which is both their depth-first order under the task and
    their ascending ``role_id`` order, since each role is inserted just before its
    line. ``"own"`` gives the role a calendar of its own, ``"none"`` leaves it
    without one.
    """

    def __init__(self, label: str, role_calendars: tuple[str, ...]) -> None:
        self.label = label
        self.role_calendars = role_calendars


_CALENDAR_SCENARIOS = [
    CalendarScenario("one role carrying its own calendar", ("own",)),
    CalendarScenario("two roles with different calendars", ("own", "own")),
    CalendarScenario("a role with no calendar at all", ("none",)),
]


@pytest.mark.parametrize(
    "scenario", _CALENDAR_SCENARIOS, ids=[case.label for case in _CALENDAR_SCENARIOS]
)
def test_the_calendar_of_a_task_matches_the_legacy_resolution_for_equivalent_assignments(
    scenario: CalendarScenario,
) -> None:
    """Same tree, same role assignments, same answer -- by a different route.

    Before the migration, a task's calendar was *derived on read* from
    `wf_task_role_assignment` through ``resolve_task_calendar_ids``. Règle 1 makes
    it a **stored** attribute of the planning facet instead, written when a role is
    assigned. This pins that the two agree on equivalent data, which is what
    "no regression" means for this attribute: the legacy path is computed here on a
    twin `ms_task` + assignments, the new one is read off the facet through the API.

    Three configurations rather than one (#331 review, B6), because the interesting
    part of Rule 1 is precisely what happens when the answer is *not* obvious:

    * one role carrying its own calendar -- the calendar is the role's, not the
      project's, which is the only case a single scenario could demonstrate;
    * two roles with different calendars -- both sides have to pick *one*, and the
      two formulate the tie-break differently: the legacy resolution keeps the
      lowest ``role_id``, Rule 1 keeps the first MO facet in depth-first order of
      the subtree. They agree here because the fixture creates roles and lines in
      the same order, which is the realistic case; a planning where the two orders
      disagree would get two different answers, and that is a property of the
      *legacy* tie-break being arbitrary (it says so itself), not a regression of
      this one. Pinned so the divergence is a known one rather than a surprise;
    * a role with no calendar -- the legacy resolution omits the task from its
      mapping entirely (MS Project then applies the project calendar), and Rule 1
      falls back to the project calendar with ``calendar_source`` = ``project``.
      Same outcome, said two different ways.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]
        project_calendar_id = fixture.reference.calendar_id

        role_ids: list[int] = []
        role_calendar_ids: list[int | None] = []
        with get_session_factory()() as session:
            # Legacy twin: an ms_task carrying the very same role assignments.
            legacy_task = MsTask(project_id=fixture.project_id, uid=42, name="Design")
            session.add(legacy_task)
            session.flush()
            for index, kind in enumerate(scenario.role_calendars):
                calendar_id: int | None = None
                if kind == "own":
                    # A calendar of its own, so that "inherited from the project"
                    # and "taken from the role" cannot be confused.
                    calendar = Calendar(
                        code=f"ROLE-{uuid4().hex[:8]}",
                        name=f"Calendrier du role {index}",
                        weeks_per_year=47,
                        is_active=True,
                        is_default=False,
                    )
                    session.add(calendar)
                    session.flush()
                    calendar_id = calendar.id
                role = ResourceRole(
                    node_id=session.query(ResourceRole)
                    .filter(ResourceRole.id == fixture.reference.role_id)
                    .one()
                    .node_id,
                    cost_category_id=fixture.reference.cost_category_id,
                    calendar_id=calendar_id,
                    name=f"Role {index} {uuid4().hex[:6]}",
                )
                session.add(role)
                session.flush()
                role_ids.append(role.id)
                role_calendar_ids.append(calendar_id)
                session.add(
                    TaskRoleAssignment(
                        task_id=legacy_task.id,
                        role_id=role.id,
                        quantity=Decimal("1"),
                        hours=Decimal("8"),
                    )
                )
            session.commit()
            legacy = resolve_task_calendar_ids(session, fixture.project_id, {42}).get(42)

        # Ascending role ids and depth-first order of the cost lines coincide, which
        # is what makes the two tie-breaks comparable at all -- see the docstring.
        assert role_ids == sorted(role_ids)

        with get_session_factory()() as session:
            for index, role_id in enumerate(role_ids):
                revision_tree.add_cost_line(
                    session,
                    fixture.revision_id,
                    expected_lock_version=index,
                    nature=domain.CostNature.LABOR,
                    label=f"Etude {index}",
                    parent_id=design,
                    role_id=role_id,
                    hours=Decimal("8"),
                )
            session.commit()

        read = client.get(fixture.url("/nodes"), headers=headers)

    nodes = {
        node["node_id"]: node
        for node in cast(list[dict[str, Any]], cast(dict[str, Any], read.json())["nodes"])
    }
    planning = cast(dict[str, Any], nodes[design]["planning"])

    first_role_calendar = next(
        (calendar_id for calendar_id in role_calendar_ids if calendar_id is not None), None
    )
    assert legacy == first_role_calendar
    if first_role_calendar is None:
        # The legacy path says "nothing to say, use the project calendar" by leaving
        # the task out of its mapping; Rule 1 says it by storing the project's.
        assert planning["calendar_id"] == project_calendar_id
        assert planning["calendar_source"] == "project"
    else:
        assert planning["calendar_id"] == legacy
        assert planning["calendar_source"] == "role"


# --------------------------------------------------------------------------------------
# Ownership and addressing
# --------------------------------------------------------------------------------------


def test_a_revision_of_somebody_elses_project_is_not_found() -> None:
    with TestClient(app) as client:
        owner_headers = _auth_headers(client)
        fixture = _seed(client, owner_headers)
        intruder_headers = _auth_headers(client)

        response = client.get(fixture.url("/nodes"), headers=intruder_headers)

    assert response.status_code == 404


def test_the_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/projects/1/revisions/1/nodes")
    assert response.status_code == 401


def test_a_revision_whose_project_has_no_default_calendar_reports_it_as_a_conflict() -> None:
    """#350: the missing-calendar refusal reaches reads too, and is named rather than a 500."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        with get_session_factory()() as session:
            session.query(Calendar).filter(Calendar.is_default.is_(True)).update(
                {Calendar.is_default: False}
            )
            session.commit()

        response = client.get(fixture.url("/nodes"), headers=headers)

    assert response.status_code == 409
    assert _detail(response) == {"code": "PROJECT_CALENDAR_MISSING"}


@pytest.mark.parametrize("project_status", ["perdu", "termine", "abandonne"])
def test_a_read_only_project_refuses_every_write_without_mutating(project_status: str) -> None:
    """The project-level guard the legacy planning routes carried, kept on its own code.

    Distinct from INV-03 on purpose: the revision here is a perfectly editable
    draft, and what refuses the write is the *project*'s status. Ported from
    ``test_planning_acceptance.test_read_only_project_rejects_direct_edit_without_mutating``,
    whose endpoint E14-05 (#331) removed.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        with get_session_factory()() as session:
            project = session.get(MsProject, fixture.project_id)
            assert project is not None
            project.status = project_status
            session.commit()

        responses = [
            (url, getattr(client, method)(url, json=payload, headers=headers))
            for method, url, payload in _writes(fixture)
        ]
        read = client.get(fixture.url("/nodes"), headers=headers)

    for url, response in responses:
        assert response.status_code == 409, url
        assert _detail(response) == {"code": "PROJECT_READ_ONLY"}, url
    assert _lock_version(fixture.revision_id) == 0
    # Reading stays allowed: a finished project is consultable, only frozen.
    assert read.status_code == 200


def test_the_seeded_project_really_has_an_owner() -> None:
    """Guard on the fixture itself: an unowned project would make every 404 above vacuous.

    ``get_project_or_404`` filters on ``owner_id``, so a fixture that seeded its
    project straight into the table would answer 404 to *everything* and every
    ownership assertion in this module would pass for the wrong reason.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
    with get_session_factory()() as session:
        project = session.get(MsProject, fixture.project_id)
        assert project is not None
        assert project.owner_id is not None


# --------------------------------------------------------------------------------------
# Bounds: no numeric field reaches a column it cannot fit in (#331 review, H1)
# --------------------------------------------------------------------------------------


_OUT_OF_RANGE_SMALLINT = 100_000
_OUT_OF_RANGE_INT32 = 3_000_000_000


def _out_of_range_bodies(fixture: Fixture) -> list[tuple[str, str, str, dict[str, Any]]]:
    """``(label, method, url, payload)`` for every numeric field a column constrains."""
    design = fixture.nodes["design"]
    planning = fixture.url(f"/nodes/{design}/planning")
    predecessors = fixture.url(f"/nodes/{design}/predecessors")
    return [
        # SMALLINT columns, and the two fields the review found unbounded.
        (
            "duration_format above SMALLINT",
            "patch",
            planning,
            {"duration_format": _OUT_OF_RANGE_SMALLINT, "expected_lock_version": 0},
        ),
        (
            "duration_format outside the MSPDI enumeration",
            "patch",
            planning,
            {"duration_format": 13, "expected_lock_version": 0},
        ),
        (
            "lag_format above SMALLINT",
            "put",
            predecessors,
            {
                "predecessors": [
                    {
                        "predecessor_node_id": fixture.nodes["build"],
                        "lag_format": _OUT_OF_RANGE_SMALLINT,
                    }
                ],
                "expected_lock_version": 0,
            },
        ),
        (
            "lag_format below SMALLINT",
            "put",
            predecessors,
            {
                "predecessors": [{"predecessor_node_id": fixture.nodes["build"], "lag_format": -1}],
                "expected_lock_version": 0,
            },
        ),
        # INTEGER columns: an id that no query would match, but that psycopg would
        # have to adapt into an int4 parameter on the way to the facet row.
        (
            "calendar_id above INTEGER",
            "patch",
            planning,
            {"calendar_id": _OUT_OF_RANGE_INT32, "expected_lock_version": 0},
        ),
        (
            "parent_id above INTEGER",
            "post",
            fixture.url("/tasks"),
            {"name": "Hors bornes", "parent_id": _OUT_OF_RANGE_INT32, "expected_lock_version": 0},
        ),
        (
            "node_ids above INTEGER",
            "post",
            fixture.url("/nodes/delete"),
            {"node_ids": [_OUT_OF_RANGE_INT32], "expected_lock_version": 0},
        ),
        (
            "predecessor_node_id above INTEGER",
            "put",
            predecessors,
            {
                "predecessors": [{"predecessor_node_id": _OUT_OF_RANGE_INT32}],
                "expected_lock_version": 0,
            },
        ),
        (
            "expected_lock_version above INTEGER",
            "patch",
            planning,
            {"duration_minutes": 60, "expected_lock_version": _OUT_OF_RANGE_INT32},
        ),
        (
            "too many predecessors",
            "put",
            predecessors,
            {
                "predecessors": [
                    {"predecessor_node_id": fixture.nodes["build"], "link_type": 1}
                    for _ in range(1_001)
                ],
                "expected_lock_version": 0,
            },
        ),
    ]


def test_a_numeric_field_its_column_cannot_hold_is_refused_before_the_flush() -> None:
    """H1: an unbounded numeric field is a 500 on PostgreSQL, and SQLite cannot see it.

    ``duration_format`` and ``lag_format`` land in ``SmallInteger`` columns and
    every id lands in an ``Integer`` one. A value outside those ranges reaches
    ``flush()`` and PostgreSQL answers ``DataError`` -- which is **not** an
    ``IntegrityError``, so it crosses ``revision_operation`` untranslated and comes
    back as a 500 on a request the client had every reason to think well-formed. (The
    rollback covers it, so the ``FOR UPDATE`` lock is released; that is damage control,
    not an answer.) SQLite gives both types an unbounded INTEGER affinity, so nothing on the
    default test backend can catch it: the schema bound is the whole guard, and this
    is where it is pinned.

    Asserted as one table rather than one test per field so that adding a numeric
    field without its bound shows up as a missing row here.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        responses = [
            (label, getattr(client, method)(url, json=payload, headers=headers))
            for label, method, url, payload in _out_of_range_bodies(fixture)
        ]

    assert len(responses) == 10
    for label, response in responses:
        assert response.status_code == 422, (label, response.text)
    # Nothing was written, on any of them.
    assert _lock_version(fixture.revision_id) == 0


# --------------------------------------------------------------------------------------
# Partial edition: null is a value, except where there is no empty state (M1, M7, B9)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [("name", None), ("percent_complete", None), ("is_milestone", None), ("is_manual", None)],
)
def test_an_explicit_null_on_a_field_with_no_empty_state_is_refused(
    field: str, value: None
) -> None:
    """M1: the contract published these four as nullable, the handler silently ignored it.

    ``name``, ``percent_complete``, ``is_milestone`` and ``is_manual`` sit in
    ``NOT NULL`` columns and the domain types them without ``None``. Declared
    ``| None`` only so that *omitting* them is legal, they used to answer 200 to an
    explicit ``null``, advance ``lock_version`` and change nothing -- the one answer
    a client cannot distinguish from success. Now a 422, and the counter stays put.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]

        response = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={field: value, "expected_lock_version": 0},
            headers=headers,
        )

    assert response.status_code == 422
    errors = cast(list[dict[str, Any]], cast(dict[str, Any], response.json())["detail"])
    assert [error["loc"] for error in errors] == [["body"]]
    assert field in errors[0]["msg"]
    assert _lock_version(fixture.revision_id) == 0


def test_a_null_on_a_field_that_does_have_an_empty_state_still_clears_it() -> None:
    """The other half of M1: the refusal above must not have made the payload total.

    ``duration_minutes``, ``start_at``, ``finish_at``, ``work_minutes`` and
    ``calendar_id`` all have a meaningful "cleared" state, and ``null`` remains the
    way to reach it -- which is why the guard names four fields instead of refusing
    ``null`` outright.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]

        assert (
            client.patch(
                fixture.url(f"/nodes/{design}/planning"),
                json={"duration_minutes": 600, "expected_lock_version": 0},
                headers=headers,
            ).status_code
            == 200
        )
        cleared = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={"duration_minutes": None, "expected_lock_version": 1},
            headers=headers,
        )

    assert cleared.status_code == 200
    assert _facet(design).duration_minutes is None


def test_a_body_carrying_only_the_lock_version_advances_it_and_changes_nothing() -> None:
    """B9: defensible, so documented and frozen rather than left to be rediscovered.

    ``lock_version`` records "a write happened", not "something differs". Making it
    conditional would let two clients holding the same value both succeed, which is
    the failure the counter exists to prevent -- so an empty edit costs one crank
    and is not an error.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        design = fixture.nodes["design"]
        before = _facet(design)

        response = client.patch(
            fixture.url(f"/nodes/{design}/planning"),
            json={"expected_lock_version": 0},
            headers=headers,
        )

    assert response.status_code == 200
    assert cast(dict[str, Any], response.json())["lock_version"] == 1
    assert _lock_version(fixture.revision_id) == 1
    after = _facet(design)
    assert (after.name, after.duration_minutes, after.percent_complete, after.calendar_id) == (
        before.name,
        before.duration_minutes,
        before.percent_complete,
        before.calendar_id,
    )


@pytest.mark.parametrize("mode", ["up", "down", "indent", "outdent"])
def test_a_destination_supplied_with_a_mode_that_computes_its_own_is_refused(mode: str) -> None:
    """M7: ``position`` used to be dropped in silence on four of the five modes.

    ``up``/``down``/``indent``/``outdent`` derive their own destination, so a
    ``target_parent_id`` or a ``position`` alongside them is an intention the server
    cannot honour. Answering 200 destroyed it without a word; 422 names the field.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url("/nodes/move"),
            json={
                "node_ids": [fixture.nodes["build"]],
                "mode": mode,
                "position": 3,
                "expected_lock_version": 0,
            },
            headers=headers,
        )

    assert response.status_code == 422
    assert "position" in cast(list[dict[str, Any]], response.json()["detail"])[0]["msg"]
    assert _lock_version(fixture.revision_id) == 0


# --------------------------------------------------------------------------------------
# Règle 1 on creation belongs to the domain, not to the route (M3)
# --------------------------------------------------------------------------------------


def test_creating_a_task_with_a_named_calendar_pins_it_as_manual() -> None:
    """M3: the only business rule the route carried, moved back where it already lived.

    ``_apply_calendar_defaults`` in ``domain.revision.tree`` has always done this;
    the route restated it, which left #333 free to restate it differently for the
    cost facet. The route no longer passes ``calendar_source`` at all, and this is
    the branch that was untested while it did.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        with get_session_factory()() as session:
            pinned = Calendar(
                code=f"PIN-{uuid4().hex[:8]}",
                name="Calendrier epingle",
                weeks_per_year=47,
                is_active=True,
                is_default=False,
            )
            session.add(pinned)
            session.commit()
            pinned_id = pinned.id

        created = client.post(
            fixture.url("/tasks"),
            json={"name": "Epinglee", "calendar_id": pinned_id, "expected_lock_version": 0},
            headers=headers,
        )
        read = client.get(fixture.url("/nodes"), headers=headers)

    assert created.status_code == 201
    node_id = cast(dict[str, Any], created.json())["node_id"]
    node = next(
        node
        for node in cast(list[dict[str, Any]], cast(dict[str, Any], read.json())["nodes"])
        if node["node_id"] == node_id
    )
    assert node["planning"]["calendar_id"] == pinned_id
    assert node["planning"]["calendar_source"] == "manual"
    assert _facet(node_id).calendar_source == "manual"


# --------------------------------------------------------------------------------------
# The error table and the published contract say the same thing (M2)
# --------------------------------------------------------------------------------------

#: Codes the routes decide themselves, because they are about the project rather
#: than about the revision -- see the docstring of ``api.routes.revisions``.
_PROJECT_CODES = {
    404: {"PROJECT_NOT_FOUND"},
    409: {"PROJECT_READ_ONLY"},
}

#: Which shared response component each status comes back on.
_RESPONSE_COMPONENT = {
    400: "RevisionBadRequest",
    404: "RevisionNotFound",
    409: "RevisionConflict",
}


def test_every_emitted_error_code_is_documented_in_the_contract() -> None:
    """M2: parity between what the API emits and what its descriptions promise.

    A frontend builds its translation table off those descriptions, so a code that
    is emitted but undocumented reaches a user untranslated -- exactly what
    ``_generic_http_exception_handler`` exists to prevent -- and a code documented
    but never emitted is a dead branch in that table. #333 doubles the size of this
    table, which is why the check is here rather than in a review comment.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    responses = cast(dict[str, Any], cast(dict[str, Any], raw_document)["components"])["responses"]

    emitted: dict[int, set[str]] = {code: set(names) for code, names in _PROJECT_CODES.items()}
    emitted.setdefault(409, set()).add("REVISION_LOCK_CONFLICT")
    for _error_type, status_code, code in _TRANSLATIONS:
        emitted.setdefault(status_code, set()).add(code)

    assert set(emitted) == set(_RESPONSE_COMPONENT)
    for status_code, codes in emitted.items():
        description = cast(str, responses[_RESPONSE_COMPONENT[status_code]]["description"])
        cited = {word.strip(".,;:()`") for word in description.split()}
        cited = {word for word in cited if word.isupper() and "_" in word}
        assert codes == cited, status_code


def test_the_docstring_table_is_the_inventory_it_claims_to_be() -> None:
    """B-1: the module docstring presents a table of reference; nothing held it to it.

    The check above asserts ``_TRANSLATIONS`` against the OpenAPI descriptions and
    never reads the docstring, so a new code could be -- and was, for
    ``REVISION_MILESTONE_HAS_CHILDREN`` -- emitted and documented on the wire while
    missing from the inventory a reader consults first. The drift is silent by
    construction and repeats with every code, which #333 will add by the dozen.
    """
    docstring = revision_errors.__doc__
    assert docstring is not None
    tabled = {
        (int(match.group(1)), match.group(2))
        for match in re.finditer(r"\s(\d{3})\s+``([A-Z_]+)``", docstring)
    }

    emitted = {(status_code, code) for _error_type, status_code, code in _TRANSLATIONS}
    # Not a translation of a domain exception: the routes raise it directly, but it
    # is a revision code and the table carries it.
    emitted.add((409, "REVISION_LOCK_CONFLICT"))

    assert tabled == emitted


def test_the_six_operations_document_the_422_they_can_answer() -> None:
    """M6: 422 was reachable on all six and named nowhere in the contract."""
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    document = cast(dict[str, Any], raw_document)
    paths = cast(dict[str, Any], document["paths"])

    revision_paths = [path for path in paths if "/revisions/" in path]
    assert len(revision_paths) == 6
    for path in revision_paths:
        for method, operation in cast(dict[str, Any], paths[path]).items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert operation["responses"]["422"]["$ref"] == (
                "#/components/responses/RevisionUnprocessable"
            ), (path, method)

    schema = cast(dict[str, Any], document["components"])["responses"]["RevisionUnprocessable"]
    assert schema["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/RevisionValidationError"
    )


# --------------------------------------------------------------------------------------
# Ownership on the write path too (B1)
# --------------------------------------------------------------------------------------


def test_a_write_on_somebody_elses_project_is_not_found() -> None:
    """B1: the read path was covered, the write path -- a different helper -- was not.

    ``_writable_project`` re-implements the ownership filter of ``_readable_project``
    with a row lock on top, so "somebody else's project answers 404" has to be
    proved on it too, and before the read-only check it also performs.
    """
    with TestClient(app) as client:
        owner_headers = _auth_headers(client)
        fixture = _seed(client, owner_headers)
        intruder_headers = _auth_headers(client)

        responses = [
            (url, getattr(client, method)(url, json=payload, headers=intruder_headers))
            for method, url, payload in _writes(fixture)
        ]

    assert len(responses) == 5
    for url, response in responses:
        assert response.status_code == 404, url
        assert _detail(response) == {"code": "PROJECT_NOT_FOUND"}, url
    assert _lock_version(fixture.revision_id) == 0
