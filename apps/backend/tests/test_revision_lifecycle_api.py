"""The lifecycle of a revision, over HTTP (E14-08, issue #334).

The four acceptance criteria this issue keeps are pinned here -- copying a validated
revision, the symmetric immutability of the two facets, the single reference pointer
fixed when a project enters ``en_cours``, and two variants of a chiffrage living as
two independent revisions -- plus the two decisions #334 had to take on the way:

* **a frozen line is cut per year**, carrying the annual rate and the inflation
  coefficient it was priced under. A labour facet borne by a task spanning two years
  produces two lines, and no line carries an average of anything;
* **an amount is rounded per line and only then summed**, the rule #364 and #368
  fixed for every published figure, so the document a client reads adds up to the
  totals the aggregates endpoint answers.

The fifth criterion of the issue -- "`ms_project` no longer carries the three legacy
pointers" -- belongs to E14-12 (#339) under the amended scope, and its counterpart
here is that the *new* pointer is written and that nothing can make a planning
reference and a devis reference disagree, there being one pointer for both.

The fixture follows ``test_revision_cost_api``'s: the project is created through the
API (so it has an owner the routes check) and the tree straight into the tables (so
what is under test owes nothing to the endpoints being tested).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from _revision_db_support import (
    ReferenceData,
    insert_labor_line,
    insert_purchase_line,
    insert_revision,
    insert_task,
    seed_annual_rate,
    seed_reference_data,
)
from waterfall.db.session import get_session_factory
from waterfall.domain import revision as domain
from waterfall.main import app
from waterfall.models.ms_core import MsProject
from waterfall.models.resources import ProjectCostCode
from waterfall.models.revision import (
    ProjectRevision,
    ProjectRevisionPointer,
    RevisionCostFacet,
    RevisionFrozenLine,
    RevisionNode,
    RevisionPlanFacet,
)
from waterfall.services import project_lifecycle
from waterfall.services.project_lifecycle import REFERENCE_REVISION_KINDS

#: The two years the fixture's bearing task spans, with two different annual rates
#: and two different inflation coefficients -- which is the whole point: a single
#: scalar rate on a frozen line could not represent either of them.
FIRST_YEAR = 2026
SECOND_YEAR = 2027


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"revision.lifecycle.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


class Fixture:
    """A project, a draft revision spanning two years, and its chiffrage."""

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

    def url(self, suffix: str = "", *, revision_id: int | None = None) -> str:
        revision = self.revision_id if revision_id is None else revision_id
        return f"/projects/{self.project_id}/revisions/{revision}{suffix}"


def _seed(client: TestClient, headers: dict[str, str], *, rates: bool = True) -> Fixture:
    response = client.post("/projects", json={"name": "Revision lifecycle"}, headers=headers)
    assert response.status_code == 201
    project_id = cast(int, response.json()["id"])
    with get_session_factory()() as session:
        # The shared referential builder, re-pointed at the project the API created:
        # the routes check ownership, and `seed_reference_data`'s own project has none.
        reference = dataclasses.replace(
            seed_reference_data(session, key=uuid4().hex[:8]), project_id=project_id
        )
        revision = insert_revision(session, reference)
        alpha = insert_task(
            session,
            reference,
            revision,
            name="Alpha",
            position=1,
            start_at=datetime(FIRST_YEAR, 3, 1, tzinfo=UTC),
            finish_at=datetime(SECOND_YEAR, 6, 30, tzinfo=UTC),
        )
        study = insert_labor_line(
            session, reference, revision, label="Etude", parent_id=alpha.id, hours=Decimal("10")
        )
        beta = insert_task(session, reference, revision, name="Beta", position=2)
        supply = insert_purchase_line(
            session,
            reference,
            revision,
            label="Serveur",
            parent_id=beta.id,
            unit_cost=Decimal("1200.00"),
        )
        if rates:
            seed_annual_rate(session, reference, year=FIRST_YEAR, hourly_rate=Decimal("100.00"))
            seed_annual_rate(
                session,
                reference,
                year=SECOND_YEAR,
                hourly_rate=Decimal("110.00"),
                inflation=Decimal("1.05000000"),
            )
        session.commit()
        return Fixture(
            project_id,
            reference,
            revision.id,
            {"alpha": alpha.id, "study": study.id, "beta": beta.id, "supply": supply.id},
        )


def _body(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], response.json())


def _detail(response: Any) -> Any:
    return _body(response)["detail"]


def _frozen_lines(revision_id: int) -> list[RevisionFrozenLine]:
    with get_session_factory()() as session:
        return (
            session.query(RevisionFrozenLine)
            .filter(RevisionFrozenLine.revision_id == revision_id)
            .order_by(RevisionFrozenLine.id)
            .all()
        )


def _tree(revision_id: int) -> list[tuple[int, str]]:
    """``(work_item_id, label)`` of every node, in a shape two revisions can be
    compared by: node ids differ between a revision and its copy, identities do not."""
    with get_session_factory()() as session:
        rows: list[tuple[int, str]] = []
        for node in (
            session.query(RevisionNode)
            .filter(RevisionNode.revision_id == revision_id)
            .order_by(RevisionNode.id)
        ):
            plan = (
                session.query(RevisionPlanFacet)
                .filter(RevisionPlanFacet.node_id == node.id)
                .one_or_none()
            )
            cost = (
                session.query(RevisionCostFacet)
                .filter(RevisionCostFacet.node_id == node.id)
                .one_or_none()
            )
            label = plan.name if plan is not None else cast(RevisionCostFacet, cost).label
            rows.append((node.work_item_id, label))
        return sorted(rows)


def _validate(
    client: TestClient,
    headers: dict[str, str],
    fixture: Fixture,
    *,
    revision_id: int | None = None,
    expected_lock_version: int = 0,
) -> Any:
    return client.post(
        fixture.url("/validate", revision_id=revision_id),
        json={"expected_lock_version": expected_lock_version},
        headers=headers,
    )


def _copy(
    client: TestClient,
    headers: dict[str, str],
    fixture: Fixture,
    *,
    revision_id: int | None = None,
    expected_lock_version: int,
    **payload: Any,
) -> Any:
    """Copy a revision, quoting the counter it currently carries.

    Validating **bumps** ``lock_version`` like every other write of the domain, so a
    copy made right after one quotes 1 and not 0. Spelled as a parameter rather than
    defaulted, because getting it wrong is a 409 and not a silent success.
    """
    return client.post(
        fixture.url("/copy", revision_id=revision_id),
        json={"expected_lock_version": expected_lock_version, **payload},
        headers=headers,
    )


# --------------------------------------------------------------------------------------
# Acceptance 1: a copy reproduces the identities, and the source never moves
# --------------------------------------------------------------------------------------


def test_copying_a_validated_revision_reproduces_every_work_item_and_both_facets() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200

        response = _copy(client, headers, fixture, expected_lock_version=1)

    assert response.status_code == 201
    created = _body(response)
    assert created["source_revision_id"] == fixture.revision_id
    assert created["version_number"] == 2
    assert created["lock_version"] == 0
    # Node for node: the same work items, carrying the same facets. The ids of the
    # nodes themselves are not compared because they are deliberately *not* shared.
    assert _tree(created["revision_id"]) == _tree(fixture.revision_id)
    with get_session_factory()() as session:
        copy = session.get(ProjectRevision, created["revision_id"])
        assert copy is not None
        assert copy.status == "draft"
        assert set(_node_ids(session, copy.id)) & set(_node_ids(session, fixture.revision_id)) == (
            set()
        )
    # A draft carries no frozen line, whatever its source froze (INV-24).
    assert _frozen_lines(created["revision_id"]) == []


def _node_ids(session: Session, revision_id: int) -> list[int]:
    return [
        row.id
        for row in session.query(RevisionNode).filter(RevisionNode.revision_id == revision_id)
    ]


def test_editing_a_copy_never_modifies_the_revision_it_was_copied_from() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        created = _body(_copy(client, headers, fixture, expected_lock_version=1))
        source_before = _tree(fixture.revision_id)

        added = client.post(
            fixture.url("/tasks", revision_id=created["revision_id"]),
            json={"name": "Ajout dans la copie", "expected_lock_version": 0},
            headers=headers,
        )

    assert added.status_code == 201
    assert len(_tree(created["revision_id"])) == len(source_before) + 1
    assert _tree(fixture.revision_id) == source_before
    with get_session_factory()() as session:
        source = session.get(ProjectRevision, fixture.revision_id)
        assert source is not None
        # The source is rigorously unchanged by the edit made on its copy: the
        # counter still reads what the validation left it at, and no write since.
        assert (source.status, source.lock_version) == ("validated", 1)


# --------------------------------------------------------------------------------------
# Acceptance 2: one refusal, the same code, on both facets
# --------------------------------------------------------------------------------------


def test_validating_refuses_every_later_write_on_both_facets_with_the_same_code() -> None:
    """The criterion of #334, and the reason the guard is in one place.

    Both attempts below are aimed at the *same* revision through two different
    facets, and both come back with ``REVISION_IMMUTABLE`` -- not two codes a
    frontend would have to translate twice, and not one facet refusing while the
    other writes.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200

        planning_write = client.patch(
            fixture.url(f"/nodes/{fixture.nodes['alpha']}/planning"),
            json={"duration_minutes": 480, "expected_lock_version": 1},
            headers=headers,
        )
        cost_write = client.patch(
            fixture.url(f"/nodes/{fixture.nodes['study']}/cost"),
            json={"hours": "42", "expected_lock_version": 1},
            headers=headers,
        )
        structure_write = client.post(
            fixture.url("/nodes/delete"),
            json={"node_ids": [fixture.nodes["study"]], "expected_lock_version": 1},
            headers=headers,
        )
        revalidation = _validate(client, headers, fixture, expected_lock_version=1)

    assert planning_write.status_code == 409
    assert cost_write.status_code == 409
    assert structure_write.status_code == 409
    assert revalidation.status_code == 409
    assert (
        _detail(planning_write)
        == _detail(cost_write)
        == _detail(structure_write)
        == _detail(revalidation)
        == {"code": "REVISION_IMMUTABLE"}
    )


