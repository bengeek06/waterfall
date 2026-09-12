from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from waterfall.schemas.pagination import PaginatedList

# The one definition of the MSPDI `LagFormat` enumeration, imported rather than
# restated: this module used to carry its own copy, derived from the *documentation*
# of the bundled MS Project schema instead of its normative ``xsd:enumeration`` list,
# and therefore missing 53 (#331 review, M1). Two copies would have to be corrected
# twice; this one dies with the legacy routes at E14-12 (#339), the other stays.
from waterfall.schemas.revisions import MspdiLagFormat

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
    minutes_per_day: int
    minutes_per_week: int
    days_per_month: int
    currency_code: str | None
    planning_reference_id: int | None
    displayed_planning_id: int | None
    reference_estimate_id: int | None


class ProjectListRead(PaginatedList[ProjectRead]):
    pass


class ProjectSetupWarningCode(StrEnum):
    """Issue #109: a missing global setup prerequisite for project creation.

    Deliberately limited to the 3 prerequisites the issue lists as
    verifiable at project-creation time (a usable default calendar, at
    least one active cost category, at least one active resource role).
    ``CostRate``/``InflationRate`` and ``RoleCapacity`` are explicitly out of
    scope (see the issue: not meaningfully verifiable before a project has
    tasks, or not consumed by any cost/scheduling calculation yet).
    """

    NO_DEFAULT_CALENDAR = "no_default_calendar"
    DEFAULT_CALENDAR_HAS_NO_WORKING_DAY = "default_calendar_has_no_working_day"
    NO_ACTIVE_COST_CATEGORY = "no_active_cost_category"
    NO_ACTIVE_RESOURCE_ROLE = "no_active_resource_role"


class ProjectSetupWarning(BaseModel):
    code: ProjectSetupWarningCode
    message: str = Field(
        description=(
            "English diagnostic text, not localized and not meant for direct display. "
            "Callers must always branch on `code` to pick their own user-facing "
            "(French) message -- same principle as issue #137 for "
            "`HTTPException.detail` -- rather than rendering this field verbatim."
        )
    )


class ProjectSetupWarningsRead(BaseModel):
    warnings: list[ProjectSetupWarning]


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
    row_number: int = Field(
        description=(
            "Rank of the task in the planning's current display order (flattened "
            "depth-first walk, siblings sorted the same way as `outline_number`). "
            "Recomputed on every read, never stored -- it changes whenever the task "
            "is moved, reparented, or another task is created/deleted ahead of it. "
            "Read-only: this field cannot be set by clients."
        )
    )
    structure_key: str | None
    structure_kind: StructureKind | None
    parent_uid: int | None
    position: int | None
    name: str
    outline_number: str | None
    outline_level: int | None
    wbs: str | None
    start_at: datetime | None
    finish_at: datetime | None
    duration_minutes: int | None
    duration_format: int | None
    work_minutes: int | None
    task_type: int | None
    percent_complete: int | None
    is_summary: bool
    is_milestone: bool
    is_manual: bool | None
    calendar_uid: int | None
    description: str | None
    predecessor_links: list["TaskLinkRead"] = Field(default_factory=list)


# Unreferenced since E14-05 (#331) removed the legacy planning task listing; kept,
# like the rest of the legacy planning payloads, until E14-12 (#339) sweeps them out
# together with the routes and services they belonged to.
class TaskListRead(PaginatedList[TaskRead]):
    pass


class TaskLinkRead(BaseModel):
    predecessor_uid: int
    link_type: int
    lag_tenth_minute: int | None
    lag_format: int | None


class PlanningLinkRead(TaskLinkRead):
    task_uid: int


