from decimal import Decimal

import pytest
from pydantic import ValidationError

from waterfall.schemas.resources import (
    CostRateCreate,
    InflationRateCreate,
    ResourceNodeCreate,
    TaskRoleAssignmentCreate,
)


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
