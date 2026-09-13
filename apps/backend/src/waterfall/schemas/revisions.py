"""Wire shapes of the revision API (E14-05, issue #331).

The planning facet of a revision, read and written on the **node** of
`wf_revision_node` rather than on a row of `wf_planning_task_snapshot`. The cost
facet follows on the same node in E14-07 (#333), which extends
:class:`RevisionNodeRead` with its own facet block rather than adding a second,
parallel read.

Three conventions run through the whole module:

* every write carries ``expected_lock_version`` and every write answers with the
  new ``lock_version``, so a client always holds the value its next write needs
  (E14-04, #330). There is one counter per revision because there is one tree;
* ``row_number`` and ``level`` are computed on read and stored nowhere -- the
  principle E9 settled, made structural by the node model. See
  :class:`RevisionNodeRead`;
* **every numeric field of a write payload is bounded by the column it lands in.**
  Not a style rule: an unbounded value reaches ``flush()`` and PostgreSQL answers
  :class:`sqlalchemy.exc.DataError`, which is *not* an
  :class:`~sqlalchemy.exc.IntegrityError`, has no entry in the translation table of
  :mod:`waterfall.api.revision_errors` and therefore comes back as a 500 on a request
  a client had every reason to think well-formed. (That module rolls the session back
  for it all the same, so the ``FOR UPDATE`` lock is released -- defence in depth
  behind these bounds, not a substitute for them.) SQLite
  gives ``SMALLINT``/``INTEGER`` the same unbounded affinity, so no test on the
  default backend can catch it -- the bound is the only guard. The constants below
  are the column ranges, named once so #333 applies the same rule to the ``Numeric``
  columns of the cost facet (``max_digits``/``decimal_places`` matching
  ``Numeric(14, 2)``/``Numeric(16, 2)`` exactly).

Read models are deliberately *not* bounded: their values come out of the database,
which is where the bound was enforced on the way in, and rejecting a stored value on
read would make a row unreadable rather than unwritable.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RevisionKind = Literal["initial", "contract_reference", "forecast_remaining"]
RevisionStatus = Literal["draft", "validated", "superseded"]
WorkItemKind = Literal["task", "cost"]
CalendarSource = Literal["project", "role", "manual"]
CostNature = Literal["labor", "non_labor"]
SupplyStatus = Literal["planned", "ordered", "received", "cancelled"]
#: Why the calculation engine could put a chiffrage in no year at all. Restated as a
#: ``Literal`` like every enumeration of this module rather than imported from
#: ``services.estimate_calculation.UnpriceableReason``: a request/response model
#: publishes the *contract*, and pinning the two strings here is what makes renaming
#: the service-side enum a visible break instead of a silent one.
UnpriceableReason = Literal["bearing_task_undated", "bearing_task_empty_range"]

#: MSPDI link types, as `wf_revision_node_link.link_type` constrains them.
LinkType = Annotated[int, Field(ge=0, le=3)]

#: MSPDI ``LagFormat``/``DurationFormat`` legal values, read off the
#: ``xsd:enumeration`` list of this repository's own bundled schema
#: (``resources/msproject-schemas/2016/tasks_2016_schema.xml``, ``LagFormat`` at line
#: 607 and ``DurationFormat`` at line 113): "3=m, 4=em, 5=h, 6=eh, 7=d, 8=ed, 9=w,
#: 10=ew, 11=mo, 12=emo, 19=%, 20=e%, 35=m?, ... 51=%?, 52=e%?, 53=null", the ``e``
#: prefix denoting *elapsed* (wall-clock) time and "null" no unit displayed.
#: ``DurationFormat`` adds 21 -- a second "null" code -- and that single value is the
#: only difference between the two enumerations.
#:
#: Read off the ``xsd:enumeration`` list and deliberately **not** off the
#: ``xsd:documentation`` beside it: the prose of ``LagFormat`` stops at "51=%? and
#: 52=e%?" while its own, normative enumeration descends to 53. ``TaskLinkWrite`` was
#: derived from that prose and consequently rejected a ``LagFormat`` of 53 that a
#: perfectly valid MSPDI file may carry (#331 review, M1); both aliases are now pinned
#: by ``tests/test_mspdi_enumerations.py``, which re-derives the two expected sets from
#: the bundled XSD on every run rather than restating them, so this comment cannot
#: drift from the schema again.
#:
#: Constrained to the enumeration rather than merely range-bound to the
#: ``SmallInteger`` storage column -- the constraint the legacy ``TaskLinkWrite``
#: carries and which this payload must not lose, since an out-of-domain code is a
#: syntactically valid but meaningless value MS Project cannot render. That legacy
#: payload (``schemas/projects.py``, alive until E14-12/#339 removes its routes; only
#: its *OpenAPI component* went with this issue) imports :data:`MspdiLagFormat` from
#: here rather than restating it, so the two cannot diverge in the meantime.
MspdiLagFormat = Literal[
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 19, 20, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 51, 52, 53
]
MspdiDurationFormat = Literal[
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 19, 20, 21, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 51, 52, 53
]

#: Upper bound of a task duration, in minutes: 15 years. Same value, and the same
#: reasoning, as the legacy planning schedule payload it replaces -- far past any
#: real task, well under what would overflow a PostgreSQL ``INTEGER`` on flush.
_MAX_DURATION_MINUTES = 7_884_000

#: PostgreSQL ``INTEGER``, the type of every id column of the revision tables and of
#: `wf_revision_node_link.lag_tenth_minute`.
_MIN_INT32 = -2_147_483_648
_MAX_INT32 = 2_147_483_647
_MIN_LAG = _MIN_INT32
_MAX_LAG = _MAX_INT32

#: The two ``Numeric`` precisions of `wf_revision_cost_facet`, named once so the
#: cost payloads below cannot drift from the columns they land in:
#: ``quantity``/``hours`` are ``Numeric(14, 2)``, ``unit_cost`` ``Numeric(16, 2)``.
#: Both are spelled as ``max_digits``/``decimal_places`` rather than as a numeric
#: range, because that is exactly what PostgreSQL refuses on: a value with more
#: than ``max_digits - decimal_places`` integer digits raises ``DataError`` on
#: flush, which is *not* an ``IntegrityError`` -- the 500-without-a-code the module
#: docstring above describes. SQLite stores the same value happily, so no test on
#: the default backend can catch it and the bound is the only guard.
_COST_AMOUNT_DIGITS = 14
_COST_UNIT_COST_DIGITS = 16
_COST_DECIMAL_PLACES = 2

#: Upper bound of a predecessor list. Cycle detection walks the candidate link set
#: once per supplied link, so an unbounded list is quadratic in the size of the
#: request body; a task with a thousand predecessors is already beyond anything a
#: planning expresses.
_MAX_PREDECESSORS = 1_000


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("must not be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _required_text(value)


class RevisionPredecessorRead(BaseModel):
    """One precedence link arriving at a node, by node id -- never by uid."""

    model_config = ConfigDict(from_attributes=True)

    predecessor_node_id: int
    link_type: int
    lag_tenth_minute: int
    lag_format: int | None


class RevisionPlanFacetRead(BaseModel):
    """The planning facet of a node: what makes it a task."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    calendar_id: int | None
    calendar_source: CalendarSource | None
    is_milestone: bool
    duration_minutes: int | None
    duration_format: int | None
    start_at: datetime | None
    finish_at: datetime | None
    work_minutes: int | None
    percent_complete: int
    is_manual: bool


