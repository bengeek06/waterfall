"""Tests for estimate calculation engine."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsProject, MsTask
from waterfall.models.resources import (
    CostCategory,
    CostRate,
    CostType,
    InflationRate,
    ResourceNode,
    ResourceRole,
)


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
            code="DEV",
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
                id_display=1,
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
        assign_response = client.post(
            f"/projects/{project_id}/tasks/{task_uid}/role-assignments",
            json={"role_id": labor_role_id, "quantity": "1", "hours": "1000"},
            headers=headers,
        )
        assert assign_response.status_code == 201

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
                id_display=1,
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
        assign_response = client.post(
            f"/projects/{project_id}/tasks/{task_uid}/role-assignments",
            json={"role_id": labor_role_id, "quantity": "1", "hours": "1000"},
            headers=headers,
        )
        assert assign_response.status_code == 201

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
            supply_category_id = supply_category.id

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
