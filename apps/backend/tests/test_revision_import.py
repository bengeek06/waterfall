"""MS Project import onto the revision model (E14-06, issue #332).

Every acceptance criterion of the issue is pinned here, the two that carry the
value of the EPIC first: a re-import that drops a task removes it from a **draft**
even when the project carries a devis (resolves #325), and the diff names the
chiffrage that removal takes away (Règle 3's safeguard) instead of letting it go
silently.

The batch flow is driven through the real HTTP API, because "no 409" is a
statement about the endpoint and not about a service call.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from _calendar_support import ensure_default_calendar
from _revision_db_support import ReferenceData, insert_labor_line, insert_purchase_line
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
)
from waterfall.models.revision import ProjectRevision, RevisionNode, RevisionPlanFacet, WorkItem
from waterfall.services import revision_import
from waterfall.services.msproject_xml import parse_msproject_xml, validate_canonical_export_xml

COBRA_XML = Path(__file__).resolve().parents[3] / "examples" / "planning_cobra.xml"
#: Tasks of ``planning_cobra.xml`` minus MS Project's project summary task (UID 0),
#: which the parser drops: it is not a schedulable task.
COBRA_TASK_COUNT = 542


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"revision.import.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    ensure_default_calendar()
    response = client.post("/projects", json={"name": "Revision import"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _reference(project_id: int) -> ReferenceData:
    """A role and its cost category, hung off the calendar the project already uses."""
    calendar_id = ensure_default_calendar()
    key = uuid4().hex[:8]
    with get_session_factory()() as session:
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
            calendar_id=calendar_id,
            name="Developpeur",
        )
        session.add(role)
        session.commit()
        return ReferenceData(
            project_id=project_id,
            calendar_id=calendar_id,
            role_id=role.id,
            cost_type_id=cost_type.id,
            cost_category_id=category.id,
        )


def _tasks_xml(*uids: int) -> bytes:
    tasks = "".join(
        f"<Task><UID>{uid}</UID><ID>{uid}</ID><Name>T{uid}</Name>"
        f"<OutlineNumber>{uid}</OutlineNumber><OutlineLevel>1</OutlineLevel></Task>"
        for uid in uids
    )
    return _project_xml(tasks)


def _outlined_tasks_xml(*tasks: tuple[int, str]) -> bytes:
    """``(uid, dotted outline number)`` pairs, so a test can build a *nested* file."""
    body = "".join(
        f"<Task><UID>{uid}</UID><ID>{uid}</ID><Name>T{uid}</Name>"
        f"<OutlineNumber>{outline}</OutlineNumber>"
        f"<OutlineLevel>{outline.count('.') + 1}</OutlineLevel></Task>"
        for uid, outline in tasks
    )
    return _project_xml(body)


def _project_xml(tasks: str) -> bytes:
    return (
        '<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion>'
        "<ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate>"
        f"<Tasks>{tasks}</Tasks></Project>"
    ).encode()


def _upload(client: TestClient, headers: dict[str, str], project_id: int, xml: bytes) -> int:
    create = client.post(
        "/imports/v1/batches",
        json={"projectId": project_id, "importMode": "standard"},
        headers=headers,
    )
    assert create.status_code == 201
    batch_id = cast(int, create.json()["id"])
    upload = client.post(
        f"/imports/v1/batches/{batch_id}/xml",
        files={"file": ("import.xml", xml, "application/xml")},
        headers=headers,
    )
    assert upload.status_code == 202
    return batch_id


def _run(client: TestClient, headers: dict[str, str], batch_id: int) -> Response:
    return client.post(
        f"/imports/v1/batches/{batch_id}/run",
        json={"dryRun": False, "confirm": True},
        headers=headers,
    )


def _import(client: TestClient, headers: dict[str, str], project_id: int, xml: bytes) -> Response:
    return _run(client, headers, _upload(client, headers, project_id, xml))


def _revision_id(project_id: int) -> int:
    """Id of the revision an import targets: the latest by version number.

    ``.first()`` and not ``.scalar()``: a project may legitimately hold several
    revisions at once, and ``scalar()`` raises on more than one row.
    """
    with get_session_factory()() as session:
        row = (
            session.query(ProjectRevision.id)
            .filter(ProjectRevision.project_id == project_id)
            .order_by(ProjectRevision.version_number.desc(), ProjectRevision.id.desc())
            .first()
        )
        assert row is not None
        return cast(int, row[0])


def _lock_version(revision_id: int) -> int:
    with get_session_factory()() as session:
        return (
            session.query(ProjectRevision.lock_version)
            .filter(ProjectRevision.id == revision_id)
            .scalar()
        )


def _external_uids(project_id: int) -> dict[int, str]:
    """``external_uid -> planning facet name`` of every planning node of the revision."""
    with get_session_factory()() as session:
        rows = (
            session.query(WorkItem.external_uid, RevisionPlanFacet.name)
            .join(RevisionNode, RevisionNode.work_item_id == WorkItem.id)
            .join(RevisionPlanFacet, RevisionPlanFacet.node_id == RevisionNode.id)
            .join(ProjectRevision, ProjectRevision.id == RevisionNode.revision_id)
            .filter(ProjectRevision.project_id == project_id)
            .all()
        )
    return {uid: name for uid, name in rows if uid is not None}


def _planning_nodes(project_id: int) -> list[tuple[int | None, str, int, int]]:
    """``(external_uid, name, node_id, work_item_id)`` of every planning node."""
    with get_session_factory()() as session:
        rows = (
            session.query(
                WorkItem.external_uid,
                RevisionPlanFacet.name,
                RevisionNode.id,
                WorkItem.id,
            )
            .join(RevisionNode, RevisionNode.work_item_id == WorkItem.id)
            .join(RevisionPlanFacet, RevisionPlanFacet.node_id == RevisionNode.id)
            .join(ProjectRevision, ProjectRevision.id == RevisionNode.revision_id)
            .filter(ProjectRevision.project_id == project_id)
            .order_by(RevisionNode.id)
            .all()
        )
    return [(uid, name, node_id, item_id) for uid, name, node_id, item_id in rows]


def _work_items(project_id: int) -> dict[int, int | None]:
    """``work_item id -> external_uid`` for the whole project, nodes or no nodes."""
    with get_session_factory()() as session:
        rows = (
            session.query(WorkItem.id, WorkItem.external_uid)
            .filter(WorkItem.project_id == project_id)
            .all()
        )
    return {item_id: uid for item_id, uid in rows}  # noqa: C416


@contextmanager
def _captured_records(caplog: pytest.LogCaptureFixture, name: str) -> Generator[None]:
    """Capture WARNING-and-above records of one logger while the ASGI app is running.

    ``caplog`` alone does not see them: its handler is installed on the *root*
    logger, and ``waterfall.core.logging.configure_logging`` -- which the app runs on
    startup, i.e. after the fixture -- replaces ``root.handlers`` wholesale through
    ``dictConfig``. Hanging the same handler off the emitting logger side-steps that
    without touching the application's own configuration.
    """
    logger = logging.getLogger(name)
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=name):
            yield
    finally:
        logger.removeHandler(caplog.handler)


def _displayed_planning_id(project_id: int) -> int:
    """Id of the legacy planning the project currently displays.

    Read from the table rather than from ``GET /projects/{id}``: the diff preview
    reads the very same column, so the fixture and the code under test agree by
    construction.
    """
    with get_session_factory()() as session:
        planning_id = (
            session.query(MsProject.displayed_planning_id)
            .filter(MsProject.id == project_id)
            .scalar()
        )
    assert planning_id is not None
    return cast(int, planning_id)


def _exported_uids(document: bytes) -> set[int]:
    namespace = {"ms": "http://schemas.microsoft.com/project/2007"}
    return {
        int(cast(str, node.findtext("ms:UID", namespaces=namespace)))
        for node in ET.fromstring(document).findall("ms:Tasks/ms:Task", namespace)
    }


# --------------------------------------------------------------------------------------
# 1. A file becomes a revision
# --------------------------------------------------------------------------------------


def test_importing_planning_cobra_creates_one_node_per_task_keyed_by_external_uid() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        assert _import(client, headers, project_id, COBRA_XML.read_bytes()).status_code == 202

        parsed = parse_msproject_xml(COBRA_XML.read_bytes())
        assert len(parsed.tasks) == COBRA_TASK_COUNT
        revision_id = _revision_id(project_id)
        with get_session_factory()() as session:
            facets = (
                session.query(RevisionPlanFacet)
                .join(RevisionNode, RevisionNode.id == RevisionPlanFacet.node_id)
                .filter(RevisionNode.revision_id == revision_id)
                .count()
            )
            assert facets == COBRA_TASK_COUNT
            # Every node designates a work item carrying the file's own uid, and the
            # calendar is a stored attribute initialised to the project's (Règle 1),
            # never derived on read.
            assert all(
                facet.calendar_id is not None and facet.calendar_source == "project"
                for facet in session.query(RevisionPlanFacet).all()
            )
        assert set(_external_uids(project_id)) == {task.uid for task in parsed.tasks}


def test_the_import_still_writes_the_legacy_tables_in_the_same_transaction() -> None:
    """Deliberate double write until #333 migrates the devis stack off ``ms_task``.

    Dropping the legacy write now would make every newly imported project
    unchiffrable -- #313 reintroduced backwards -- so both are written, and this
    test is what would catch a premature removal.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        with get_session_factory()() as session:
            assert session.query(MsTask).filter(MsTask.project_id == project_id).count() == 2
        assert set(_external_uids(project_id)) == {1, 2}


