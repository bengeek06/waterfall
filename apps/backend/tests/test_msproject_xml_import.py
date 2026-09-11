from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanning, WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import CostCategory, CostType, ResourceNode, ResourceRole
from waterfall.services.msproject_xml import MsProjectValidationError
from waterfall.services.msproject_xml_import import import_tasks_and_links

EXAMPLE_XML = Path(__file__).resolve().parent / "planning_test.xml"


def _new_project(name: str) -> MsProject:
    return MsProject(
        owner_id=None,
        source_version=2016,
        save_version_out=16,
        name=name,
        schedule_from_start=True,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        finish_date=datetime(2026, 1, 1, tzinfo=UTC),
        minutes_per_day=480,
        minutes_per_week=2400,
        days_per_month=20,
    )


_PROJECT_SUMMARY_TASK = """
<Task><UID>0</UID><ID>0</ID><Name>Project</Name>
  <OutlineNumber>0</OutlineNumber><OutlineLevel>0</OutlineLevel><Summary>1</Summary>
</Task>
"""


def _xml_with_tasks(tasks: str) -> bytes:
    return (
        '<Project xmlns="http://schemas.microsoft.com/project"><SaveVersion>16</SaveVersion>'
        "<ScheduleFromStart>true</ScheduleFromStart><StartDate>2026-01-01T08:00:00</StartDate>"
        f"<MinutesPerDay>480</MinutesPerDay><Tasks>{tasks}</Tasks></Project>"
    ).encode()


def test_import_service_persists_tasks_links_and_notes() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=None,
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Import service target",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            finish_date=datetime(2026, 1, 1, tzinfo=UTC),
            calendar_uid=None,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()

        task_count, link_count, warnings = import_tasks_and_links(
            session,
            EXAMPLE_XML.read_bytes(),
            project,
        )
        session.commit()

        assert task_count == 2
        assert link_count == 1
        assert warnings == ()
        planning = session.query(WfPlanning).filter(WfPlanning.project_id == project.id).one()
        assert planning.status == "draft"
        assert project.displayed_planning_id == planning.id
        # Issue #313: the canonical MsTask twins are written by the same import.
        assert session.query(MsTask).filter(MsTask.project_id == project.id).count() == 2
        assert (
            session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .count()
            == 2
        )
        assert (
            session.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
            .count()
            == 1
        )
        task = (
            session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .filter(WfPlanningTaskSnapshot.uid == 1)
            .one()
        )
        assert task.notes == "description de l'étude"


def test_import_service_replaces_draft_and_preserves_validated_history() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=None,
            source_version=2016,
            save_version_out=16,
            name="Sync target",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            finish_date=datetime(2026, 1, 1, tzinfo=UTC),
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
        )
        session.add(project)
        session.flush()

        source = EXAMPLE_XML.read_bytes()
        import_tasks_and_links(session, source, project)
        first_planning_id = project.displayed_planning_id
        changed = source.replace(b"Etude documentaire", b"Etude documentaire v2")
        import_tasks_and_links(session, changed, project)
        assert project.displayed_planning_id == first_planning_id
        draft = session.get(WfPlanning, first_planning_id)
        assert draft is not None
        assert session.query(WfPlanning).filter(WfPlanning.project_id == project.id).count() == 1
        assert (
            session.query(WfPlanningTaskSnapshot)
            .filter(
                WfPlanningTaskSnapshot.planning_id == first_planning_id,
                WfPlanningTaskSnapshot.name == "Etude documentaire v2",
            )
            .count()
            == 1
        )

        draft.status = "validated"
        session.flush()
        import_tasks_and_links(session, source, project)
        session.commit()

        # Issue #313: MsTask is keyed by (project_id, uid), not by planning, so
        # three successive imports -- including the one that had to open a new
        # planning version -- still leave exactly one twin per imported uid.
        assert session.query(MsTask).filter(MsTask.project_id == project.id).count() == 2
        assert session.query(WfPlanning).filter(WfPlanning.project_id == project.id).count() == 2
        validated = session.get(WfPlanning, first_planning_id)
        assert validated is not None
        assert validated.status == "validated"
        assert project.displayed_planning_id != first_planning_id
        displayed = session.get(WfPlanning, project.displayed_planning_id)
        assert displayed is not None
        assert displayed.status == "draft"