class TaskLinkWrite(BaseModel):
    predecessor_uid: int = Field(ge=1)
    link_type: int = Field(ge=0, le=3)
    # Bounded to fit wf_planning_link_snapshot.lag_tenth_minute (PostgreSQL Integer),
    # so an out-of-range value is rejected as a 400 instead of reaching the database
    # as an uncaught DataError (see models/planning.py).
    lag_tenth_minute: int | None = Field(default=None, ge=-2_147_483_648, le=2_147_483_647)
    lag_format: MspdiLagFormat | None = None


# Unreferenced since E14-05 (#331) replaced `PUT .../tasks/{uid}/links` with the
# revision's own `PUT .../nodes/{id}/predecessors`; kept until E14-12 (#339), like
# `TaskLinkWrite` above, which is still served by `estimates` and `planning_links`.
class TaskLinksReplace(BaseModel):
    links: list[TaskLinkWrite]
    expected_revision: int = Field(ge=0)


class TaskUpdate(BaseModel):
    """`PATCH .../tasks/{task_uid}` (issue #290, E12-08, extends the pre-existing
    description-only endpoint with `name`).

    ``description`` keeps its pre-existing "always applied" semantics (an
    absent/blank value clears it -- see ``normalize_description`` below,
    unchanged since before E12-08): it is the endpoint's original, only field,
    and every caller of this schema already always supplies it. ``name`` is
    genuinely optional -- ``None`` means "leave the task's name untouched",
    never "clear the name" (`MsTask.name`/`WfPlanningTaskSnapshot.name` are
    both `NOT NULL`), so it deliberately does *not* reuse
    ``normalize_description``'s blank-clears-to-``None`` behaviour: a blank
    ``name`` is rejected outright by ``_optional_text`` instead.
    """

    description: str | None = Field(default=None, max_length=10000)
    name: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    _normalize_name = field_validator("name")(_optional_text)


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
    revision: int
    note: str | None
    created_at: datetime
    validated_at: datetime | None


class PlanningListRead(PaginatedList[PlanningRead]):
    pass


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
    expected_revision: int = Field(ge=0)


class PlanningTaskSnapshotWrite(BaseModel):
    """One task's full raw state for :class:`PlanningSnapshotRestore` (E4-01 undo/redo).

    Mirrors every field of ``WfPlanningTaskSnapshot`` the client can already see
    via ``TaskRead`` (plus the raw ``notes``, not exposed as ``description`` on
    reads for no particular reason other than naming): values are restored
    verbatim, never recalculated, since they were already valid when the
    server originally computed and returned them. Deliberately excludes
    ``TaskRead.row_number``: it is never stored on ``WfPlanningTaskSnapshot`` and
    is always recomputed at read time (see #147/E9-02), so there is nothing to
    restore verbatim here.
    """

    uid: int = Field(ge=1)
    structure_key: str | None = Field(max_length=128)
    structure_kind: StructureKind | None
    parent_uid: int | None = Field(gt=0)
    position: int | None = Field(gt=0)
    name: str = Field(min_length=1, max_length=512)
    outline_number: str | None = Field(max_length=512)
    outline_level: int | None
    wbs: str | None = Field(max_length=255)
    start_at: datetime | None
    finish_at: datetime | None
    duration_minutes: int | None = Field(ge=0)
    duration_format: int | None
    work_minutes: int | None = Field(ge=0)
    task_type: int | None = Field(ge=0, le=2)
    percent_complete: int | None = Field(ge=0, le=100)
    is_summary: bool
    is_milestone: bool
    is_manual: bool | None
    calendar_uid: int | None
    # Unbounded, unlike most other free-text fields here: imported MSPDI Notes are stored
    # in an unbounded Text column (wf_planning_task_snapshot.notes), so a snapshot captured
    # from a legitimately imported planning can already exceed a smaller limit -- this must
    # round-trip whatever the server can already return, not impose a stricter one.
    notes: str | None