# --------------------------------------------------------------------------------------
# Acceptance 3: one reference, fixed when the project starts running
# --------------------------------------------------------------------------------------


def _reference_pointer(project_id: int) -> ProjectRevisionPointer | None:
    with get_session_factory()() as session:
        return session.get(ProjectRevisionPointer, project_id)


def test_entering_en_cours_fixes_the_single_reference_revision() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        assert _reference_pointer(fixture.project_id) is None

        for target in ("initialise", "en_reponse_appel_offre", "en_cours"):
            moved = client.patch(
                f"/projects/{fixture.project_id}/status", json={"status": target}, headers=headers
            )
            assert moved.status_code == 200, (target, moved.json())

    pointer = _reference_pointer(fixture.project_id)
    assert pointer is not None
    assert pointer.reference_revision_id == fixture.revision_id
    # There is one pointer, so there is no pair of references that could disagree:
    # the planning reference and the devis reference of the legacy socle -- still in
    # place until #339 -- were never set, and nothing here needed them.
    with get_session_factory()() as session:
        project = session.get(MsProject, fixture.project_id)
        assert project is not None
        assert project.status == "en_cours"
        assert (project.planning_reference_id, project.reference_estimate_id) == (None, None)


def test_the_reference_is_fixed_on_entry_and_never_moved_again() -> None:
    """Fixed *when the project starts running*, not "whatever is validated right now".

    A project keeps running against the version it was launched on; validating a new
    revision afterwards produces a new document to compare against that reference, it
    does not replace it. Re-sending ``en_cours`` on a project that already is
    ``en_cours`` is not a transition and moves nothing.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        for target in ("initialise", "en_reponse_appel_offre", "en_cours"):
            assert (
                client.patch(
                    f"/projects/{fixture.project_id}/status",
                    json={"status": target},
                    headers=headers,
                ).status_code
                == 200
            )

        copy = _body(_copy(client, headers, fixture, expected_lock_version=1))
        assert (
            _validate(client, headers, fixture, revision_id=copy["revision_id"]).status_code == 200
        )
        again = client.patch(
            f"/projects/{fixture.project_id}/status", json={"status": "en_cours"}, headers=headers
        )

    assert again.status_code == 200
    pointer = _reference_pointer(fixture.project_id)
    assert pointer is not None
    assert pointer.reference_revision_id == fixture.revision_id


def test_a_project_with_nothing_validated_cannot_enter_en_cours() -> None:
    """The fallback on the legacy pointers is still in force, and still refuses."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        for target in ("initialise", "en_reponse_appel_offre"):
            assert (
                client.patch(
                    f"/projects/{fixture.project_id}/status",
                    json={"status": target},
                    headers=headers,
                ).status_code
                == 200
            )

        refused = client.patch(
            f"/projects/{fixture.project_id}/status", json={"status": "en_cours"}, headers=headers
        )

    assert refused.status_code == 409
    assert _reference_pointer(fixture.project_id) is None


