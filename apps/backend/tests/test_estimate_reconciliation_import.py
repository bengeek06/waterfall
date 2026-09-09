"""E6-09/#70: import an Excel reconciliation file back into a draft devis.

Covers ``POST .../import-reconciliation/preview`` and
``POST .../import-reconciliation/confirm``: both run the exact same analysis
on the uploaded file (see ``estimates._run_reconciliation``), preview never
writing, confirm applying only when ``blocking_issues`` is empty. The
uploaded fixtures round-trip through ``GET .../export-reconciliation.xlsx``
(E6-08/#69), edited in-memory with openpyxl before being resubmitted, exactly
like a human editing the exported workbook would.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from io import BytesIO
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from waterfall.core.config import get_settings
from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.planning import WfPlanningLinkSnapshot, WfPlanningTaskSnapshot
from waterfall.models.resources import (
    CostCategory,
    CostType,
    EstimateRoleAssignment,
    ResourceNode,
    ResourceRole,
)

_XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"estimate.reconciliation.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    register_response: Response = client.post(
        "/auth/register", json={"email": email, "password": password}
    )
    assert register_response.status_code == 201
    token_response: Response = client.post(
        "/auth/token", data={"username": email, "password": password}
    )
    assert token_response.status_code == 200
    return {"Authorization": f"Bearer {token_response.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/projects", json={"name": f"Reconciliation {uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _structure_payload() -> dict[str, Any]:
    return {
        "posts": [
            {
                "key": "design",
                "name": "Design",
                "lots": [
                    {
                        "key": "specification",
                        "name": "Specification",
                        "deliverables": [{"key": "requirements", "name": "Requirements"}],
                    }
                ],
            }
        ]
    }


def _generate_structure(client: TestClient, headers: dict[str, str], project_id: int) -> None:
    response = client.post(
        f"/projects/{project_id}/planning-structure",
        json=_structure_payload(),
        headers=headers,
    )
    assert response.status_code == 201


def _create_estimate(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response = client.post(
        f"/projects/{project_id}/estimates",
        json={"kind": "initial", "currency_code": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _deliverable_task(project_id: int) -> MsTask:
    with get_session_factory()() as session:
        task = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "livrable")
            .one()
        )
        session.expunge(task)
        return task


def _lot_task(project_id: int) -> MsTask:
    """The structure's single ``lot`` -- parent of the deliverable, so it always has a child."""
    with get_session_factory()() as session:
        task = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.structure_kind == "lot")
            .one()
        )
        session.expunge(task)
        return task


def _mstask_exists(task_id: int) -> bool:
    with get_session_factory()() as session:
        return session.get(MsTask, task_id) is not None


def _snapshot_exists(project_id: int, uid: int) -> bool:
    with get_session_factory()() as session:
        project = session.get(MsProject, project_id)
        assert project is not None and project.displayed_planning_id is not None
        return (
            session.query(WfPlanningTaskSnapshot)
            .filter(
                WfPlanningTaskSnapshot.planning_id == project.displayed_planning_id,
                WfPlanningTaskSnapshot.uid == uid,
            )
            .first()
            is not None
        )


def _mstask_uid(task_id: int) -> int:
    with get_session_factory()() as session:
        task = session.get(MsTask, task_id)
        assert task is not None
        return task.uid


def _displayed_planning_id(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response = _get(client, f"/projects/{project_id}", headers)
    assert response.status_code == 200
    planning_id = response.json()["displayed_planning_id"]
    assert planning_id is not None
    return cast(int, planning_id)


def _validate_displayed_planning(
    client: TestClient, headers: dict[str, str], project_id: int
) -> None:
    """Flip the project's displayed planning from ``draft`` to ``validated``.

    Used to exercise ``PLANNING_NOT_DRAFT`` (E6-09's Critical finding #3): the
    devis' own ``estimate.status`` stays ``draft`` throughout (a separate
    lifecycle from the planning's), so ``get_draft_estimate_or_409`` still lets
    the request reach ``_run_reconciliation`` -- it is
    ``_resolve_planning_for_tasks`` that then rejects the create/delete because
    the *planning* is no longer a draft.
    """
    planning_id = _displayed_planning_id(client, headers, project_id)
    response = client.post(
        f"/projects/{project_id}/plannings/{planning_id}/validate",
        headers=headers,
    )
    assert response.status_code == 200


def _remove_task_from_planning_snapshot(project_id: int, task_uid: int) -> None:
    """Delete a task's ``WfPlanningTaskSnapshot`` twin directly, leaving its legacy
    ``MsTask``/``EstimateRoleAssignment`` rows untouched.

    Engineers the exact "task removed from planning, legacy MsTask/assignment left
    behind" gap that makes ``_scoped_estimate_role_assignments`` flag an assignment
    ``hors_perimetre_planning=True`` at read time (see its own docstring) -- the
    safe, guarded ``delete_planning_tasks`` deliberately refuses this while the task
    is still referenced by an assignment (``TASK_REFERENCED``), so this reaches
    directly into the DB, the same way this module's other setup helpers
    (``_seed_labor_role``/``_seed_non_labor_category``) already do, instead of
    exercising a whole unrelated import pipeline just to reach the same state.
    """
    with get_session_factory()() as session:
        project = session.get(MsProject, project_id)
        assert project is not None and project.displayed_planning_id is not None
        planning_id = project.displayed_planning_id
        # Any predecessor/successor link snapshot referencing this uid would otherwise
        # violate wf_planning_link_snapshot's own FK to this table -- mirroring the
        # cleanup delete_planning_tasks itself does before removing a task snapshot.
        session.query(WfPlanningLinkSnapshot).filter(
            WfPlanningLinkSnapshot.planning_id == planning_id,
            (WfPlanningLinkSnapshot.task_uid == task_uid)
            | (WfPlanningLinkSnapshot.predecessor_uid == task_uid),
        ).delete(synchronize_session=False)
        session.query(WfPlanningTaskSnapshot).filter(
            WfPlanningTaskSnapshot.planning_id == planning_id,
            WfPlanningTaskSnapshot.uid == task_uid,
        ).delete()
        session.commit()


def _create_standalone_task(
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    estimate_id: int,
    name: str,
    *,
    is_milestone: bool = False,
) -> dict[str, Any]:
    """A root task with no children and no MO/Non-MO reference (E6-06/#67's own endpoint)."""
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/tasks",
        json={"name": name, "is_milestone": is_milestone},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _create_sub_cost_code(
    client: TestClient, headers: dict[str, str], project_id: int, code: str
) -> int:
    """A cost code under the project's own auto-created root (E6-01/#62's own endpoint)."""
    roots = _get(client, f"/projects/{project_id}/cost-codes", headers)
    assert roots.status_code == 200
    root_id = cast(int, _items(roots.json())[0]["id"])
    response = client.post(
        f"/projects/{project_id}/cost-codes",
        json={"code": code, "name": code, "parent_id": root_id},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _deactivate_cost_category(category_id: int) -> None:
    """Flip a ``CostCategory.is_active`` off directly (no deactivation endpoint exists yet),
    the same direct-DB pattern this module's own ``_remove_task_from_planning_snapshot``
    already uses to engineer a state unreachable through the public API.
    """
    with get_session_factory()() as session:
        category = session.get(CostCategory, category_id)
        assert category is not None
        category.is_active = False
        session.commit()


def _seed_labor_role() -> int:
    with get_session_factory()() as session:
        resource_node = ResourceNode(code=f"NODE-{uuid4().hex[:8]}", name="Direction")
        session.add(resource_node)
        session.flush()
        cost_type = CostType(code=f"MO-{uuid4().hex[:8]}", name="Main d'oeuvre", kind="labor")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"MO-DEV-{uuid4().hex[:8]}",
            category_code=f"IDEX-{uuid4().hex[:8]}",
            name="Developpement",
        )
        session.add(category)
        session.flush()
        role = ResourceRole(node_id=resource_node.id, cost_category_id=category.id, name="Dev")
        session.add(role)
        session.commit()
        return role.id


def _create_estimate_role_assignment(
    project_id: int,
    estimate_id: int,
    task_uid: int,
    role_id: int,
    *,
    quantity: str = "1.00",
    hours: str = "1.00",
    comment: str | None = None,
    cost_code_id: int | None = None,
) -> int:
    """Insert an `EstimateRoleAssignment` directly via the ORM, scoped to `estimate_id`.

    `EstimateRoleAssignment` (E12-01/#273) is now the reconciliation export/import's
    own MO sheet source of truth (E12-03/#275, replacing the legacy, project-wide
    `TaskRoleAssignment`). This reaches directly into the DB rather than through the
    real `POST .../role-assignments` route for the same reason this module's other
    setup helpers (``_seed_labor_role``/``_remove_task_from_planning_snapshot``)
    already do: full control over the exact quantity/hours/cost_code_id/comment
    combination, without incidentally exercising that route's own rate-coverage
    guard on every single reconciliation test.
    """
    with get_session_factory()() as session:
        task = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.uid == task_uid)
            .one()
        )
        assignment = EstimateRoleAssignment(
            estimate_id=estimate_id,
            task_id=task.id,
            role_id=role_id,
            cost_code_id=cost_code_id,
            quantity=Decimal(quantity),
            hours=Decimal(hours),
            comment=comment,
        )
        session.add(assignment)
        session.commit()
        return assignment.id