class PlanningLinkSnapshotWrite(BaseModel):
    """Link state for undo/redo restore. All fields required (null is explicit)."""

    task_uid: int = Field(ge=1)
    predecessor_uid: int = Field(ge=1)
    link_type: int = Field(ge=0, le=3)
    lag_tenth_minute: int | None = Field(ge=-2_147_483_648, le=2_147_483_647)
    # Unlike TaskLinkWrite (validated MSPDI import), this must round-trip whatever
    # PlanningLinkRead can already return, including a legacy-imported value outside
    # the MspdiLagFormat enum (TaskLinkRead itself exposes lag_format as a plain
    # integer for exactly that reason).
    lag_format: int | None


class PlanningSnapshotRestore(BaseModel):
    """Full-state restore payload driving undo/redo (E4-01): replaces every task and
    link of a draft planning with exactly the given lists -- the same complete
    ``tasks``/``links`` shape the client already received from a previous response
    (either before or after the mutation being undone/redone), so replaying it back
    restores that exact prior state instead of recomputing an approximation.

    Both lists are required (no default): since this endpoint replaces the *entire*
    planning, an omitted list cannot mean "leave unchanged" -- it must be an explicit,
    deliberate empty list instead, so a caller can never wipe a planning by mistake.
    """

    tasks: list[PlanningTaskSnapshotWrite]
    links: list[PlanningLinkSnapshotWrite]
    expected_revision: int = Field(ge=0)


class PlanningTaskCreate(BaseModel):
    """Create a single task at an explicit position within a draft planning (E3-05).

    Absence of ``insert_after_uid`` places the new task as the first child of
    ``target_parent_uid`` -- or, when ``target_parent_uid`` is itself absent,
    as the first root task.
    """

    name: str = Field(min_length=1, max_length=512)
    is_milestone: bool = False
    target_parent_uid: int | None = Field(default=None, gt=0)
    insert_after_uid: int | None = Field(default=None, gt=0)
    expected_revision: int = Field(ge=0)

    _normalize_name = field_validator("name")(_required_text)


class PlanningTaskDelete(BaseModel):
    task_uids: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)
    confirm_cascade: bool = False
    expected_revision: int = Field(ge=0)


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
    expected_revision: int = Field(ge=0)
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
    detail: str | dict[str, object] | list[dict[str, object]]


class ProjectStatusUpdate(BaseModel):
    status: ProjectStatus


# Both unreferenced since E14-05 (#331) replaced the planning-snapshot tree read with
# `RevisionTreeRead` (which is flat: `row_number`/`level` are computed, so the nesting
# these two expressed is gone for good). Kept until E14-12 (#339) removes the legacy
# planning services along with them.
class PlanningTaskTreeRead(TaskRead):
    children: list["PlanningTaskTreeRead"] = Field(default_factory=list)


class PlanningTreeRead(BaseModel):
    tasks: list[PlanningTaskTreeRead]


class MissingRateCoverageEntry(BaseModel):
    """One missing (cost category, year) `CostRate` combination, part of
    `MissingRateCoverageDetail.missing_cost_rates` (E6-11/#175)."""

    category_id: int
    category_name: str
    accounting_code: str
    year: int


class MissingRateCoverageDetail(BaseModel):
    """Structured 400/409 `detail` for `create_estimate_role_assignment`
    (``POST .../role-assignments``) and `validate_project_estimate`
    (``POST .../validate``) when a labor assignment covers a (cost category,
    year) with no `CostRate`, or a year with no `InflationRate` (E6-11/#175).

    Lists every missing combination found (via
    ``waterfall.services.estimate_calculation.collect_missing_rate_coverage``),
    not just the first one, so a real HTTP client actually receives the
    category/year detail the acceptance criteria calls for -- previously lost
    because `_generic_http_exception_handler` rewrites any string/list
    `HTTPException.detail` into a generic `{"code": "GENERIC_ERROR"}` before it
    reaches the response; only a structured (dict) `detail`, like this one,
    passes through unchanged.
    """

    code: Literal["MISSING_RATE_COVERAGE"]
    missing_cost_rates: list[MissingRateCoverageEntry]
    missing_inflation_years: list[int]