# --------------------------------------------------------------------------------------
# 2. A re-import removes a task even when the project is priced -- resolves #325
# --------------------------------------------------------------------------------------


def test_reimport_removes_a_task_of_a_project_that_already_carries_an_estimate() -> None:
    """The test this issue exists for: no 409, whatever the devis references.

    Until #332 this very sequence answered 409 ``IMPORT_CONFLICT``: creating a
    devis fills ``EstimateTaskRow.task_id`` for every task, which
    ``is_task_referenced`` read as "cannot be removed". A re-import targets a
    draft, where the user is entitled to remove anything (EPIC #326).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        estimate = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert estimate.status_code == 201
        rows = client.get(
            f"/projects/{project_id}/estimates/{estimate.json()['id']}/task-rows", headers=headers
        )
        assert rows.status_code == 200
        assert {row["task_uid"] for row in rows.json()["items"]} == {1, 2}

        rerun = _import(client, headers, project_id, _tasks_xml(1))

        assert rerun.status_code == 202, rerun.text
        assert rerun.json()["status"] == "success"
        assert set(_external_uids(project_id)) == {1}


# --------------------------------------------------------------------------------------
# 3. An unchanged file changes nothing at all
# --------------------------------------------------------------------------------------


def test_reimporting_an_unchanged_file_leaves_the_revision_and_its_lock_version_alone() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        xml = _tasks_xml(1, 2, 3)
        assert _import(client, headers, project_id, xml).status_code == 202

        revision_id = _revision_id(project_id)
        before_lock = _lock_version(revision_id)
        with get_session_factory()() as session:
            before_nodes = {
                (node.id, node.parent_id, node.position)
                for node in session.query(RevisionNode)
                .filter(RevisionNode.revision_id == revision_id)
                .all()
            }

        assert _import(client, headers, project_id, xml).status_code == 202

        assert _lock_version(revision_id) == before_lock
        with get_session_factory()() as session:
            after_nodes = {
                (node.id, node.parent_id, node.position)
                for node in session.query(RevisionNode)
                .filter(RevisionNode.revision_id == revision_id)
                .all()
            }
        assert after_nodes == before_nodes


# --------------------------------------------------------------------------------------
# 4. Export, re-import, same external uids
# --------------------------------------------------------------------------------------


def test_exporting_a_revision_from_another_project_is_not_served() -> None:
    """The revision export is scoped to the project named in the path, like #331's."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        other_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1)).status_code == 202
        revision_id = _revision_id(project_id)

        response = client.get(
            f"/projects/{other_id}/export.xml?revision_id={revision_id}", headers=headers
        )

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "REVISION_NOT_FOUND"