class RevisionCostFacetRead(BaseModel):
    """The cost facet of a node, read-only here.

    Exposed by the tree read so that a client sees *one* tree rather than two
    filtered views of it -- moving a cost line is a move of the same tree, which is
    the whole point of the model.

    ``bearing_task_node_id``/``bearing_task_name`` are the task this line hangs
    under (INV-01), **resolved on read and stored in no column** -- the same
    treatment as ``row_number``, and for the same reason: it is a consequence of
    where the node sits, so moving the node (or moving the task above it) changes
    it with nothing to update. Both are ``null`` on a line placed at the root,
    which is a project-wide global cost and explicitly allowed.

    Unbounded on purpose, like every read model of this module: the values come out
    of the database, where the bound was enforced on the way in, and a constrained
    ``response_model`` would turn a stored value into a ``ResponseValidationError``
    -- a 500 on a ``GET``, making the row unreadable rather than unwritable.
    """

    model_config = ConfigDict(from_attributes=True)

    nature: CostNature
    label: str
    quantity: Decimal
    role_id: int | None
    hours: Decimal | None
    cost_type_id: int | None
    cost_category_id: int | None
    unit_cost: Decimal | None
    supply_status: SupplyStatus | None
    planned_date: date | None
    cost_code_id: int | None
    comment: str | None
    bearing_task_node_id: int | None
    bearing_task_name: str | None


