from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

StructureKind = Literal["poste", "lot", "livrable", "milestone", "task"]


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("must not be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _required_text(value)


class ProjectRead(BaseModel):
    id: int
    name: str
    status: str
    code: str | None
    short_description: str | None
    source_version: int
    save_version_out: int
    schedule_from_start: bool
    start_date: datetime | None
    finish_date: datetime | None
    currency_code: str | None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    short_description: str | None = Field(default=None, max_length=500)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)

    _normalize_name = field_validator("name")(_required_text)
    _normalize_code = field_validator("code")(_optional_text)
    _normalize_short_description = field_validator("short_description")(_optional_text)

    @field_validator("currency_code", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value).upper()


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    short_description: str | None = Field(default=None, max_length=500)

    _normalize_name = field_validator("name")(_optional_text)
    _normalize_code = field_validator("code")(_optional_text)
    _normalize_short_description = field_validator("short_description")(_optional_text)


class TaskRead(BaseModel):
    id: int
    project_id: int
    uid: int
    id_display: int | None
    structure_key: str | None
    structure_kind: StructureKind | None
    parent_uid: int | None
    position: int | None
    name: str
    outline_number: str | None
    outline_level: int | None
    start_at: datetime | None
    finish_at: datetime | None
    percent_complete: int | None
    is_summary: bool
    is_milestone: bool
    is_manual: bool | None
    description: str | None
    predecessor_links: list["TaskLinkRead"] = Field(default_factory=list)


class TaskLinkRead(BaseModel):
    predecessor_uid: int
    link_type: int
    lag_tenth_minute: int | None
    lag_format: int | None


class TaskDescriptionUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=10000)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    parent_task_id: int | None = Field(default=None, gt=0)
    is_milestone: bool = False

    _normalize_name = field_validator("name")(_required_text)


class PlanningDeliverableCreate(BaseModel):
    key: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=512)

    _normalize_key = field_validator("key")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class PlanningLotCreate(BaseModel):
    key: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=512)
    deliverables: list[PlanningDeliverableCreate] = Field(min_length=1)

    _normalize_key = field_validator("key")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class PlanningPostCreate(BaseModel):
    key: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=512)
    lots: list[PlanningLotCreate] = Field(min_length=1)

    _normalize_key = field_validator("key")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class PlanningStructureCreate(BaseModel):
    posts: list[PlanningPostCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_structure_keys(self) -> "PlanningStructureCreate":
        keys: set[str] = set()

        def add_key(key: str) -> None:
            if key in keys:
                raise ValueError(f"Duplicate planning key: {key}")
            keys.add(key)

        for post in self.posts:
            add_key(post.key)
            for lot in post.lots:
                lot_key = f"{post.key}/{lot.key}"
                add_key(lot_key)
                for deliverable in lot.deliverables:
                    add_key(f"{lot_key}/{deliverable.key}")
                add_key(f"{lot_key}/completion")
        return self


class PlanningStructureRead(BaseModel):
    tasks: list[TaskRead]


class PlanningTaskTreeRead(TaskRead):
    children: list["PlanningTaskTreeRead"] = Field(default_factory=list)


class PlanningTreeRead(BaseModel):
    tasks: list[PlanningTaskTreeRead]


class TaskRoleAssignmentCreate(BaseModel):
    role_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    hours: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    comment: str | None = Field(default=None, max_length=10000)

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


class TaskRoleAssignmentRead(BaseModel):
    id: int
    task_id: int
    role_id: int
    role_code: str
    role_name: str
    cost_category_id: int
    accounting_code: str
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

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_kind(cls, value: str) -> str:
        return _required_text(value).lower()

    @field_validator("currency_code", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: str) -> str:
        return _required_text(value).upper()

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


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

    @field_validator("supply_status", mode="before")
    @classmethod
    def normalize_supply_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value).lower()

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return _required_text(value)


class EstimateCostLineUpdate(BaseModel):
    task_id: int | None = Field(default=None, gt=0)
    cost_category_id: int | None = Field(default=None, gt=0)
    label: str | None = Field(default=None, min_length=1, max_length=512)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    supply_status: SupplyStatus | None = None

    @field_validator("supply_status", mode="before")
    @classmethod
    def normalize_supply_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value).lower()

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value)


class EstimateCostLineRead(BaseModel):
    id: int
    estimate_id: int
    task_id: int | None
    cost_type_id: int
    cost_category_id: int
    cost_type_code: str
    accounting_code: str
    category_code: str | None
    label: str
    quantity: Decimal
    unit_cost: Decimal
    purchase_cost: Decimal
    supply_status: SupplyStatus | None


class EstimateAggregatesRead(BaseModel):
    total_labor_cost: Decimal
    total_purchase_cost: Decimal
    total_unburdened_cost: Decimal
    by_category: dict[str, Decimal]
