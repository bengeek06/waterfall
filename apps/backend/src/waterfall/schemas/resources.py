from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EstimateKind = Literal["initial", "remaining"]
EstimateStatus = Literal["draft", "validated", "superseded", "archived"]


class CostTypeKind(StrEnum):
    LABOR = "labor"
    SUPPLY = "supply"
    OTHER = "other"


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("must not be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _required_text(value)


class CalendarWeekdayBase(BaseModel):
    day_type: int = Field(ge=1, le=7)
    hours_per_day: Decimal = Field(ge=0, le=24, max_digits=4, decimal_places=2)


class CalendarWeekdayCreate(CalendarWeekdayBase):
    pass


class CalendarWeekdayUpdate(BaseModel):
    hours_per_day: Decimal | None = Field(default=None, ge=0, le=24, max_digits=4, decimal_places=2)


class CalendarWeekdayRead(CalendarWeekdayBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calendar_id: int
    created_at: datetime
    updated_at: datetime


class CalendarBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    weeks_per_year: int = Field(ge=1, le=53)

    _normalize_code = field_validator("code")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class CalendarCreate(CalendarBase):
    weekdays: list[CalendarWeekdayCreate] = Field(default_factory=list, max_length=7)


class CalendarUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    weeks_per_year: int | None = Field(default=None, ge=1, le=53)
    is_active: bool | None = None

    _normalize_code = field_validator("code")(_optional_text)
    _normalize_name = field_validator("name")(_optional_text)


class CalendarRead(CalendarBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ResourceNodeBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)

    _normalize_code = field_validator("code")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class ResourceNodeCreate(ResourceNodeBase):
    parent_id: int | None = Field(default=None, gt=0)


class ResourceNodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    _normalize_code = field_validator("code")(_optional_text)
    _normalize_name = field_validator("name")(_optional_text)


class ResourceNodeRead(ResourceNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ResourceRoleBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)

    _normalize_code = field_validator("code")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class ResourceRoleCreate(ResourceRoleBase):
    node_id: int = Field(gt=0)
    cost_category_id: int = Field(gt=0)
    calendar_id: int | None = Field(default=None, gt=0)


class ResourceRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    node_id: int | None = Field(default=None, gt=0)
    cost_category_id: int | None = Field(default=None, gt=0)
    calendar_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    _normalize_name = field_validator("name")(_optional_text)


class ResourceRoleRead(ResourceRoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_id: int
    cost_category_id: int
    calendar_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CostTypeBase(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    kind: CostTypeKind

    _normalize_code = field_validator("code")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class CostTypeCreate(CostTypeBase):
    pass


class CostTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None

    _normalize_name = field_validator("name")(_optional_text)


class CostTypeRead(CostTypeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CostCategoryBase(BaseModel):
    cost_type_id: int = Field(gt=0)
    accounting_code: str = Field(min_length=1, max_length=64)
    category_code: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)

    _normalize_accounting_code = field_validator("accounting_code")(_required_text)
    _normalize_name = field_validator("name")(_required_text)

    @field_validator("category_code", mode="before")
    @classmethod
    def normalize_category_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CostCategoryCreate(CostCategoryBase):
    pass


class CostCategoryUpdate(BaseModel):
    cost_type_id: int | None = Field(default=None, gt=0)
    accounting_code: str | None = Field(default=None, min_length=1, max_length=64)
    category_code: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None

    _normalize_name = field_validator("name")(_optional_text)
    _normalize_accounting_code = field_validator("accounting_code")(_optional_text)

    @field_validator("category_code", mode="before")
    @classmethod
    def normalize_category_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CostCategoryRead(CostCategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CostRateBase(BaseModel):
    year: int = Field(ge=2000, le=9999)
    hourly_rate: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    currency_code: str = Field(min_length=3, max_length=3)

    @field_validator("currency_code", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: str) -> str:
        return _required_text(value).upper()


class CostRateCreate(CostRateBase):
    cost_category_id: int = Field(gt=0)


class CostRateUpdate(BaseModel):
    hourly_rate: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency_code", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value).upper()


class CostRateRead(CostRateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cost_category_id: int
    created_at: datetime
    updated_at: datetime


class InflationRateBase(BaseModel):
    year: int = Field(ge=2000, le=9999)
    coefficient: Decimal = Field(gt=0, max_digits=12, decimal_places=8)


class InflationRateCreate(InflationRateBase):
    pass


class InflationRateUpdate(BaseModel):
    coefficient: Decimal = Field(gt=0, max_digits=12, decimal_places=8)


class InflationRateRead(InflationRateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class RoleCapacityBase(BaseModel):
    person_count: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    available_hours: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class RoleCapacityCreate(RoleCapacityBase):
    role_id: int = Field(gt=0)


class RoleCapacityUpdate(BaseModel):
    person_count: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    available_hours: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
    )


class RoleCapacityRead(RoleCapacityBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_id: int
    created_at: datetime
    updated_at: datetime


class TaskRoleAssignmentBase(BaseModel):
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    hours: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    comment: str | None = Field(default=None, max_length=10000)


class TaskRoleAssignmentCreate(TaskRoleAssignmentBase):
    task_id: int = Field(gt=0)
    role_id: int = Field(gt=0)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TaskRoleAssignmentUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    hours: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    comment: str | None = Field(default=None, max_length=10000)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TaskRoleAssignmentRead(TaskRoleAssignmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    role_id: int
    created_at: datetime
    updated_at: datetime


class EstimateBase(BaseModel):
    kind: EstimateKind
    currency_code: str = Field(min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=10000)

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_kind(cls, value: str) -> str:
        return _required_text(value).lower()

    @field_validator("currency_code", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: str) -> str:
        return _required_text(value).upper()


class EstimateCreate(EstimateBase):
    project_id: int = Field(gt=0)


class EstimateRead(EstimateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version_number: int
    status: EstimateStatus
    created_at: datetime
    validated_at: datetime | None


class EstimateLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    estimate_id: int
    task_id: int
    role_id: int
    task_name: str
    role_code: str
    role_name: str
    accounting_code: str
    year: int
    quantity: Decimal
    hours: Decimal
    hourly_rate: Decimal
    inflation_coefficient: Decimal
    budget_cost: Decimal