class RevisionNodeRead(BaseModel):
    """One node of the tree, in depth-first order.

    ``row_number`` (rank in the depth-first walk) and ``level`` (depth, roots at 1)
    are recomputed on every read and stored in no column: a positional identifier
    that a move would have to renumber is one that drifts, which is exactly what E9
    (#145-#149) settled for the legacy planning and what this model makes
    structural. Both are read-only and can never be set by a client.

    Exactly one of ``planning``/``cost`` is set, and which one is ``kind`` (INV-11,
    INV-13).
    """

    node_id: int
    work_item_id: int
    kind: WorkItemKind
    parent_id: int | None
    position: int
    row_number: int
    level: int
    external_uid: int | None
    description: str | None
    planning: RevisionPlanFacetRead | None
    cost: RevisionCostFacetRead | None
    predecessors: list[RevisionPredecessorRead]


class RevisionTreeRead(BaseModel):
    """A whole revision: its header, and its nodes depth-first.

    ``lock_version`` is here rather than only on write responses because it is what
    a client hands back as ``expected_lock_version`` on the first write following a
    read.
    """

    revision_id: int
    project_id: int
    version_number: int
    kind: RevisionKind
    status: RevisionStatus
    lock_version: int
    note: str | None
    nodes: list[RevisionNodeRead]


class RevisionSummaryRead(BaseModel):
    """One revision of a project, without its tree (E14-10, #336).

    The header of :class:`RevisionTreeRead` plus the two dates a history screen
    needs, and deliberately **not** the nodes: this is what a client reads to know
    which revisions exist before choosing one to open, and loading every tree of
    every version to draw a selector would be the opposite of what the unpaginated
    ``GET .../nodes`` is for.

    ``lock_version`` is carried here too, for the one command that needs the
    counter of a revision whose tree has not been read: ``POST .../copy`` takes the
    **source**'s counter, so a draft can be opened from a validated revision listed
    here without first downloading it.
    """

    revision_id: int
    project_id: int
    version_number: int
    kind: RevisionKind
    status: RevisionStatus
    lock_version: int
    note: str | None
    created_at: datetime
    validated_at: datetime | None


class RevisionListRead(BaseModel):
    """Every revision of a project, oldest first, and the two pointers to it.

    The pointers travel with the list rather than on ``ProjectRead`` because they
    are only meaningful against it, and because ``ms_project`` does not carry them:
    they live on `wf_project_revision_pointer` precisely so no foreign-key cycle is
    closed back onto the project (see :class:`ProjectRevisionPointer`). A client
    that has this list has everything it needs to decide what to display --
    ``displayed_revision_id`` when there is a draft on screen, the reference
    otherwise, and the latest by ``version_number`` when neither is set.

    Not paginated: a project has versions, not a stream of them, and the caller is
    a version selector that needs them all to be honest about what exists.
    """

    items: list[RevisionSummaryRead]
    reference_revision_id: int | None
    displayed_revision_id: int | None


class RevisionWriteRead(BaseModel):
    """What every write answers: the revision, and the counter its next write needs."""

    revision_id: int
    lock_version: int


class RevisionCreatedRead(RevisionWriteRead):
    """The draft revision a copy produced (E14-08, #334).

    ``lock_version`` is the **copy's** counter and starts at 0: copying reads the
    source and writes a new revision, so the source comes out exactly as it went in
    -- which is what lets a validated revision be copied at all (INV-03, INV-07).
    """

    source_revision_id: int
    version_number: int
    kind: RevisionKind