def _estimate_role_assignment(assignment_id: int) -> EstimateRoleAssignment:
    """Read an `EstimateRoleAssignment` back directly (see
    `_create_estimate_role_assignment` for why this reaches directly into the DB)."""
    with get_session_factory()() as session:
        assignment = session.get(EstimateRoleAssignment, assignment_id)
        assert assignment is not None
        session.expunge(assignment)
        return assignment


def _seed_non_labor_category() -> int:
    with get_session_factory()() as session:
        cost_type = CostType(code=f"MAT-{uuid4().hex[:8]}", name="Materiel")
        session.add(cost_type)
        session.flush()
        category = CostCategory(
            cost_type_id=cost_type.id,
            accounting_code=f"ACC-{uuid4().hex[:8]}",
            category_code=f"CAT-{uuid4().hex[:8]}",
            name="Materiel",
        )
        session.add(category)
        session.commit()
        return category.id


def _export_workbook(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int
) -> bytes:
    response = _get(
        client,
        f"/projects/{project_id}/estimates/{estimate_id}/export-reconciliation.xlsx",
        headers,
    )
    assert response.status_code == 200
    return response.content


def _dump_workbook(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _header_row(sheet: Worksheet) -> tuple[Any, ...]:
    return next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))


def _find_row_number(sheet: Worksheet, match_column: str, match_value: object) -> int:
    headers = _header_row(sheet)
    match_index = headers.index(match_column)
    for row in sheet.iter_rows(min_row=2):
        if row[match_index].value == match_value:
            row_number = row[match_index].row
            assert row_number is not None
            return row_number
    raise AssertionError(f"No row with {match_column}={match_value!r} in sheet {sheet.title!r}")


def _set_cell(
    sheet: Worksheet, match_column: str, match_value: object, target_column: str, new_value: object
) -> None:
    """Overwrite a single cell, including clearing it back to blank.

    Deliberately never calls ``sheet.cell(row, column, value=...)`` with the new
    value: openpyxl's own ``Worksheet.cell`` treats ``value=None`` as "leave this
    cell's existing value untouched" (its default sentinel for "no value given"),
    not "set it to None" -- so a caller passing ``new_value=None`` to blank a cell
    would otherwise silently leave the original value in place, making every
    "blank cell" reconciliation test in this module a no-op that happened to still
    pass for the wrong reason (E6-09 round 3 review). Fetching the cell first and
    assigning ``.value`` directly has no such special-case.
    """
    headers = _header_row(sheet)
    target_index = headers.index(target_column)
    row_number = _find_row_number(sheet, match_column, match_value)
    cell = sheet.cell(row=row_number, column=target_index + 1)
    cell.value = cast(Any, new_value)


def _delete_row(sheet: Worksheet, match_column: str, match_value: object) -> None:
    row_number = _find_row_number(sheet, match_column, match_value)
    sheet.delete_rows(row_number, 1)


def _get(client: TestClient, url: str, headers: dict[str, str]) -> Response:
    """Thin wrapper with a fully-known return annotation.

    Unlike a bare local variable annotation (``x: Response = client.get(...)``),
    a function's own return-type annotation fully launders any partially-unknown
    type ``TestClient.get`` itself carries -- otherwise pyright strict keeps
    flagging ``.json()`` on the result as ``reportUnknownArgumentType`` even
    though the variable is explicitly typed ``Response``.
    """
    return client.get(url, headers=headers)


def _preview(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int, content: bytes
) -> Response:
    return client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/import-reconciliation/preview",
        files={"file": ("reconciliation.xlsx", content, _XLSX_CONTENT_TYPE)},
        headers=headers,
    )