def test_exporting_with_both_selectors_is_refused_rather_than_dropping_one() -> None:
    """#332 review, B3: the contract said "exclusive", the handler ignored planning_id.

    A caller that sends both got a 200 and the revision, with no hint that the
    planning it named was never consulted -- the kind of silence that convinces a
    client it exported something it did not.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1)).status_code == 202
        revision_id = _revision_id(project_id)

        response = client.get(
            f"/projects/{project_id}/export.xml?planning_id=1&revision_id={revision_id}",
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == {"code": "EXPORT_SELECTION_AMBIGUOUS"}


def test_exporting_a_revision_without_a_default_calendar_is_a_conflict_not_a_crash() -> None:
    """#332 review, round 3: the export was the one revision route left unwrapped.

    ``build_revision_export_xml`` loads the revision, which loads the project, which
    asks ``ensure_project_calendar`` -- and that raises ``MissingProjectCalendarError``
    when no active calendar is flagged as the organisation default (Règle 1/INV-15).
    With no ``revision_operation`` around the call it escaped untranslated as a 500,
    while the import path this very diff wrapped answers 409
    ``PROJECT_CALENDAR_MISSING`` on the same state, and so does every route of #331.
    The condition is an operator-repairable configuration, not an incident.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1)).status_code == 202
        revision_id = _revision_id(project_id)
        assert (
            client.get(
                f"/projects/{project_id}/export.xml?revision_id={revision_id}", headers=headers
            ).status_code
            == 200
        )

        with get_session_factory()() as session:
            calendar = session.query(Calendar).filter(Calendar.is_default.is_(True)).one()
            calendar.is_default = False
            session.commit()

        response = client.get(
            f"/projects/{project_id}/export.xml?revision_id={revision_id}", headers=headers
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {"code": "PROJECT_CALENDAR_MISSING"}


def test_exporting_a_revision_and_reimporting_it_restores_the_same_external_uids() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, COBRA_XML.read_bytes()).status_code == 202
        original = _external_uids(project_id)

        revision_id = _revision_id(project_id)
        export = client.get(
            f"/projects/{project_id}/export.xml?revision_id={revision_id}", headers=headers
        )
        assert export.status_code == 200, export.text
        exported = cast(bytes, export.content)
        # The route validates before serving; asserting it again here states what
        # the round trip relies on -- a document MS Project would actually accept.
        validate_canonical_export_xml(exported)

        namespace = {"ms": "http://schemas.microsoft.com/project/2007"}
        exported_uids = {
            int(cast(str, node.findtext("ms:UID", namespaces=namespace)))
            for node in ET.fromstring(exported).findall("ms:Tasks/ms:Task", namespace)
        }
        assert exported_uids == set(original)

        assert _import(client, headers, project_id, exported).status_code == 202
        assert _external_uids(project_id) == original


# --------------------------------------------------------------------------------------
# 5. A validated revision refuses the import
# --------------------------------------------------------------------------------------


def test_importing_into_a_validated_revision_is_refused_as_immutable() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202
        revision_id = _revision_id(project_id)
        with get_session_factory()() as session:
            revision = (
                session.query(ProjectRevision).filter(ProjectRevision.id == revision_id).one()
            )
            revision.status = "validated"
            session.commit()

        batch_id = _upload(client, headers, project_id, _tasks_xml(1))
        refused = _run(client, headers, batch_id)

        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "REVISION_IMMUTABLE"
        # The batch stays reusable: the refusal is decided before it is marked running.
        status_response = client.get(f"/imports/v1/batches/{batch_id}", headers=headers)
        assert status_response.json()["status"] == "pending"
        assert set(_external_uids(project_id)) == {1, 2}


# --------------------------------------------------------------------------------------
# 6. Règle 3's safeguard: the diff names the chiffrage a removal destroys
# --------------------------------------------------------------------------------------