def test_import_service_persists_only_real_tasks_dropping_project_summary() -> None:
    task = (
        _PROJECT_SUMMARY_TASK
        + """
        <Task><UID>1</UID><ID>1</ID><Name>A</Name>
          <OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel>
        </Task>
        <Task><UID>2</UID><ID>2</ID><Name>B</Name>
          <OutlineNumber>2</OutlineNumber><OutlineLevel>1</OutlineLevel>
          <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type></PredecessorLink>
        </Task>
        """
    )
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("Summary task dropped")
        session.add(project)
        session.flush()

        task_count, link_count, warnings = import_tasks_and_links(
            session, _xml_with_tasks(task), project
        )
        session.commit()

        assert (task_count, link_count, warnings) == (2, 1, ())
        planning = session.query(WfPlanning).filter(WfPlanning.project_id == project.id).one()
        snapshots = (
            session.query(WfPlanningTaskSnapshot)
            .filter(WfPlanningTaskSnapshot.planning_id == planning.id)
            .all()
        )
        assert {snapshot.uid for snapshot in snapshots} == {1, 2}
        assert all(
            snapshot.position is not None and snapshot.position > 0 for snapshot in snapshots
        )
        links = (
            session.query(WfPlanningLinkSnapshot)
            .filter(WfPlanningLinkSnapshot.planning_id == planning.id)
            .all()
        )
        assert {link.predecessor_uid for link in links} == {1}


_NESTED_TASKS = (
    _PROJECT_SUMMARY_TASK
    + """
    <Task><UID>1</UID><ID>1</ID><Name>Lot A</Name>
      <OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel><Summary>1</Summary>
    </Task>
    <Task><UID>2</UID><ID>2</ID><Name>Etude</Name>
      <OutlineNumber>1.1</OutlineNumber><OutlineLevel>2</OutlineLevel>
    </Task>
    <Task><UID>3</UID><ID>3</ID><Name>Travaux</Name>
      <OutlineNumber>1.2</OutlineNumber><OutlineLevel>2</OutlineLevel>
    </Task>
    """
)


# Same three-task tree as `_NESTED_TASKS`, but with every column
# `msproject_xml_import._shared_task_fields` copies actually filled in, so
# `test_import_creates_ms_task_twins_mirroring_snapshots` compares meaningful
# values instead of NULLs. Kept separate from `_NESTED_TASKS`, which must stay
# undated for the tests that create role assignments (E6-11/#175 rate coverage).
_DETAILED_TASKS = (
    _PROJECT_SUMMARY_TASK
    + """
    <Task><UID>1</UID><ID>1</ID><Name>Lot A</Name><WBS>1</WBS><Type>1</Type>
      <OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel><Summary>1</Summary>
      <Manual>0</Manual><CalendarUID>1</CalendarUID>
    </Task>
    <Task><UID>2</UID><ID>2</ID><Name>Etude</Name><WBS>1.1</WBS><Type>0</Type>
      <OutlineNumber>1.1</OutlineNumber><OutlineLevel>2</OutlineLevel>
      <Start>2026-01-05T08:00:00</Start><Finish>2026-01-07T18:00:00</Finish>
      <Duration>PT960M0S</Duration><DurationFormat>7</DurationFormat>
      <PercentComplete>25</PercentComplete><Summary>0</Summary><Milestone>0</Milestone>
      <Manual>0</Manual><CalendarUID>1</CalendarUID>
    </Task>
    <Task><UID>3</UID><ID>3</ID><Name>Fin Lot A</Name><WBS>1.2</WBS><Type>0</Type>
      <OutlineNumber>1.2</OutlineNumber><OutlineLevel>2</OutlineLevel>
      <Duration>PT0M0S</Duration><DurationFormat>7</DurationFormat>
      <PercentComplete>0</PercentComplete><Summary>0</Summary><Milestone>1</Milestone>
      <Manual>0</Manual>
    </Task>
    """
)

# Every column both tables carry, derived from the mappings themselves rather
# than hand-listed, so a column added to `_shared_task_fields` later is covered
# without touching this test. Identity/bookkeeping columns are excluded: `id`
# and the owning key differ by construction, `created_at`/`updated_at` are
# per-row, and `structure_key`/`structure_kind` are asserted separately (they
# are always NULL on an imported task).
_MIRRORED_COLUMNS = tuple(
    sorted(
        (
            {column.name for column in MsTask.__table__.columns}
            & {column.name for column in WfPlanningTaskSnapshot.__table__.columns}
        )
        - {"id", "created_at", "updated_at", "structure_key", "structure_kind"}
    )
)


