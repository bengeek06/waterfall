"""Entities of the revision model, as plain dataclasses (E14-02).

Direct transcription of ``docs/revision-v0.1-specification.md`` -- ``work_item``,
``ProjectRevision``, ``node``, the two facets, the precedence links and the frozen
lines of a validated estimate. No persistence concern: ids are plain integers
allocated by :class:`Project` counters, and timestamps are always passed in by the
caller (the domain never reads a clock).

Every field is mutable and nullable where the target column would be, so that a
test can deliberately build an invalid state and check that
:func:`waterfall.domain.revision.invariants.check_invariants` names the violated
invariant. The *operations* (see :mod:`waterfall.domain.revision.tree`) never
produce such a state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class WorkItemKind(StrEnum):
    """Nature of a ``work_item``, invariable across revisions (INV-13)."""

    TASK = "task"
    COST = "cost"


class RevisionKind(StrEnum):
    """Nature of a revision. ``forecast_remaining`` is the RAE (reste à engager)."""

    INITIAL = "initial"
    CONTRACT_REFERENCE = "contract_reference"
    FORECAST_REMAINING = "forecast_remaining"


class RevisionStatus(StrEnum):
    """Lifecycle status. Only ``draft`` accepts writes (INV-03)."""

    DRAFT = "draft"
    VALIDATED = "validated"
    SUPERSEDED = "superseded"


class CostNature(StrEnum):
    """Nature of a cost facet: labour (MO) or anything else (INV-19, INV-20)."""

    LABOR = "labor"
    NON_LABOR = "non_labor"


class CalendarSource(StrEnum):
    """Provenance of a plan facet's calendar, ordered ``manual`` > ``role`` > ``project``.

    See "Règle 1 — Origine du calendrier d'une tâche" of the specification: only
    ``project`` and ``role`` may be overwritten by an automatic resynchronisation.
    """

    PROJECT = "project"
    ROLE = "role"
    MANUAL = "manual"


class SupplyStatus(StrEnum):
    """Supply follow-up status of a non-labour cost facet."""

    PLANNED = "planned"
    ORDERED = "ordered"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class ProjectStatus(StrEnum):
    """Lifecycle status of the *project*, not of one of its revisions.

    Spelled with the values the existing ``ms_project.status`` check constraint
    already uses. The revision domain only reads the first transition:
    saving the lotissement moves ``cree`` to ``initialise`` and is the **only**
    trigger of that transition (INV-26).
    """

    CREE = "cree"
    INITIALISE = "initialise"
    EN_REPONSE_APPEL_OFFRE = "en_reponse_appel_offre"
    PERDU = "perdu"
    EN_COURS = "en_cours"
    TERMINE = "termine"
    ABANDONNE = "abandonne"


class BreakdownKind(StrEnum):
    """Nature of a lotissement entry, in the vocabulary the product already uses."""

    POSTE = "poste"
    LOT = "lot"
    LIVRABLE = "livrable"


@dataclass(frozen=True)
class BreakdownEntry:
    """One entry of the **lotissement**: a poste, a lot or a livrable.

    Project data, never revision data (INV-26): the lotissement is not versioned,
    has no history, and a validated revision does not freeze it. Frozen as a
    dataclass because the lotissement is replaced wholesale by
    :func:`~waterfall.domain.revision.work_breakdown.save_work_breakdown` -- the
    "enregistrement" that moves the project from ``cree`` to ``initialise``.

    The display order is the order of :attr:`Project.work_breakdown`, exactly as
    the file order carries it for an imported task; no ``position`` is stored.
    """

    id: int
    kind: BreakdownKind
    name: str
    parent_id: int | None = None


@dataclass(frozen=True)
class SkeletonFingerprint:
    """Marker of "this tree is still the skeleton that was generated" (Règle 4).

    Two independent parts on purpose:

    * ``breakdown_digest`` records *which* lotissement the skeleton was generated
      from. It goes stale as soon as the lotissement is edited, which is precisely
      when regenerating becomes *useful*, so it never authorises nor refuses a
      regeneration; its single reader is
      :func:`~waterfall.domain.revision.work_breakdown.breakdown_changed_since_generation`;
    * ``tree_digest`` is the marker itself: "not touched since" means the tree as
      it stands now condenses to this very digest.

    Both halves are **non-reversible** condensates and neither is readable content:
    a revision keeps an *empreinte* of the skeleton, never a copy of the
    lotissement nor of the labels it was generated from (INV-26). A validated
    revision would otherwise freeze them, and a typo in a lot label would become
    incorrigible.

    Deliberately not a timestamp compared against ``updated_at``, and deliberately
    not a flag carried by each node: both were considered and refused.
    """

    breakdown_digest: str
    tree_digest: str


@dataclass
class WorkItem:
    """Stable identity of an element of work, across every revision of a project.

    Two optional hooks onto an outside identity, and both serve the very same
    purpose -- landing on the *same* work item when the same thing is created
    again in another revision:

    * ``external_uid`` is the MS Project uid a re-import hooks onto (Rule 3 c,
      INV-25);
    * ``breakdown_entry_id`` is the lotissement entry a generated skeleton task
      hooks onto (Règle 4). It is a plain reference to project data, never a copy
      of it: no label, no nature, nothing a validated revision could freeze
      (INV-26).
    """

    id: int
    project_id: int
    kind: WorkItemKind
    description: str | None = None
    external_uid: int | None = None
    breakdown_entry_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class RevisionNode:
    """A position in the tree of one revision: ``(revision, work_item, parent, position)``."""

    id: int
    revision_id: int
    work_item_id: int
    parent_id: int | None = None
    position: int = 1


@dataclass
class PlanFacet:
    """Planning facet: what makes a node a *task*."""

    node_id: int
    name: str
    calendar_id: int | None = None
    calendar_source: CalendarSource | None = None
    is_milestone: bool = False
    duration_minutes: int | None = None
    duration_format: int | None = None
    start_at: datetime | None = None
    finish_at: datetime | None = None
    work_minutes: int | None = None
    percent_complete: int = 0
    is_manual: bool = False


@dataclass
class CostFacet:
    """Cost facet: what makes a node a *cost line*.

    ``role_id``/``hours`` are the labour attributes; ``cost_type_id``/
    ``cost_category_id``/``unit_cost`` the non-labour ones. Derived amounts are
    never stored here (see :mod:`waterfall.domain.revision.pricing`).
    """

    node_id: int
    nature: CostNature
    label: str
    quantity: Decimal = Decimal("1")
    role_id: int | None = None
    hours: Decimal | None = None
    cost_type_id: int | None = None
    cost_category_id: int | None = None
    unit_cost: Decimal | None = None
    supply_status: SupplyStatus | None = None
    planned_date: date | None = None
    cost_code_id: int | None = None
    comment: str | None = None


@dataclass
class NodeLink:
    """A precedence link, node -> node, inside a single revision."""

    node_id: int
    predecessor_node_id: int
    link_type: int = 1
    lag_tenth_minute: int = 0
    lag_format: int | None = None


@dataclass
class FrozenLine:
    """A line of the immutable financial document produced at validation time.

    Carries identities (``work_item_id``, ``bearing_work_item_id``) and copied
    labels/amounts only -- never a node id, a facet or a line of another revision
    (INV-23).
    """

    revision_id: int
    work_item_id: int
    bearing_work_item_id: int | None
    label: str
    bearing_task_name: str | None = None
    role_name: str | None = None
    accounting_code: str | None = None
    category_code: str | None = None
    year: int | None = None
    quantity: Decimal = Decimal("1")
    hours: Decimal | None = None
    hourly_rate: Decimal | None = None
    inflation_coefficient: Decimal | None = None
    amount: Decimal = Decimal("0")


@dataclass
class ProjectRevision:
    """A complete version of a project: one tree, two facets, and its frozen lines."""

    id: int
    project_id: int
    version_number: int
    kind: RevisionKind = RevisionKind.INITIAL
    status: RevisionStatus = RevisionStatus.DRAFT
    source_revision_id: int | None = None
    currency_code: str = "EUR"
    lock_version: int = 0
    note: str | None = None
    created_at: datetime | None = None
    validated_at: datetime | None = None
    #: Set when a skeleton is generated from the project's lotissement, and only
    #: then. Never holds the lotissement itself, which stays project data (INV-26).
    skeleton_fingerprint: SkeletonFingerprint | None = None
    nodes: dict[int, RevisionNode] = field(default_factory=dict[int, RevisionNode])
    plan_facets: dict[int, PlanFacet] = field(default_factory=dict[int, PlanFacet])
    cost_facets: dict[int, CostFacet] = field(default_factory=dict[int, CostFacet])
    links: list[NodeLink] = field(default_factory=list[NodeLink])
    frozen_lines: list[FrozenLine] = field(default_factory=list[FrozenLine])


@dataclass
class Role:
    """A resource role, reduced to what the tree domain needs of it.

    Only the attributes the revision domain actually reads: the calendar that
    "Règle 1" propagates onto a task, plus labels/rates copied into frozen lines.
    """

    id: int
    name: str
    calendar_id: int | None = None
    category_code: str | None = None
    accounting_code: str | None = None
    hourly_rate: Decimal | None = None


@dataclass
class Project:
    """Owner of the work items, the roles and every revision of a project.

    Also holds the identity counters: the domain allocates ids itself so that a
    scenario is fully deterministic and reproducible without a database sequence.
    """

    id: int
    name: str = "Project"
    status: ProjectStatus = ProjectStatus.CREE
    calendar_id: int = 1
    #: The lotissement, in display order. Project data: not versioned, no history,
    #: and editable whatever the status of any revision (INV-26).
    work_breakdown: tuple[BreakdownEntry, ...] = ()
    work_items: dict[int, WorkItem] = field(default_factory=dict[int, WorkItem])
    roles: dict[int, Role] = field(default_factory=dict[int, Role])
    #: Cost category id -> accounting code, only used to copy a label onto a frozen line.
    cost_categories: dict[int, str] = field(default_factory=dict[int, str])
    revisions: dict[int, ProjectRevision] = field(default_factory=dict[int, ProjectRevision])
    reference_revision_id: int | None = None
    next_work_item_id: int = 1
    next_revision_id: int = 1
    next_node_id: int = 1