def _confirm(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int, content: bytes
) -> Response:
    return client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/import-reconciliation/confirm",
        files={"file": ("reconciliation.xlsx", content, _XLSX_CONTENT_TYPE)},
        headers=headers,
    )


def _items(payload: object) -> list[dict[str, Any]]:
    """Take a response's already-decoded ``.json()`` payload (typed ``Any`` by httpx's
    own stubs) rather than the ``Response`` itself: passing the ``Response`` object
    through an extra function call resurfaces it as a partially-unknown type under
    pyright strict, even when the caller's local variable is explicitly annotated.
    """
    return cast(list[dict[str, Any]], cast(dict[str, Any], payload)["items"])


def _plan(payload: object) -> dict[str, Any]:
    return cast(dict[str, Any], payload)


def _seed_fixture(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    """Project + draft devis with one MO row and one Non-MO row on the deliverable task."""
    project_id = _create_project(client, headers)
    _generate_structure(client, headers, project_id)
    estimate_id = _create_estimate(client, headers, project_id)
    deliverable = _deliverable_task(project_id)
    role_id = _seed_labor_role()
    category_id = _seed_non_labor_category()

    assignment_id = _create_estimate_role_assignment(
        project_id,
        estimate_id,
        deliverable.uid,
        role_id,
        quantity="2.00",
        hours="10.00",
        comment="Initial",
    )

    cost_line_response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
        json={
            "task_id": deliverable.id,
            "cost_category_id": category_id,
            "label": "Materiel initial",
            "quantity": "1.00",
            "unit_cost": "50.00",
        },
        headers=headers,
    )
    assert cost_line_response.status_code == 201
    cost_line_id = cast(int, cost_line_response.json()["id"])

    task_rows_response = _get(
        client, f"/projects/{project_id}/estimates/{estimate_id}/task-rows", headers
    )
    assert task_rows_response.status_code == 200
    task_row_id = next(
        row["id"] for row in _items(task_rows_response.json()) if row["task_id"] == deliverable.id
    )

    return {
        "project_id": project_id,
        "estimate_id": estimate_id,
        "deliverable_id": deliverable.id,
        "deliverable_uid": deliverable.uid,
        "role_id": role_id,
        "category_id": category_id,
        "assignment_id": assignment_id,
        "cost_line_id": cost_line_id,
        "task_row_id": task_row_id,
    }


def test_reconciliation_import_round_trip_confirms_without_changes() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], content)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["warnings"] == []
        assert plan["tasks_to_create"] == 0
        assert plan["tasks_to_delete"] == []
        assert plan["labor_to_create"] == 0
        assert plan["labor_to_update"] == []
        assert plan["labor_to_delete"] == []
        assert plan["non_labor_to_create"] == 0
        assert plan["non_labor_to_update"] == []
        assert plan["non_labor_to_delete"] == []
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], content)
        assert confirm.status_code == 200
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["blocking_issues"] == []
        assert confirmed_plan["applied"] is True


def test_reconciliation_import_updates_only_modified_labor_quantity() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["MO"], "id", fixture["assignment_id"], "quantity", 5)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["labor_to_update"] == [fixture["assignment_id"]]
        assert plan["non_labor_to_update"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        updated = _estimate_role_assignment(fixture["assignment_id"])
        assert updated.quantity == Decimal("5.00")


def test_reconciliation_import_updates_only_modified_cost_line_quantity() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["Non-MO"], "id", fixture["cost_line_id"], "quantity", 9)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["non_labor_to_update"] == [fixture["cost_line_id"]]
        assert plan["labor_to_update"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        assert cost_lines.status_code == 200
        updated = next(
            item for item in _items(cost_lines.json()) if item["id"] == fixture["cost_line_id"]
        )
        assert float(updated["quantity"]) == 9.0


def test_reconciliation_import_flags_and_then_applies_deletion() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Non-MO"], "id", fixture["cost_line_id"])
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["non_labor_to_delete"] == [fixture["cost_line_id"]]
        assert plan["applied"] is False

        # Preview never writes: the cost line must still be there afterwards.
        cost_lines_after_preview = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        assert any(
            item["id"] == fixture["cost_line_id"]
            for item in _items(cost_lines_after_preview.json())
        )

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        cost_lines_after_confirm = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        assert not any(
            item["id"] == fixture["cost_line_id"]
            for item in _items(cost_lines_after_confirm.json())
        )


def test_reconciliation_import_rejects_validated_estimate() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        validate_response = client.post(
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], content)
        assert preview.status_code == 409

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], content)
        assert confirm.status_code == 409


def test_reconciliation_import_creates_task_labor_and_non_labor_rows() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        # A second labor role: the fixture's deliverable task already has an
        # assignment for `role_id` (see _seed_fixture), so reusing it here would
        # be a legitimate LABOR_DUPLICATE_ASSIGNMENT, not a fresh creation.
        second_role_id = _seed_labor_role()
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        workbook["Tâches"].append(
            [None, None, None, fixture["deliverable_id"], None, "Nouvelle tache", None, None, False]
        )
        workbook["MO"].append(
            [
                None,
                fixture["deliverable_id"],
                None,
                second_role_id,
                None,
                None,
                None,
                None,
                1,
                3,
                None,
                False,
            ]
        )
        workbook["Non-MO"].append(
            [
                None,
                fixture["deliverable_id"],
                None,
                None,
                fixture["category_id"],
                None,
                None,
                None,
                "Nouvelle ligne",
                2,
                20,
                None,
                None,
                None,
            ]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["tasks_to_create"] == 1
        assert plan["labor_to_create"] == 1
        assert plan["non_labor_to_create"] == 1

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        task_rows = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert any(row["task_name"] == "Nouvelle tache" for row in _items(task_rows.json()))

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        assert any(item["label"] == "Nouvelle ligne" for item in _items(cost_lines.json()))


def test_reconciliation_import_unknown_id_is_blocking_and_nothing_applied() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        # A quantity change alongside a bogus id: the whole import must be rejected,
        # so the legitimate quantity change must not be applied either.
        _set_cell(workbook["MO"], "id", fixture["assignment_id"], "quantity", 5)
        _set_cell(workbook["Non-MO"], "id", fixture["cost_line_id"], "id", 999999999)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(issue["code"] == "COST_LINE_ROW_ID_UNKNOWN" for issue in plan["blocking_issues"])
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "COST_LINE_ROW_ID_UNKNOWN"
            for issue in confirmed_plan["blocking_issues"]
        )

        unchanged = _estimate_role_assignment(fixture["assignment_id"])
        assert unchanged.quantity == Decimal("2.00")