def _ms_tasks_by_uid(session: Session, project_id: int) -> dict[int, MsTask]:
    return {
        task.uid: task for task in session.query(MsTask).filter(MsTask.project_id == project_id)
    }


def test_import_creates_ms_task_twins_mirroring_snapshots() -> None:
    """Issue #313: the XML import must write the canonical `MsTask` rows too,
    with the same tree metadata *and* the same scalar columns as the planning
    snapshots it already wrote.

    Compares every column the two tables share (`_MIRRORED_COLUMNS`, derived
    from the mappings themselves) rather than a hand-picked subset, so a copy
    mistake on e.g. `duration_minutes` or `calendar_uid` cannot slip through --
    hence the deliberately field-complete `_DETAILED_TASKS` fixture.
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("MsTask twins")
        session.add(project)
        session.flush()

        import_tasks_and_links(session, _xml_with_tasks(_DETAILED_TASKS), project)
        session.commit()

        tasks = _ms_tasks_by_uid(session, project.id)
        assert set(tasks) == {1, 2, 3}
        assert [(tasks[uid].parent_uid, tasks[uid].position) for uid in (1, 2, 3)] == [
            (None, 1),
            (1, 1),
            (1, 2),
        ]
        # Imported tasks carry no structure identity: that belongs to the
        # "Lotissement" generation flow (generate_planning_structure).
        assert all(task.structure_key is None for task in tasks.values())
        assert all(task.structure_kind is None for task in tasks.values())

        snapshots = {
            snapshot.uid: snapshot
            for snapshot in session.query(WfPlanningTaskSnapshot).filter(
                WfPlanningTaskSnapshot.planning_id == project.displayed_planning_id
            )
        }
        assert set(snapshots) == set(tasks)
        assert "duration_minutes" in _MIRRORED_COLUMNS  # guards the derivation above
        for uid, task in tasks.items():
            assert {field: getattr(task, field) for field in _MIRRORED_COLUMNS} == {
                field: getattr(snapshots[uid], field) for field in _MIRRORED_COLUMNS
            }

        # The fixture must actually exercise every field: a NULL-everywhere task
        # would make the comparison above vacuous.
        detailed = tasks[2]
        assert detailed.start_at is not None
        assert detailed.finish_at is not None
        assert detailed.duration_minutes == 960
        assert detailed.duration_format == 7
        assert detailed.percent_complete == 25
        assert detailed.calendar_uid == 1
        assert detailed.wbs == "1.1"
        assert detailed.task_type == 0
        assert detailed.is_manual is False
        assert tasks[1].is_summary is True
        assert tasks[3].is_milestone is True


def test_reimport_upserts_ms_tasks_without_duplicating_them() -> None:
    """Issue #313: `(project_id, uid)` is the upsert key -- re-importing the same
    file updates the existing `MsTask` rows in place instead of adding a set."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("MsTask upsert")
        session.add(project)
        session.flush()

        import_tasks_and_links(session, _xml_with_tasks(_NESTED_TASKS), project)
        session.flush()
        first_ids = {uid: task.id for uid, task in _ms_tasks_by_uid(session, project.id).items()}

        changed = _NESTED_TASKS.replace("<Name>Travaux</Name>", "<Name>Travaux v2</Name>").replace(
            "<OutlineNumber>1.2</OutlineNumber><OutlineLevel>2</OutlineLevel>",
            "<OutlineNumber>2</OutlineNumber><OutlineLevel>1</OutlineLevel>",
        )
        import_tasks_and_links(session, _xml_with_tasks(changed), project)
        session.commit()

        tasks = _ms_tasks_by_uid(session, project.id)
        assert set(tasks) == {1, 2, 3}
        assert {uid: task.id for uid, task in tasks.items()} == first_ids
        assert tasks[3].name == "Travaux v2"
        assert (tasks[3].parent_uid, tasks[3].position, tasks[3].outline_level) == (None, 2, 1)


