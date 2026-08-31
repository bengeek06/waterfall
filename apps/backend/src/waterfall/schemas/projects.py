from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

StructureKind = Literal["poste", "lot", "livrable", "milestone", "task"]
ProjectStatus = Literal[
    "cree",
    "initialise",
    "en_reponse_appel_offre",
    "perdu",
    "en_cours",
    "termine",
    "abandonne",
]


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
    status: ProjectStatus
    code: str | None
    short_description: str | None
    source_version: int
    save_version_out: int
    schedule_from_start: bool
    start_date: datetime | None
    finish_date: datetime | None
    currency_code: str | None
    planning_reference_id: int | None
    displayed_planning_id: int | None
    reference_estimate_id: int | None


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
    status: ProjectStatus | None = None

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
    duration_minutes: int | None
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


class PlanningLinkRead(TaskLinkRead):
    task_uid: int


# MSPDI LagFormat legal values (see waterfall.services.planning_tree's own
# documentation of this same enumeration, sourced from the bundled MS Project
# schema). Constrained here -- not just range-bound to the SmallInteger
# storage column -- so an out-of-domain value is rejected as a 400 instead of
# reaching the database as a syntactically valid but meaningless code.
MspdiLagFormat = Literal[
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 19, 20, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 51, 52
]


class TaskLinkWrite(BaseModel):
    predecessor_uid: int = Field(ge=1)
    link_type: int = Field(ge=0, le=3)
    # Bounded to fit wf_planning_link_snapshot.lag_tenth_minute (PostgreSQL Integer),
    # so an out-of-range value is rejected as a 400 instead of reaching the database
    # as an uncaught DataError (see models/planning.py).
    lag_tenth_minute: int | None = Field(default=None, ge=-2_147_483_648, le=2_147_483_647)
    lag_format: MspdiLagFormat | None = None


class TaskLinksReplace(BaseModel):
    links: list[TaskLinkWrite]


class TaskDescriptionUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=10000)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


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


class PlanningStructureDraftRead(BaseModel):
    planning_id: int
    structure: PlanningStructureCreate


class PlanningRead(BaseModel):
    id: int
    project_id: int
    version_number: int
    status: Literal["draft", "validated", "superseded"]
    note: str | None
    created_at: datetime
    validated_at: datetime | None


class PlanningDetailRead(PlanningRead):
    tasks: list[TaskRead]
    links: list["PlanningLinkRead"]


class PlanningCreate(BaseModel):
    note: str | None = Field(default=None, max_length=10000)
    source_planning_id: int | None = Field(default=None, gt=0)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PlanningTaskMove(BaseModel):
    task_uids: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)
    target_parent_uid: int | None = Field(default=None, gt=0)
    position: int = Field(ge=1)


class PlanningTaskCreate(BaseModel):
    """Create a single task at an explicit position within a draft planning (E3-05).

    Absence of both ``target_parent_uid`` and ``insert_after_uid`` places the
    new task as the first child of the targeted parent, or -- when
    ``target_parent_uid`` is also absent -- the first root task.
    """

    name: str = Field(min_length=1, max_length=512)
    is_milestone: bool = False
    target_parent_uid: int | None = Field(default=None, gt=0)
    insert_after_uid: int | None = Field(default=None, gt=0)

    _normalize_name = field_validator("name")(_required_text)


class PlanningTaskDelete(BaseModel):
    task_uids: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)
    confirm_cascade: bool = False


class PlanningTaskDeleteConflictDetail(BaseModel):
    """Structured 409 body for ``delete_planning_tasks_route`` (E3-05).

    ``code`` discriminates the two conflict causes raised by
    ``delete_planning_tasks``: ``CASCADE_CONFIRMATION_REQUIRED`` populates
    ``descendant_uids`` (every descendant that would be removed alongside the
    selection), ``TASK_REFERENCED`` populates ``task_uids`` (every uid in the
    selection, or its to-be-cascaded descendants, still referenced by an
    estimate, an assignment, or a charge). The two fields are mutually
    exclusive in practice but both declared optional since the shared schema
    covers either cause.
    """

    code: Literal["CASCADE_CONFIRMATION_REQUIRED", "TASK_REFERENCED"]
    descendant_uids: list[int] | None = None
    task_uids: list[int] | None = None


class PlanningTaskDeleteConflict(BaseModel):
    detail: PlanningTaskDeleteConflictDetail


class PlanningTaskScheduleUpdate(BaseModel):
    """Manual/automatic scheduling edit for a single draft planning task (E3-03).

    ``is_manual`` is required: this endpoint's purpose is to switch (or
    confirm) a task's scheduling mode, so the target mode must always be
    stated explicitly rather than defaulted. ``start_at``/``finish_at``/
    ``duration_minutes`` are optional because their requiredness depends on
    the task's mode and structural flags (manual/automatic/milestone), which
    is validated server-side in ``waterfall.services.planning_tree`` -- not
    at the schema level, since it cannot be expressed as a static per-field
    rule.
    """

    is_manual: bool
    start_at: datetime | None = None
    finish_at: datetime | None = None
    # Upper-bounded at 15 years in minutes (365 * 24 * 60 = 525_600 per year,
    # * 15 = 7_884_000): far beyond any realistic single planning task's
    # duration, but well under the limits that would otherwise be reachable
    # with an unbounded value -- e.g. exceeding the PostgreSQL ``INTEGER``
    # column's ~2.1 billion range on ``flush()``.
    #
    # This bound alone does *not* cap how long ``compute_finish_at``/
    # ``compute_start_at`` (``waterfall.services.calendar_schedule``) can
    # spend walking the calendar day by day: ``duration_minutes`` counts
    # *working* minutes, not calendar minutes, and a legally configured
    # calendar can have an arbitrarily small non-zero capacity (down to 1
    # minute/day once rounded) on as little as a single weekday per week.
    # Consuming even a modest ``duration_minutes`` against such a calendar
    # would need millions of day-by-day loop iterations. That risk is
    # guarded directly inside those functions' loops (see
    # ``_MAX_CALENDAR_DAYS_WALKED``/``_guard_max_days_walked`` in
    # ``calendar_schedule.py``), independently of this schema-level bound,
    # which remains useful on its own (integer overflow, obviously
    # unreasonable input) but is not sufficient by itself.
    duration_minutes: int | None = Field(default=None, ge=0, le=7_884_000)

    @field_validator("start_at", "finish_at", mode="after")
    @classmethod
    def _drop_tzinfo(cls, value: datetime | None) -> datetime | None:
        """Normalize to a naive UTC datetime, matching the storage convention
        already used for ``WfPlanningTaskSnapshot.start_at``/``finish_at``
        (populated as naive wall-clock values by the MS Project XML import,
        see ``waterfall.services.msproject_xml._datetime``). Without this,
        an offset-aware value parsed from a client-supplied ``...Z`` payload
        could not be compared (``min``/``max``) against a sibling task's
        naive value freshly reloaded from the database in the same request.
        """
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value


class FastAPIErrorResponse(BaseModel):
    detail: str | list[dict[str, object]]


class ProjectStatusUpdate(BaseModel):
    status: ProjectStatus


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
    planning_id: int | None
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
    task_id: int | None = None
    parent_task_id: int | None = None
    position: int
    task_name: str
    outline_number: str | None = None
    outline_level: int | None = None
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