def test_reconciliation_import_task_name_change_is_warning_not_applied() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["Tâches"], "id", fixture["task_row_id"], "task_name", "Renamed")
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert any(issue["code"] == "TASK_FIELD_CHANGE_IGNORED" for issue in plan["warnings"])
        assert plan["tasks_to_create"] == 0
        assert plan["tasks_to_delete"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200

        task_rows = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        row = next(
            item for item in _items(task_rows.json()) if item["id"] == fixture["task_row_id"]
        )
        assert row["task_name"] == "Requirements"


def test_reconciliation_import_hors_perimetre_row_is_ignored() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _set_cell(
            workbook["MO"],
            "id",
            fixture["assignment_id"],
            "hors_perimetre_planning",
            True,
        )
        # Also change the quantity: even so, a hors-perimetre row must never be
        # created/updated/deleted.
        _set_cell(workbook["MO"], "id", fixture["assignment_id"], "quantity", 42)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["labor_to_update"] == []
        assert plan["labor_to_delete"] == []
        assert any(
            issue["code"] == "LABOR_OUT_OF_PLANNING_SCOPE_IGNORED" for issue in plan["warnings"]
        )

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200

        unchanged = _estimate_role_assignment(fixture["assignment_id"])
        assert unchanged.quantity == Decimal("2.00")


def test_reconciliation_import_hors_perimetre_row_absent_from_file_is_not_deleted() -> None:
    """Critical finding #1 (E6-09 review): an absent-from-file hors-perimetre row must
    never land in ``labor_to_delete`` -- only a row still *present but flagged* is
    skipped by ``_stage_labor_sheet``'s own per-row branch; a row missing entirely
    from the file falls through to the generic "not seen => delete" set unless it is
    also excluded there by DB-truth out-of-scope status (the actual fix).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        _remove_task_from_planning_snapshot(fixture["project_id"], fixture["deliverable_uid"])
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["MO"], "id", fixture["assignment_id"])
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["labor_to_delete"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        # `_estimate_role_assignment` itself asserts the row still exists.
        _estimate_role_assignment(fixture["assignment_id"])


def test_reconciliation_import_delete_and_recreate_same_pair_succeeds() -> None:
    """Regression test for issue #268 (fixed as part of E12-03/#275's migration to
    ``EstimateRoleAssignment``): a file that both deletes the MO row for a
    ``(task_id, role_id)`` pair and creates a fresh row for that *exact same* pair
    must succeed -- not be spuriously rejected as ``LABOR_DUPLICATE_ASSIGNMENT``.
    Before the fix, ``_stage_new_labor_row``'s uniqueness check saw the pair as
    still assigned (the deletion is only actually applied later, in
    ``_run_reconciliation``), so a delete+recreate of the same pair in one import
    could never succeed.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["MO"], "id", fixture["assignment_id"])
        workbook["MO"].append(
            [
                None,
                fixture["deliverable_id"],
                None,
                fixture["role_id"],
                None,
                None,
                None,
                None,
                4,
                8,
                "Recreated",
                False,
            ]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["labor_to_delete"] == [fixture["assignment_id"]]
        assert plan["labor_to_create"] == 1

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        assignments_response = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/role-assignments",
            headers,
        )
        assert assignments_response.status_code == 200
        items = _items(assignments_response.json())
        # Exactly one assignment for this (task, role) pair: the delete and the
        # creation both happened, never a rejected/duplicated pair. The recreated
        # row's id may or may not coincide with the deleted one's (SQLite is free to
        # recycle a freed rowid), so this asserts on content, not identity.
        matching = [item for item in items if item["role_id"] == fixture["role_id"]]
        assert len(matching) == 1
        recreated = matching[0]
        assert float(recreated["quantity"]) == 4.0
        assert float(recreated["hours"]) == 8.0
        assert recreated["comment"] == "Recreated"