# --------------------------------------------------------------------------------------
# Acceptance 4: two variants of a chiffrage are two independent revisions
# --------------------------------------------------------------------------------------


def test_two_variants_of_the_same_project_are_two_independent_revisions() -> None:
    """What replaces E12's (#272) "two devis drafts coexist" criterion.

    A variant is a **complete revision**, tree included, so the two share no node and
    editing the structure of one cannot reach the other. They stay comparable all the
    same: their nodes designate the same ``work_item`` identities.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200

        first = _body(_copy(client, headers, fixture, expected_lock_version=1))
        second = _body(
            _copy(client, headers, fixture, expected_lock_version=1, kind="forecast_remaining")
        )
        assert first["revision_id"] != second["revision_id"]
        assert (first["version_number"], second["version_number"]) == (2, 3)
        assert (first["kind"], second["kind"]) == ("initial", "forecast_remaining")

        before = _tree(second["revision_id"])
        deleted = client.post(
            fixture.url("/nodes/delete", revision_id=first["revision_id"]),
            json={
                "node_ids": [_node_of(first["revision_id"], "Beta")],
                "expected_lock_version": 0,
            },
            headers=headers,
        )

    assert deleted.status_code == 200
    # The first variant lost a subtree; the second is untouched, node for node.
    assert len(_tree(first["revision_id"])) == len(before) - 2
    assert _tree(second["revision_id"]) == before
    # And both still describe the same work items as the revision they came from.
    assert {identity for identity, _label in before} <= {
        identity for identity, _label in _tree(fixture.revision_id)
    }


def _node_of(revision_id: int, name: str) -> int:
    with get_session_factory()() as session:
        return (
            session.query(RevisionPlanFacet.node_id)
            .join(RevisionNode, RevisionNode.id == RevisionPlanFacet.node_id)
            .filter(RevisionNode.revision_id == revision_id, RevisionPlanFacet.name == name)
            .scalar()
        )


# --------------------------------------------------------------------------------------
# The frozen document: one line per year, with the rate and the coefficient it used
# --------------------------------------------------------------------------------------


def test_a_labour_line_spanning_two_years_freezes_one_line_per_year() -> None:
    """The cardinality #334 had to settle, and the reason it is settled that way.

    ``Etude`` is ten hours borne by a task running from March 2026 to June 2027. The
    engine spreads them over the two years, at ``100.00`` under an inflation of 1 and
    at ``110.00`` under 1.05 -- two rates and two coefficients that no single scalar
    on a single line could carry without averaging them into a figure absent from
    `wf_cost_rate` and uncheckable against it.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        response = _validate(client, headers, fixture)

    assert response.status_code == 200
    assert _body(response)["frozen_line_count"] == 3  # two MO years, one disbursement
    lines = {
        (line.label, line.year): line
        for line in _frozen_lines(fixture.revision_id)
        if line.label == "Etude"
    }
    assert sorted(line.year or 0 for line in lines.values()) == [FIRST_YEAR, SECOND_YEAR]
    first = lines[("Etude", FIRST_YEAR)]
    second = lines[("Etude", SECOND_YEAR)]
    assert (first.hours, second.hours) == (Decimal("5.00"), Decimal("5.00"))
    assert (first.hourly_rate, second.hourly_rate) == (Decimal("100.0000"), Decimal("110.0000"))
    assert (first.inflation_coefficient, second.inflation_coefficient) == (
        Decimal("1.00000000"),
        Decimal("1.05000000"),
    )
    assert (first.amount, second.amount) == (Decimal("500.00"), Decimal("577.50"))
    # The bearing task is carried as an identity, and the labels are copies.
    assert first.bearing_task_name == "Alpha"
    assert first.role_name == "Developpeur"


