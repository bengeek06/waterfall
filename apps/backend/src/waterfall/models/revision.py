"""Tables of the revision model (E14-03, issue #329).

A one-for-one translation of the pure domain of E14-02
(:mod:`waterfall.domain.revision.entities`), itself a transcription of
``docs/revision-v0.1-specification.md``: a ``work_item`` is the stable identity of
an element of work across the versions of a project, a revision carries the tree
of one version exactly once, a node is a position in that tree, and the planning
and the cost are two facets hung on the same node.

Strictly **additive**: these tables are created next to `ms_task`,
`wf_planning_task_snapshot`, `wf_estimate_task_row`, `wf_estimate_grid_node` and
the rest of the twin-task base, which stay in place and keep serving every
existing consumer until E14-12 (#339) removes them.

Deliberately **not** modelled here, even though the pure domain carries them: the
lotissement (``breakdown_entry_id``, the skeleton fingerprint). Règle 4 and INV-26
of the specification are flagged provisoire -- they come out of an information
architecture spike still in progress -- and the specification states that no
table, no migration and no API of E14 may be built on them. The test bench keeps
them because undoing a decision there costs a rewritten test; the database does
not, because undoing it here would cost a migration.

Which invariant each constraint translates is stated on the constraint itself.
The ones this schema does **not** enforce are enumerated here, and the list is
meant to be exhaustive -- a partial list would read as an assurance it does not
give. They fall in three groups:

* *not expressible in SQL on either dialect*: acyclicity of the parent graph
  (INV-06) and of the precedence graph (INV-18), contiguity of sibling positions
  (INV-05, whose positivity and uniqueness *are* constrained), the "never none"
  half of "exactly one facet" (INV-11, whose "never both" half *is* constrained),
  upward closure of the planning layer (INV-14);
* *expressible, but deliberately left out*: a node's ``work_item`` belongs to the
  project owning the revision (INV-10). Constraining it would mean carrying a
  denormalised ``project_id`` on `wf_revision_node` plus two composite foreign
  keys; it is tracked as its own issue, and the adapter refuses a node whose work
  item is not one of the loaded project's meanwhile;
* *about a table this issue does not create*: the frozen lines of a validated
  revision (INV-01, INV-23, INV-24) have no table here -- see
  :class:`RevisionCostFacet` -- and `wf_revision_frozen_line` comes with the
  validation of a revision, E14-08 (#334). INV-26 is in the same case for the
  lotissement, see the paragraph above.

Everything else -- INV-04, INV-08, INV-09, INV-12, INV-13, INV-15, INV-16,
INV-17, INV-19, INV-20, INV-21, INV-22, INV-25 -- is carried by a constraint of
this module, and the three ``opération``-scoped invariants (INV-02 cascade
delete, INV-03 immutability of a validated revision, INV-07 copy) are
post-conditions of an operation, which no constraint of a single state expresses.
:func:`~waterfall.services.revision_store.save_revision` refuses to overwrite a
revision the database holds as ``validated`` or ``superseded``, which is as close
to INV-03 as a check on one state gets.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from waterfall.db.base import Base


class WorkItem(Base):
    """Stable identity of an element of work, across every revision of a project.

    Carries only what survives the versions: the ``description`` that
    `wf_task_enrichment` holds today at project level, and the MS Project uid as
    the **external** identifier of the import/export layer. A label never lives
    here -- a task name and a cost line label belong to a facet, hence to one
    revision, so that renaming in a draft cannot alter what a validated revision
    shows.
    """

    __tablename__ = "wf_work_item"
    __table_args__ = (
        # INV-25: an external_uid is unique per project when set. NULLs stay
        # distinct from one another in SQL, which is exactly what the invariant
        # asks for -- every item created in Waterfall and never exported has none.
        UniqueConstraint("project_id", "external_uid", name="uq_wf_work_item_external_uid"),
        # INV-25, second half: an external_uid on a cost item would be an uid the
        # MS Project file has no image for.
        CheckConstraint(
            "external_uid IS NULL OR kind = 'task'",
            name="ck_wf_work_item_external_uid_task_only",
        ),
        CheckConstraint(
            "external_uid IS NULL OR external_uid >= 0",
            name="ck_wf_work_item_external_uid_non_negative",
        ),
        CheckConstraint("kind IN ('task', 'cost')", name="ck_wf_work_item_kind"),
        # Target of wf_revision_node's composite FK, which is what makes a node's
        # own `kind` provably the kind of its work item (INV-13). Redundant with
        # the primary key on its own, and declared for that FK alone -- the same
        # shape `ms_task`/`ms_task_link` already use.
        UniqueConstraint("id", "kind", name="uq_wf_work_item_id_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    #: ``task`` or ``cost``, invariable from one revision to the next (INV-13).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: MS Project uid, the external identifier of the import/export layer alone.
    external_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ProjectRevision(Base):
    """A complete version of a project: one tree and its two facets.

    ``lock_version`` is a brand new column, not a rename: the optimistic-lock
    counters of `wf_planning.revision` and `wf_estimate.revision` are still read
    by the current code and are left strictly alone until E14-12 (#339).
    """

    __tablename__ = "wf_revision"
    __table_args__ = (
        # INV-21: version numbers are unique per project and strictly positive.
        UniqueConstraint("project_id", "version_number", name="uq_wf_revision_project_version"),
        CheckConstraint("version_number > 0", name="ck_wf_revision_version"),
        CheckConstraint(
            "kind IN ('initial', 'contract_reference', 'forecast_remaining')",
            name="ck_wf_revision_kind",
        ),
        CheckConstraint(
            "status IN ('draft', 'validated', 'superseded')",
            name="ck_wf_revision_status",
        ),
        CheckConstraint("lock_version >= 0", name="ck_wf_revision_lock_version"),
        # INV-22: at most one `validated` revision per (project, kind); the earlier
        # validated ones of the same kind are `superseded`. A partial unique index
        # is the only shape that constrains one status value without constraining
        # the others -- same dialect-specific kwargs as
        # `uq_wf_calendar_is_default_true` (issue #51).
        Index(
            "uq_wf_revision_validated_per_kind",
            "project_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'validated'"),
            sqlite_where=text("status = 'validated'"),
        ),
        Index("idx_wf_revision_project_status", "project_id", "status", "id"),
        # "Which revisions descend from this one?", and the referencing side of
        # `source_revision_id`'s self-foreign-key, which PostgreSQL scans on every
        # delete of a revision without it.
        Index("idx_wf_revision_source_revision", "source_revision_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("ms_project.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="initial")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    #: Revision this one was copied from, NULL for a revision created from scratch.
    source_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_revision.id"), nullable=True
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    #: Optimistic lock counter, bumped on every write to a draft. Not a version
    #: number: `version_number` above is the version number.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RevisionNode(Base):
    """One position in the tree of one revision: ``(revision, work_item, parent, position)``.

    Carries no business data at all -- every business attribute belongs to one of
    the two facets. ``outline_level`` and ``outline_number`` are not stored
    either: they are computed from ``parent_id`` and ``position``, which is what
    removes the label and position drift `wf_estimate_task_row` had to correct on
    read.

    ``kind`` is the one deliberately denormalised column of this schema: a
    projection of `WorkItem.kind`, held consistent by a composite foreign key
    rather than by convention, and the hook the two facet tables need to make
    INV-13 a database constraint rather than an application rule.
    """

    __tablename__ = "wf_revision_node"
    __table_args__ = (
        # INV-04: a work_item appears at most once in a given revision.
        UniqueConstraint("revision_id", "work_item_id", name="uq_wf_revision_node_work_item"),
        # INV-05: sibling positions start at 1. Contiguity itself is not
        # expressible in SQL and stays with the domain module.
        CheckConstraint("position > 0", name="ck_wf_revision_node_position"),
        # INV-05: two siblings never share a position. This constraint covers
        # every non-root sibling set -- and *only* those: SQL compares NULL to
        # NULL as unknown, so the root nodes (parent_id IS NULL) all slip through
        # it. `parent_id` alone is enough to scope it, a node id being unique
        # across revisions.
        UniqueConstraint("parent_id", "position", name="uq_wf_revision_node_sibling_position"),
        # INV-05 for the root sibling set the constraint above cannot see. A
        # partial unique index is what closes that hole rather than leaving it:
        # scoped to the revision, since "the root siblings" is a per-revision set.
        Index(
            "uq_wf_revision_node_root_position",
            "revision_id",
            "position",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
            sqlite_where=text("parent_id IS NULL"),
        ),
        CheckConstraint("kind IN ('task', 'cost')", name="ck_wf_revision_node_kind"),
        # INV-09: a node and its parent belong to the same revision. Same shape as
        # `ms_task`'s self-referencing composite FK: the pair (revision_id,
        # parent_id) can only match a row of this very revision.
        UniqueConstraint("revision_id", "id", name="uq_wf_revision_node_revision_id"),
        ForeignKeyConstraint(
            ["revision_id", "parent_id"],
            ["wf_revision_node.revision_id", "wf_revision_node.id"],
            name="fk_wf_revision_node_parent",
        ),
        # INV-13, first half: this node's kind *is* its work item's kind. The
        # second half -- the facet carried matches that kind -- is enforced by the
        # facet tables below, through `uq_wf_revision_node_id_kind`.
        UniqueConstraint("id", "kind", name="uq_wf_revision_node_id_kind"),
        ForeignKeyConstraint(
            ["work_item_id", "kind"],
            ["wf_work_item.id", "wf_work_item.kind"],
            name="fk_wf_revision_node_work_item",
        ),
        Index("idx_wf_revision_node_revision_parent", "revision_id", "parent_id", "position"),
        # "In which revisions does this work item appear?" -- the cross-version
        # comparison a `work_item` exists for in the first place, and a full scan
        # without this index. It is also the referencing side of
        # `fk_wf_revision_node_work_item`, which PostgreSQL does not index on its
        # own: every delete or key update on `wf_work_item` scans this table
        # otherwise, E14-12 (#339) included.
        Index("idx_wf_revision_node_work_item", "work_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("wf_revision.id"), nullable=False)
    #: Constrained by the composite FK above, not by a second single-column one.
    work_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Denormalised projection of `WorkItem.kind` -- see the class docstring.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class RevisionPlanFacet(Base):
    """Planning facet: what makes a node a *task*. At most one row per node.

    ``node_kind`` exists for its composite foreign key alone: pinned to ``task``
    by a check constraint and matched against `wf_revision_node.(id, kind)`, it
    makes "a planning facet only ever hangs on a task node" a database
    constraint (INV-13). Together with the uniqueness of ``node_id`` on both
    facet tables it also rules out a node carrying *both* facets -- the "never
    both" half of INV-11. The "never none" half needs a deferred check no
    dialect here offers, and stays with the domain module.
    """

    __tablename__ = "wf_revision_plan_facet"
    __table_args__ = (
        UniqueConstraint("node_id", name="uq_wf_revision_plan_facet_node"),
        CheckConstraint("node_kind = 'task'", name="ck_wf_revision_plan_facet_node_kind"),
        ForeignKeyConstraint(
            ["node_id", "node_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_plan_facet_node",
        ),
        # INV-15: a planning facet always carries a calendar -- `calendar_id` is
        # NOT NULL and `calendar_source` names where the value comes from. An
        # unpriced task stays schedulable, which is the whole reason the calendar
        # is an attribute of this facet and never derived from the roles (Règle 1).
        CheckConstraint(
            "calendar_source IN ('project', 'role', 'manual')",
            name="ck_wf_revision_plan_facet_calendar_source",
        ),
        # Numeric domains, which the specification explicitly assigns to the
        # column constraints of the database rather than to the invariants.
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="ck_wf_revision_plan_facet_duration",
        ),
        CheckConstraint(
            "work_minutes IS NULL OR work_minutes >= 0",
            name="ck_wf_revision_plan_facet_work",
        ),
        CheckConstraint(
            "percent_complete BETWEEN 0 AND 100",
            name="ck_wf_revision_plan_facet_percent_complete",
        ),
        Index("idx_wf_revision_plan_facet_calendar", "calendar_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Always ``task`` -- see the class docstring.
    node_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="task")
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("wf_calendar.id"), nullable=False)
    calendar_source: Mapped[str] = mapped_column(String(16), nullable=False, default="project")
    is_milestone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_format: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent_complete: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RevisionCostFacet(Base):
    """Cost facet: what makes a node a *cost line*. At most one row per node.

    ``role_id``/``hours`` are the labour attributes, ``cost_type_id``/
    ``cost_category_id``/``unit_cost`` the non-labour ones, and the check
    constraint below is INV-19/INV-20 verbatim. Derived amounts -- MO, Achat,
    PRU -- are never stored here: they are computed, and only frozen at
    validation time onto the frozen lines of the validated revision.

    ``node_kind`` plays exactly the role it plays on the planning facet, pinned
    to ``cost`` instead.
    """

    __tablename__ = "wf_revision_cost_facet"
    __table_args__ = (
        UniqueConstraint("node_id", name="uq_wf_revision_cost_facet_node"),
        CheckConstraint("node_kind = 'cost'", name="ck_wf_revision_cost_facet_node_kind"),
        ForeignKeyConstraint(
            ["node_id", "node_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_cost_facet_node",
        ),
        CheckConstraint(
            "nature IN ('labor', 'non_labor')", name="ck_wf_revision_cost_facet_nature"
        ),
        # INV-19 and INV-20, in one constraint: a labour line carries a role and
        # hours and neither a cost category of its own (it inherits its role's),
        # nor a disbursement, nor a supply follow-up; a non-labour line carries a
        # cost type, a category and a disbursement, and neither role nor hours.
        CheckConstraint(
            "(nature = 'labor' AND role_id IS NOT NULL AND hours IS NOT NULL "
            "AND cost_type_id IS NULL AND cost_category_id IS NULL "
            "AND unit_cost IS NULL AND supply_status IS NULL) OR "
            "(nature = 'non_labor' AND role_id IS NULL AND hours IS NULL "
            "AND cost_type_id IS NOT NULL AND cost_category_id IS NOT NULL "
            "AND unit_cost IS NOT NULL)",
            name="ck_wf_revision_cost_facet_shape",
        ),
        CheckConstraint(
            "supply_status IN ('planned', 'ordered', 'received', 'cancelled') "
            "OR supply_status IS NULL",
            name="ck_wf_revision_cost_facet_supply_status",
        ),
        CheckConstraint("quantity > 0", name="ck_wf_revision_cost_facet_quantity"),
        CheckConstraint("hours IS NULL OR hours >= 0", name="ck_wf_revision_cost_facet_hours"),
        CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name="ck_wf_revision_cost_facet_unit_cost",
        ),
        # The four referential foreign keys of this table, all indexed on their
        # referencing side for the same reason: PostgreSQL does not index it on
        # its own, and every delete or key update in the referential scans the
        # table without it.
        Index("idx_wf_revision_cost_facet_role", "role_id"),
        Index("idx_wf_revision_cost_facet_category", "cost_category_id"),
        Index("idx_wf_revision_cost_facet_cost_type", "cost_type_id"),
        Index("idx_wf_revision_cost_facet_cost_code", "cost_code_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Always ``cost`` -- see the class docstring.
    node_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="cost")
    nature: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("1"))
    role_id: Mapped[int | None] = mapped_column(ForeignKey("wf_resource_role.id"), nullable=True)
    hours: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cost_type_id: Mapped[int | None] = mapped_column(ForeignKey("wf_cost_type.id"), nullable=True)
    cost_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_cost_category.id"), nullable=True
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    supply_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Forecast cash-out date, independent of the bearing task's own dates.
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cost_code_id: Mapped[int | None] = mapped_column(
        ForeignKey("wf_project_cost_code.id"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class RevisionNodeLink(Base):
    """A precedence link, task node -> task node, inside a single revision.

    Replaces `ms_task_link` and `wf_planning_link_snapshot`, which both
    referenced a task by the natural key ``(owner, uid)``.

    ``node_kind`` and ``predecessor_kind`` play exactly the role ``node_kind``
    plays on the two facet tables, pinned to ``task`` on both ends: they turn
    INV-17 into a database constraint instead of an application rule. A
    precedence between a cost line and anything else has no meaning for the
    scheduler, and a cost line is not something a date can be computed for.
    """

    __tablename__ = "wf_revision_node_link"
    __table_args__ = (
        # INV-08: a predecessor designates a node of the same revision. Both
        # endpoints are matched against (revision_id, id), so neither can come
        # from another revision -- the copy of a revision that forgot to
        # retranslate its links is refused by the database itself.
        ForeignKeyConstraint(
            ["revision_id", "node_id"],
            ["wf_revision_node.revision_id", "wf_revision_node.id"],
            name="fk_wf_revision_node_link_node",
        ),
        ForeignKeyConstraint(
            ["revision_id", "predecessor_node_id"],
            ["wf_revision_node.revision_id", "wf_revision_node.id"],
            name="fk_wf_revision_node_link_predecessor",
        ),
        UniqueConstraint(
            "node_id",
            "predecessor_node_id",
            "link_type",
            name="uq_wf_revision_node_link",
        ),
        # INV-16: a node is never its own predecessor. The degenerate one-node
        # cycle is the only case of INV-18 that expresses in SQL.
        CheckConstraint(
            "node_id <> predecessor_node_id",
            name="ck_wf_revision_node_link_not_self",
        ),
        CheckConstraint("link_type IN (0, 1, 2, 3)", name="ck_wf_revision_node_link_type"),
        # INV-17: both ends of a precedence link carry a planning facet, i.e. are
        # task nodes. Same shape as the facet tables: a kind column pinned by a
        # check constraint, matched against `uq_wf_revision_node_id_kind`.
        CheckConstraint("node_kind = 'task'", name="ck_wf_revision_node_link_node_kind"),
        CheckConstraint(
            "predecessor_kind = 'task'", name="ck_wf_revision_node_link_predecessor_kind"
        ),
        ForeignKeyConstraint(
            ["node_id", "node_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_node_link_node_kind",
        ),
        ForeignKeyConstraint(
            ["predecessor_node_id", "predecessor_kind"],
            ["wf_revision_node.id", "wf_revision_node.kind"],
            name="fk_wf_revision_node_link_predecessor_kind",
        ),
        Index("idx_wf_revision_node_link_predecessor", "revision_id", "predecessor_node_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("wf_revision.id"), nullable=False)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Always ``task`` -- see the class docstring.
    node_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="task")
    predecessor_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Always ``task`` -- see the class docstring.
    predecessor_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="task")
    link_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    lag_tenth_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lag_format: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