def test_reconciliation_import_does_not_touch_role_assignments_of_another_estimate() -> None:
    """New acceptance test (E12-03/#275), on the model of
    ``test_estimate_reconciliation_export_does_not_leak_role_assignments_across_projects``
    (``test_projects_api.py``, #69): reimporting one devis' reconciliation file must
    only ever update/create/delete ``EstimateRoleAssignment`` rows of *that* devis,
    never a sibling devis' of the same project.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        other_estimate_id = _create_estimate(client, headers, fixture["project_id"])
        other_role_id = _seed_labor_role()
        other_assignment_id = _create_estimate_role_assignment(
            fixture["project_id"],
            other_estimate_id,
            fixture["deliverable_uid"],
            other_role_id,
            quantity="9.00",
            hours="9.00",
            comment="OTHER_ESTIMATE_ONLY",
        )

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["MO"], "id", fixture["assignment_id"], "quantity", 7)
        edited = _dump_workbook(workbook)

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        updated = _estimate_role_assignment(fixture["assignment_id"])
        assert updated.quantity == Decimal("7.00")

        untouched = _estimate_role_assignment(other_assignment_id)
        assert untouched.quantity == Decimal("9.00")
        assert untouched.comment == "OTHER_ESTIMATE_ONLY"


def test_reconciliation_import_duplicate_check_is_scoped_per_estimate() -> None:
    """New acceptance test (E12-03/#275): a MO creation row proposing a
    ``(task_id, role_id)`` pair already present in a *different* devis of the same
    project must NOT be rejected as ``LABOR_DUPLICATE_ASSIGNMENT`` -- the
    ``(estimate_id, task_id, role_id)`` unique constraint (E12-01/#273) is scoped
    per-estimate, never project-wide. Only a duplicate *within the same* devis is
    refused.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        other_role_id = _seed_labor_role()
        other_estimate_id = _create_estimate(client, headers, fixture["project_id"])
        _create_estimate_role_assignment(
            fixture["project_id"],
            other_estimate_id,
            fixture["deliverable_uid"],
            other_role_id,
            quantity="3.00",
            hours="3.00",
        )

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        # Same (task, role) pair as the OTHER estimate's own assignment: must be
        # accepted as a fresh creation on THIS estimate -- no cross-estimate collision.
        workbook["MO"].append(
            [
                None,
                fixture["deliverable_id"],
                None,
                other_role_id,
                None,
                None,
                None,
                None,
                1,
                1,
                None,
                False,
            ]
        )
        # Same (task, role) pair as THIS estimate's own existing assignment
        # (fixture["role_id"]): a genuine duplicate, must be rejected.
        workbook["MO"].append(
            [
                None,
                fixture["deliverable_id"],
                None,
                fixture["role_id"],
                None,
                None,
                None,
                None,
                1,
                1,
                None,
                False,
            ]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        duplicate_issues = [
            issue
            for issue in plan["blocking_issues"]
            if issue["code"] == "LABOR_DUPLICATE_ASSIGNMENT"
        ]
        assert len(duplicate_issues) == 1
        assert plan["labor_to_create"] == 1
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        assert _plan(confirm.json())["applied"] is False


def test_reconciliation_import_blank_cost_line_task_id_does_not_clear_it() -> None:
    """Critical finding #2 (E6-09 review): a blanked task_id cell on an otherwise
    unchanged Non-MO row must not silently detach the cost line from its task.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["Non-MO"], "id", fixture["cost_line_id"], "task_id", None)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        assert _plan(preview.json())["blocking_issues"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        updated = next(
            item for item in _items(cost_lines.json()) if item["id"] == fixture["cost_line_id"]
        )
        assert updated["task_id"] == fixture["deliverable_id"]


def test_reconciliation_import_blank_cost_line_planned_date_does_not_clear_it() -> None:
    """Critical finding #2 (E6-09 review): a blanked planned_date cell on an otherwise
    unchanged Non-MO row must not silently clear the planned date.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)

        cost_line_response = client.post(
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            json={
                "task_id": fixture["deliverable_id"],
                "cost_category_id": fixture["category_id"],
                "label": "Materiel date",
                "quantity": "1.00",
                "unit_cost": "10.00",
                "planned_date": "2026-01-15",
            },
            headers=headers,
        )
        assert cost_line_response.status_code == 201
        dated_cost_line_id = cast(int, cost_line_response.json()["id"])

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["Non-MO"], "id", dated_cost_line_id, "planned_date", None)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        assert _plan(preview.json())["blocking_issues"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        updated = next(
            item for item in _items(cost_lines.json()) if item["id"] == dated_cost_line_id
        )
        assert updated["planned_date"] is not None
        assert cast(str, updated["planned_date"]).startswith("2026-01-15")


def test_reconciliation_import_cost_line_update_supply_status_incompatible_is_blocking() -> None:
    """Finding Haute (E6-09 round 2 review): a Non-MO row's supply_status/category-kind
    compatibility must be validated at staging (preview *and* confirm's precheck), not
    only at apply.

    Before this fix, ``_stage_cost_line_sheet`` never checked this rule -- preview
    reported ``blocking_issues: []`` for exactly this file, and confirm then blew up
    with a bare, unstructured 400 (an ``HTTPException`` raised deep inside
    ``_apply_cost_line_updates``, uncaught by any of confirm's own ``except`` clauses)
    instead of the expected 409 with a ``ReconciliationPlanRead`` body and
    ``applied=False``.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        # fixture["category_id"] is an "other"-kind category (see _seed_non_labor_category):
        # supply_status is only ever valid on a SUPPLY-kind cost type.
        _set_cell(workbook["Non-MO"], "id", fixture["cost_line_id"], "supply_status", "planned")
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(
            issue["code"] == "COST_LINE_SUPPLY_STATUS_INVALID" for issue in plan["blocking_issues"]
        )
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "COST_LINE_SUPPLY_STATUS_INVALID"
            for issue in confirmed_plan["blocking_issues"]
        )

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        unchanged = next(
            item for item in _items(cost_lines.json()) if item["id"] == fixture["cost_line_id"]
        )
        assert unchanged["supply_status"] is None


def test_reconciliation_import_cost_line_create_supply_status_incompatible_is_blocking() -> None:
    """Same rule as above (E6-09 round 2 review), exercised on the creation branch of
    ``_stage_cost_line_sheet`` rather than the update branch -- both were fixed
    identically, reusing the same shared ``_cost_line_supply_status_is_compatible``.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        workbook["Non-MO"].append(
            [
                None,
                fixture["deliverable_id"],
                None,
                None,
                fixture["category_id"],
                None,
                None,
                None,
                "Nouvelle ligne invalide",
                2,
                20,
                None,
                "planned",
                None,
            ]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(
            issue["code"] == "COST_LINE_SUPPLY_STATUS_INVALID" for issue in plan["blocking_issues"]
        )
        assert plan["non_labor_to_create"] == 0
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "COST_LINE_SUPPLY_STATUS_INVALID"
            for issue in confirmed_plan["blocking_issues"]
        )

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        assert not any(
            item["label"] == "Nouvelle ligne invalide" for item in _items(cost_lines.json())
        )


def test_reconciliation_import_deletes_task_row_without_children_or_references() -> None:
    """Critical finding #3, case 1 (E6-09 review): deleting a childless, unreferenced
    task row is proposed in preview and genuinely removes both the ``EstimateTaskRow``
    and its planning ``WfPlanningTaskSnapshot`` at confirm.

    Does *not* assert the legacy ``MsTask`` twin itself disappears: ``_apply_task_deletes``
    only ever calls ``delete_planning_tasks`` (E3-05), which -- consistently with the
    direct Planning-tree delete route (``plannings.py::delete_planning_tasks_route``) --
    only ever removes the ``wf_planning_task_snapshot``/``wf_planning_link_snapshot``
    rows, never the ``ms_task`` row itself (a pre-existing, project-wide gap between the
    legacy and snapshot task models, unrelated to this import feature).
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        standalone = _create_standalone_task(
            client, headers, fixture["project_id"], fixture["estimate_id"], "Standalone"
        )
        task_row_id = cast(int, standalone["id"])
        task_id = cast(int, standalone["task_id"])
        task_uid = _mstask_uid(task_id)

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Tâches"], "id", task_row_id)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert plan["blocking_issues"] == []
        assert plan["tasks_to_delete"] == [task_row_id]
        assert plan["applied"] is False

        # Preview never writes.
        assert _mstask_exists(task_id)
        assert _snapshot_exists(fixture["project_id"], task_uid)

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        task_rows = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert not any(row["id"] == task_row_id for row in _items(task_rows.json()))
        assert not _snapshot_exists(fixture["project_id"], task_uid)


def test_reconciliation_import_task_deletion_with_children_requires_cascade() -> None:
    """Critical finding #3, case 2 (E6-09 review): deleting a task row with a
    planning child is blocked, in both preview and confirm, applying nothing.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        lot = _lot_task(fixture["project_id"])

        task_rows_response = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        lot_row_id = next(
            row["id"] for row in _items(task_rows_response.json()) if row["task_id"] == lot.id
        )

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Tâches"], "id", lot_row_id)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(
            issue["code"] == "TASK_DELETE_REQUIRES_CASCADE_CONFIRMATION"
            for issue in plan["blocking_issues"]
        )
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "TASK_DELETE_REQUIRES_CASCADE_CONFIRMATION"
            for issue in confirmed_plan["blocking_issues"]
        )

        task_rows_after = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert any(row["id"] == lot_row_id for row in _items(task_rows_after.json()))
        assert _mstask_exists(lot.id)