def test_the_import_diff_names_every_cost_bearing_node_a_removal_would_destroy() -> None:
    """Both natures, and the amount asserted against a figure the test did not read back.

    The #332 review (B6) was right that the previous version copied the served
    ``amount`` into its own expectation, so any value at all passed -- and the MO
    fixture served ``0`` anyway, the store deliberately leaving ``Role.hourly_rate``
    unset until E14-07 plugs the real pricing engine in. A non-labour line is priced
    from ``quantity x unit_cost``, both stored on the facet, so it is the one shape
    whose money is real end to end today; it is seeded here and pinned to a literal.
    The MO line stays, pinned to ``0`` *with* the reason, so that E14-07 landing the
    resolver breaks this test instead of quietly changing a confirmation dialog.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        reference = _reference(project_id)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        revision_id = _revision_id(project_id)
        with get_session_factory()() as session:
            revision = (
                session.query(ProjectRevision).filter(ProjectRevision.id == revision_id).one()
            )
            doomed = (
                session.query(RevisionNode)
                .join(WorkItem, WorkItem.id == RevisionNode.work_item_id)
                .filter(RevisionNode.revision_id == revision_id, WorkItem.external_uid == 2)
                .one()
            )
            insert_labor_line(
                session,
                reference,
                revision,
                label="Etude",
                parent_id=doomed.id,
                hours=Decimal("12"),
            )
            insert_purchase_line(
                session,
                reference,
                revision,
                label="Cables",
                parent_id=doomed.id,
                position=2,
                quantity=Decimal("2"),
                unit_cost=Decimal("150"),
            )
            session.commit()

        batch_id = _upload(client, headers, project_id, _tasks_xml(1))
        diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)

        assert diff.status_code == 200
        removed = [item for item in diff.json()["items"] if item["kind"] == "removed"]
        assert [item["uid"] for item in removed] == [2]
        losses = cast(list[dict[str, object]], removed[0]["costLosses"])
        assert [(loss["label"], loss["nature"], loss["bearingTaskName"]) for loss in losses] == [
            ("Etude", "labor", "T2"),
            ("Cables", "non_labor", "T2"),
        ]
        # 2 x 150, read off the facet and not off the response.
        assert Decimal(cast(str, losses[1]["amount"])) == Decimal("300")
        # 0 until E14-07 injects the real amount resolver: ``default_amount`` prices
        # MO as ``quantity x hours x hourly_rate`` and the store leaves the rate
        # unset on purpose, a rate being per year and belonging to the engine.
        assert Decimal(cast(str, losses[0]["amount"])) == Decimal("0")

        # And confirming really does take it away, exactly as announced.
        assert _run(client, headers, batch_id).status_code == 202
        with get_session_factory()() as session:
            assert (
                session.query(RevisionNode).filter(RevisionNode.revision_id == revision_id).count()
                == 1
            )


def test_a_removal_that_costs_nothing_carries_an_empty_loss_list() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        batch_id = _upload(client, headers, project_id, _tasks_xml(1))
        diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)

        assert diff.status_code == 200
        removed = [item for item in diff.json()["items"] if item["kind"] == "removed"]
        assert [(item["uid"], item["costLosses"]) for item in removed] == [(2, [])]


def test_a_loss_the_displayed_planning_cannot_attribute_is_degraded_not_five_hundred(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#332 review, round 3: the join between revision and snapshot *is* breakable.

    The sequence below uses public endpoints only, every one of them answering
    200/202, and leaves the diff preview computing losses for an external uid the
    displayed planning has never heard of:

    1. import ``(1, 2)``   -- planning v1 displayed, revision ``{1, 2}``;
    2. validate planning v1;
    3. import ``(1, 2, 3)`` -- planning **v2** created and displayed, revision
       ``{1, 2, 3}``;
    4. a cost facet under the node of uid 3;
    5. ``POST .../plannings/{v1}/display`` -- back to v1, which never knew uid 3;
    6. ``GET .../diff`` for a file that drops uid 3.

    Step 5 is what the first analysis missed: ``set_displayed_planning`` accepts
    *any* planning of the project, older uid set included. The condition used to
    raise a ``RuntimeError`` and answer 500, which destroys strictly more than it
    protects -- ``costLosses``, the one summable figure, never passes through this
    join and would have survived. So the preview degrades instead: the total stands,
    the orphaned loss is attributed to a synthesised ``removed`` item, and the
    developer gets a WARNING naming the uids.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        reference = _reference(project_id)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202
        first_planning_id = _displayed_planning_id(project_id)

        validated = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/validate", headers=headers
        )
        assert validated.status_code == 200, validated.text

        assert _import(client, headers, project_id, _tasks_xml(1, 2, 3)).status_code == 202
        second_planning_id = _displayed_planning_id(project_id)
        assert second_planning_id != first_planning_id

        revision_id = _revision_id(project_id)
        with get_session_factory()() as session:
            revision = (
                session.query(ProjectRevision).filter(ProjectRevision.id == revision_id).one()
            )
            doomed = (
                session.query(RevisionNode)
                .join(WorkItem, WorkItem.id == RevisionNode.work_item_id)
                .filter(RevisionNode.revision_id == revision_id, WorkItem.external_uid == 3)
                .one()
            )
            insert_purchase_line(
                session,
                reference,
                revision,
                label="Cables",
                parent_id=doomed.id,
                quantity=Decimal("2"),
                unit_cost=Decimal("150"),
            )
            session.commit()

        displayed = client.post(
            f"/projects/{project_id}/plannings/{first_planning_id}/display", headers=headers
        )
        assert displayed.status_code == 200, displayed.text

        batch_id = _upload(client, headers, project_id, _tasks_xml(1, 2))
        with _captured_records(caplog, "waterfall.services.import_diff"):
            diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)

        assert diff.status_code == 200, diff.text
        payload = cast(dict[str, object], diff.json())
        total = cast(list[dict[str, object]], payload["costLosses"])
        assert [cast(str, loss["label"]) for loss in total] == ["Cables"]
        assert Decimal(cast(str, total[0]["amount"])) == Decimal("300")

        items = cast(list[dict[str, object]], payload["items"])
        removed = [item for item in items if item["kind"] == "removed"]
        # The displayed planning reports no removal at all -- it never carried uid 3
        # -- so the only ``removed`` item is the synthesised one the loss hangs on.
        assert [cast(int, item["uid"]) for item in removed] == [3]
        attributed = cast(list[dict[str, object]], removed[0]["costLosses"])
        assert [cast(str, loss["label"]) for loss in attributed] == ["Cables"]

        # WARNING, not ERROR (#332 review, B-2): this very scenario is built out of
        # endpoints that all answer 200/202, so an ERROR here would have alerting fire
        # on a supported display choice.
        assert any(
            record.levelno == logging.WARNING and "[3]" in record.getMessage()
            for record in caplog.records
        ), [record.getMessage() for record in caplog.records]
        assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


# --------------------------------------------------------------------------------------
# A file listing the same uid twice is refused (#345)
# --------------------------------------------------------------------------------------


def test_a_file_listing_the_same_external_uid_twice_is_refused_by_the_domain() -> None:
    """#345: the one malformed shape the domain used to swallow.

    Indexing the file by ``external_uid`` silently kept the last occurrence, so a
    task simply vanished from the imported tree -- the "silent removal" Règle 3's
    safeguard exists to make impossible. The MSPDI parser catches the duplicate
    first on the HTTP path (``DUPLICATE_UID``), which is why this is pinned on the
    domain: a caller that does not come through the parser gets the same refusal.
    """
    project = domain.Project(id=1, calendar_id=1)
    revision = domain.create_revision(project)
    tasks = [
        domain.ImportedTask(external_uid=1, name="First"),
        domain.ImportedTask(external_uid=1, name="Again"),
    ]

    try:
        domain.plan_reimport(project, revision, tasks)
    except domain.ImportStructureError as exc:
        assert "listed twice" in str(exc)
        assert "1" in str(exc)
    else:  # pragma: no cover - the assertion below reports the miss
        raise AssertionError("a duplicated external uid must be refused")


def test_the_http_import_refuses_a_file_listing_the_same_uid_twice() -> None:
    """What refuses it on the HTTP path is the **parser**, and the test says so.

    The MSPDI parser rejects a duplicated ``<UID>`` before the domain ever sees the
    file, so this endpoint answers ``DUPLICATE_UID`` and would answer it just the
    same if the domain guard of #345 were deleted. Asserting the code rather than a
    bare ``400`` is what makes that visible instead of leaving the test looking
    like a proof of the domain rule -- which is pinned, on its own, by
    ``test_a_file_listing_the_same_external_uid_twice_is_refused_by_the_domain``
    (#332 review, B6).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        batch_id = _upload(client, headers, project_id, _tasks_xml(1, 1))
        refused = _run(client, headers, batch_id)

        assert refused.status_code == 400
        errors = client.get(f"/imports/v1/batches/{batch_id}/errors", headers=headers)
        assert errors.status_code == 200
        assert "DUPLICATE_UID" in {item["code"] for item in errors.json()["items"]}
        assert _external_uids(project_id) == {}


# --------------------------------------------------------------------------------------
# The contract names REVISION_IMPORT_STRUCTURE_INVALID on both import endpoints
# --------------------------------------------------------------------------------------

#: A file whose second task is the *parent* of its first, expressed the only way an
#: MSPDI document can: through dotted outline numbers. ``outline_parent_uids`` reads
#: uid 2 as a child of uid 1, and uid 1 comes after it, which is exactly the shape
#: ``_validate_import_structure`` refuses ("the file lists it only after it"). The
#: MSPDI parser accepts the document -- nothing about it is invalid XML or invalid
#: MSPDI -- so the refusal really does come from the revision domain.
_CHILD_BEFORE_PARENT = ((2, "1.1"), (1, "1"))


def test_running_an_import_whose_child_precedes_its_parent_answers_the_documented_code() -> None:
    """Pins the code the contract promises on ``POST .../run``, body included.

    ``imports.yaml`` names ``REVISION_IMPORT_STRUCTURE_INVALID`` on the 400 of this
    endpoint, and until now nothing held it there: the code is produced by
    ``revision_http_exception`` and survives to the client only because its ``detail``
    is a dict, which stops ``_generic_http_exception_handler`` rewriting it to
    ``GENERIC_ERROR``. Flattening that detail to a string would keep the status at 400
    and break the contract in silence, so the **body** is asserted, not the status
    (#332 review, B-5).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        refused = _import(client, headers, project_id, _outlined_tasks_xml(*_CHILD_BEFORE_PARENT))

        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "REVISION_IMPORT_STRUCTURE_INVALID"
        # Refused before a single node was touched: the revision is untouched, not
        # half-applied.
        assert _external_uids(project_id) == {}


def test_previewing_an_import_whose_child_precedes_its_parent_answers_the_documented_code() -> None:
    """The same code on ``GET .../diff``, which the contract promises separately.

    The preview refuses the whole file rather than rendering a diff with empty
    ``costLosses`` -- see ``get_batch_diff`` -- so a client is told the file is
    unusable instead of being shown a removal that looks free. Asserting the body
    here too: a 400 alone would also be produced by ``IMPORT_VALIDATION_FAILED``,
    which is a different remedy for the user.

    A first import runs beforehand, and it is not scene-setting: the refusal is
    raised against the **target revision**, and ``plan_import`` returns ``None`` for a
    project that has none yet, so the preview of a first-ever import serves a 200 with
    an ordinary "added" diff whatever the file's internal order. This endpoint is
    where that distinction lives; ``POST .../run`` refuses both.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        batch_id = _upload(client, headers, project_id, _outlined_tasks_xml(*_CHILD_BEFORE_PARENT))
        refused = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)

        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "REVISION_IMPORT_STRUCTURE_INVALID"


