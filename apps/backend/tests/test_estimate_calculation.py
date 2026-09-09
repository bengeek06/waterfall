"""Tests for estimate calculation engine."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    Calendar,
    CalendarWeekday,
    CostCategory,
    CostRate,
    CostType,
    Estimate,
    EstimateLine,
    EstimateRoleAssignment,
    InflationRate,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)
from waterfall.services.calendar_schedule import resolve_task_calendar_ids
from waterfall.services.estimate_calculation import (
    UNASSIGNED_COST_CODE_LABEL,
    calculate_estimate_aggregates,
)


def _seed_root_cost_code(
    session_factory: sessionmaker[Session], project_id: int, project_name: str
) -> None:
    """Uphold the #62/E6-01 root-cost-code invariant for a project seeded directly
    via the ORM (bypassing POST /projects, which creates it automatically) -- role
    assignment / cost line creation (E6-02/#63) below relies on it always existing."""
    with session_factory() as session:
        session.add(
            ProjectCostCode(
                project_id=project_id,
                parent_id=None,
                code=f"PRJ-{project_id}",
                name=project_name,
            )
        )
        session.commit()


def _auth_headers(client: TestClient, email: str | None = None) -> dict[str, str]:
    email = email or f"estimate.calc.{uuid4().hex}@example.com"
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


def _current_user_id(client: TestClient, headers: dict[str, str]) -> int:
    response: Response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    payload = cast(dict[str, Any], response.json())
    return cast(int, payload["id"])


def _seed_resources_with_rates() -> tuple[int, dict[int, dict[int, Decimal]]]:
    """Create cost categories with rates and inflation."""
    session_factory = get_session_factory()
    with session_factory() as session:
        root = ResourceNode(code="DIRECTION", name="Direction")
        session.add(root)
        session.flush()

        labor_type = CostType(code="MO", name="Main d'oeuvre", kind="labor")
        session.add(labor_type)
        session.flush()

        labor_category = CostCategory(
            cost_type_id=labor_type.id,
            accounting_code="MO-DEV",
            category_code="IDEX",
            name="Développement",
        )
        session.add(labor_category)
        session.flush()

        labor_role = ResourceRole(
            node_id=root.id,
            cost_category_id=labor_category.id,
            name="Développeur",
        )
        session.add(labor_role)
        session.flush()

        # Add rates for 2 years
        rate_2026 = CostRate(
            cost_category_id=labor_category.id,
            year=2026,
            hourly_rate=Decimal("100.00"),
            currency_code="EUR",
        )
        rate_2027 = CostRate(
            cost_category_id=labor_category.id,
            year=2027,
            hourly_rate=Decimal("110.00"),
            currency_code="EUR",
        )
        session.add_all([rate_2026, rate_2027])
        session.flush()

        # Add inflation
        inflation_2026 = InflationRate(year=2026, coefficient=Decimal("1.0"))
        inflation_2027 = InflationRate(year=2027, coefficient=Decimal("1.05"))
        session.add_all([inflation_2026, inflation_2027])
        session.commit()

        rates_by_category = {
            labor_category.id: {
                2026: Decimal("100.00"),
                2027: Decimal("110.00"),
            }
        }
        return labor_role.id, rates_by_category


def _seed_task_role_assignment(
    project_id: int,
    task_uid: int,
    role_id: int,
    quantity: str,
    hours: str,
    *,
    cost_code_id: int | None = None,
    comment: str | None = None,
) -> int:
    """Insert a legacy, project-wide `TaskRoleAssignment` directly via the ORM.

    E12-01 (#273) removed the `/tasks/{uid}/role-assignments` HTTP route this
    module used to create these fixtures through. `calculate_estimate_lines`
    no longer reads `TaskRoleAssignment` at all (E12-02/#274 moved it onto the
    devis-scoped `EstimateRoleAssignment`, see `_seed_estimate_role_assignment`
    below) -- this helper survives only to seed a pre-existing `TaskRoleAssignment`
    a devis validation's project-wide resync
    (`sync_task_role_assignments_from_estimate`) is expected to replace/remove/
    update in place.
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        task = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.uid == task_uid)
            .one()
        )
        assignment = TaskRoleAssignment(
            task_id=task.id,
            role_id=role_id,
            quantity=Decimal(quantity),
            hours=Decimal(hours),
            cost_code_id=cost_code_id,
            comment=comment,
        )
        session.add(assignment)
        session.commit()
        return assignment.id


def _seed_estimate_role_assignment(
    project_id: int,
    estimate_id: int,
    task_uid: int,
    role_id: int,
    quantity: str,
    hours: str,
    *,
    cost_code_id: int | None = None,
    comment: str | None = None,
) -> int:
    """Insert an `EstimateRoleAssignment` directly via the ORM, scoped to `estimate_id`.

    Mirrors `_seed_task_role_assignment` above, but on the devis-scoped table
    `calculate_estimate_lines` reads from since E12-02/#274.
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        task = (
            session.query(MsTask)
            .filter(MsTask.project_id == project_id, MsTask.uid == task_uid)
            .one()
        )
        assignment = EstimateRoleAssignment(
            estimate_id=estimate_id,
            task_id=task.id,
            role_id=role_id,
            quantity=Decimal(quantity),
            hours=Decimal(hours),
            cost_code_id=cost_code_id,
            comment=comment,
        )
        session.add(assignment)
        session.commit()
        return assignment.id


def test_validation_rejects_assignments_outside_estimate_planning_snapshot() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        labor_role_id, _ = _seed_resources_with_rates()
        project = client.post("/projects", json={"name": "Snapshot source"}, headers=headers)
        assert project.status_code == 201
        project_payload = cast(dict[str, Any], project.json())
        project_id = cast(int, project_payload["id"])
        planning = client.post(
            f"/projects/{project_id}/planning-structure",
            json={
                "posts": [
                    {
                        "key": "post",
                        "name": "Post",
                        "lots": [
                            {
                                "key": "lot",
                                "name": "Lot",
                                "deliverables": [{"key": "task", "name": "Task"}],
                            }
                        ],
                    }
                ],
            },
            headers=headers,
        )
        assert planning.status_code == 201

        with get_session_factory()() as session:
            project_model = session.get(MsProject, project_id)
            assert project_model is not None
            extra_task = MsTask(
                project_id=project_id,
                uid=9999,
                name="Outside snapshot",
                task_type=0,
                outline_number="99",
                outline_level=1,
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 8, 0, tzinfo=UTC),
            )
            session.add(extra_task)
            session.commit()

        estimate = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert estimate.status_code == 201
        estimate_payload = cast(dict[str, Any], estimate.json())
        estimate_id = cast(int, estimate_payload["id"])
        _seed_estimate_role_assignment(project_id, estimate_id, 9999, labor_role_id, "1", "10")

        validation = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validation.status_code == 409
        assert validation.json()["detail"] == {"code": "GENERIC_ERROR"}