def test_reconciliation_import_task_deletion_still_referenced_is_blocked() -> None:
    """Critical finding #3, case 3 (E6-09 review): deleting a task row still referenced
    by a MO assignment/Non-MO line that is *not itself* removed in the same import is
    blocked, in both preview and confirm, applying nothing.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Tâches"], "id", fixture["task_row_id"])
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(issue["code"] == "TASK_DELETE_REFERENCED" for issue in plan["blocking_issues"])
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "TASK_DELETE_REFERENCED" for issue in confirmed_plan["blocking_issues"]
        )

        task_rows_after = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert any(row["id"] == fixture["task_row_id"] for row in _items(task_rows_after.json()))
        assert _mstask_exists(fixture["deliverable_id"])


def test_reconciliation_import_task_mutation_blocked_when_planning_not_draft() -> None:
    """Critical finding #3, case 4 (E6-09 review): a create+delete task mutation is
    blocked by ``PLANNING_NOT_DRAFT`` in both preview and confirm, applying nothing in
    either, once the project's displayed planning is no longer a draft.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        standalone = _create_standalone_task(
            client, headers, fixture["project_id"], fixture["estimate_id"], "Standalone"
        )
        standalone_row_id = cast(int, standalone["id"])
        standalone_task_id = cast(int, standalone["task_id"])

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        _validate_displayed_planning(client, headers, fixture["project_id"])

        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Tâches"], "id", standalone_row_id)
        workbook["Tâches"].append(
            [None, None, None, None, None, "Nouvelle tache bloquee", None, None, False]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(issue["code"] == "PLANNING_NOT_DRAFT" for issue in plan["blocking_issues"])
        assert plan["tasks_to_create"] == 1
        assert plan["tasks_to_delete"] == [standalone_row_id]
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "PLANNING_NOT_DRAFT" for issue in confirmed_plan["blocking_issues"]
        )

        task_rows_after = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        rows_after = _items(task_rows_after.json())
        assert any(row["id"] == standalone_row_id for row in rows_after)
        assert not any(row["task_name"] == "Nouvelle tache bloquee" for row in rows_after)
        assert _mstask_exists(standalone_task_id)


def test_reconciliation_import_malformed_file_returns_structured_400() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)

        preview = _preview(
            client, headers, fixture["project_id"], fixture["estimate_id"], b"not an excel file"
        )
        assert preview.status_code == 400
        detail = cast(dict[str, Any], preview.json()["detail"])
        assert detail["code"] == "RECONCILIATION_FORMAT_ERROR"
        assert detail["issues"]

        confirm = _confirm(
            client, headers, fixture["project_id"], fixture["estimate_id"], b"not an excel file"
        )
        assert confirm.status_code == 400
        assert (
            cast(dict[str, Any], confirm.json()["detail"])["code"] == "RECONCILIATION_FORMAT_ERROR"
        )


def test_reconciliation_import_missing_sheet_returns_structured_400() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)

        workbook = Workbook()
        active_sheet = workbook.active
        assert active_sheet is not None
        active_sheet.title = "Tâches"
        workbook["Tâches"].append(
            [
                "id",
                "task_id",
                "task_uid",
                "parent_task_id",
                "position",
                "task_name",
                "outline_number",
                "outline_level",
                "is_milestone",
            ]
        )
        content = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], content)
        assert preview.status_code == 400
        detail = cast(dict[str, Any], preview.json()["detail"])
        assert detail["code"] == "RECONCILIATION_FORMAT_ERROR"
        codes = {issue["code"] for issue in detail["issues"]}
        assert "MISSING_SHEET" in codes