# --------------------------------------------------------------------------------------
# Règle 3 a/b: identity survives, locally created nodes are invisible to the file
# --------------------------------------------------------------------------------------


def test_a_node_created_in_waterfall_is_never_reported_as_removed_by_a_reimport() -> None:
    """Règle 3 a: a work item with no ``external_uid`` was never in the file."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1)).status_code == 202
        revision_id = _revision_id(project_id)

        created = client.post(
            f"/projects/{project_id}/revisions/{revision_id}/tasks",
            json={"expected_lock_version": _lock_version(revision_id), "name": "Local"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        local_node_id = cast(int, created.json()["node_id"])

        assert _import(client, headers, project_id, _tasks_xml(1)).status_code == 202

        with get_session_factory()() as session:
            assert session.query(RevisionNode).filter(RevisionNode.id == local_node_id).count() == 1


def test_reimporting_the_same_file_into_another_revision_reuses_the_same_work_items() -> None:
    """Règle 3, "Identité de projet, pas de révision": the work item is the link."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202
        with get_session_factory()() as session:
            before = {
                item.external_uid: item.id
                for item in session.query(WorkItem).filter(WorkItem.project_id == project_id).all()
            }

        # A second revision of the same project, copied from the first, then
        # re-imported into: the uids must land on the very same work items.
        first_revision_id = _revision_id(project_id)
        with get_session_factory()() as session:
            source = (
                session.query(ProjectRevision).filter(ProjectRevision.id == first_revision_id).one()
            )
            source.status = "validated"
            session.add(
                ProjectRevision(
                    project_id=project_id,
                    version_number=2,
                    kind="initial",
                    status="draft",
                    currency_code="EUR",
                )
            )
            session.commit()

        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        with get_session_factory()() as session:
            after = {
                item.external_uid: item.id
                for item in session.query(WorkItem).filter(WorkItem.project_id == project_id).all()
            }
        assert after == before