def test_calculate_labor_lines_spanning_years() -> None:
    """Test that labor hours are distributed uniformly across multiple years."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        labor_role_id, _ = _seed_resources_with_rates()

        session_factory = get_session_factory()
        project_id: int
        task_uid: int
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Calculation Test",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            task = MsTask(
                project_id=project.id,
                uid=1001,
                name="Dev Task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                duration_minutes=None,
                duration_format=None,
                work_minutes=None,
                percent_complete=0,
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add(task)
            session.commit()
            project_id = project.id
            task_uid = task.uid
            project_name = project.name

        _seed_root_cost_code(session_factory, project_id, project_name)

        # Create estimate
        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate = cast(dict[str, Any], create_response.json())
        estimate_id = cast(int, estimate["id"])

        # Add task role assignment
        _seed_estimate_role_assignment(
            project_id, estimate_id, task_uid, labor_role_id, "1", "1000"
        )

        # Validate and trigger calculation
        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        # Verify lines were calculated
        session_factory = get_session_factory()
        with session_factory() as session:
            from waterfall.models.resources import EstimateLine

            lines = (
                session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all()
            )
            assert len(lines) == 1  # Only 2026 (task is entirely in 2026)
            line = lines[0]
            assert line.year == 2026
            assert line.hours == Decimal("1000")
            assert line.hourly_rate == Decimal("100.00")
            # cost = 1 * 1000 * 100.00 * 1.0 = 100000
            assert line.budget_cost == Decimal("100000.00")
            # accounting_code must come from cost_category.accounting_code ("MO-DEV"),
            # never from the role itself (role.name "Développeur" looks nothing like it) -
            # this is the acceptance criterion for issue #46. role_code is derived from
            # role.name (not the removed ResourceRole.code column), so it must equal
            # role.name here too.
            assert line.role_name == "Développeur"
            assert line.role_code == "Développeur"
            assert line.accounting_code == "MO-DEV"


def test_calculate_labor_lines_across_two_years() -> None:
    """Test labor distribution when task spans two years."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        labor_role_id, _ = _seed_resources_with_rates()

        session_factory = get_session_factory()
        project_id: int
        task_uid: int
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Multi-year Test",
                schedule_from_start=True,
                start_date=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2027, 2, 28, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            task = MsTask(
                project_id=project.id,
                uid=2001,
                name="Cross-year Task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2027, 2, 28, 18, 0, tzinfo=UTC),
                duration_minutes=None,
                duration_format=None,
                work_minutes=None,
                percent_complete=0,
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add(task)
            session.commit()
            project_id = project.id
            task_uid = task.uid
            project_name = project.name

        _seed_root_cost_code(session_factory, project_id, project_name)

        # Create estimate
        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate = cast(dict[str, Any], create_response.json())
        estimate_id = cast(int, estimate["id"])

        # Add task role assignment with 1000 total hours
        _seed_estimate_role_assignment(
            project_id, estimate_id, task_uid, labor_role_id, "1", "1000"
        )

        # Validate
        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        # Verify lines were split and calculated
        session_factory = get_session_factory()
        with session_factory() as session:
            from waterfall.models.resources import EstimateLine

            lines = (
                session.query(EstimateLine)
                .filter(EstimateLine.estimate_id == estimate_id)
                .order_by(EstimateLine.year)
                .all()
            )
            assert len(lines) == 2
            # 2026: 500 hours at 100/hr * 1.0 inflation = 50000
            line_2026 = lines[0]
            assert line_2026.year == 2026
            assert line_2026.hours == Decimal("500")
            assert line_2026.hourly_rate == Decimal("100.00")
            assert line_2026.inflation_coefficient == Decimal("1.0")
            assert line_2026.budget_cost == Decimal("50000.00")

            # 2027: 500 hours at 110/hr * 1.05 inflation = 57750
            line_2027 = lines[1]
            assert line_2027.year == 2027
            assert line_2027.hours == Decimal("500")
            assert line_2027.hourly_rate == Decimal("110.00")
            assert line_2027.inflation_coefficient == Decimal("1.05")
            assert line_2027.budget_cost == Decimal("57750.00")


def test_non_labor_cost_lines_create_single_snapshot() -> None:
    """Test that non-labor cost lines (Fourniture/Frais/UO) create snapshot."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        _seed_resources_with_rates()

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Non-labor Test",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            # Create supply type and category
            supply_type = CostType(code="FOURNITURE", name="Fourniture", kind="supply")
            session.add(supply_type)
            session.flush()

            supply_category = CostCategory(
                cost_type_id=supply_type.id,
                accounting_code="FO-CABLE",
                category_code="ACHAT",
                name="Câbles",
            )
            session.add(supply_category)
            session.commit()
            project_id = project.id
            project_name = project.name
            supply_category_id = supply_category.id

        _seed_root_cost_code(session_factory, project_id, project_name)

        # Create estimate
        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate = cast(dict[str, Any], create_response.json())
        estimate_id = cast(int, estimate["id"])

        # Add cost line
        cost_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "cost_category_id": supply_category_id,
                "label": "Câbles réseau",
                "quantity": "5",
                "unit_cost": "25.00",
            },
            headers=headers,
        )
        assert cost_response.status_code == 201

        # Validate
        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        # Verify non-labor snapshot created
        session_factory = get_session_factory()
        with session_factory() as session:
            from waterfall.models.resources import EstimateLine

            lines = (
                session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all()
            )
            assert len(lines) == 1
            line = lines[0]
            assert line.role_id is None
            assert line.budget_cost == Decimal("125.00")  # 5 * 25


def test_calculate_estimate_aggregates_by_cost_code_sums_match_total() -> None:
    """Issue #71 (E6-10): `by_cost_code` must partition `total_unburdened_cost` exactly
    the way `by_category` already does, keyed by `ProjectCostCode.code`. A line with no
    `cost_code_id` (e.g. one validated before #63/E6-02 shipped, see
    `EstimateLine.cost_code_id`'s docstring) must fall back to
    `UNASSIGNED_COST_CODE_LABEL` rather than being dropped or raising."""
    session_factory = get_session_factory()
    with session_factory() as session:
        project = MsProject(
            owner_id=None,
            external_uid=None,
            source_version=2016,
            save_version_out=16,
            name="Cost code aggregates",
            schedule_from_start=True,
            start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
            finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
            calendar_uid=1,
            minutes_per_day=480,
            minutes_per_week=2400,
            days_per_month=20,
            currency_code="EUR",
        )
        session.add(project)
        session.flush()

        root_code = ProjectCostCode(project_id=project.id, parent_id=None, code="ROOT", name="Root")
        session.add(root_code)
        session.flush()
        child_code = ProjectCostCode(
            project_id=project.id, parent_id=root_code.id, code="ROOT.1", name="Child"
        )
        session.add(child_code)
        session.flush()

        estimate = Estimate(
            project_id=project.id,
            version_number=1,
            kind="initial",
            status="draft",
            currency_code="EUR",
        )
        session.add(estimate)
        session.flush()

        def _line(
            cost_code_id: int | None, accounting_code: str, budget_cost: Decimal
        ) -> EstimateLine:
            return EstimateLine(
                estimate_id=estimate.id,
                task_id=None,
                role_id=None,
                cost_code_id=cost_code_id,
                task_name="Line",
                role_code="",
                role_name="",
                accounting_code=accounting_code,
                year=2026,
                quantity=Decimal("1"),
                hours=Decimal("0"),
                hourly_rate=Decimal("0"),
                inflation_coefficient=Decimal("1"),
                budget_cost=budget_cost,
            )

        session.add_all(
            [
                _line(root_code.id, "ACC-A", Decimal("100.00")),
                _line(child_code.id, "ACC-B", Decimal("50.00")),
                _line(None, "ACC-C", Decimal("25.00")),
            ]
        )
        session.commit()
        estimate_id = estimate.id
        root_code_value = root_code.code
        child_code_value = child_code.code

    with session_factory() as session:
        aggregates = calculate_estimate_aggregates(session, estimate_id)

    assert aggregates["by_cost_code"] == {
        root_code_value: Decimal("100.00"),
        child_code_value: Decimal("50.00"),
        UNASSIGNED_COST_CODE_LABEL: Decimal("25.00"),
    }
    assert (
        sum(aggregates["by_cost_code"].values(), Decimal("0"))
        == aggregates["total_unburdened_cost"]
    )


def test_validate_estimate_rejects_missing_cost_rate_and_persists_no_lines() -> None:
    """Issue #175 (E6-11): a labor assignment whose task ends up covering a
    (category, year) combination with no `CostRate` must block validation with a
    409 -- and, crucially, no `EstimateLine` (partial or otherwise) is persisted,
    and the estimate stays a draft.

    The assignment itself is created while the task is still undated (so the
    creation-time guard in `create_task_role_assignment` doesn't apply), then the
    task is scheduled directly at the ORM layer -- a realistic sequence the
    creation-time guard alone can never fully prevent, since a task can always be
    (re)scheduled after its role assignments already exist.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        labor_role_id, _ = _seed_resources_with_rates()  # covers 2026/2027 only

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Missing rate coverage",
                schedule_from_start=True,
                start_date=datetime(2029, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2029, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            task = MsTask(
                project_id=project.id,
                uid=3001,
                name="Uncovered task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add(task)
            session.commit()
            project_id = project.id
            task_uid = task.uid
            project_name = project.name

        _seed_root_cost_code(session_factory, project_id, project_name)

        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate = cast(dict[str, Any], create_response.json())
        estimate_id = cast(int, estimate["id"])

        _seed_estimate_role_assignment(project_id, estimate_id, task_uid, labor_role_id, "1", "100")

        with session_factory() as session:
            scheduled_task = (
                session.query(MsTask)
                .filter(MsTask.project_id == project_id, MsTask.uid == task_uid)
                .one()
            )
            scheduled_task.start_at = datetime(2029, 1, 1, 8, 0, tzinfo=UTC)
            scheduled_task.finish_at = datetime(2029, 6, 30, 18, 0, tzinfo=UTC)
            session.commit()

        with session_factory() as session:
            labor_category_id = (
                session.query(ResourceRole)
                .filter(ResourceRole.id == labor_role_id)
                .one()
                .cost_category_id
            )

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 409
        # Review finding (E6-11/#175): assert on the JSON a real HTTP client
        # actually receives -- previously this only checked the generic
        # `{"code": "GENERIC_ERROR"}` placeholder that
        # `_generic_http_exception_handler` produces for a plain-string
        # `detail`, losing every trace of the missing category/year. The
        # task's single year (2029) is outside the seeded 2026/2027 coverage,
        # so both the `CostRate` and the `InflationRate` are missing for it.
        detail = cast(dict[str, Any], validate_response.json())["detail"]
        assert detail["code"] == "MISSING_RATE_COVERAGE"
        assert detail["missing_cost_rates"] == [
            {
                "category_id": labor_category_id,
                "category_name": "Développement",
                "accounting_code": "MO-DEV",
                "year": 2029,
            }
        ]
        assert detail["missing_inflation_years"] == [2029]

        with session_factory() as session:
            assert (
                session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all()
                == []
            )
            persisted_estimate = session.query(Estimate).filter(Estimate.id == estimate_id).one()
            assert persisted_estimate.status == "draft"


def test_calculate_estimate_lines_lists_every_missing_rate_combination() -> None:
    """Issue #175 (E6-11): `POST .../validate`'s structured `MISSING_RATE_COVERAGE`
    detail lists every missing (category, year) `CostRate` and every missing
    `InflationRate` year found across all assignments -- not just the first one.

    Asserts on the JSON actually returned to an HTTP client (review finding),
    not on an in-memory `ValueError` message: the assignment is seeded directly
    at the ORM layer (a `calculate_estimate_lines` implementation detail --
    exhaustiveness across *years*, not creation-time behavior, is what this test
    covers), but the missing-rate-coverage detail itself is read back from
    `POST .../validate`'s real response.
    """
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Exhaustive missing rates",
                schedule_from_start=True,
                start_date=datetime(2028, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2029, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            root = ResourceNode(code="DIRECTION-MISSING", name="Direction")
            session.add(root)
            session.flush()
            labor_type = CostType(code="MO-MISSING", name="Main d'oeuvre", kind="labor")
            session.add(labor_type)
            session.flush()
            labor_category = CostCategory(
                cost_type_id=labor_type.id,
                accounting_code="MO-DEV-MISSING",
                category_code="IDEX-MISSING",
                name="Développement",
            )
            session.add(labor_category)
            session.flush()
            labor_role = ResourceRole(
                node_id=root.id, cost_category_id=labor_category.id, name="Développeur"
            )
            session.add(labor_role)
            session.flush()

            # A task spanning 2028-2029 -- no CostRate and no InflationRate exist for
            # either year, so both years must be reported for both kinds of gap.
            task = MsTask(
                project_id=project.id,
                uid=5001,
                name="Two uncovered years",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2028, 6, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2029, 6, 30, 18, 0, tzinfo=UTC),
                duration_minutes=None,
                duration_format=None,
                work_minutes=None,
                percent_complete=0,
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add(task)
            session.flush()

            estimate = Estimate(
                project_id=project.id,
                version_number=1,
                kind="initial",
                status="draft",
                currency_code="EUR",
            )
            session.add(estimate)
            session.flush()

            assignment = EstimateRoleAssignment(
                estimate_id=estimate.id,
                task_id=task.id,
                role_id=labor_role.id,
                cost_code_id=None,
                quantity=Decimal("1"),
                hours=Decimal("2000"),
            )
            session.add(assignment)
            session.commit()
            project_id = project.id
            estimate_id = estimate.id
            labor_category_id = labor_category.id

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 409
        detail = cast(dict[str, Any], validate_response.json())["detail"]
        assert detail["code"] == "MISSING_RATE_COVERAGE"
        assert detail["missing_cost_rates"] == [
            {
                "category_id": labor_category_id,
                "category_name": "Développement",
                "accounting_code": "MO-DEV-MISSING",
                "year": 2028,
            },
            {
                "category_id": labor_category_id,
                "category_name": "Développement",
                "accounting_code": "MO-DEV-MISSING",
                "year": 2029,
            },
        ]
        assert detail["missing_inflation_years"] == [2028, 2029]

    with session_factory() as session:
        assert (
            session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all() == []
        )


def test_non_labor_lines_validate_without_any_rate_coverage() -> None:
    """Issue #175 (E6-11): a devis made up only of non-labor (Fourniture/Frais/UO)
    cost lines must never be blocked by the CostRate/InflationRate coverage rule --
    it only ever applies to labor (MO) lines. No CostRate/InflationRate is seeded
    anywhere in this test, on purpose."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Non-labor only",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            supply_type = CostType(code="FOURN-NO-RATE", name="Fourniture", kind="supply")
            session.add(supply_type)
            session.flush()
            supply_category = CostCategory(
                cost_type_id=supply_type.id,
                accounting_code="FO-NO-RATE",
                category_code="ACHAT-NO-RATE",
                name="Câbles",
            )
            session.add(supply_category)
            session.commit()
            project_id = project.id
            project_name = project.name
            supply_category_id = supply_category.id

        _seed_root_cost_code(session_factory, project_id, project_name)

        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate_id = cast(int, create_response.json()["id"])

        cost_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/cost-lines",
            json={
                "cost_category_id": supply_category_id,
                "label": "Câbles réseau",
                "quantity": "5",
                "unit_cost": "25.00",
            },
            headers=headers,
        )
        assert cost_response.status_code == 201

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        with session_factory() as session:
            lines = (
                session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_id).all()
            )
            assert len(lines) == 1
            assert lines[0].budget_cost == Decimal("125.00")
            assert lines[0].role_id is None


def test_validating_one_draft_estimate_ignores_another_drafts_role_assignments() -> None:
    """E12-02 (#274): two draft estimates of the same project may each carry their
    own `EstimateRoleAssignment` for the very same task/role pair (E12-01/#273) --
    validating one must never pull in lines calculated from the other's
    assignments, even when both reference the exact same task and role.

    Also covers the review finding that `get_estimate_validation_warnings` must
    stay isolated the same way: an `EstimateRoleAssignment` on a *different*
    task, carried by another draft estimate of the same project, must never be
    mistaken for coverage of that task in the estimate being validated -- it
    must still be reported as an uncovered-task warning."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        labor_role_id, _ = _seed_resources_with_rates()

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Two drafts isolation",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            task = MsTask(
                project_id=project.id,
                uid=9301,
                name="Shared task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            other_task = MsTask(
                project_id=project.id,
                uid=9302,
                name="Other draft's task",
                task_type=0,
                outline_number="2",
                outline_level=1,
                wbs="2",
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add_all([task, other_task])
            session.commit()
            project_id = project.id
            project_name = project.name
            task_uid = task.uid
            other_task_uid = other_task.uid

        _seed_root_cost_code(session_factory, project_id, project_name)

        create_v1 = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_v1.status_code == 201
        estimate_v1_id = cast(int, create_v1.json()["id"])

        create_v2 = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_v2.status_code == 201
        estimate_v2_id = cast(int, create_v2.json()["id"])

        _seed_estimate_role_assignment(
            project_id, estimate_v1_id, task_uid, labor_role_id, "1", "100"
        )
        _seed_estimate_role_assignment(
            project_id, estimate_v2_id, task_uid, labor_role_id, "1", "9999"
        )
        # v2-only assignment on a task v1 never references: must not falsely
        # "cover" that task for v1's own uncovered-task warning below.
        _seed_estimate_role_assignment(
            project_id, estimate_v2_id, other_task_uid, labor_role_id, "1", "10"
        )

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_v1_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200
        # v1 has no assignment/cost line of its own for other_task -- v2's
        # EstimateRoleAssignment on it must not mask this warning.
        assert validate_response.json()["warnings"] == [
            {"task_uid": other_task_uid, "task_name": "Other draft's task"}
        ]

        with session_factory() as session:
            v1_lines = (
                session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_v1_id).all()
            )
            assert len(v1_lines) == 1
            # Reflects v1's own 100 hours, never v2's differing 9999.
            assert v1_lines[0].hours == Decimal("100")

            v2_lines = (
                session.query(EstimateLine).filter(EstimateLine.estimate_id == estimate_v2_id).all()
            )
            assert v2_lines == []


def test_validate_syncs_project_wide_task_role_assignments_from_this_estimate() -> None:
    """E12-02 (#274): validating a devis makes the project's legacy, project-wide
    `TaskRoleAssignment` reflect this estimate's own `EstimateRoleAssignment` rows
    exactly -- a complete replacement, not an additive merge. A pre-existing
    `TaskRoleAssignment` whose (task_id, role_id) pair is absent from this
    estimate's assignments must be deleted outright, a pair present in the
    estimate but with no `TaskRoleAssignment` counterpart yet must be created,
    and a pair present in both must be updated in place -- same row `id`, new
    `quantity`/`hours`/`cost_code_id`/`comment` (review finding: this branch of
    `sync_task_role_assignments_from_estimate` was previously untested)."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)
        labor_role_id, _ = _seed_resources_with_rates()

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Sync replacement",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            stale_task = MsTask(
                project_id=project.id,
                uid=9401,
                name="Stale task",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            new_task = MsTask(
                project_id=project.id,
                uid=9402,
                name="New task",
                task_type=0,
                outline_number="2",
                outline_level=1,
                wbs="2",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            updated_task = MsTask(
                project_id=project.id,
                uid=9403,
                name="Updated task",
                task_type=0,
                outline_number="3",
                outline_level=1,
                wbs="3",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add_all([stale_task, new_task, updated_task])
            session.commit()

            project_id = project.id
            project_name = project.name
            new_task_id = new_task.id
            new_task_uid = new_task.uid
            stale_task_id = stale_task.id
            stale_task_uid = stale_task.uid
            updated_task_id = updated_task.id
            updated_task_uid = updated_task.uid

        _seed_root_cost_code(session_factory, project_id, project_name)

        with session_factory() as session:
            root_cost_code = (
                session.query(ProjectCostCode)
                .filter(
                    ProjectCostCode.project_id == project_id,
                    ProjectCostCode.parent_id.is_(None),
                )
                .one()
            )
            other_cost_code = ProjectCostCode(
                project_id=project_id,
                parent_id=root_cost_code.id,
                code="SYNC-B",
                name="Other cost code",
            )
            session.add(other_cost_code)
            session.commit()
            root_cost_code_id = root_cost_code.id
            other_cost_code_id = other_cost_code.id

        # Pre-existing project-wide assignment, e.g. from a backfill or an
        # earlier devis validation -- absent from the devis validated below.
        _seed_task_role_assignment(project_id, stale_task_uid, labor_role_id, "1", "50")

        # Pre-existing project-wide assignment on the SAME (task, role) pair as
        # an assignment carried by the devis validated below -- exercises the
        # "update in place" branch of sync_task_role_assignments_from_estimate,
        # as opposed to stale_task (deleted) and new_task (created).
        updated_assignment_id = _seed_task_role_assignment(
            project_id,
            updated_task_uid,
            labor_role_id,
            "1",
            "10",
            cost_code_id=root_cost_code_id,
        )

        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate_id = cast(int, create_response.json()["id"])

        _seed_estimate_role_assignment(
            project_id, estimate_id, new_task_uid, labor_role_id, "2", "80"
        )
        _seed_estimate_role_assignment(
            project_id,
            estimate_id,
            updated_task_uid,
            labor_role_id,
            "5",
            "99",
            cost_code_id=other_cost_code_id,
            comment="x",
        )

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        with session_factory() as session:
            remaining = (
                session.query(TaskRoleAssignment)
                .join(MsTask, TaskRoleAssignment.task_id == MsTask.id)
                .filter(MsTask.project_id == project_id)
                .all()
            )
            remaining_pairs = {(row.task_id, row.role_id) for row in remaining}
            # The stale (task, role) pair is gone; only the validated devis'
            # own pairs remain.
            assert remaining_pairs == {
                (new_task_id, labor_role_id),
                (updated_task_id, labor_role_id),
            }
            assert all(row.task_id != stale_task_id for row in remaining)

            synced = next(row for row in remaining if row.task_id == new_task_id)
            assert synced.quantity == Decimal("2")
            assert synced.hours == Decimal("80")

            updated = next(row for row in remaining if row.task_id == updated_task_id)
            # Same row id: updated in place, never deleted and recreated.
            assert updated.id == updated_assignment_id
            assert updated.quantity == Decimal("5")
            assert updated.hours == Decimal("99")
            assert updated.cost_code_id == other_cost_code_id
            assert updated.comment == "x"


def test_validate_reports_409_when_task_role_assignment_sync_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding (Basse, #274): `validate_project_estimate` must guard its
    call to `sync_task_role_assignments_from_estimate` with the same
    `except IntegrityError` -> 409 pattern every sibling `EstimateRoleAssignment`
    write in this module already follows
    (`create_estimate_role_assignment`/`update_estimate_role_assignment`),
    rather than letting an `IntegrityError` from the resync escape as an
    uncaught 500.

    A genuine unique/FK-constraint violation from the resync itself would
    require a real concurrent writer racing it; monkeypatching the sync
    function to raise for the duration of this one request is the narrower,
    deterministic way to exercise this specific `except` branch (same
    approach as `test_reopen_integrity_conflict_gets_its_own_structured_code`
    in `test_planning_structure.py`)."""
    import waterfall.api.routes.estimates as estimates_route

    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Sync conflict",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.commit()
            project_id = project.id
            project_name = project.name

        _seed_root_cost_code(session_factory, project_id, project_name)

        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate_id = cast(int, create_response.json()["id"])

        def _raise_integrity_error(*_args: object, **_kwargs: object) -> None:
            raise IntegrityError(
                "INSERT INTO wf_task_role_assignment ...", {}, Exception("conflict")
            )

        monkeypatch.setattr(
            estimates_route, "sync_task_role_assignments_from_estimate", _raise_integrity_error
        )
        response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        monkeypatch.undo()

        assert response.status_code == 409
        # A plain-string `detail` is rewritten into this opaque placeholder by
        # `_generic_http_exception_handler` before it reaches an HTTP client
        # (same rationale as `format_missing_rate_message`'s docstring) -- the
        # actionable message only ever appears in application logs.
        assert response.json()["detail"] == {"code": "GENERIC_ERROR"}

        with session_factory() as session:
            estimate = session.query(Estimate).filter(Estimate.id == estimate_id).one()
            # The whole transaction rolled back: the estimate must remain a draft.
            assert estimate.status == "draft"


def test_validate_syncs_task_role_assignments_reflecting_this_estimates_calendars() -> None:
    """E12-02 (#274) end-to-end: after validating a devis, `resolve_task_calendar_ids`
    (`services/calendar_schedule.py`, unchanged and still reading exclusively from
    `TaskRoleAssignment`) resolves each task's calendar from the newly
    synchronized, project-wide `TaskRoleAssignment` rows -- which now mirror this
    devis's own `EstimateRoleAssignment`, keeping planning calendar resolution
    representative of the last officially validated devis."""
    with TestClient(app) as client:
        headers = _auth_headers(client)
        owner_id = _current_user_id(client, headers)

        session_factory = get_session_factory()
        with session_factory() as session:
            project = MsProject(
                owner_id=owner_id,
                external_uid=None,
                source_version=2016,
                save_version_out=16,
                name="Calendar sync",
                schedule_from_start=True,
                start_date=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_date=datetime(2026, 12, 31, 18, 0, tzinfo=UTC),
                calendar_uid=1,
                minutes_per_day=480,
                minutes_per_week=2400,
                days_per_month=20,
                currency_code="EUR",
            )
            session.add(project)
            session.flush()

            calendar_a = Calendar(code="CAL-A", name="Calendar A", weeks_per_year=47)
            calendar_b = Calendar(code="CAL-B", name="Calendar B", weeks_per_year=47)
            session.add_all([calendar_a, calendar_b])
            session.flush()
            session.add_all(
                CalendarWeekday(
                    calendar_id=calendar.id, day_type=day_type, hours_per_day=Decimal("7.00")
                )
                for calendar in (calendar_a, calendar_b)
                for day_type in range(1, 8)
            )

            root = ResourceNode(code="DIRECTION-CAL", name="Direction")
            session.add(root)
            session.flush()
            labor_type = CostType(code="MO-CAL", name="Main d'oeuvre", kind="labor")
            session.add(labor_type)
            session.flush()
            labor_category = CostCategory(
                cost_type_id=labor_type.id,
                accounting_code="MO-DEV-CAL",
                category_code="IDEX",
                name="Développement",
            )
            session.add(labor_category)
            session.flush()
            role_a = ResourceRole(
                node_id=root.id,
                cost_category_id=labor_category.id,
                calendar_id=calendar_a.id,
                name="Role A",
            )
            role_b = ResourceRole(
                node_id=root.id,
                cost_category_id=labor_category.id,
                calendar_id=calendar_b.id,
                name="Role B",
            )
            session.add_all([role_a, role_b])
            session.flush()

            session.add(
                CostRate(
                    cost_category_id=labor_category.id,
                    year=2026,
                    hourly_rate=Decimal("100.00"),
                    currency_code="EUR",
                )
            )
            session.add(InflationRate(year=2026, coefficient=Decimal("1.0")))

            task_a = MsTask(
                project_id=project.id,
                uid=9501,
                name="Task A",
                task_type=0,
                outline_number="1",
                outline_level=1,
                wbs="1",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            task_b = MsTask(
                project_id=project.id,
                uid=9502,
                name="Task B",
                task_type=0,
                outline_number="2",
                outline_level=1,
                wbs="2",
                start_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                finish_at=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                is_summary=False,
                is_milestone=False,
                calendar_uid=1,
            )
            session.add_all([task_a, task_b])
            session.commit()

            project_id = project.id
            project_name = project.name
            task_a_uid = task_a.uid
            task_b_uid = task_b.uid
            role_a_id = role_a.id
            role_b_id = role_b.id
            calendar_a_id = calendar_a.id
            calendar_b_id = calendar_b.id

        _seed_root_cost_code(session_factory, project_id, project_name)

        create_response = client.post(
            f"/projects/{project_id}/estimates",
            json={"kind": "initial", "currency_code": "EUR"},
            headers=headers,
        )
        assert create_response.status_code == 201
        estimate_id = cast(int, create_response.json()["id"])

        _seed_estimate_role_assignment(project_id, estimate_id, task_a_uid, role_a_id, "1", "10")
        _seed_estimate_role_assignment(project_id, estimate_id, task_b_uid, role_b_id, "1", "10")

        validate_response = client.post(
            f"/projects/{project_id}/estimates/{estimate_id}/validate",
            headers=headers,
        )
        assert validate_response.status_code == 200

        with session_factory() as session:
            resolved = resolve_task_calendar_ids(session, project_id, {task_a_uid, task_b_uid})

        assert resolved[task_a_uid] == calendar_a_id
        assert resolved[task_b_uid] == calendar_b_id