class RevisionValidatedRead(RevisionWriteRead):
    """What a validation produced: an immutable revision and its frozen document.

    ``frozen_line_count`` is the size of that document, at the grain it is cut at --
    one line per (chiffrage, year), so a revision with three multi-year MO lines
    answers more than three. ``superseded_revision_ids`` names the revision that
    stopped being the validated one of its kind (INV-22), so that a client holding a
    stale reference learns it here rather than on its next 409.
    """

    version_number: int
    status: RevisionStatus
    validated_at: datetime
    frozen_line_count: int
    superseded_revision_ids: list[int]


class RevisionNodeWriteRead(RevisionWriteRead):
    """A node that was just created, by the ids the database allocated."""

    node_id: int
    work_item_id: int


class RevisionCostLossRead(BaseModel):
    """One cost facet a cascade delete took away, named rather than dropped silently.

    Rule 3's safeguard: a deletion never removes chiffrage without saying which.

    ``amount`` is in **euros at the cent** (#368), and gets there the way every
    other published figure of this API does: the engine rounds each priced line on
    its own and sums the rounded amounts
    (:meth:`~waterfall.services.estimate_calculation.RevisionPricing.published_amount_of`).
    Four callers quote a loss through that one method and therefore quote the same
    figure: ``POST .../nodes/delete``, the MS Project import diff, the MS Project
    import run, and -- since #365 -- the reconciliation round trip, which reuses this
    very model inside its plan.
    Unbounded here all the same, like every read model of this module -- a bound on
    a response field turns a stored state into a 500, see the module docstring --
    so the rounding is a decision about what to publish and not a constraint on
    what may be read.
    """

    node_id: int
    work_item_id: int
    label: str
    nature: CostNature
    amount: Decimal
    bearing_task_name: str | None


class RevisionNodeDeleteRead(RevisionWriteRead):
    """What a cascade delete removed (INV-02), and the chiffrage it took with it."""

    removed_node_ids: list[int]
    cost_losses: list[RevisionCostLossRead]


class RevisionMissingRateRead(BaseModel):
    """One ``(cost category, year)`` combination the rate table does not cover.

    Same four fields as ``schemas.projects.MissingRateCoverageEntry``, which the
    legacy devis returns inside a 400 ``detail``. Here it is part of a **200**:
    reading the totals of a draft whose 2031 rate has not been entered yet has to
    answer, so the line is priced at a zero rate and the gap is named beside it.
    Refusing a *validation* on the same gap is the right answer and is what
    ``POST .../validate`` does since E14-08 (#334), with the code
    ``REVISION_RATE_COVERAGE_MISSING``: this body is where a client reads *which*
    rates it has to complete.
    """

    category_id: int
    category_name: str
    accounting_code: str
    year: int


class RevisionUnpriceableFacetRead(BaseModel):
    """One chiffrage the engine could put in **no year at all** (E14-08 review, H2).

    The gap beside :class:`RevisionMissingRateRead`, and the one it could never
    report: a labour facet borne by a task with no dates has no year to spread its
    hours over, so it produces no priced line, so it lands in none of the
    ``(cost category, year)`` pairs ``missing_cost_rates`` is built from. The screen
    showed ``total_labor_cost: 0`` with ``missing_cost_rates: []`` beside it -- a
    zero with nothing to explain it -- and ``POST .../validate`` froze that zero.

    Published here for the same reason the missing rates are: a validation now
    refuses on this (``REVISION_UNPRICEABLE_FACET``), and a user who discovers the
    refusal at validation time without knowing what to correct has been told the
    wrong half of it. ``bearing_*`` names the task to date, which is where the fix
    is: the facet itself carries its role and its hours and is perfectly valid.

    ``reason`` is ``bearing_task_undated`` (the task has no ``start_at`` and/or no
    ``finish_at``) or ``bearing_task_empty_range`` (its ``finish_at`` precedes its
    ``start_at``), the two remedies being different.
    """

    node_id: int
    work_item_id: int
    label: str
    hours: Decimal
    bearing_node_id: int | None
    bearing_work_item_id: int | None
    bearing_task_name: str | None
    reason: UnpriceableReason