def test_a_frozen_line_carries_identities_and_copies_and_no_mutable_reference() -> None:
    """INV-23 / Règle 2, on the schema itself: there is no column to hold a node in.

    Checked on the table rather than on a row, because that is what makes it a
    property of the model: a frozen line could not reference a node, a facet or a
    line of another revision even if somebody wanted it to.
    """
    columns = {column.name for column in RevisionFrozenLine.__table__.columns}

    assert not [name for name in columns if "node" in name or "facet" in name]
    assert {"work_item_id", "bearing_work_item_id"} <= columns

    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200

    with get_session_factory()() as session:
        work_items = {
            node.work_item_id
            for node in session.query(RevisionNode).filter(
                RevisionNode.revision_id == fixture.revision_id
            )
        }
    for line in _frozen_lines(fixture.revision_id):
        assert line.work_item_id in work_items
        assert line.bearing_work_item_id is None or line.bearing_work_item_id in work_items


def test_the_frozen_amounts_are_rounded_per_line_and_add_up_to_the_published_total() -> None:
    """The rounding rule of #364/#368, applied to the document rather than to a node.

    Ten hours over three years divide into ``3.333...``, which no line can display.
    What matters is that the rounding happens **per line** and that the lines a client
    reads add up to the total the aggregates endpoint answers -- rounding the node
    total instead would produce a document whose own rows do not sum to it.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _span_bearing_task(fixture, start_year=FIRST_YEAR, finish_year=FIRST_YEAR + 2)
        with get_session_factory()() as session:
            seed_annual_rate(
                session,
                fixture.reference,
                year=FIRST_YEAR + 2,
                hourly_rate=Decimal("120.00"),
                inflation=Decimal("1.10000000"),
            )
            session.commit()
        aggregates = _body(client.get(fixture.url("/aggregates"), headers=headers))
        assert _validate(client, headers, fixture).status_code == 200

    lines = _frozen_lines(fixture.revision_id)
    assert len(lines) == 4  # three MO years, one disbursement
    for line in lines:
        assert line.amount == line.amount.quantize(Decimal("0.01"))
    total = sum((line.amount for line in lines), Decimal("0"))
    assert total == Decimal(cast(str, aggregates["total_unburdened_cost"]))


def _span_bearing_task(fixture: Fixture, *, start_year: int, finish_year: int) -> None:
    with get_session_factory()() as session:
        facet = (
            session.query(RevisionPlanFacet)
            .filter(RevisionPlanFacet.node_id == fixture.nodes["alpha"])
            .one()
        )
        facet.start_at = datetime(start_year, 3, 1, tzinfo=UTC)
        facet.finish_at = datetime(finish_year, 6, 30, tzinfo=UTC)
        session.commit()


def test_a_validation_the_rate_table_cannot_price_is_refused() -> None:
    """A read tolerates a missing rate; a document frozen for good must not.

    ``GET .../aggregates`` prices the uncovered line at zero and names the gap in its
    body, which is what keeps an editable draft readable. Freezing that same zero into
    an immutable financial document would record an error as a price, so the
    validation is refused instead -- and the list of what is missing is read from the
    very endpoint that tolerates it.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers, rates=False)
        aggregates = client.get(fixture.url("/aggregates"), headers=headers)
        refused = _validate(client, headers, fixture)

    assert aggregates.status_code == 200
    assert _body(aggregates)["missing_cost_rates"]
    assert refused.status_code == 409
    assert _detail(refused) == {"code": "REVISION_RATE_COVERAGE_MISSING"}
    assert _frozen_lines(fixture.revision_id) == []
    with get_session_factory()() as session:
        revision = session.get(ProjectRevision, fixture.revision_id)
        assert revision is not None
        assert (revision.status, revision.lock_version) == ("draft", 0)