class MissingRateCoverage(BaseModel):
    detail: MissingRateCoverageDetail


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
    # Issue #289 (E12-07): optimistic-concurrency counter for the devis's grid
    # node tree, mirroring PlanningRead.revision -- see
    # EstimateGridNodeMove/move_estimate_grid_nodes.
    revision: int
    created_at: datetime
    validated_at: datetime | None
    note: str | None


class ProjectEstimateListRead(PaginatedList[ProjectEstimateRead]):
    pass


class EstimateValidationWarning(BaseModel):
    """Issue #65 (E6-04): a "real" planning task with neither a labor
    assignment nor a linked cost line at the moment an estimate is validated
    -- i.e. a task the pricing exercise likely forgot. Purely advisory: it
    never blocks validation, it only surfaces which tasks to double-check.
    """

    task_uid: int
    task_name: str


class EstimateValidationRead(ProjectEstimateRead):
    """Response of ``POST .../estimates/{estimate_id}/validate`` only.

    Deliberately not folded into ``ProjectEstimateRead`` itself: that schema
    is shared by `list_project_estimates`/`create_project_estimate`/
    `set_estimate_reference`, none of which compute this warning, so they
    would otherwise carry an always-empty/absent `warnings` field with no
    meaning in their context.
    """

    warnings: list[EstimateValidationWarning]


class EstimateTaskCreate(BaseModel):
    """Add a task to the project's displayed draft planning from the estimate screen (E6-06/#67).

    Mirrors ``PlanningTaskCreate``'s own task-placement fields (``target_parent_uid``
    identifies the parent by its planning uid, not by an ``EstimateTaskRow``/``MsTask``
    id) so the same placement semantics apply regardless of which screen -- Planning
    tree or Devis -- created the task; kept as its own schema (rather than reused
    directly) since this is a distinct capability documented under the estimates
    resource, with its own response shape (``EstimateTaskRowRead``, not
    ``PlanningDetailRead``). Absence of ``insert_after_uid`` places the new task as
    the first child of ``target_parent_uid`` -- or, when ``target_parent_uid`` is
    itself absent, as the first root task -- identical to ``PlanningTaskCreate``.
    """

    name: str = Field(min_length=1, max_length=512)
    is_milestone: bool = False
    target_parent_uid: int | None = Field(default=None, gt=0)
    insert_after_uid: int | None = Field(default=None, gt=0)

    _normalize_name = field_validator("name")(_required_text)


class EstimateTaskRowRead(BaseModel):
    id: int
    estimate_id: int
    task_id: int | None = None
    # Issue #290 (E12-08): the task's own business `uid`, resolved live from
    # WfPlanningTaskSnapshot/MsTask for a draft estimate (see
    # services.estimate_task_display) -- exposed for E12-09's future
    # tasks/cost-lines tree merge, not consumed by anything in this issue.
    task_uid: int | None = None
    # Issue #291 (E12-09): this row's 1-based rank in the devis's merged
    # tasks+grid-node tree (see order_estimate_grid_depth_first),
    # recomputed on every read, never stored. `None` only in the same
    # pre-existing degenerate case `task_uid` itself already falls back to
    # `None` for (this row's task can no longer be resolved at all).
    row_number: int | None = None
    parent_task_id: int | None = None
    position: int
    task_name: str
    outline_number: str | None = None
    outline_level: int | None = None
    is_milestone: bool


class EstimateTaskRowListRead(PaginatedList[EstimateTaskRowRead]):
    pass