class RevisionAggregatesRead(BaseModel):
    """The totals of one revision, computed from its cost facets (E14-07b, #364).

    Replaces ``GET .../estimates/{id}/aggregates``, which could only ever sum the
    ``wf_estimate_line`` rows a validation had already written -- a devis in
    progress had no total at all. These are computed live, so a draft has one, and
    a cost facet sitting at the **root** of the tree (no bearing task, INV-01's
    project-wide global cost) counts towards it like any other.

    ``by_category`` is keyed by accounting code and ``by_cost_code`` by the
    project cost code's ``code``, a line carrying none falling under the shared
    ``UNASSIGNED_COST_CODE_LABEL``. Deliberately unbounded, like every read model
    here: a bound on a response field turns a stored value into a 500 (see the
    module docstring) -- ``decimal_places=2`` here would be exactly that, a stored
    state turned into a crash, where the engine's cent-rounding below is a decision
    about what to publish.

    Every amount is an amount in **euros, at the cent**:
    :func:`waterfall.services.estimate_calculation.calculate_revision_aggregates`
    rounds each priced line before summing it, restating the rule the
    ``wf_estimate_line.budget_cost`` column used to carry for the endpoint this one
    replaces -- per line, which is also what keeps these five figures additive
    (``total_labor_cost + total_purchase_cost == total_unburdened_cost``, and the
    same for either breakdown).
    """

    revision_id: int
    total_labor_cost: Decimal
    total_purchase_cost: Decimal
    total_unburdened_cost: Decimal
    by_category: dict[str, Decimal]
    by_cost_code: dict[str, Decimal]
    unpriceable_facets: list[RevisionUnpriceableFacetRead]
    missing_cost_rates: list[RevisionMissingRateRead]
    missing_inflation_years: list[int]


class RevisionReconciliationIssueRead(BaseModel):
    """One problem or ignored change found in a reconciliation workbook (E14-07c, #365).

    ``sheet``/``row`` point at the exact Excel cell it came from -- ``row`` is the
    1-based Excel row number, header row included -- and are both ``null`` for a
    problem no single row can be attributed to, a deletion having by definition no
    row left in the file to point at.
    """

    code: str
    message: str
    sheet: str | None
    row: int | None


class RevisionReconciliationPlanRead(BaseModel):
    """What a reconciliation workbook would do -- or did -- to a revision (E14-07c, #365).

    Answered by both ``POST .../import-reconciliation/preview`` (always
    ``applied=false``, nothing written) and ``.../confirm``: the two run the *same*
    analysis on the same file, so a preview predicts a confirm exactly.

    ``blocking_issues`` non-empty means nothing was written and nothing will be. The
    counts and id lists still describe the diff the file states, because they are
    what the user has to act on; shrinking them would hide the rows that need
    attention.

    The identifiers are **node ids** throughout, where the legacy plan carried three
    families of them (devis task rows, role assignments, cost lines). One tree, one
    kind of identifier.

    ``cost_losses`` is Règle 3's safeguard, in the very shape
    ``POST .../nodes/delete`` already publishes it: a line the file no longer
    mentions is a deletion, and a deletion that takes chiffrage away names it rather
    than letting it go quietly. Amounts are in euros at the cent (#368).

    ``lock_version`` is the revision's counter -- unchanged on a preview, the new one
    after an applied confirm -- so a client can chain a write onto the result without
    re-reading the tree.
    """

    revision_id: int
    lock_version: int
    blocking_issues: list[RevisionReconciliationIssueRead]
    warnings: list[RevisionReconciliationIssueRead]
    tasks_to_create: int
    tasks_to_delete: list[int]
    labor_to_create: int
    labor_to_update: list[int]
    labor_to_delete: list[int]
    non_labor_to_create: int
    non_labor_to_update: list[int]
    non_labor_to_delete: list[int]
    cost_losses: list[RevisionCostLossRead]
    applied: bool


class RevisionWrite(BaseModel):
    """Base of every write payload: the optimistic lock, and nothing else."""

    expected_lock_version: int = Field(ge=0, le=_MAX_INT32)


class RevisionCopy(RevisionWrite):
    """Create a draft revision reproducing an existing one (INV-07).

    ``kind`` absent keeps the source's own: a plain "work on a new version of this".
    Naming one is how the two derived documents of the model are made -- a
    ``contract_reference`` copied from the estimate that won the order, a
    ``forecast_remaining`` copied from the budget it will be compared against -- and
    it is the only attribute of the copy a caller gets to choose, everything else
    being reproduced from the source.

    ``expected_lock_version`` is the **source's**, and guards *what is copied*: a
    source that moved on since the caller read it would produce a copy of a tree the
    caller never saw.
    """

    kind: RevisionKind | None = None
    note: str | None = Field(default=None, max_length=10000)

    _normalize_note = field_validator("note")(_optional_text)


