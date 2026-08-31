from decimal import Decimal

import pytest
from pydantic import ValidationError

from waterfall.schemas.projects import (
    EstimateCostLineCreate,
    EstimateCostLineUpdate,
    PlanningTaskCreate,
    ProjectCreate,
    ProjectEstimateCreate,
    ProjectUpdate,
    TaskDescriptionUpdate,
)
from waterfall.schemas.resources import (
    CalendarCreate,
    CalendarWeekdayCreate,
    CostCategoryCreate,
    CostCategoryUpdate,
    CostRateCreate,
    CostRateUpdate,
    InflationRateCreate,
    ResourceNodeCreate,
    ResourceNodeUpdate,
    TaskRoleAssignmentCreate,
    TaskRoleAssignmentUpdate,
)


def test_calendar_schemas_accept_boundary_values() -> None:
    calendar = CalendarCreate(
        code="  STANDARD  ",
        name="  Standard  ",
        weeks_per_year=47,
        weekdays=[
            CalendarWeekdayCreate(day_type=day_type, hours_per_day=Decimal("7.00"))
            for day_type in range(2, 7)
        ],
    )

    assert calendar.code == "STANDARD"
    assert calendar.name == "Standard"
    assert len(calendar.weekdays) == 5
    assert CalendarWeekdayCreate(day_type=1, hours_per_day=Decimal("0")).hours_per_day == 0
    assert CalendarWeekdayCreate(day_type=7, hours_per_day=Decimal("24")).hours_per_day == 24
    assert CalendarCreate(code="MIN", name="Min", weeks_per_year=1).weeks_per_year == 1
    assert CalendarCreate(code="MAX", name="Max", weeks_per_year=53).weeks_per_year == 53


def test_calendar_schemas_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        CalendarWeekdayCreate(day_type=0, hours_per_day=Decimal("7"))

    with pytest.raises(ValidationError):
        CalendarWeekdayCreate(day_type=8, hours_per_day=Decimal("7"))

    with pytest.raises(ValidationError):
        CalendarWeekdayCreate(day_type=2, hours_per_day=Decimal("-1"))

    with pytest.raises(ValidationError):
        CalendarWeekdayCreate(day_type=2, hours_per_day=Decimal("24.01"))

    with pytest.raises(ValidationError):
        CalendarCreate(code="KO", name="Ko", weeks_per_year=0)

    with pytest.raises(ValidationError):
        CalendarCreate(code="KO", name="Ko", weeks_per_year=54)

    with pytest.raises(ValidationError):
        CalendarCreate(code="   ", name="Ko", weeks_per_year=47)


def test_resource_schema_normalizes_text_values() -> None:
    node = ResourceNodeCreate(code="  IT  ", name="  Informatique  ")
    rate = CostRateCreate(
        cost_category_id=1,
        year=2026,
        hourly_rate=Decimal("100"),
        currency_code=" eur ",
    )

    assert node.code == "IT"
    assert node.name == "Informatique"
    assert rate.currency_code == "EUR"


def test_resource_schema_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        InflationRateCreate(year=2026, coefficient=Decimal("0"))

    with pytest.raises(ValidationError):
        TaskRoleAssignmentCreate(
            task_id=1,
            role_id=1,
            quantity=Decimal("0"),
            hours=Decimal("10"),
        )


def test_resource_update_schemas_allow_optional_fields_to_remain_none() -> None:
    node = ResourceNodeUpdate(code="  IT  ", name=None, parent_id=None, is_active=True)
    category = CostCategoryUpdate(name=None, accounting_code=None, is_active=False)
    rate = CostRateUpdate(hourly_rate=Decimal("120"), currency_code=None)

    assert node.code == "IT"
    assert node.name is None
    assert category.name is None
    assert category.accounting_code is None
    assert rate.hourly_rate == Decimal("120")
    assert rate.currency_code is None


def test_project_schema_normalizes_and_rejects_blank_input() -> None:
    project = ProjectCreate(
        name="  Nouveau projet  ",
        code="  PRJ  ",
        short_description="  Description  ",
        currency_code=" eur ",
    )
    update = ProjectUpdate(
        name="  Mise à jour  ",
        code="  MOD  ",
        short_description="  Texte  ",
    )
    estimate = ProjectEstimateCreate(
        kind=" Initial ",
        currency_code=" usd ",
        note="  Budget initial  ",
    )
    description = TaskDescriptionUpdate(description="  Commentaire  ")
    line = EstimateCostLineCreate.model_validate(
        {
            "task_id": 1,
            "cost_category_id": 2,
            "label": "  Ligne de charge  ",
            "quantity": Decimal("2"),
            "unit_cost": Decimal("10"),
            "supply_status": " Planned ",
        }
    )
    line_update = EstimateCostLineUpdate(label="  Ligne modifiée  ")
    assignment_update = TaskRoleAssignmentUpdate(comment="  Commentaire de mission  ")
    assignment_create = TaskRoleAssignmentCreate(
        task_id=1,
        role_id=2,
        quantity=Decimal("1"),
        hours=Decimal("10"),
        comment="  Commentaire de création  ",
    )
    category = CostCategoryCreate(
        cost_type_id=1,
        accounting_code="  MO-DEV  ",
        category_code="  DEV  ",
        name="  Développement  ",
    )
    category_update = CostCategoryUpdate(category_code="  MAJ  ")
    task = PlanningTaskCreate(name="  Nouvelle tâche  ", is_milestone=True)
    task_assignment = TaskRoleAssignmentCreate(
        task_id=1,
        role_id=2,
        quantity=Decimal("1"),
        hours=Decimal("10"),
        comment="  Commentaire tâche  ",
    )

    assert project.name == "Nouveau projet"
    assert project.code == "PRJ"
    assert project.short_description == "Description"
    assert project.currency_code == "EUR"
    assert update.name == "Mise à jour"
    assert update.code == "MOD"
    assert update.short_description == "Texte"
    assert estimate.kind == "initial"
    assert estimate.currency_code == "USD"
    assert estimate.note == "Budget initial"
    assert description.description == "Commentaire"
    assert line.label == "Ligne de charge"
    assert line.supply_status == "planned"
    assert line_update.label == "Ligne modifiée"
    assert assignment_update.comment == "Commentaire de mission"
    assert assignment_create.comment == "Commentaire de création"
    assert category.accounting_code == "MO-DEV"
    assert category.category_code == "DEV"
    assert category_update.category_code == "MAJ"
    assert task.name == "Nouvelle tâche"
    assert task_assignment.comment == "Commentaire tâche"

    with pytest.raises(ValidationError):
        ProjectCreate(name="   ", code="PRJ", currency_code="EUR")