# --------------------------------------------------------------------------------------
# A work item outlives its node, and the export must not hand its uid to somebody else
# --------------------------------------------------------------------------------------


def test_a_local_task_never_exports_the_uid_of_a_work_item_that_outlived_its_node() -> None:
    """#332 review, H1: the export allocated document uids above the *revision*'s.

    A work item outlives the node that carried it -- a re-import deletes nodes and
    facets, never work items -- so an uid the revision no longer shows is still
    taken by the project. Allocating above the revision's uids alone handed a
    locally created task the identity of one of those survivors, and re-importing
    that very document then landed the local task on the stranger's
    ``work_item_id``: the single join key the reconciliation of a forecast against
    its budget has, silently rewritten, with two identically named tasks in the
    tree.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2, 3)).status_code == 202
        # Nodes 2 and 3 go; their work items stay, as they must (Rule 3, identity).
        assert _import(client, headers, project_id, _tasks_xml(1)).status_code == 202
        assert set(_external_uids(project_id)) == {1}
        assert set(_work_items(project_id).values()) == {1, 2, 3}

        revision_id = _revision_id(project_id)
        created = client.post(
            f"/projects/{project_id}/revisions/{revision_id}/tasks",
            json={"expected_lock_version": _lock_version(revision_id), "name": "LOCAL"},
            headers=headers,
        )
        assert created.status_code == 201, created.text

        export = client.get(
            f"/projects/{project_id}/export.xml?revision_id={revision_id}", headers=headers
        )
        assert export.status_code == 200, export.text
        document = cast(bytes, export.content)
        exported = _exported_uids(document)
        # The allocated uid clears every uid the *project* owns, not just the two
        # the revision still shows -- so it is 4, never the freed 2.
        assert exported == {1, 4}

        assert _import(client, headers, project_id, document).status_code == 202

        work_items = _work_items(project_id)
        nodes = _planning_nodes(project_id)
        # The assertion this bug exists for: no node hangs off a work item carrying
        # an uid the document does not list. Work items 2 and 3 outlived their nodes
        # and keep their identity to themselves; before the fix the local task had
        # adopted the one of uid 2.
        stranded = {
            item_id
            for item_id, uid in work_items.items()
            if uid is not None and uid not in exported
        }
        assert stranded, "the fixture must really leave orphaned work items behind"
        assert {item_id for _uid, _name, _node_id, item_id in nodes}.isdisjoint(stranded)

        # What is left is the limit the docstring of ``_document_uids`` claims and,
        # now, really has: the local task is not recognised through the round trip,
        # so uid 4 comes back as a *new* work item beside the uid-less original.
        # Nobody's identity was taken, and #336 is where a local task earns one.
        assert sorted(name for _uid, name, _node_id, _item_id in nodes) == [
            "LOCAL",
            "LOCAL",
            "T1",
        ]
        assert sorted(str(uid) for uid, _name, _node_id, _item_id in nodes) == ["1", "4", "None"]
        assert len({item_id for _uid, _name, _node_id, item_id in nodes}) == len(nodes)

        # And the limit **accumulates** (#332 review, B8): the original still carries
        # no external uid, so a second round trip allocates it yet another one and
        # duplicates it again. One copy per local task per round trip, unbounded --
        # which is what the docstring now says, instead of reading like a one-shot.
        second_export = client.get(
            f"/projects/{project_id}/export.xml?revision_id={revision_id}", headers=headers
        )
        assert second_export.status_code == 200, second_export.text
        second_document = cast(bytes, second_export.content)
        assert _exported_uids(second_document) == {1, 4, 5}
        assert _import(client, headers, project_id, second_document).status_code == 202
        assert sorted(name for _uid, name, _node_id, _item_id in _planning_nodes(project_id)) == [
            "LOCAL",
            "LOCAL",
            "LOCAL",
            "T1",
        ]


# --------------------------------------------------------------------------------------
# No default calendar: refused up front, batch left replayable
# --------------------------------------------------------------------------------------


def test_an_import_without_a_default_calendar_is_refused_and_leaves_the_batch_pending() -> None:
    """#332 review, H2: the refusal is real, and it must not burn the batch.

    Règle 1 gives every planning facet a stored calendar, so on an instance with no
    active ``is_default`` calendar -- a state the product already knows and reports
    as ``no_default_calendar`` -- an import is refused. The refusal used to happen
    *after* the batch was marked running, which failed it for a condition the user
    fixes in one click and then forced a re-upload. It is asked in the pre-flight
    now, so the very same batch replays once a calendar exists.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        # Deliberately no ``ensure_default_calendar()`` here -- that is the fixture.
        project = client.post("/projects", json={"name": "No calendar"}, headers=headers)
        assert project.status_code == 201
        project_id = cast(int, project.json()["id"])
        batch_id = _upload(client, headers, project_id, _tasks_xml(1, 2))

        refused = _run(client, headers, batch_id)

        assert refused.status_code == 409
        assert refused.json()["detail"] == {"code": "PROJECT_CALENDAR_MISSING"}
        status_response = client.get(f"/imports/v1/batches/{batch_id}", headers=headers)
        assert status_response.json()["status"] == "pending"
        # Nothing was written on either side of the double write.
        with get_session_factory()() as session:
            assert session.query(MsTask).filter(MsTask.project_id == project_id).count() == 0
        assert _external_uids(project_id) == {}

        ensure_default_calendar()
        replayed = _run(client, headers, batch_id)

        assert replayed.status_code == 202, replayed.text
        assert set(_external_uids(project_id)) == {1, 2}