class RevisionValidate(RevisionWrite):
    """Validate a draft: freeze its document and make it immutable.

    Carries the optimistic lock and nothing else. Everything a validation writes is
    derived -- the frozen lines from the cost facets and the rate table, the
    supersession from INV-22 -- so there is nothing for a caller to supply, and any
    attribute accepted here would be an attribute of the revision that should have
    been set while it was still a draft.
    """


class RevisionTaskCreate(RevisionWrite):
    """Create a task node -- a new ``work_item`` of kind ``task`` and its plan facet.

    ``parent_id`` absent means "at the root", ``position`` absent means "last child
    of the parent". The calendar follows Règle 1 when ``calendar_id`` is absent: the
    project's, recorded as inherited rather than pinned (INV-15); an explicit
    ``calendar_id`` pins it as ``manual``. Both halves of that rule are the domain's
    (``domain.revision.tree._apply_calendar_defaults``) and are deliberately *not*
    restated by the route, so the cost facet of #333 cannot end up with a second,
    divergent formulation of the same rule.
    """

    name: str = Field(min_length=1, max_length=512)
    parent_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    position: int | None = Field(default=None, ge=1, le=_MAX_INT32)
    description: str | None = Field(default=None, max_length=10000)
    duration_minutes: int | None = Field(default=None, ge=0, le=_MAX_DURATION_MINUTES)
    is_milestone: bool = False
    start_at: datetime | None = None
    finish_at: datetime | None = None
    calendar_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)

    _normalize_name = field_validator("name")(_required_text)
    _normalize_description = field_validator("description")(_optional_text)


class RevisionCostLineCreate(RevisionWrite):
    """Create a cost node -- a new ``work_item`` of kind ``cost`` and its cost facet.

    The cost-side twin of :class:`RevisionTaskCreate`, on the *same* tree: ``parent_id``
    absent means "at the root", and a line at the root is a project-wide cost with no
    bearing task at all, which INV-01 explicitly allows. ``position`` absent means
    "last child of the parent".

    Which attributes a line carries is decided by its ``nature`` -- a labour line has a
    role and hours, a non-labour one a cost type, a category and a débours (INV-19,
    INV-20) -- and that rule is deliberately **not** restated here as a
    ``model_validator``. It is the domain's
    (:func:`~waterfall.domain.revision.invariants.check_cost_facet_shape`), it is
    enforced by the table's own check constraint, and a third formulation on the wire
    is exactly the duplication EPIC #326 exists to remove. A malformed shape therefore
    comes back as a 400 carrying ``REVISION_FACET_CONTRACT``, not as a 422.

    What *is* decided here is the numeric bounds, for the reason the module docstring
    gives: they are properties of the ``Numeric`` columns, and nothing below this layer
    would turn an over-wide value into anything but a 500.
    """

    nature: CostNature
    label: str = Field(min_length=1, max_length=512)
    parent_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    position: int | None = Field(default=None, ge=1, le=_MAX_INT32)
    quantity: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        max_digits=_COST_AMOUNT_DIGITS,
        decimal_places=_COST_DECIMAL_PLACES,
    )
    role_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    hours: Decimal | None = Field(
        default=None, ge=0, max_digits=_COST_AMOUNT_DIGITS, decimal_places=_COST_DECIMAL_PLACES
    )
    cost_type_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    cost_category_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    unit_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=_COST_UNIT_COST_DIGITS, decimal_places=_COST_DECIMAL_PLACES
    )
    supply_status: SupplyStatus | None = None
    planned_date: date | None = None
    cost_code_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    comment: str | None = Field(default=None, max_length=10000)
    description: str | None = Field(default=None, max_length=10000)

    _normalize_label = field_validator("label")(_required_text)
    _normalize_comment = field_validator("comment")(_optional_text)
    _normalize_description = field_validator("description")(_optional_text)