# --------------------------------------------------------------------------------------
# Supersession (INV-22) and the displayed pointer
# --------------------------------------------------------------------------------------


def test_validating_supersedes_the_previous_validated_revision_of_the_same_kind() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        copy = _body(_copy(client, headers, fixture, expected_lock_version=1))

        response = _validate(client, headers, fixture, revision_id=copy["revision_id"])

    assert response.status_code == 200
    body = _body(response)
    assert body["status"] == "validated"
    assert body["superseded_revision_ids"] == [fixture.revision_id]
    with get_session_factory()() as session:
        statuses = {
            row.id: row.status
            for row in session.query(ProjectRevision).filter(
                ProjectRevision.project_id == fixture.project_id
            )
        }
    assert statuses == {fixture.revision_id: "superseded", copy["revision_id"]: "validated"}
    # The superseded revision keeps its own document: it is still immutable, and the
    # comparison it exists for reads it years later (Règle 2).
    assert _frozen_lines(fixture.revision_id)


def test_creating_a_draft_points_the_project_at_the_revision_being_worked_on() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        copy = _body(_copy(client, headers, fixture, expected_lock_version=1))

    pointer = _reference_pointer(fixture.project_id)
    assert pointer is not None
    assert pointer.displayed_revision_id == copy["revision_id"]
    # Displaying a draft is not referencing it: only `en_cours` sets that one.
    assert pointer.reference_revision_id is None


# --------------------------------------------------------------------------------------
# The refusals the two endpoints share with the rest of the API
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["/copy", "/validate"])
def test_a_lifecycle_write_on_somebody_elses_project_is_not_found(suffix: str) -> None:
    with TestClient(app) as client:
        owner = _auth_headers(client)
        fixture = _seed(client, owner)
        intruder = _auth_headers(client)

        response = client.post(
            fixture.url(suffix), json={"expected_lock_version": 0}, headers=intruder
        )

    assert response.status_code == 404
    assert _detail(response) == {"code": "PROJECT_NOT_FOUND"}


@pytest.mark.parametrize("suffix", ["/copy", "/validate"])
def test_a_lifecycle_write_on_a_stale_lock_version_is_refused(suffix: str) -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)

        response = client.post(
            fixture.url(suffix), json={"expected_lock_version": 7}, headers=headers
        )

    assert response.status_code == 409
    assert _detail(response)["code"] == "REVISION_LOCK_CONFLICT"
    assert _detail(response)["current_lock_version"] == 0


# --------------------------------------------------------------------------------------
# What the frozen document must carry, and must not invent (#334 review: H1, H2, M2, M3)
# --------------------------------------------------------------------------------------


def _imputation_code(fixture: Fixture, node_id: int, code: str) -> int:
    """Give ``node_id``'s cost facet an imputation code of the project, and return its id.

    Hung under the root `POST /projects` creates automatically (#62): a project has
    exactly one root code (`uq_wf_project_cost_code_single_root`), so a second one
    would be refused by the database before this test reached its point.
    """
    with get_session_factory()() as session:
        root_id = (
            session.query(ProjectCostCode.id)
            .filter(
                ProjectCostCode.project_id == fixture.project_id,
                ProjectCostCode.parent_id.is_(None),
            )
            .scalar()
        )
        cost_code = ProjectCostCode(
            project_id=fixture.project_id,
            parent_id=root_id,
            code=code,
            name="Etudes amont",
        )
        session.add(cost_code)
        session.flush()
        facet = session.query(RevisionCostFacet).filter(RevisionCostFacet.node_id == node_id).one()
        facet.cost_code_id = cost_code.id
        session.commit()
        return cost_code.id


