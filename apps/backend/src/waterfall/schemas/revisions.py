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
    the whole point of the model. Its **edition** is E14-07's (#333), which owns
    every write on this facet.
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


class RevisionWriteRead(BaseModel):
    """What every write answers: the revision, and the counter its next write needs."""

    revision_id: int
    lock_version: int


class RevisionNodeWriteRead(RevisionWriteRead):
    """A node that was just created, by the ids the database allocated."""

    node_id: int
    work_item_id: int


class RevisionCostLossRead(BaseModel):
    """One cost facet a cascade delete took away, named rather than dropped silently.

    Rule 3's safeguard: a deletion never removes chiffrage without saying which.
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


class RevisionWrite(BaseModel):
    """Base of every write payload: the optimistic lock, and nothing else."""

    expected_lock_version: int = Field(ge=0, le=_MAX_INT32)


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


class RevisionNodeMove(RevisionWrite):
    """Move a selection of nodes, whatever facet each of them carries.

    ``mode`` is what the selection is asked to do, and it is the only field
    ``target_parent_id``/``position`` mean anything for:

    * ``to_parent`` re-parents the selection under ``target_parent_id`` (absent =
      the root) at ``position`` (absent = last);
    * ``up``/``down`` shift a contiguous block of siblings by one;
    * ``indent`` puts a block under its immediately preceding sibling,
      ``outdent`` moves it to its grandparent.

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