def test_a_malformed_file_is_reported_as_malformed_before_the_calendar_refusal() -> None:
    """#332 review, B7: E14-06 had quietly reordered which complaint a user hears.

    ``ensure_importable`` was inserted ahead of the parse result, so a broken MSPDI
    dropped on a project with no default calendar answered 409
    ``PROJECT_CALENDAR_MISSING``. The user flags a calendar, replays, and *only then*
    learns the file never parsed -- two round trips for a fault that was true from
    the first. A file that cannot be read is unusable whatever the target's state, so
    it is judged first again, and its issues are recorded where a client reads them.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        # Same fixture as the test above: no active default calendar anywhere.
        project = client.post("/projects", json={"name": "No calendar"}, headers=headers)
        assert project.status_code == 201
        project_id = cast(int, project.json()["id"])
        batch_id = _upload(client, headers, project_id, b"<Project")

        refused = _run(client, headers, batch_id)

        assert refused.status_code == 400, refused.text
        errors = client.get(f"/imports/v1/batches/{batch_id}/errors", headers=headers)
        assert errors.status_code == 200
        assert [item["code"] for item in errors.json()["items"]] == ["MALFORMED_XML"]
        # And the batch is burned, not left pending: replaying it would parse the
        # same bytes into the same error, which no configuration change can repair.
        assert client.get(f"/imports/v1/batches/{batch_id}", headers=headers).json()["status"] == (
            "failed"
        )


# --------------------------------------------------------------------------------------
# The deduplicated total of the chiffrage at stake (#332 review, M1)
# --------------------------------------------------------------------------------------


def test_the_diff_totals_the_chiffrage_at_stake_without_counting_it_twice() -> None:
    """The per-item lists are attributions, the response-level list is the total.

    A cost node under uid 2, itself a child of uid 1, is destroyed by *both*
    removals when the file drops the pair -- so it is named under each item, because
    each disappearance really does take it away. A frontend summing the item lists
    would show twice the money at risk in a dialog that is about money, which is why
    the deduplicated total is now served alongside them.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        reference = _reference(project_id)
        nested = _outlined_tasks_xml((1, "1"), (2, "1.1"))
        assert _import(client, headers, project_id, nested).status_code == 202

        revision_id = _revision_id(project_id)
        with get_session_factory()() as session:
            revision = (
                session.query(ProjectRevision).filter(ProjectRevision.id == revision_id).one()
            )
            doomed = (
                session.query(RevisionNode)
                .join(WorkItem, WorkItem.id == RevisionNode.work_item_id)
                .filter(RevisionNode.revision_id == revision_id, WorkItem.external_uid == 2)
                .one()
            )
            insert_purchase_line(
                session,
                reference,
                revision,
                label="Cables",
                parent_id=doomed.id,
                quantity=Decimal("2"),
                unit_cost=Decimal("150"),
            )
            session.commit()

        batch_id = _upload(client, headers, project_id, _tasks_xml(3))
        diff = client.get(f"/imports/v1/batches/{batch_id}/diff", headers=headers)

        assert diff.status_code == 200
        payload = cast(dict[str, object], diff.json())
        items = cast(list[dict[str, object]], payload["items"])
        removed = [item for item in items if item["kind"] == "removed"]
        assert sorted(cast(int, item["uid"]) for item in removed) == [1, 2]
        per_item = [
            loss for item in removed for loss in cast(list[dict[str, object]], item["costLosses"])
        ]
        # Named twice across the items -- once per disappearance that destroys it.
        assert [cast(str, loss["label"]) for loss in per_item] == ["Cables", "Cables"]
        assert len({cast(int, loss["nodeId"]) for loss in per_item}) == 1

        total = cast(list[dict[str, object]], payload["costLosses"])
        assert [cast(str, loss["label"]) for loss in total] == ["Cables"]
        assert Decimal(cast(str, total[0]["amount"])) == Decimal("300")