def test_a_frozen_line_copies_the_imputation_code_and_survives_it_being_renamed() -> None:
    """H1: the ventilation by code d'imputation stays readable years later.

    `wf_estimate_line` and `wf_estimate_cost_line`, the two tables this one replaces,
    both carried ``cost_code_id`` -- "a frozen snapshot of the source line's
    ``cost_code_id`` at validation time" (#63) -- and the devis export publishes a
    column off it. The frozen line carried nothing at all, so the only way back to a
    code was a join on `wf_project_cost_code`: a *mutable* tree, which is exactly what
    Règle 2 forbids a frozen document to depend on.

    So the **code** is copied, like the accounting code and the category code beside
    it, and the proof is the renaming below: the document read after it still says
    what was validated, where a join would now answer something else.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        cost_code_id = _imputation_code(fixture, fixture.nodes["study"], "ETU-01")
        assert _validate(client, headers, fixture).status_code == 200

    frozen = [line for line in _frozen_lines(fixture.revision_id) if line.label == "Etude"]
    assert frozen and {line.cost_code for line in frozen} == {"ETU-01"}
    # No id is kept, on this column as on every other: INV-23 leaves a frozen line
    # exactly two references, and both are work items.
    assert "cost_code_id" not in {column.name for column in RevisionFrozenLine.__table__.columns}

    with get_session_factory()() as session:
        renamed = session.get(ProjectCostCode, cost_code_id)
        assert renamed is not None
        renamed.code = "REORG-99"
        session.commit()

    assert {
        line.cost_code for line in _frozen_lines(fixture.revision_id) if line.label == "Etude"
    } == {"ETU-01"}


def test_a_frozen_disbursement_says_not_applicable_rather_than_zero() -> None:
    """M3: ``0.0000`` in the rate column of a line no rate table was read for.

    ``hourly_rate`` documents itself as copied from `wf_cost_rate.hourly_rate`; on a
    disbursement priced ``quantity x unit_cost`` no such row is consulted, so the
    three labour columns say "not applicable" -- which is what nullable columns are
    for -- instead of carrying a filler shaped like a figure.

    And ``nature`` is carried rather than inferred: this one table merges what the
    legacy socle split *by table*, and ``role_name IS NOT NULL`` is a coincidence,
    not the MO/Achat partition.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200

    by_label = {line.label: line for line in _frozen_lines(fixture.revision_id)}
    supply = by_label["Serveur"]
    assert supply.nature == "non_labor"
    assert (supply.hours, supply.hourly_rate, supply.inflation_coefficient) == (None, None, None)
    assert (supply.quantity, supply.amount) == (Decimal("2.00"), Decimal("2400.00"))
    # The labour line is the counter-example, and keeps all three.
    labour = by_label["Etude"]
    assert labour.nature == "labor"
    assert labour.hourly_rate is not None and labour.inflation_coefficient is not None


def test_the_frozen_hours_of_a_chiffrage_add_up_to_the_chiffrage() -> None:
    """M2: ten hours over three years are ten hours, not 9.99.

    ``hours`` is a ``Numeric(14, 2)`` and ``10 / 3`` is not, so a plain division wrote
    ``3.33`` three times and a document froze 9.99 hours for a chiffrage of ten. The
    engine distributes them by largest remainder instead -- the residue to the latest
    year -- so the rows of one facet total exactly what the facet carries.

    The amounts are **not** recomputed from these shares: they are the engine's own
    full-precision products rounded per line (#364, #368), and the line below still
    checks that the two rules coexist.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _span_bearing_task(fixture, start_year=FIRST_YEAR, finish_year=FIRST_YEAR + 2)
        with get_session_factory()() as session:
            seed_annual_rate(
                session,
                fixture.reference,
                year=FIRST_YEAR + 2,
                hourly_rate=Decimal("120.00"),
                inflation=Decimal("1.10000000"),
            )
            session.commit()
        aggregates = _body(client.get(fixture.url("/aggregates"), headers=headers))
        assert _validate(client, headers, fixture).status_code == 200

    labour = sorted(
        (line for line in _frozen_lines(fixture.revision_id) if line.label == "Etude"),
        key=lambda line: line.year or 0,
    )
    assert [line.hours for line in labour] == [
        Decimal("3.33"),
        Decimal("3.33"),
        Decimal("3.34"),
    ]
    assert sum((line.hours or Decimal("0") for line in labour), Decimal("0")) == Decimal("10.00")
    # And the amounts still add up to the published total, which is the other half.
    total = sum((line.amount for line in _frozen_lines(fixture.revision_id)), Decimal("0"))
    assert total == Decimal(cast(str, aggregates["total_unburdened_cost"]))


def _undate_bearing_task(fixture: Fixture) -> None:
    with get_session_factory()() as session:
        facet = (
            session.query(RevisionPlanFacet)
            .filter(RevisionPlanFacet.node_id == fixture.nodes["alpha"])
            .one()
        )
        facet.start_at = None
        facet.finish_at = None
        session.commit()


def test_a_chiffrage_the_engine_can_price_in_no_year_refuses_the_validation() -> None:
    """H2: the sibling of the rate-coverage refusal, on the gap it could not see.

    A labour facet borne by a task with **no dates** has no year to spread its hours
    over, so the engine produces no priced line for it at all -- and therefore no
    ``(cost category, year)`` pair, which is the matter ``missing_cost_rates`` is made
    of. The rate table here is complete: the previous refusal cannot fire. The
    document was freezing ``0.00`` for a chiffrage of a thousand euros, with
    ``missing_cost_rates: []`` beside it and ``frozen_line_count`` counting it like
    any other line.

    Same decision as its sibling, and the same asymmetry: the read answers 200 and
    *names* the facet, because the remedy is to date ``Alpha`` and a user cannot date
    what an unreadable screen will not show.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        _undate_bearing_task(fixture)
        aggregates = client.get(fixture.url("/aggregates"), headers=headers)
        refused = _validate(client, headers, fixture)

    assert aggregates.status_code == 200
    body = _body(aggregates)
    # The rate table covers everything: this is not the other refusal in disguise.
    assert body["missing_cost_rates"] == [] and body["missing_inflation_years"] == []
    assert [facet["label"] for facet in body["unpriceable_facets"]] == ["Etude"]
    unpriceable = cast(list[dict[str, Any]], body["unpriceable_facets"])[0]
    assert unpriceable["reason"] == "bearing_task_undated"
    assert unpriceable["bearing_task_name"] == "Alpha"
    assert Decimal(cast(str, unpriceable["hours"])) == Decimal("10")

    assert refused.status_code == 409
    assert _detail(refused) == {"code": "REVISION_UNPRICEABLE_FACET"}
    assert _frozen_lines(fixture.revision_id) == []
    with get_session_factory()() as session:
        revision = session.get(ProjectRevision, fixture.revision_id)
        assert revision is not None
        assert (revision.status, revision.lock_version) == ("draft", 0)


