"""Tests for estimate calculation engine."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session, sessionmaker

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    CostType,
    Estimate,
    EstimateLine,
    InflationRate,
    ProjectCostCode,
    ResourceNode,
    ResourceRole,
    TaskRoleAssignment,
)
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
    project_id: int, task_uid: int, role_id: int, quantity: str, hours: str
) -> int:
    """Insert a `TaskRoleAssignment` directly via the ORM.

    E12-01 (#273) removed the `/tasks/{uid}/role-assignments` HTTP route this
    module used to create these fixtures through; `TaskRoleAssignment` (and
    `calculate_estimate_lines`'s own reading of it, unaffected by that issue) is
    untouched, so this reaches directly into the DB instead of going through a
    route that no longer exists.
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
        _seed_task_role_assignment(project_id, 9999, labor_role_id, "1", "10")

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
        _seed_task_role_assignment(project_id, task_uid, labor_role_id, "1", "1000")

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
        _seed_task_role_assignment(project_id, task_uid, labor_role_id, "1", "1000")

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

        _seed_task_role_assignment(project_id, task_uid, labor_role_id, "1", "100")

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

            assignment = TaskRoleAssignment(
                task_id=task.id,
                role_id=labor_role.id,
                cost_code_id=None,
                quantity=Decimal("1"),
                hours=Decimal("2000"),
            )
            session.add(assignment)

            estimate = Estimate(
                project_id=project.id,
                version_number=1,
                kind="initial",
                status="draft",
                currency_code="EUR",
            )
            session.add(estimate)
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