def test_reconciliation_import_rejects_files_over_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding Moyenne #1 (E6-09 review): both endpoints enforce
    ``settings.import_max_upload_bytes`` -- the same size limit already applied to the
    MS Project XML import pipeline (``imports.py``'s own
    ``test_upload_rejects_files_over_configured_limit``) -- with a 413, never buffering
    an oversized upload without limit.
    """
    monkeypatch.setenv("IMPORT_MAX_UPLOAD_BYTES", "8")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            headers = _auth_headers(client)
            fixture = _seed_fixture(client, headers)
            oversized = b"0123456789"

            preview = _preview(
                client, headers, fixture["project_id"], fixture["estimate_id"], oversized
            )
            assert preview.status_code == 413

            confirm = _confirm(
                client, headers, fixture["project_id"], fixture["estimate_id"], oversized
            )
            assert confirm.status_code == 413
    finally:
        get_settings.cache_clear()


def test_reconciliation_import_blank_labor_cost_code_id_does_not_clear_it() -> None:
    """Critical finding (E6-09 round 3 review): a blanked cost_code_id cell on an
    otherwise-changed MO row must not silently reassign the role assignment to the
    project's root cost code -- resolve_cost_code_id's None means "attach to the
    active root", which only applies to a *creation*, never a silent detach from an
    already-set attachment on an update.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        _generate_structure(client, headers, project_id)
        estimate_id = _create_estimate(client, headers, project_id)
        deliverable = _deliverable_task(project_id)
        role_id = _seed_labor_role()
        sub_cost_code_id = _create_sub_cost_code(client, headers, project_id, "LOT-CRIT-MO")

        assignment_id = _create_estimate_role_assignment(
            project_id,
            estimate_id,
            deliverable.uid,
            role_id,
            quantity="2.00",
            hours="10.00",
            cost_code_id=sub_cost_code_id,
        )

        content = _export_workbook(client, headers, project_id, estimate_id)
        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["MO"], "id", assignment_id, "cost_code_id", None)
        # Change something else too, so the row is a genuine update candidate rather
        # than a no-op skipped entirely by the "no actual change" staging guard.
        _set_cell(workbook["MO"], "id", assignment_id, "quantity", 5)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, project_id, estimate_id, edited)
        assert preview.status_code == 200
        assert _plan(preview.json())["blocking_issues"] == []

        confirm = _confirm(client, headers, project_id, estimate_id, edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        updated = _estimate_role_assignment(assignment_id)
        assert updated.cost_code_id == sub_cost_code_id
        assert updated.quantity == Decimal("5.00")


def test_reconciliation_import_blank_cost_line_cost_code_id_does_not_clear_it() -> None:
    """Critical finding (E6-09 round 3 review): same guarantee as above, on the
    Non-MO sheet -- a blanked cost_code_id cell on an otherwise-changed cost line
    must not silently reassign it to the project's root cost code.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        sub_cost_code_id = _create_sub_cost_code(
            client, headers, fixture["project_id"], "LOT-CRIT-NONMO"
        )

        cost_line_response = client.post(
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            json={
                "task_id": fixture["deliverable_id"],
                "cost_category_id": fixture["category_id"],
                "cost_code_id": sub_cost_code_id,
                "label": "Materiel avec code",
                "quantity": "1.00",
                "unit_cost": "10.00",
            },
            headers=headers,
        )
        assert cost_line_response.status_code == 201
        cost_line_id = cast(int, cost_line_response.json()["id"])

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["Non-MO"], "id", cost_line_id, "cost_code_id", None)
        _set_cell(workbook["Non-MO"], "id", cost_line_id, "quantity", 9)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        assert _plan(preview.json())["blocking_issues"] == []

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 200
        assert _plan(confirm.json())["applied"] is True

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        updated = next(item for item in _items(cost_lines.json()) if item["id"] == cost_line_id)
        assert updated["cost_code_id"] == sub_cost_code_id
        assert float(updated["quantity"]) == 9.0


def test_reconciliation_import_task_parent_is_milestone_is_blocking() -> None:
    """Finding Haute #1 (E6-09 round 3 review): a new Tâches row referencing an
    existing milestone as its parent_task_id must be blocked at preview -- exactly
    the invariant ``create_planning_task`` itself enforces
    (``PlanningTreeInvariantError("A milestone cannot contain children")``) -- as a
    structured blocking issue rather than a bare ``HTTPException`` leaking past
    confirm's own ``except`` clauses.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        milestone = _create_standalone_task(
            client,
            headers,
            fixture["project_id"],
            fixture["estimate_id"],
            "Jalon",
            is_milestone=True,
        )
        milestone_task_id = cast(int, milestone["task_id"])

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        workbook["Tâches"].append(
            [None, None, None, milestone_task_id, None, "Sous-tache interdite", None, None, False]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(issue["code"] == "TASK_PARENT_IS_MILESTONE" for issue in plan["blocking_issues"])
        assert plan["tasks_to_create"] == 0
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "TASK_PARENT_IS_MILESTONE"
            for issue in confirmed_plan["blocking_issues"]
        )

        task_rows = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert not any(
            row["task_name"] == "Sous-tache interdite" for row in _items(task_rows.json())
        )


def test_reconciliation_import_task_deletion_referenced_by_new_labor_row_is_blocked() -> None:
    """Finding Haute #2 (E6-09 round 3 review): deleting a Tâches row that isn't
    referenced today, while the same file also stages a brand new MO row against
    that same task_id, must be blocked. Applying deletions before creations (see
    ``_run_reconciliation``'s own docstring) would otherwise violate the new MO
    row's task_id FK once the task disappears first.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        standalone = _create_standalone_task(
            client, headers, fixture["project_id"], fixture["estimate_id"], "Standalone"
        )
        standalone_row_id = cast(int, standalone["id"])
        standalone_task_id = cast(int, standalone["task_id"])
        second_role_id = _seed_labor_role()

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Tâches"], "id", standalone_row_id)
        workbook["MO"].append(
            [
                None,
                standalone_task_id,
                None,
                second_role_id,
                None,
                None,
                None,
                None,
                1,
                3,
                None,
                False,
            ]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(
            issue["code"] == "TASK_DELETE_REFERENCED_BY_NEW_ROW"
            for issue in plan["blocking_issues"]
        )
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "TASK_DELETE_REFERENCED_BY_NEW_ROW"
            for issue in confirmed_plan["blocking_issues"]
        )

        task_rows_after = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert any(row["id"] == standalone_row_id for row in _items(task_rows_after.json()))
        assert _mstask_exists(standalone_task_id)


def test_reconciliation_import_task_deletion_referenced_by_new_cost_line_is_blocked() -> None:
    """Finding Haute #2 (E6-09 round 3 review), symmetric case on the Non-MO sheet."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        standalone = _create_standalone_task(
            client, headers, fixture["project_id"], fixture["estimate_id"], "Standalone"
        )
        standalone_row_id = cast(int, standalone["id"])
        standalone_task_id = cast(int, standalone["task_id"])

        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        _delete_row(workbook["Tâches"], "id", standalone_row_id)
        workbook["Non-MO"].append(
            [
                None,
                standalone_task_id,
                None,
                None,
                fixture["category_id"],
                None,
                None,
                None,
                "Nouvelle ligne sur tache supprimee",
                2,
                20,
                None,
                None,
                None,
            ]
        )
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(
            issue["code"] == "TASK_DELETE_REFERENCED_BY_NEW_ROW"
            for issue in plan["blocking_issues"]
        )
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "TASK_DELETE_REFERENCED_BY_NEW_ROW"
            for issue in confirmed_plan["blocking_issues"]
        )

        task_rows_after = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/task-rows",
            headers,
        )
        assert any(row["id"] == standalone_row_id for row in _items(task_rows_after.json()))
        assert _mstask_exists(standalone_task_id)