def test_a_priceable_revision_reports_no_unpriceable_facet() -> None:
    """The other half of H2: the new list is empty when there is nothing to say.

    A refusal that fired on a perfectly schedulable revision would be worse than the
    silence it replaces, so the fixture that validates everywhere else in this module
    is asserted to report nothing here.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        aggregates = client.get(fixture.url("/aggregates"), headers=headers)
        validated = _validate(client, headers, fixture)

    assert _body(aggregates)["unpriceable_facets"] == []
    assert validated.status_code == 200


# --------------------------------------------------------------------------------------
# The pointers and the copy, on the details the review named (B1, B2, B4, B5, B6)
# --------------------------------------------------------------------------------------


def test_validating_stops_the_project_displaying_the_revision() -> None:
    """B1: ``displayed_revision_id`` names the draft being worked on, and there is none.

    Copying points the project at the new draft; validating that draft makes every
    write on it answer ``REVISION_IMMUTABLE``, so it is no longer "the revision being
    worked on" in any sense the column's own documentation allows. ``NULL`` already
    means "show the reference", which is the honest answer.

    The reference pointer is not touched by a validation: only entering ``en_cours``
    fixes that one, and the assertion below is what keeps the two from being confused.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        copy = _body(_copy(client, headers, fixture, expected_lock_version=1))
        assert _reference_pointer(fixture.project_id) is not None
        displayed_before = _reference_pointer(fixture.project_id)
        assert displayed_before is not None
        assert displayed_before.displayed_revision_id == copy["revision_id"]

        assert (
            _validate(client, headers, fixture, revision_id=copy["revision_id"]).status_code == 200
        )

    pointer = _reference_pointer(fixture.project_id)
    assert pointer is not None
    assert pointer.displayed_revision_id is None
    assert pointer.reference_revision_id is None


def test_validating_another_revision_leaves_the_displayed_one_alone() -> None:
    """B1, scoped: validating revision N does not blank a pointer aimed at revision M."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        copy = _body(_copy(client, headers, fixture, expected_lock_version=0))
        # The copy is what is on screen; the *source* is the one being validated.
        assert _validate(client, headers, fixture).status_code == 200

    pointer = _reference_pointer(fixture.project_id)
    assert pointer is not None
    assert pointer.displayed_revision_id == copy["revision_id"]


def test_moving_a_pointer_moves_its_updated_at() -> None:
    """B2: ``updated_at`` is the column's business, not each write site's.

    It was maintained by hand in one branch of one helper, so every other way of
    moving a pointer left a row claiming it had not changed since it was created.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        copy = _body(_copy(client, headers, fixture, expected_lock_version=1))
        created = _reference_pointer(fixture.project_id)
        assert created is not None
        first_write = created.updated_at

        for target in ("initialise", "en_reponse_appel_offre", "en_cours"):
            assert (
                client.patch(
                    f"/projects/{fixture.project_id}/status",
                    json={"status": target},
                    headers=headers,
                ).status_code
                == 200
            )

    moved = _reference_pointer(fixture.project_id)
    assert moved is not None
    assert moved.reference_revision_id == fixture.revision_id
    assert moved.displayed_revision_id == copy["revision_id"]
    assert moved.updated_at > first_write


def test_the_reference_kinds_are_the_domain_enumeration_and_not_two_strings() -> None:
    """B4: one vocabulary for `ck_wf_revision_kind` and for ``domain.RevisionKind``.

    Spelled as literals, a rename of the enumeration would leave this tuple matching
    no row at all, silently and with every test still green.
    """
    assert set(REFERENCE_REVISION_KINDS) <= set(domain.RevisionKind)
    assert domain.RevisionKind.FORECAST_REMAINING not in REFERENCE_REVISION_KINDS
    assert REFERENCE_REVISION_KINDS[0] is domain.RevisionKind.CONTRACT_REFERENCE