class RevisionCostFacetUpdate(RevisionWrite):
    """Partial edit of a node's cost facet: label, quantité, débours, rôle, heures.

    Partial in exactly the sense :class:`RevisionPlanFacetUpdate` is: an absent field
    is left alone and ``null`` is a *value* (clear the planned date, drop the cost
    code, erase the comment), read through ``model_fields_set`` and never through "is
    not None".

    ``nature`` is absent, and that is the one deliberate asymmetry with the creation
    payload. Flipping it would swap the entire attribute set of the line in a single
    request -- role and hours out, cost type, category and débours in -- so what a
    client wants there is a *different* line, and deleting this one and creating
    another says so without inventing a half-state the check constraint would refuse
    anyway.

    ``label`` and ``quantity`` refuse an explicit ``null`` for the same reason the four
    planning fields do: their columns are ``NOT NULL`` and they have no cleared state,
    so accepting ``null`` and doing nothing would answer 200, advance ``lock_version``
    and change nothing -- the one response a client cannot tell from success.
    """

    #: Fields whose declared ``| None`` means "may be omitted", never "may be nulled".
    NON_NULLABLE_FIELDS: ClassVar[tuple[str, ...]] = ("label", "quantity")

    label: str | None = Field(default=None, min_length=1, max_length=512)
    quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=_COST_AMOUNT_DIGITS, decimal_places=_COST_DECIMAL_PLACES
    )
    role_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    hours: Decimal | None = Field(
        default=None, ge=0, max_digits=_COST_AMOUNT_DIGITS, decimal_places=_COST_DECIMAL_PLACES
    )
    cost_type_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    cost_category_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    unit_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=_COST_UNIT_COST_DIGITS, decimal_places=_COST_DECIMAL_PLACES
    )
    supply_status: SupplyStatus | None = None
    planned_date: date | None = None
    cost_code_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    comment: str | None = Field(default=None, max_length=10000)

    _normalize_label = field_validator("label")(_optional_text)
    _normalize_comment = field_validator("comment")(_optional_text)

    @model_validator(mode="after")
    def validate_no_null_on_mandatory_fields(self) -> "RevisionCostFacetUpdate":
        supplied = self.model_fields_set
        nulled = [
            name
            for name in RevisionCostFacetUpdate.NON_NULLABLE_FIELDS
            if name in supplied and getattr(self, name) is None
        ]
        if nulled:
            raise ValueError(
                f"{', '.join(nulled)} cannot be set to null: omit the field to leave it "
                "unchanged, there is no cleared state for it"
            )
        return self


class RevisionNodeMove(RevisionWrite):
    """Move a selection of nodes, whatever facet each of them carries.

    ``mode`` is what the selection is asked to do, and it is the only field
    ``target_parent_id``/``position`` mean anything for:

    * ``to_parent`` re-parents the selection under ``target_parent_id`` (absent =
      the root) at ``position`` (absent = last);
    * ``up``/``down`` shift a contiguous block of siblings by one;
    * ``indent`` puts a block under its immediately preceding sibling,
      ``outdent`` moves it to its grandparent, right after its former parent, and
      hands the siblings that followed it over to it so that the order of the
      displayed rows is preserved (Règle 5 of the revision specification).

    A node whose ancestor is also selected is carried by that ancestor rather than
    moved twice, and every selected node takes its subtree and both its facets with
    it -- there is one tree, so moving a cost line and moving a task are the same
    operation.
    """

    node_ids: list[Annotated[int, Field(gt=0, le=_MAX_INT32)]] = Field(min_length=1)
    mode: Literal["to_parent", "up", "down", "indent", "outdent"] = "to_parent"
    target_parent_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)
    position: int | None = Field(default=None, ge=1, le=_MAX_INT32)

    @model_validator(mode="after")
    def validate_target_belongs_to_mode(self) -> "RevisionNodeMove":
        """Refuse a target the chosen ``mode`` would silently drop.

        ``up``/``down``/``indent``/``outdent`` compute their own destination, so a
        ``target_parent_id`` or a ``position`` supplied alongside them is an
        intention the server cannot honour. Answering 200 and discarding it would
        hand the client a success for a move it did not ask for; 422 says which
        field does not belong.
        """
        if self.mode == "to_parent":
            return self
        ignored = [
            name for name in ("target_parent_id", "position") if getattr(self, name) is not None
        ]
        if ignored:
            raise ValueError(
                f"{', '.join(ignored)} only mean something with mode 'to_parent'; "
                f"mode '{self.mode}' computes its own destination"
            )
        return self