class MilestoneTemplate(StrEnum):
    """Fixed chained-milestone templates applied to a non-labor cost line (E6-07/#68).

    Hard-coded, not an editable engine: ``FOURNITURE`` always yields exactly the
    2 milestones "Commande" -> "Reception" linked by 1 FS link; ``SOUS_TRAITANCE``
    always yields "Commande" -> N "Jalon intermediaire" milestones -> "Livraison"
    (N+2 total, chained by N+1 FS links), N coming from
    ``EstimateCostLineMilestonesCreate.intermediate_milestones_count``.
    """

    FOURNITURE = "fourniture"
    SOUS_TRAITANCE = "sous_traitance"


class EstimateCostLineMilestonesCreate(BaseModel):
    """Apply a chained-milestone template to a non-labor cost line (E6-07/#68).

    All milestones created by a single call share the exact same lag: the
    template models a single supplier delay applied uniformly to every link in
    the chain, not a per-link value the caller would otherwise have to repeat.
    ``intermediate_milestones_count`` only applies to ``SOUS_TRAITANCE`` -- an
    explicit non-zero value together with ``FOURNITURE`` is rejected rather
    than silently ignored, since it can only reflect a caller/template mismatch.
    """

    template: MilestoneTemplate
    # Bounded well above any realistic subcontracting chain, but still finite: an
    # unbounded value would let a single call insert an arbitrarily large number of
    # tasks/links into the draft planning within one request.
    intermediate_milestones_count: int = Field(default=0, ge=0, le=50)
    # Expressed in minutes -- like the rest of this schema's duration/lag fields
    # (see PlanningTaskScheduleUpdate.duration_minutes) -- and converted to
    # lag_tenth_minute (x10) plus a fixed lag_format=7 (MSPDI "d", working days,
    # see services.planning_tree's own LagFormat convention comment), matching
    # the convention already used by TaskLinkWrite-based predecessor edits (see
    # apps/frontend/src/hooks/use-planning-task-links.ts). Bounded to the same
    # ~15 years as PlanningTaskScheduleUpdate.duration_minutes.
    lag_minutes: int = Field(default=0, ge=0, le=7_884_000)

    @model_validator(mode="after")
    def _validate_intermediate_count(self) -> "EstimateCostLineMilestonesCreate":
        if (
            self.template == MilestoneTemplate.FOURNITURE
            and self.intermediate_milestones_count != 0
        ):
            raise ValueError(
                "intermediate_milestones_count is only valid for the sous_traitance template"
            )
        return self


SupplyStatus = Literal["planned", "ordered", "received", "cancelled"]


def _nonzero_or_none(value: int | None) -> int | None:
    """Shared `target_parent_uid` validator: 0 is never a valid grid node/task uid
    (positive uids are `MsTask.id`, negative uids are `EstimateGridNode.uid` --
    see EstimateGridNodeMove), unlike `None` (the devis root)."""
    if value == 0:
        raise ValueError("must not be 0")
    return value


class EstimateCostLineCreate(BaseModel):
    task_id: int | None = Field(default=None, gt=0)
    cost_category_id: int = Field(gt=0)
    # Issue #63 (E6-02): see EstimateRoleAssignmentCreate.cost_code_id below for the
    # same default-to-project-root / must-belong-to-project rules.
    cost_code_id: int | None = Field(default=None, gt=0)
    label: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    unit_cost: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    supply_status: SupplyStatus | None = None
    # Issue #66 (E6-05): forecast date for future cashflow curves, independent
    # from task_id -- either, both, or neither may be set.
    planned_date: datetime | None = None
    # Issue #289 (E12-07): the new grid node's position, same semantics as
    # PlanningTaskCreate.target_parent_uid/insert_after_uid -- positive
    # references a task of this estimate's own task-rows, negative another
    # grid node of this estimate. Both absent places the new line as the last
    # child of the devis root (unlike PlanningTaskCreate, which defaults to
    # the first child -- see create_estimate_grid_node/move_estimate_grid_nodes).
    target_parent_uid: int | None = Field(default=None)
    insert_after_uid: int | None = Field(default=None, lt=0)

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

    _validate_target_parent_uid = field_validator("target_parent_uid")(_nonzero_or_none)