def test_entering_en_cours_asks_which_revision_to_reference_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B5: the check and the write read the same answer instead of asking twice.

    The transition validated "is there something to reference?" and then the entry
    asked the database the very same question again -- two queries, and therefore two
    possible answers, for one decision.
    """
    calls: list[int] = []
    real = project_lifecycle.reference_revision_candidate

    def counting(db: Session, project_id: int) -> ProjectRevision | None:
        calls.append(project_id)
        return real(db, project_id)

    monkeypatch.setattr(project_lifecycle, "reference_revision_candidate", counting)

    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        for target in ("initialise", "en_reponse_appel_offre"):
            assert (
                client.patch(
                    f"/projects/{fixture.project_id}/status",
                    json={"status": target},
                    headers=headers,
                ).status_code
                == 200
            )
        calls.clear()
        entered = client.patch(
            f"/projects/{fixture.project_id}/status", json={"status": "en_cours"}, headers=headers
        )

    assert entered.status_code == 200
    assert calls == [fixture.project_id]
    pointer = _reference_pointer(fixture.project_id)
    assert pointer is not None
    assert pointer.reference_revision_id == fixture.revision_id


def test_a_copy_answers_the_kind_it_wrote_and_not_the_one_it_was_asked_for() -> None:
    """B6: the response describes the row, not the request.

    Copying without a ``kind`` inherits the source's, which the route used to read off
    the ORM behind a ``cast`` -- silencing the type checker on a string only a
    ``CheckConstraint`` guarantees -- and then answer with *its own* value rather than
    the one the service persisted. Both halves are asserted here: the kind comes back
    from the created revision, and it is the kind the database holds.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        with get_session_factory()() as session:
            source = session.get(ProjectRevision, fixture.revision_id)
            assert source is not None
            source.kind = "contract_reference"
            session.commit()

        inherited = _body(_copy(client, headers, fixture, expected_lock_version=0))
        chosen = _body(
            _copy(client, headers, fixture, expected_lock_version=0, kind="forecast_remaining")
        )

    assert inherited["kind"] == "contract_reference"
    assert chosen["kind"] == "forecast_remaining"
    with get_session_factory()() as session:
        stored = {
            row.id: row.kind
            for row in session.query(ProjectRevision).filter(
                ProjectRevision.project_id == fixture.project_id
            )
        }
    assert stored[inherited["revision_id"]] == inherited["kind"]
    assert stored[chosen["revision_id"]] == chosen["kind"]


# --------------------------------------------------------------------------------------
# Listing the revisions of a project (E14-10, #336)
# --------------------------------------------------------------------------------------


def test_listing_revisions_answers_every_version_oldest_first_with_its_pointers() -> None:
    """The read the frontend needs before it can open anything.

    Until it existed, a revision id only ever reached a client as the by-product of
    an import: no history, no way to open a validated revision, no way to copy one.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed(client, headers)
        assert _validate(client, headers, fixture).status_code == 200
        copy = _body(_copy(client, headers, fixture, expected_lock_version=1))

        response = client.get(f"/projects/{fixture.project_id}/revisions", headers=headers)

    assert response.status_code == 200
    body = _body(response)
    items = cast(list[dict[str, Any]], body["items"])
    assert [item["revision_id"] for item in items] == [fixture.revision_id, copy["revision_id"]]
    assert [item["version_number"] for item in items] == [1, 2]
    assert [item["status"] for item in items] == ["validated", "draft"]
    # The counter travels with the summary: `POST .../copy` quotes the *source*'s,
    # so a draft opens from a validated revision without downloading its tree first.
    with get_session_factory()() as session:
        source = session.get(ProjectRevision, fixture.revision_id)
        assert source is not None
        assert items[0]["lock_version"] == source.lock_version
    assert items[0]["validated_at"] is not None
    assert items[1]["validated_at"] is None
    # Copying points the project at the draft being worked on; the reference is only
    # fixed by entering `en_cours`, which this project never did.
    assert body["displayed_revision_id"] == copy["revision_id"]
    assert body["reference_revision_id"] is None


def test_listing_revisions_of_a_project_without_any_answers_an_empty_list() -> None:
    """A project created from the lotissement holds no revision yet, and says so.

    Answering 404 here would make "no version yet" indistinguishable from "no such
    project", which is the one thing the planning screen has to tell apart before it
    can offer to import a file rather than report an error.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        created = client.post("/projects", json={"name": "Sans revision"}, headers=headers)
        assert created.status_code == 201
        project_id = cast(int, created.json()["id"])

        response = client.get(f"/projects/{project_id}/revisions", headers=headers)

    assert response.status_code == 200
    assert _body(response) == {
        "items": [],
        "reference_revision_id": None,
        "displayed_revision_id": None,
    }


def test_listing_the_revisions_of_somebody_elses_project_is_not_found() -> None:
    with TestClient(app) as client:
        owner = _auth_headers(client)
        fixture = _seed(client, owner)
        intruder = _auth_headers(client)

        response = client.get(f"/projects/{fixture.project_id}/revisions", headers=intruder)

    assert response.status_code == 404
    assert _detail(response) == {"code": "PROJECT_NOT_FOUND"}