def test_reconciliation_import_cost_line_update_blank_category_now_inactive_is_blocking() -> None:
    """Finding Haute #3 (E6-09 round 3 review): a Non-MO row's blank
    cost_category_id cell means "keep the persisted category" -- but if that
    category has since been deactivated, the apply-time
    ``get_non_labor_category_or_400`` call would raise a bare 400 unless the
    same condition is already reported as a blocking issue at staging.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])

        _deactivate_cost_category(fixture["category_id"])

        workbook = load_workbook(BytesIO(content))
        _set_cell(workbook["Non-MO"], "id", fixture["cost_line_id"], "cost_category_id", None)
        _set_cell(workbook["Non-MO"], "id", fixture["cost_line_id"], "quantity", 9)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(
            issue["code"] == "COST_LINE_CATEGORY_INVALID" for issue in plan["blocking_issues"]
        )
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(
            issue["code"] == "COST_LINE_CATEGORY_INVALID"
            for issue in confirmed_plan["blocking_issues"]
        )

        cost_lines = _get(
            client,
            f"/projects/{fixture['project_id']}/estimates/{fixture['estimate_id']}/cost-lines",
            headers,
        )
        unchanged = next(
            item for item in _items(cost_lines.json()) if item["id"] == fixture["cost_line_id"]
        )
        assert float(unchanged["quantity"]) == 1.0


def _mutate_task_name_required(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["Tâches"].append([None, None, None, None, None, None, None, None, False])


def _mutate_task_parent_unresolved(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["Tâches"].append([None, None, None, 999999999, None, "Sans parent", None, None, False])


def _mutate_labor_row_id_unknown(fixture: dict[str, Any], workbook: Workbook) -> None:
    _set_cell(workbook["MO"], "id", fixture["assignment_id"], "id", 999999999)


def _mutate_labor_identity_change_rejected(fixture: dict[str, Any], workbook: Workbook) -> None:
    other_role_id = _seed_labor_role()
    _set_cell(workbook["MO"], "id", fixture["assignment_id"], "role_id", other_role_id)


def _mutate_labor_value_required(fixture: dict[str, Any], workbook: Workbook) -> None:
    _set_cell(workbook["MO"], "id", fixture["assignment_id"], "quantity", None)


def _mutate_labor_cost_code_invalid(fixture: dict[str, Any], workbook: Workbook) -> None:
    _set_cell(workbook["MO"], "id", fixture["assignment_id"], "cost_code_id", 999999999)


def _mutate_labor_row_incomplete(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["MO"].append([None, None, None, None, None, None, None, None, None, None, None, False])


def _mutate_labor_task_invalid(fixture: dict[str, Any], workbook: Workbook) -> None:
    other_role_id = _seed_labor_role()
    workbook["MO"].append(
        [None, 999999999, None, other_role_id, None, None, None, None, 1, 1, None, False]
    )


def _mutate_labor_role_invalid(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["MO"].append(
        [
            None,
            fixture["deliverable_id"],
            None,
            999999999,
            None,
            None,
            None,
            None,
            1,
            1,
            None,
            False,
        ]
    )


def _mutate_labor_duplicate_assignment(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["MO"].append(
        [
            None,
            fixture["deliverable_id"],
            None,
            fixture["role_id"],
            None,
            None,
            None,
            None,
            1,
            1,
            None,
            False,
        ]
    )


def _mutate_cost_line_row_incomplete(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["Non-MO"].append(
        [
            None,
            fixture["deliverable_id"],
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ]
    )


def _mutate_cost_line_task_invalid(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["Non-MO"].append(
        [
            None,
            999999999,
            None,
            None,
            fixture["category_id"],
            None,
            None,
            None,
            "X",
            1,
            1,
            None,
            None,
            None,
        ]
    )


def _mutate_cost_line_category_invalid(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["Non-MO"].append(
        [
            None,
            fixture["deliverable_id"],
            None,
            None,
            999999999,
            None,
            None,
            None,
            "X",
            1,
            1,
            None,
            None,
            None,
        ]
    )


def _mutate_cost_line_cost_code_invalid(fixture: dict[str, Any], workbook: Workbook) -> None:
    workbook["Non-MO"].append(
        [
            None,
            fixture["deliverable_id"],
            None,
            None,
            fixture["category_id"],
            None,
            None,
            999999999,
            "X",
            1,
            1,
            None,
            None,
            None,
        ]
    )


_ERROR_CODE_CASES: list[tuple[str, Callable[[dict[str, Any], Workbook], None]]] = [
    ("TASK_NAME_REQUIRED", _mutate_task_name_required),
    ("TASK_PARENT_UNRESOLVED", _mutate_task_parent_unresolved),
    ("LABOR_ROW_ID_UNKNOWN", _mutate_labor_row_id_unknown),
    ("LABOR_IDENTITY_CHANGE_REJECTED", _mutate_labor_identity_change_rejected),
    ("LABOR_VALUE_REQUIRED", _mutate_labor_value_required),
    ("LABOR_COST_CODE_INVALID", _mutate_labor_cost_code_invalid),
    ("LABOR_ROW_INCOMPLETE", _mutate_labor_row_incomplete),
    ("LABOR_TASK_INVALID", _mutate_labor_task_invalid),
    ("LABOR_ROLE_INVALID", _mutate_labor_role_invalid),
    ("LABOR_DUPLICATE_ASSIGNMENT", _mutate_labor_duplicate_assignment),
    ("COST_LINE_ROW_INCOMPLETE", _mutate_cost_line_row_incomplete),
    ("COST_LINE_TASK_INVALID", _mutate_cost_line_task_invalid),
    ("COST_LINE_CATEGORY_INVALID", _mutate_cost_line_category_invalid),
    ("COST_LINE_COST_CODE_INVALID", _mutate_cost_line_cost_code_invalid),
]


@pytest.mark.parametrize(
    ("expected_code", "mutate"), _ERROR_CODE_CASES, ids=[case[0] for case in _ERROR_CODE_CASES]
)
def test_reconciliation_import_reports_business_rule_error_code(
    expected_code: str, mutate: Callable[[dict[str, Any], Workbook], None]
) -> None:
    """Finding Moyenne #1 (E6-09 round 3 review): every business-rule blocking-issue
    code the three staging functions can raise must be exercised by at least one
    test, in both preview and confirm's own precheck.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        fixture = _seed_fixture(client, headers)
        content = _export_workbook(client, headers, fixture["project_id"], fixture["estimate_id"])
        workbook = load_workbook(BytesIO(content))
        mutate(fixture, workbook)
        edited = _dump_workbook(workbook)

        preview = _preview(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert preview.status_code == 200
        plan = _plan(preview.json())
        assert any(issue["code"] == expected_code for issue in plan["blocking_issues"])
        assert plan["applied"] is False

        confirm = _confirm(client, headers, fixture["project_id"], fixture["estimate_id"], edited)
        assert confirm.status_code == 409
        confirmed_plan = _plan(confirm.json())
        assert confirmed_plan["applied"] is False
        assert any(issue["code"] == expected_code for issue in confirmed_plan["blocking_issues"])