def test_reimport_keeps_ms_task_whose_uid_left_the_file() -> None:
    """Issue #313, deliberate asymmetry with the snapshots: an `MsTask` that
    disappeared from the re-imported file is kept, because an existing devis may
    still reference it through `EstimateTaskRow`/`EstimateCostLine`/
    `EstimateRoleAssignment.task_id`. Reaping true orphans is issue #267."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("MsTask never deleted")
        session.add(project)
        session.flush()

        import_tasks_and_links(session, _xml_with_tasks(_NESTED_TASKS), project)
        session.flush()
        dropped_id = _ms_tasks_by_uid(session, project.id)[3].id

        without_uid_3 = _NESTED_TASKS.replace(
            """<Task><UID>3</UID><ID>3</ID><Name>Travaux</Name>
      <OutlineNumber>1.2</OutlineNumber><OutlineLevel>2</OutlineLevel>
    </Task>""",
            "",
        )
        assert "<UID>3</UID>" not in without_uid_3
        import_tasks_and_links(session, _xml_with_tasks(without_uid_3), project)
        session.commit()

        assert set(_ms_tasks_by_uid(session, project.id)) == {1, 2, 3}
        kept = session.get(MsTask, dropped_id)
        assert kept is not None and kept.uid == 3
        # The snapshot side keeps its existing rebuild-from-scratch behaviour.
        snapshot_uids = {
            snapshot.uid
            for snapshot in session.query(WfPlanningTaskSnapshot).filter(
                WfPlanningTaskSnapshot.planning_id == project.displayed_planning_id
            )
        }
        assert snapshot_uids == {1, 2}


def _register_and_login(client: TestClient) -> dict[str, str]:
    email = f"msproject.import.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, headers: dict[str, str], name: str) -> int:
    response = client.post(
        "/projects", json={"name": name, "currency_code": "EUR"}, headers=headers
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


# One poste / one lot / one livrable -- `generate_planning_structure` turns this
# into uids 1..4 (poste, lot, livrable, milestone "Fin Lot 1"), i.e. exactly the
# uid range an MS Project file also uses.
_LOTISSEMENT_PAYLOAD: dict[str, Any] = {
    "posts": [
        {
            "key": "p1",
            "name": "Poste 1",
            "lots": [
                {
                    "key": "l1",
                    "name": "Lot 1",
                    "deliverables": [{"key": "d1", "name": "Livrable 1"}],
                }
            ],
        }
    ]
}


def test_import_takes_ownership_of_ms_tasks_generated_by_lotissement() -> None:
    """Issue #313: an import that adopts an existing `MsTask` must clear its
    `structure_key`/`structure_kind`.

    `generate_planning_structure` allocates its uids from 1 -- the very range an
    MS Project file uses -- so the overlap is systematic, not exotic. Leaving the
    structure key on an adopted row would keep `generate_planning_structure`
    believing it owns it: the next save of the same Lotissement payload would
    silently overwrite the imported task (while the snapshots keep the imported
    values), and renaming the lot would send the row into the removal branch,
    destroying an imported task's twin or raising an unexplainable 409.
    """
    with TestClient(app) as client:
        headers = _register_and_login(client)
        project_id = _create_project(client, headers, "Lotissement then import")
        assert (
            client.post(
                f"/projects/{project_id}/planning-structure",
                json=_LOTISSEMENT_PAYLOAD,
                headers=headers,
            ).status_code
            == 201
        )

        session_factory = get_session_factory()
        with session_factory() as session:
            generated = _ms_tasks_by_uid(session, project_id)
            assert set(generated) == {1, 2, 3, 4}
            assert generated[1].structure_key == "p1"
            assert generated[2].structure_kind == "lot"

        # The imported file reuses uids 1..3, adopting three generated rows.
        _import_into_project(project_id, _xml_with_tasks(_NESTED_TASKS))

        with session_factory() as session:
            tasks = _ms_tasks_by_uid(session, project_id)
            assert [tasks[uid].name for uid in (1, 2, 3)] == ["Lot A", "Etude", "Travaux"]
            assert all(tasks[uid].structure_key is None for uid in (1, 2, 3))
            assert all(tasks[uid].structure_kind is None for uid in (1, 2, 3))
            # uid 4 was absent from the file: untouched, still owned by the
            # structure flow (no deletion, see test_reimport_keeps_ms_task...).
            assert tasks[4].structure_key == "p1/l1/completion"

        # The regression this locks: re-saving the very same Lotissement payload.
        assert (
            client.post(
                f"/projects/{project_id}/planning-structure",
                json=_LOTISSEMENT_PAYLOAD,
                headers=headers,
            ).status_code
            == 201
        )

        with session_factory() as session:
            tasks = _ms_tasks_by_uid(session, project_id)
            assert [tasks[uid].name for uid in (1, 2, 3)] == ["Lot A", "Etude", "Travaux"]
            # The structure nodes it no longer owns are recreated under fresh
            # uids -- generate_planning_structure's documented additive behaviour.
            regenerated = {
                task.structure_key: task.uid
                for task in tasks.values()
                if task.structure_key is not None
            }
            assert set(regenerated) == {"p1", "p1/l1", "p1/l1/d1", "p1/l1/completion"}
            assert all(regenerated[key] > 4 for key in ("p1", "p1/l1", "p1/l1/d1"))
            assert regenerated["p1/l1/completion"] == 4


def _seed_labor_role() -> int:
    """An active labor `ResourceRole` (no `CostRate` needed: the tasks imported
    by these tests are undated, so E6-11/#175's coverage guard does not fire)."""
    session_factory = get_session_factory()
    with session_factory() as session:
        node = ResourceNode(code=f"DIRECTION-{uuid4().hex[:8]}", name="Direction")
        session.add(node)
        cost_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"MO-DEV-{uuid4().hex[:8]}",
            category_code="IDEX",
            name="Developpement",
        )
        session.add(category)
        session.flush()
        role = ResourceRole(node_id=node.id, cost_category_id=category.id, name="Developpeur")
        session.add(role)
        session.commit()
        return role.id