class EstimateCostLineUpdate(BaseModel):
    task_id: int | None = Field(default=None, gt=0)
    cost_category_id: int | None = Field(default=None, gt=0)
    cost_code_id: int | None = Field(default=None, gt=0)
    label: str | None = Field(default=None, min_length=1, max_length=512)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    supply_status: SupplyStatus | None = None
    planned_date: datetime | None = None

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
    cost_code_id: int | None
    cost_type_code: str
    accounting_code: str
    category_code: str | None
    label: str
    quantity: Decimal
    unit_cost: Decimal
    purchase_cost: Decimal
    supply_status: SupplyStatus | None
    planned_date: datetime | None
    # Issue #289 (E12-07)/#291 (E12-09): this line's own EstimateGridNode,
    # exposed as-is -- a positive `parent_uid` is a `MsTask.id` (see
    # EstimateGridNode's own docstring), matching EstimateGridNodeMove's wire
    # contract, so a value read here can be fed straight back into
    # `target_parent_uid` on a later grid-nodes/move call without translation.
    uid: int
    parent_uid: int | None
    position: int
    # Issue #291 (E12-09): this line's 1-based rank in the devis's merged
    # tasks+grid-node tree -- recomputed on every read, never stored. Always
    # present (unlike EstimateTaskRowRead.row_number): every existing line
    # owns exactly one grid node, always visited by the merged traversal.
    row_number: int


class EstimateCostLineListRead(PaginatedList[EstimateCostLineRead]):
    pass


class EstimateRoleAssignmentCreate(BaseModel):
    """A devis-version-scoped labor role assignment (E12-01/#273).

    `task_id` refers to `MsTask.id` -- like `EstimateCostLineCreate.task_id` --
    never a planning uid: the caller is expected to already have resolved a
    task through the estimate's own task-rows/tasks endpoints.
    """

    task_id: int = Field(gt=0)
    role_id: int = Field(gt=0)
    # Issue #63 (E6-02): the project cost-imputation code this line of labor cost is
    # attached to. Left unset, it defaults to the project's active root cost code
    # (see resolve_cost_code_id); an explicit value must belong to the same project.
    cost_code_id: int | None = Field(default=None, gt=0)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    hours: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    comment: str | None = Field(default=None, max_length=10000)
    # Issue #289 (E12-07): same grid-node positioning semantics as
    # EstimateCostLineCreate.target_parent_uid/insert_after_uid above --
    # entirely independent of `task_id`. Left unset, the new node lands at the
    # devis root, regardless of `task_id`; a later move (move_estimate_grid_nodes)
    # is what keeps `task_id` in sync with the node's actual tree position.
    target_parent_uid: int | None = Field(default=None)
    insert_after_uid: int | None = Field(default=None, lt=0)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    _validate_target_parent_uid = field_validator("target_parent_uid")(_nonzero_or_none)


class EstimateRoleAssignmentUpdate(BaseModel):
    """`task_id`/`role_id` are immutable once created -- only the fields below may
    change, mirroring the removed `TaskRoleAssignmentUpdate`'s own contract."""

    cost_code_id: int | None = Field(default=None, gt=0)
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


class EstimateRoleAssignmentRead(BaseModel):
    id: int
    estimate_id: int
    # Nullable since issue #289 (E12-07): a role assignment unindented all the
    # way to the devis root (see move_estimate_grid_nodes) has no ancestor
    # task left to reference.
    task_id: int | None
    role_id: int
    role_code: str
    role_name: str
    cost_category_id: int
    accounting_code: str
    cost_code_id: int | None
    quantity: Decimal
    hours: Decimal
    comment: str | None
    created_at: datetime
    updated_at: datetime
    # Issue #291 (E12-09): same EstimateGridNode-as-is contract as
    # EstimateCostLineRead.uid/parent_uid/position above.
    uid: int
    parent_uid: int | None
    position: int
    # Issue #291 (E12-09): same always-present row_number contract as
    # EstimateCostLineRead.row_number above.
    row_number: int


