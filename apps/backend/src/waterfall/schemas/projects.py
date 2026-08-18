from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ProjectRead(BaseModel):
    id: int
    name: str
    source_version: int
    save_version_out: int
    schedule_from_start: bool
    start_date: datetime | None
    finish_date: datetime | None
    currency_code: str | None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TaskRead(BaseModel):
    id: int
    project_id: int
    uid: int
    id_display: int | None
    name: str
    outline_number: str | None
    outline_level: int | None
    start_at: datetime | None
    finish_at: datetime | None
    percent_complete: int | None
    is_summary: bool
    is_milestone: bool
    description: str | None


class TaskDescriptionUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=10000)


class TaskRoleAssignmentCreate(BaseModel):
    role_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    hours: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    comment: str | None = Field(default=None, max_length=10000)


class TaskRoleAssignmentUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    hours: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    comment: str | None = Field(default=None, max_length=10000)


class TaskRoleAssignmentRead(BaseModel):
    id: int
    task_id: int
    role_id: int
    role_code: str
    role_name: str
    cost_category_id: int
    cost_category_code: str
    quantity: Decimal
    hours: Decimal
    comment: str | None
    created_at: datetime
    updated_at: datetime


class ProjectEstimateCreate(BaseModel):
    kind: str = Field(pattern="^(initial|contract_reference|forecast_remaining)$")
    currency_code: str = Field(min_length=3, max_length=3)
    reference_estimate_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=10000)


class ProjectEstimateRead(BaseModel):
    id: int
    project_id: int
    reference_estimate_id: int | None
    version_number: int
    kind: str
    status: str
    currency_code: str
    created_at: datetime
    validated_at: datetime | None
    note: str | None


class EstimateTaskRowRead(BaseModel):
    id: int
    estimate_id: int
    task_id: int
    parent_task_id: int | None
    position: int
    task_name: str
    outline_number: str | None
    outline_level: int | None
    is_milestone: bool


SupplyStatus = Literal["planned", "ordered", "received", "cancelled"]


class EstimateCostLineCreate(BaseModel):
    task_id: int | None = Field(default=None, gt=0)
    cost_category_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    unit_cost: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    supply_status: SupplyStatus | None = None


class EstimateCostLineUpdate(BaseModel):
    task_id: int | None = Field(default=None, gt=0)
    cost_category_id: int | None = Field(default=None, gt=0)
    label: str | None = Field(default=None, min_length=1, max_length=512)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    supply_status: SupplyStatus | None = None


class EstimateCostLineRead(BaseModel):
    id: int
    estimate_id: int
    task_id: int | None
    cost_type_id: int
    cost_category_id: int
    cost_type_code: str
    cost_category_code: str
    accounting_code: str | None
    label: str
    quantity: Decimal
    unit_cost: Decimal
    purchase_cost: Decimal
    supply_status: SupplyStatus | None