class RevisionNodeDelete(RevisionWrite):
    """Delete a selection, its whole subtree, and both facets of every node removed.

    No ``confirm_cascade`` flag, unlike the legacy planning endpoint it replaces:
    the cascade is INV-02 and is not optional, and what the caller gets back instead
    is the list of chiffrage the deletion took away (Rule 3's safeguard), named in
    the response rather than guarded by a second round-trip.
    """

    node_ids: list[Annotated[int, Field(gt=0, le=_MAX_INT32)]] = Field(min_length=1)


class RevisionPlanFacetUpdate(RevisionWrite):
    """Partial edit of a node's planning facet: duration, dates, avancement, calendar.

    Genuinely partial: an absent field is left alone, and ``null`` is a *value*
    (clear the duration, clear a date). The distinction is read through
    ``model_fields_set``, never through "is not None", which is why every field
    here defaults to ``None`` yet ``None`` never means "unchanged".

    ``calendar_id`` carries Règle 1: an id pins the calendar (``calendar_source``
    becomes ``manual``), ``null`` drops the override and lets the rule choose again
    from the roles of the subtree, and omitting it changes neither.

    Four fields are the exception and refuse an explicit ``null``:
    :attr:`name`, :attr:`percent_complete`, :attr:`is_milestone` and
    :attr:`is_manual` have no "cleared" state -- the column is ``NOT NULL`` and the
    domain types them ``str | Unset`` / ``int | Unset`` / ``bool | Unset``, without
    ``None``. They are declared optional only so that omitting them is legal, so
    :meth:`validate_no_null_on_mandatory_fields` refuses the ``null`` the type would
    otherwise publish as acceptable. The alternative -- accepting it and doing
    nothing -- answers 200, advances ``lock_version`` and changes nothing, which is
    the one response a client cannot tell from success.
    """

    #: Fields whose declared ``| None`` means "may be omitted", never "may be nulled".
    NON_NULLABLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "name",
        "percent_complete",
        "is_milestone",
        "is_manual",
    )

    name: str | None = Field(default=None, min_length=1, max_length=512)
    duration_minutes: int | None = Field(default=None, ge=0, le=_MAX_DURATION_MINUTES)
    duration_format: MspdiDurationFormat | None = None
    start_at: datetime | None = None
    finish_at: datetime | None = None
    work_minutes: int | None = Field(default=None, ge=0, le=_MAX_DURATION_MINUTES)
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    is_milestone: bool | None = None
    is_manual: bool | None = None
    calendar_id: int | None = Field(default=None, gt=0, le=_MAX_INT32)

    _normalize_name = field_validator("name")(_optional_text)

    @model_validator(mode="after")
    def validate_no_null_on_mandatory_fields(self) -> "RevisionPlanFacetUpdate":
        supplied = self.model_fields_set
        nulled = [
            name
            for name in RevisionPlanFacetUpdate.NON_NULLABLE_FIELDS
            if name in supplied and getattr(self, name) is None
        ]
        if nulled:
            raise ValueError(
                f"{', '.join(nulled)} cannot be set to null: omit the field to leave it "
                "unchanged, there is no cleared state for it"
            )
        return self


class RevisionPredecessorWrite(BaseModel):
    """One precedence link to install, designating its predecessor by node id."""

    predecessor_node_id: int = Field(gt=0, le=_MAX_INT32)
    link_type: LinkType = 1
    lag_tenth_minute: int = Field(default=0, ge=_MIN_LAG, le=_MAX_LAG)
    lag_format: MspdiLagFormat | None = None


class RevisionPredecessorsReplace(RevisionWrite):
    """Replace *every* predecessor of one node with the given list.

    Set-shaped rather than incremental on purpose: a client editing the
    predecessors of a task holds the list it wants, not a handle on the links it
    wants gone. An empty list clears them, and is the only way to.
    """

    predecessors: list[RevisionPredecessorWrite] = Field(max_length=_MAX_PREDECESSORS)