class EstimateRoleAssignmentListRead(PaginatedList[EstimateRoleAssignmentRead]):
    pass


class EstimateGridNodeMove(BaseModel):
    """Move/reorder a selection of a devis grid's cost-line/role-assignment nodes
    (E12-07, issue #289) -- structurally mirrors `PlanningTaskMove`.

    `node_uids` addresses `EstimateGridNode.uid` values only (always negative,
    see `EstimateGridNode`) -- never a task. `target_parent_uid` is one of:
    positive (an existing task of this estimate's own task-rows), negative (an
    existing grid node of this estimate), or `None` (the devis root).
    """

    node_uids: list[Annotated[int, Field(lt=0)]] = Field(min_length=1)
    target_parent_uid: int | None = Field(default=None)
    position: int = Field(ge=1)
    expected_revision: int = Field(ge=0)

    _validate_target_parent_uid = field_validator("target_parent_uid")(_nonzero_or_none)


class EstimateAggregatesRead(BaseModel):
    total_labor_cost: Decimal
    total_purchase_cost: Decimal
    total_unburdened_cost: Decimal
    by_category: dict[str, Decimal]


class ReconciliationIssue(BaseModel):
    """One structured entry of a `ReconciliationPlanRead` list (E6-09/#70).

    ``sheet``/``row`` let the caller point the user at the exact Excel cell a
    problem or an ignored change came from (``row`` is the 1-based Excel row
    number, i.e. counting the header row); both are `None` for an issue that
    isn't scoped to a single file row (e.g. a precondition on the whole
    import, or an existing-row deletion, which by definition has no row left
    in the file to point at).
    """

    code: str
    message: str
    sheet: str | None = None
    row: int | None = None


class ReconciliationPlanRead(BaseModel):
    """Diagnostic + outcome of an estimate reconciliation import (E6-09/#70).

    Returned by both `POST .../import-reconciliation/preview` (always
    `applied=False`, nothing written) and `POST .../import-reconciliation/confirm`
    (`applied=True` once committed) -- the two endpoints run the exact same
    analysis on the same file, so a preview accurately predicts what a
    confirm on the same, unmodified file will do. `blocking_issues` non-empty
    means nothing was, or will be, written: a `confirm` in that state reports
    `applied=False` and responds with a non-2xx status instead of a
    misleadingly successful one.

    The `_to_create`/`_to_update`/`_to_delete` fields describe the plan as
    computed from the file diff, independently of whether every individual
    change could actually be applied -- an apply-time failure on one specific
    row (e.g. a task deletion blocked by a cascade or a reference) is
    reported as its own `blocking_issues` entry rather than by shrinking
    these counts, since `blocking_issues` non-empty already means none of
    them were kept.
    """

    blocking_issues: list[ReconciliationIssue] = Field(default_factory=list)
    warnings: list[ReconciliationIssue] = Field(default_factory=list)
    tasks_to_create: int = 0
    tasks_to_delete: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    labor_to_create: int = 0
    labor_to_update: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    labor_to_delete: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    non_labor_to_create: int = 0
    non_labor_to_update: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    non_labor_to_delete: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    applied: bool = False


class ProjectCostCodeBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)

    _normalize_code = field_validator("code")(_required_text)
    _normalize_name = field_validator("name")(_required_text)


class ProjectCostCodeCreate(ProjectCostCodeBase):
    parent_id: int | None = Field(default=None, gt=0)


class ProjectCostCodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    _normalize_code = field_validator("code")(_optional_text)
    _normalize_name = field_validator("name")(_optional_text)


class ProjectCostCodeRead(ProjectCostCodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectCostCodeListRead(PaginatedList[ProjectCostCodeRead]):
    pass