def _import_into_project(project_id: int, xml_bytes: bytes) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        project = session.query(MsProject).filter(MsProject.id == project_id).one()
        import_tasks_and_links(session, xml_bytes, project)
        session.commit()


def test_imported_project_estimate_is_priceable_per_task() -> None:
    """Issue #313 acceptance: on a project imported from MS Project XML, a devis
    must get a non-NULL `task_id` on every row (it used to be NULL everywhere,
    silently) and a role assignment on an imported task must be accepted."""
    with TestClient(app) as client:
        headers = _register_and_login(client)
        project_id = _create_project(client, headers, "Imported project")
        _import_into_project(project_id, _xml_with_tasks(_NESTED_TASKS))

        create_estimate = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_estimate.status_code == 201
        estimate_id = cast(int, create_estimate.json()["id"])

        rows_response = client.get(
            f"/projects/{project_id}/estimates/{estimate_id}/task-rows", headers=headers
        )
        assert rows_response.status_code == 200
        rows = cast(list[dict[str, Any]], rows_response.json()["items"])
        assert len(rows) == 3
        assert all(row["task_id"] is not None for row in rows)
        # E12-09/#291 ranks, depth-first over the imported tree (1, then its two
        # children) -- not merely "not null", which is what used to degrade.
        assert [(row["task_uid"], row["row_number"]) for row in rows] == [(1, 1), (2, 2), (3, 3)]

        leaf = next(row for row in rows if row["task_uid"] == 2)
        assignment = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/role-assignments",
            json={
                "task_id": leaf["task_id"],
                "role_id": _seed_labor_role(),
                "quantity": "1",
                "hours": "8",
            },
            headers=headers,
        )
        assert assignment.status_code == 201
        assert assignment.json()["task_id"] == leaf["task_id"]


def test_import_service_rejects_link_to_omitted_project_summary_before_persisting() -> None:
    task = (
        _PROJECT_SUMMARY_TASK
        + """
        <Task><UID>1</UID><ID>1</ID><Name>A</Name>
          <OutlineNumber>1</OutlineNumber><OutlineLevel>1</OutlineLevel>
          <PredecessorLink><PredecessorUID>0</PredecessorUID><Type>1</Type></PredecessorLink>
        </Task>
        """
    )
    session_factory = get_session_factory()
    with session_factory() as session:
        project = _new_project("Dangling link to summary")
        session.add(project)
        session.flush()

        with pytest.raises(MsProjectValidationError) as error:
            import_tasks_and_links(session, _xml_with_tasks(task), project)
        assert {issue["code"] for issue in error.value.issues} == {"ORPHAN_LINK"}

        session.rollback()
        assert session.query(WfPlanning).filter(WfPlanning.project_id == project.id).count() == 0
        assert session.query(WfPlanningTaskSnapshot).count() == 0
        assert session.query(WfPlanningLinkSnapshot).count() == 0