# --------------------------------------------------------------------------------------
# Which revision the file landed in (#332 review, M2)
# --------------------------------------------------------------------------------------


def test_the_run_reports_which_revision_the_file_landed_in() -> None:
    """The import targets the latest revision and the client cannot name one.

    With several drafts open at once -- a supported state, validating one leaves
    the others intact -- a user can feed v2 while v3 exists and land in v3. Nothing
    used to say so: ``RevisionImport.revision_id`` was computed and thrown away, and
    v2's ``lock_version`` does not move either, so not even a later 409 would hint
    at it.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)

        first = _import(client, headers, project_id, _tasks_xml(1, 2))
        assert first.status_code == 202
        created_revision_id = _revision_id(project_id)
        assert first.json()["revisionId"] == created_revision_id
        assert first.json()["revisionCreated"] is True

        again = _import(client, headers, project_id, _tasks_xml(1))
        assert again.json()["revisionId"] == created_revision_id
        assert again.json()["revisionCreated"] is False

        # A dry run writes nothing and therefore targets nothing.
        dry_batch = _upload(client, headers, project_id, _tasks_xml(1))
        dry = client.post(
            f"/imports/v1/batches/{dry_batch}/run", json={"dryRun": True}, headers=headers
        )
        assert dry.status_code == 202
        assert dry.json()["revisionId"] is None
        assert dry.json()["revisionCreated"] is None

        # A second draft, higher version number: that is where the file goes, and
        # the response is the only thing that says so.
        with get_session_factory()() as session:
            session.add(
                ProjectRevision(
                    project_id=project_id,
                    version_number=2,
                    kind="initial",
                    status="draft",
                    currency_code="EUR",
                )
            )
            session.commit()
        newer = _import(client, headers, project_id, _tasks_xml(1))

        assert newer.status_code == 202, newer.text
        assert newer.json()["revisionId"] != created_revision_id
        assert newer.json()["revisionId"] == _revision_id(project_id)
        assert newer.json()["revisionCreated"] is False


# --------------------------------------------------------------------------------------
# The legacy upsert never deletes, and an EstimateCostLine no longer refuses anything
# --------------------------------------------------------------------------------------


def _seed_supply_category() -> int:
    """An active supply ``CostCategory``, the minimum needed to create a cost line."""
    key = uuid4().hex[:8]
    with get_session_factory()() as session:
        cost_type = CostType(code=f"FOURN-{key}", name="Fourniture", kind="supply")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"FO-{key}",
            category_code="ACHAT",
            name="Cables",
        )
        session.add(category)
        session.commit()
        return category.id


def test_a_reimport_drops_a_task_priced_by_a_cost_line_and_leaves_its_ms_task_behind() -> None:
    """Two properties the removal of the old ``IMPORT_CONFLICT`` test took with it.

    ``EstimateCostLine.task_id`` is the strongest reference ``is_task_referenced``
    knew, and until #332 it answered 409 on a re-import that dropped the priced
    task. It does not any more -- a draft is where the user is entitled to remove
    things (#325) -- and that is asserted here on the strongest reference rather
    than on ``EstimateTaskRow`` alone.

    The second property is the one nothing else covers: the legacy upsert **never
    deletes**, so `ms_task` keeps uid 2 while the revision drops it. The two tables
    genuinely disagree about what the planning holds, deliberately, until #333
    migrates the devis stack off `ms_task`. Writing it down is what keeps the
    "same transaction" guarantee from being read as "same content".
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        assert _import(client, headers, project_id, _tasks_xml(1, 2)).status_code == 202

        estimate = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert estimate.status_code == 201
        estimate_id = cast(int, estimate.json()["id"])
        rows = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/task-rows", headers=headers
        )
        assert rows.status_code == 200
        task_id_by_uid = {
            cast(int, row["task_uid"]): cast(int, row["task_id"]) for row in rows.json()["items"]
        }
        cost_line = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "task_id": task_id_by_uid[2],
                "cost_category_id": _seed_supply_category(),
                "label": "Cable",
                "quantity": "2.00",
                "unit_cost": "10.00",
            },
            headers=headers,
        )
        assert cost_line.status_code == 201, cost_line.text

        rerun = _import(client, headers, project_id, _tasks_xml(1))

        assert rerun.status_code == 202, rerun.text
        assert set(_external_uids(project_id)) == {1}
        with get_session_factory()() as session:
            surviving = {
                task.uid for task in session.query(MsTask).filter(MsTask.project_id == project_id)
            }
        assert surviving == {1, 2}


def test_the_service_reports_what_it_did() -> None:
    """The outcome a caller reports on, asserted once at service level."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
    parsed = parse_msproject_xml(_tasks_xml(1, 2))
    with get_session_factory()() as session:
        first = revision_import.apply_import(session, project_id, parsed)
        session.commit()
        assert first.created_revision is True
        assert first.changed is True
        assert (first.task_count, first.link_count) == (2, 0)

        second = revision_import.apply_import(session, project_id, parsed)
        session.commit()
        assert second.created_revision is False
        assert second.changed is False
        assert second.lock_version == first.lock_version

        third = revision_import.apply_import(
            session, project_id, parse_msproject_xml(_tasks_xml(1))
        )
        session.commit()
        assert third.changed is True
        assert [item.external_uid for item in third.diff.removed] == [2]
        assert third.diff.added == ()
