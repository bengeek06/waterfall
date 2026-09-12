"""Adapter between the pure revision domain and its tables (E14-03, issue #329).

Loads a revision from the database into the plain dataclasses of
:mod:`waterfall.domain.revision`, and writes a mutated state back. It is the
*only* place that knows both sides: every tree rule -- insertion, move, indent,
cascade delete, renumbering, calendar resynchronisation -- stays in the pure
domain module, which an AST architecture test (E14-02, #328) forbids from
importing SQLAlchemy at all.

Identity, and why the domain ids are session-local
--------------------------------------------------

The domain allocates its own ids from the counters of
:class:`~waterfall.domain.revision.entities.Project`, so a scenario stays
reproducible without a database sequence. Loading seeds those counters *above*
every id it just read, so a freshly created work item or node is recognisable by
its id alone: it cannot collide with a row of the scope that was loaded. Writing
back therefore never inserts an explicit primary key -- the database allocates
it, its sequence stays consistent, and :class:`SaveOutcome` hands back the
``domain id -> database id`` mapping for the caller that needs it.

Sibling positions, and why they are written in two passes
---------------------------------------------------------

``uq_wf_revision_node_sibling_position`` (and its root-sibling counterpart) are
immediate constraints: writing a reordered sibling set one row at a time would
trip them halfway through, on a state the final tree never actually contains --
swapping two siblings is enough. Every node whose parent or position changes is
therefore first pushed out of the way into a high position band, and only then
written to its final place. See :func:`_push_moved_nodes_aside`.

That band is collision-free only as long as no position ever *stored* reaches it,
which :func:`_check_position_band` checks rather than assumes: see
:data:`_POSITION_BAND`.

Refusals, and why they all happen up front
------------------------------------------

:func:`save_revision` decides every refusal in one pass over the complete state,
before its first write. The write is not atomic on its own -- it deletes rows and
parks positions, flushing as it goes -- so a refusal raised from the middle of it
would hand a caller that commits anyway a half-written revision, parked positions
included. See :func:`_validate_before_write`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
from waterfall.models import revision as tables
from waterfall.models.ms_core import MsProject
from waterfall.models.resources import CostCategory, ResourceRole
from waterfall.services.calendar_schedule import resolve_default_calendar_id

#: Offset a node is parked at while a sibling set is being reordered.
#:
#: ``position + _POSITION_BAND`` is collision-free **under the precondition that
#: every position involved is below the band** -- a property of the data, not of
#: the arithmetic, and one nothing in the schema imposes
#: (``ck_wf_revision_node_position`` only bounds positions from below). Positions
#: are renumbered from 1 and no real sibling set comes anywhere near a million, so
#: the precondition holds in practice; :func:`_check_position_band` verifies it
#: before every write rather than assuming it. See the module docstring.
_POSITION_BAND = 1_000_000


class RevisionStoreError(RuntimeError):
    """A revision could not be loaded from, or written back to, the database."""


class RevisionNotFoundError(RevisionStoreError):
    """No revision carries the requested id."""


class MissingProjectCalendarError(RevisionStoreError):
    """The project has no calendar to hand a new planning facet (Règle 1, INV-15)."""


class FrozenRevisionError(RevisionStoreError):
    """INV-03, raised from this layer: the stored revision is validated or superseded.

    Added by E14-05 (#331) to close the hazard the review of #330 reported, and
    named by :mod:`waterfall.services.revision_tree`'s own docstring: INV-03 used
    to come out of this module as a *bare* :class:`RevisionStoreError`, a class it
    also uses for refusals that have nothing to do with INV-03 (frozen lines with
    no table, an unreachable node, a position parked in the band). A transport
    layer mapping "the revision is frozen" onto its own HTTP status therefore had
    no way to tell the two apart short of matching on the message.

    Deliberately still a :class:`RevisionStoreError`, so every existing
    ``except RevisionStoreError`` keeps catching it; what changes is that the
    INV-03 refusal is now *also* catchable on its own. Together with
    :class:`~waterfall.domain.revision.ImmutableRevisionError`, which the domain
    and the tree service raise for the same invariant, it is the complete set a
    route catches -- see
    :func:`waterfall.api.revision_errors.revision_http_exception`, which is the
    single place either is translated.
    """


@dataclass(frozen=True)
class LoadedRevision:
    """One revision, fully materialised, inside the project that owns it.

    ``project`` also carries every ``work_item`` of the project and a stub -- id,
    version number, kind, status, no tree -- for each of its *other* revisions,
    so that the domain can allocate a version number (INV-21) and see the
    validated revision of each kind (INV-22) without loading every tree of the
    project. Those stubs are deliberately not writable: see
    :func:`save_revision`.

    They are held here **by identity**, not by id, which states the rule directly:
    a copy the domain created is not a stub and never becomes one, whatever number
    it ends up carrying once :func:`_adopt_database_ids` has moved the revisions it
    wrote onto the ids the database allocated.

    That is a defensive margin, not a guarantee any test holds: under the
    invariants this module maintains, comparing ids would answer the same. The ids
    of ``project.revisions`` are unique and :func:`_rekey_revision` evicts no entry
    from it, so a revision whose id equals a stub's *is* that stub. Should either
    property ever stop holding, the identity test keeps answering correctly where
    the id test would start reading "a copy that has adopted its database id" as
    "a revision loaded without its tree".
    """

    project: domain.Project
    revision: domain.ProjectRevision
    #: The revisions of the project that were loaded without their tree.
    stubs: tuple[domain.ProjectRevision, ...] = ()

    def is_stub(self, revision: domain.ProjectRevision) -> bool:
        """Whether ``revision`` is one of the tree-less revisions this load carries."""
        return any(revision is stub for stub in self.stubs)


@dataclass(frozen=True)
class SaveOutcome:
    """What the database made of the domain ids that were written back.

    Both mappings are keyed by the id each object carried *before* the save: the
    objects themselves have since adopted their database id (see
    :func:`_adopt_database_ids`), so reading ``node_ids[node.id]`` after a save
    that inserted anything looks up the wrong key. Keep the id you handed in.
    """

    #: Database id of the revision that was written.
    revision_id: int
    #: Domain node id -> database node id, for every node of the saved revision.
    node_ids: Mapping[int, int]
    #: Domain work item id -> database work item id, for every item of the project.
    work_item_ids: Mapping[int, int]


def _now() -> datetime:
    """The adapter may read a clock; the domain it feeds may not."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def load_revision(db: Session, revision_id: int) -> LoadedRevision:
    """Materialise revision ``revision_id`` and its project as domain objects."""
    row = db.get(tables.ProjectRevision, revision_id)
    if row is None:
        raise RevisionNotFoundError(f"Revision {revision_id} does not exist")
    project = _load_project(db, row.project_id)
    revision = project.revisions[row.id]
    _load_tree(db, project, revision)
    stubs = tuple(other for other in project.revisions.values() if other is not revision)
    return LoadedRevision(project=project, revision=revision, stubs=stubs)


def _load_project(db: Session, project_id: int) -> domain.Project:
    project_row = db.get(MsProject, project_id)
    if project_row is None:
        raise RevisionNotFoundError(f"Project {project_id} does not exist")
    calendar_id = resolve_default_calendar_id(db)
    if calendar_id is None:
        raise MissingProjectCalendarError(
            "No active calendar is flagged as the organisation default, so a new task "
            "would have no calendar to inherit (Règle 1, INV-15); flag one on "
            "GET /resources/calendars first"
        )
    project = domain.Project(
        id=project_row.id,
        name=project_row.name,
        status=domain.ProjectStatus(project_row.status),
        calendar_id=calendar_id,
    )
    _load_work_items(db, project)
    _load_roles(db, project)
    _load_revision_stubs(db, project)
    return project


def _load_work_items(db: Session, project: domain.Project) -> None:
    rows = (
        db.query(tables.WorkItem)
        .filter(tables.WorkItem.project_id == project.id)
        .order_by(tables.WorkItem.id)
        .all()
    )
    for row in rows:
        project.work_items[row.id] = domain.WorkItem(
            id=row.id,
            project_id=row.project_id,
            kind=domain.WorkItemKind(row.kind),
            description=row.description,
            external_uid=row.external_uid,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    project.next_work_item_id = _next_id(project.work_items)


def _load_roles(db: Session, project: domain.Project) -> None:
    """Roles and cost categories, reduced to what the tree domain reads of them.

    ``hourly_rate`` is left unset on purpose: a rate is per year (`wf_cost_rate`)
    and belongs to the pricing engine, not to the tree. The domain only reads a
    role's calendar (Règle 1) and its labels.
    """
    categories = {row.id: row for row in db.query(CostCategory).all()}
    for row in db.query(ResourceRole).order_by(ResourceRole.id).all():
        category = categories.get(row.cost_category_id)
        project.roles[row.id] = domain.Role(
            id=row.id,
            name=row.name,
            calendar_id=row.calendar_id,
            category_code=category.category_code if category is not None else None,
            accounting_code=category.accounting_code if category is not None else None,
        )
    project.cost_categories = {row.id: row.accounting_code for row in categories.values()}


def _load_revision_stubs(db: Session, project: domain.Project) -> None:
    rows = (
        db.query(tables.ProjectRevision)
        .filter(tables.ProjectRevision.project_id == project.id)
        .order_by(tables.ProjectRevision.id)
        .all()
    )
    for row in rows:
        project.revisions[row.id] = domain.ProjectRevision(
            id=row.id,
            project_id=row.project_id,
            version_number=row.version_number,
            kind=domain.RevisionKind(row.kind),
            status=domain.RevisionStatus(row.status),
            source_revision_id=row.source_revision_id,
            currency_code=row.currency_code,
            lock_version=row.lock_version,
            note=row.note,
            created_at=row.created_at,
            validated_at=row.validated_at,
        )
    project.next_revision_id = _next_id(project.revisions)


def _load_tree(db: Session, project: domain.Project, revision: domain.ProjectRevision) -> None:
    for row in _node_rows(db, revision.id):
        revision.nodes[row.id] = domain.RevisionNode(
            id=row.id,
            revision_id=row.revision_id,
            work_item_id=row.work_item_id,
            parent_id=row.parent_id,
            position=row.position,
        )
    for plan in _plan_facet_rows(db, revision.id):
        revision.plan_facets[plan.node_id] = domain.PlanFacet(
            node_id=plan.node_id,
            name=plan.name,
            calendar_id=plan.calendar_id,
            calendar_source=domain.CalendarSource(plan.calendar_source),
            is_milestone=plan.is_milestone,
            duration_minutes=plan.duration_minutes,
            duration_format=plan.duration_format,
            start_at=plan.start_at,
            finish_at=plan.finish_at,
            work_minutes=plan.work_minutes,
            percent_complete=plan.percent_complete,
            is_manual=plan.is_manual,
        )
    for cost in _cost_facet_rows(db, revision.id):
        revision.cost_facets[cost.node_id] = domain.CostFacet(
            node_id=cost.node_id,
            nature=domain.CostNature(cost.nature),
            label=cost.label,
            quantity=cost.quantity,
            role_id=cost.role_id,
            hours=cost.hours,
            cost_type_id=cost.cost_type_id,
            cost_category_id=cost.cost_category_id,
            unit_cost=cost.unit_cost,
            supply_status=(
                None if cost.supply_status is None else domain.SupplyStatus(cost.supply_status)
            ),
            planned_date=cost.planned_date,
            cost_code_id=cost.cost_code_id,
            comment=cost.comment,
        )
    revision.links = [
        domain.NodeLink(
            node_id=link.node_id,
            predecessor_node_id=link.predecessor_node_id,
            link_type=link.link_type,
            lag_tenth_minute=link.lag_tenth_minute,
            lag_format=link.lag_format,
        )
        for link in _link_rows(db, revision.id)
    ]
    project.next_node_id = _next_id(revision.nodes)


def _next_id(loaded: Mapping[int, object]) -> int:
    """One past the highest id read, so a new domain object cannot shadow a row."""
    return max(loaded, default=0) + 1


def _node_rows(db: Session, revision_id: int) -> list[tables.RevisionNode]:
    return (
        db.query(tables.RevisionNode)
        .filter(tables.RevisionNode.revision_id == revision_id)
        .order_by(tables.RevisionNode.id)
        .all()
    )


def _plan_facet_rows(db: Session, revision_id: int) -> list[tables.RevisionPlanFacet]:
    return (
        db.query(tables.RevisionPlanFacet)
        .join(tables.RevisionNode, tables.RevisionNode.id == tables.RevisionPlanFacet.node_id)
        .filter(tables.RevisionNode.revision_id == revision_id)
        .order_by(tables.RevisionPlanFacet.node_id)
        .all()
    )


def _cost_facet_rows(db: Session, revision_id: int) -> list[tables.RevisionCostFacet]:
    return (
        db.query(tables.RevisionCostFacet)
        .join(tables.RevisionNode, tables.RevisionNode.id == tables.RevisionCostFacet.node_id)
        .filter(tables.RevisionNode.revision_id == revision_id)
        .order_by(tables.RevisionCostFacet.node_id)
        .all()
    )


def _link_rows(db: Session, revision_id: int) -> list[tables.RevisionNodeLink]:
    return (
        db.query(tables.RevisionNodeLink)
        .filter(tables.RevisionNodeLink.revision_id == revision_id)
        .order_by(tables.RevisionNodeLink.id)
        .all()
    )


# --------------------------------------------------------------------------------------
# Writing back
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _StoredRows:
    """What the database holds for the revision being written, read once.

    Read *before* the first mutation -- the validation pass has to see the very
    state the write will act on -- and kept up to date as rows are deleted, so no
    step of the write has to query the same table twice.
    """

    nodes: dict[int, tables.RevisionNode]
    plan_facets: dict[int, tables.RevisionPlanFacet]
    cost_facets: dict[int, tables.RevisionCostFacet]
    #: Keyed by ``(node, predecessor, type)``: the identity of a precedence link.
    links: dict[tuple[int, int, int], tables.RevisionNodeLink]


def _link_key(node_id: int, predecessor_node_id: int, link_type: int) -> tuple[int, int, int]:
    """Identity of a precedence link -- it *is* its ``(node, predecessor, type)`` triple.

    Exactly what ``uq_wf_revision_node_link`` states, which is what lets the
    write diff links instead of rewriting them.
    """
    return (node_id, predecessor_node_id, link_type)


def _stored_rows(db: Session, revision_id: int | None) -> _StoredRows:
    """Every row of ``revision_id``; empty for a revision that is not stored yet."""
    if revision_id is None:
        return _StoredRows(nodes={}, plan_facets={}, cost_facets={}, links={})
    return _StoredRows(
        nodes={row.id: row for row in _node_rows(db, revision_id)},
        plan_facets={row.node_id: row for row in _plan_facet_rows(db, revision_id)},
        cost_facets={row.node_id: row for row in _cost_facet_rows(db, revision_id)},
        links={
            _link_key(row.node_id, row.predecessor_node_id, row.link_type): row
            for row in _link_rows(db, revision_id)
        },
    )


def save_revision(
    db: Session,
    loaded: LoadedRevision,
    revision: domain.ProjectRevision | None = None,
) -> SaveOutcome:
    """Write ``revision`` (the loaded one by default) back into the database.

    ``revision`` may also be a revision the domain created inside the same project
    -- a copy, for instance -- in which case it is inserted, and it stays saveable
    afterwards like any other: several may be created before the first is written,
    and each may be written again after it. It may *not* be one of the untouched
    stubs :class:`LoadedRevision` carries for the other revisions of the project:
    those have no tree in memory, and writing one back would read that emptiness
    as "every node was deleted". Which is which is settled by identity
    (:meth:`LoadedRevision.is_stub`) rather than by the id carried -- a defensive
    margin, the two answering alike under the invariants in force; see
    :class:`LoadedRevision`.

    A copy's provenance follows the same rule as its work items: writing its
    source renumbers the pointer, so ``source_revision_id`` designates the row the
    source became and never the revision that number has come to mean elsewhere.

    Errors and the transaction
    --------------------------

    Every business refusal is decided by :func:`_validate_before_write`, **before
    the first row is touched**: a :class:`RevisionStoreError` therefore leaves the
    transaction holding exactly what it held on entry. The caller must still
    ``rollback()`` rather than carry on and commit -- an ``IntegrityError`` raised
    by the database itself offers no such guarantee, and leaves the session
    unusable anyway.

    The session is flushed, never committed: the caller owns the transaction.
    """
    project = loaded.project
    target = loaded.revision if revision is None else revision
    if loaded.is_stub(target):
        raise RevisionStoreError(
            f"Revision {target.id} was loaded as a stub, without its tree; only the fully "
            f"loaded revision {loaded.revision.id} (or a revision the domain created since) "
            "can be written back"
        )
    stored_status = _stored_revision_status(db, project.id)
    stored = _stored_rows(db, target.id if target.id in stored_status else None)
    work_item_kinds = _stored_work_item_kinds(db, project.id)
    _validate_before_write(project, target, stored, stored_status, work_item_kinds)

    work_item_ids = _save_work_items(db, project)
    revision_id = _save_revision_row(db, project, target, stored_status)
    node_ids = _save_tree(db, project, target, revision_id, stored, work_item_ids)
    _save_facets(db, target, stored, node_ids)
    _save_links(db, target, revision_id, stored, node_ids)
    db.flush()
    _adopt_database_ids(project, target, revision_id, node_ids, work_item_ids)
    return SaveOutcome(revision_id=revision_id, node_ids=node_ids, work_item_ids=work_item_ids)


# --------------------------------------------------------------------------------------
# Validation, before anything is written
# --------------------------------------------------------------------------------------


def _validate_before_write(
    project: domain.Project,
    revision: domain.ProjectRevision,
    stored: _StoredRows,
    stored_status: Mapping[int, str],
    work_item_kinds: Mapping[int, str],
) -> None:
    """Refuse an unwritable state before a single row has been touched.

    Every refusal of this module is decided here, on the complete state, and that
    placement is the whole point: the write deletes rows and parks sibling
    positions in a high band, flushing as it goes. A refusal raised halfway
    through would leave a caller that commits anyway with its precedence links
    already gone and positions left in the parking band -- a revision violating
    INV-05 for good, and a band no later write could park a node in again.
    """
    _refuse_frozen_lines(revision)
    _refuse_a_frozen_revision(revision, stored_status)
    _check_source_revision(revision, stored_status)
    _check_stored_work_item_kinds(project, work_item_kinds)
    _check_reachable(revision)
    _check_facet_nodes(revision)
    _check_link_endpoints(revision)
    _check_position_band(revision, stored)
    for node in sorted(revision.nodes.values(), key=lambda item: item.id):
        _work_item_of(project, node)
        _node_kind(project, revision, node)
    for node_id in sorted(revision.plan_facets):
        _facet_calendar(revision.plan_facets[node_id])


def _refuse_frozen_lines(revision: domain.ProjectRevision) -> None:
    """Refuse a revision carrying frozen lines: there is no table to write them to.

    `wf_revision_frozen_line` is deliberately not part of this issue -- its shape
    is decided by the calculation engine that produces the amounts, E14-08 (#334).
    Writing such a revision anyway would silently drop the lines and store a
    validated revision that the invariant checker then reports as violating
    INV-24, which is exactly the kind of quiet corruption a refusal is worth.
    """
    if revision.frozen_lines:
        raise RevisionStoreError(
            f"Revision {revision.id} carries {len(revision.frozen_lines)} frozen line(s), "
            "which this adapter cannot persist: the frozen lines of a validated revision "
            "come with the validation itself, E14-08 (#334). Validate the revision through "
            "that service rather than writing the validated state back here"
        )


def _refuse_a_frozen_revision(
    revision: domain.ProjectRevision, stored_status: Mapping[int, str]
) -> None:
    """INV-03: a validated or superseded revision no longer accepts a write.

    Read from the **database**, not from the in-memory status: the state in hand
    may be a domain object whose status was just changed, and what must not be
    overwritten is a revision the database already considers frozen. Copying it
    is the only way to edit it (INV-07).
    """
    status = stored_status.get(revision.id)
    if status is not None and status != domain.RevisionStatus.DRAFT.value:
        raise FrozenRevisionError(
            f"Revision {revision.id} is {status} in the database and no longer accepts a "
            "write (INV-03); copy it with copy_revision() and write the copy"
        )


def _check_source_revision(
    revision: domain.ProjectRevision, stored_status: Mapping[int, str]
) -> None:
    """A provenance pointer designates a stored revision **of the same project**.

    Belt and braces next to the renumbering :func:`_adopt_database_ids` performs,
    because this is a pointer no constraint protects: ``fk_wf_revision_source``
    only asks that *some* revision carry the number, and a domain id left
    unrenumbered lands on a revision of another project as soon as the shared
    sequence has moved past it. The row then claims a provenance that is not
    merely wrong but invisible -- no exception, no violated constraint, nothing
    downstream to catch it.

    ``stored_status`` is keyed by the revisions of this project alone, so the same
    membership test covers "no such revision" and "a revision of somebody else".
    The message spells out both, because the two are not the same accident and do
    not have the same remedy: the first is the ordinary "write the source first",
    while the second is a stored row whose provenance already points outside the
    project -- a state nothing here can produce, which `fk_wf_revision_source`
    allows and which no write can clear, the pointer having to be repaired before
    the revision is saveable again.
    """
    source = revision.source_revision_id
    if source is None or source in stored_status:
        return
    raise RevisionStoreError(
        f"Revision {revision.id} descends from revision {source}, which is not a stored "
        f"revision of project {revision.project_id}: either the source has never been "
        "written -- write the source revision first, so that the copy can point at the id "
        "the database gave it (INV-07) -- or the stored provenance designates a revision of "
        "another project, which no write can mend; clear or repoint "
        "wf_revision.source_revision_id first"
    )


def _check_stored_work_item_kinds(
    project: domain.Project, work_item_kinds: Mapping[int, str]
) -> None:
    """INV-13: the nature of an element of work never changes, so a write never changes it.

    Refused here rather than left to the database, where it surfaces as an opaque
    ``IntegrityError``: ``wf_revision_node`` denormalises the kind and
    ``fk_wf_revision_node_work_item`` ties the two together, so updating
    ``wf_work_item.kind`` breaks that foreign key from the nodes of *every other*
    revision carrying the item -- rows this write never looked at, in an error
    that leaves the session unusable.
    """
    for item in sorted(project.work_items.values(), key=lambda entry: entry.id):
        stored_kind = work_item_kinds.get(item.id)
        if stored_kind is not None and stored_kind != item.kind.value:
            raise RevisionStoreError(
                f"Work item {item.id} is stored as {stored_kind} and this write would make it "
                f"{item.kind.value}; the nature of an element of work never changes from one "
                "revision to the next (INV-13). Create another work item instead"
            )


def _check_reachable(revision: domain.ProjectRevision) -> None:
    """Refuse a node no root reaches, which the level-by-level write would skip."""
    unreachable = domain.unreachable_node_ids(revision)
    if unreachable:
        raise RevisionStoreError(
            f"Revision {revision.id} holds {len(unreachable)} node(s) no root reaches "
            f"({unreachable}): their parent is missing (INV-09) or the parent graph cycles "
            "(INV-06)"
        )


def _check_facet_nodes(revision: domain.ProjectRevision) -> None:
    """Refuse a facet hanging off a node the revision no longer holds (INV-12)."""
    for kind, node_ids in (
        ("planning", sorted(revision.plan_facets)),
        ("cost", sorted(revision.cost_facets)),
    ):
        orphans = [node_id for node_id in node_ids if node_id not in revision.nodes]
        if orphans:
            raise RevisionStoreError(
                f"Revision {revision.id} carries {kind} facets for node(s) {orphans} it does "
                "not hold; a facet never outlives its node (INV-12)"
            )


def _check_link_endpoints(revision: domain.ProjectRevision) -> None:
    """Refuse a precedence link naming a node the revision no longer holds (INV-08)."""
    for link in revision.links:
        for label, node_id in (
            ("node", link.node_id),
            ("predecessor", link.predecessor_node_id),
        ):
            if node_id not in revision.nodes:
                raise RevisionStoreError(
                    f"Precedence link {link.node_id}<-{link.predecessor_node_id} of revision "
                    f"{revision.id} names a {label} {node_id} absent from it; deleting a node "
                    "drops its links (INV-02, INV-08)"
                )


def _check_position_band(revision: domain.ProjectRevision, stored: _StoredRows) -> None:
    """Precondition of the parking band: every position involved stays below it.

    See :data:`_POSITION_BAND`. Checked on the stored positions as well as on the
    ones about to be written, because a position inside the band can only be the
    residue of an interrupted write, and parking a sibling would then collide
    with it on ``uq_wf_revision_node_sibling_position`` instead of being the
    collision-free move the two-pass write relies on.
    """
    offending = [
        (f"revision {revision.id} places node {node.id}", node.position)
        for node in sorted(revision.nodes.values(), key=lambda item: item.id)
        if node.position >= _POSITION_BAND
    ] + [
        (f"the database holds node {row.id}", row.position)
        for row in sorted(stored.nodes.values(), key=lambda item: item.id)
        if row.position >= _POSITION_BAND
    ]
    if offending:
        where, position = offending[0]
        raise RevisionStoreError(
            f"{where} at position {position}, at or above the {_POSITION_BAND} band this "
            "adapter parks a moved node in; no real sibling set reaches that far, so such a "
            "position would make a reordering collide (INV-05)"
        )


def _work_item_of(project: domain.Project, node: domain.RevisionNode) -> domain.WorkItem:
    """The work item a node designates, refused when the project does not hold it.

    Close to INV-10 without being it: what this can see is that the work item
    belongs to the *loaded* project, which is the half a schema constraint does
    not carry either (see :mod:`waterfall.models.revision`).
    """
    work_item = project.work_items.get(node.work_item_id)
    if work_item is None:
        raise RevisionStoreError(
            f"Node {node.id} designates work item {node.work_item_id}, which belongs to no "
            "loaded project"
        )
    return work_item


def _adopt_database_ids(
    project: domain.Project,
    revision: domain.ProjectRevision,
    revision_id: int,
    node_ids: Mapping[int, int],
    work_item_ids: Mapping[int, int],
) -> None:
    """Renumber the in-memory state onto the ids the database just allocated.

    Without this, saving the same state twice would insert everything the domain
    created a second time: a domain id it allocated itself is not the id the
    database ended up giving that row. Renumbering keeps a loaded revision usable
    after a write -- save, keep operating, save again -- instead of making it a
    one-shot object.

    The work items are renumbered on **every** revision held in memory, not only
    on the one that was written: a work item is project-wide, so the copy of a
    revision that introduced one leaves its source designating an id that no
    longer means anything. Saving the source next would then be refused (or, worse
    on a database whose sequences happen to line up, land on somebody else's work
    item). The stubs of the other revisions carry no node at all, so that loop
    costs nothing on them.

    ``source_revision_id`` is renumbered across the project for exactly the same
    reason, and it is the more dangerous of the two: a work item id that went
    stale is caught by :func:`_work_item_of` or by a foreign key, whereas a stale
    provenance pointer lands on a revision of *another project* and no constraint
    says a word. See :func:`_check_source_revision`, which refuses the state this
    renumbering is what prevents.
    """
    _adopt_work_item_ids(project, work_item_ids)

    for other in project.revisions.values():
        if other is revision:
            continue
        for node in other.nodes.values():
            node.work_item_id = work_item_ids.get(node.work_item_id, node.work_item_id)

    for node in revision.nodes.values():
        node.id = node_ids[node.id]
        node.revision_id = revision_id
        node.parent_id = None if node.parent_id is None else node_ids[node.parent_id]
        node.work_item_id = work_item_ids.get(node.work_item_id, node.work_item_id)
    revision.nodes = {node.id: node for node in revision.nodes.values()}
    project.next_node_id = max(project.next_node_id, _next_id(revision.nodes))

    for plan in revision.plan_facets.values():
        plan.node_id = node_ids[plan.node_id]
    revision.plan_facets = {facet.node_id: facet for facet in revision.plan_facets.values()}
    for cost in revision.cost_facets.values():
        cost.node_id = node_ids[cost.node_id]
    revision.cost_facets = {facet.node_id: facet for facet in revision.cost_facets.values()}
    for link in revision.links:
        link.node_id = node_ids[link.node_id]
        link.predecessor_node_id = node_ids[link.predecessor_node_id]

    renumbered = _rekey_revision(project, revision, revision_id)
    for other in project.revisions.values():
        source = other.source_revision_id
        if source is not None:
            other.source_revision_id = renumbered.get(source, source)
    project.next_revision_id = max(project.next_revision_id, _next_id(project.revisions))


def _adopt_work_item_ids(project: domain.Project, work_item_ids: Mapping[int, int]) -> None:
    for item in project.work_items.values():
        item.id = work_item_ids.get(item.id, item.id)
    project.work_items = {item.id: item for item in project.work_items.values()}
    project.next_work_item_id = _next_id(project.work_items)


def _rekey_revision(
    project: domain.Project, revision: domain.ProjectRevision, revision_id: int
) -> dict[int, int]:
    """Move ``revision`` onto its database id without evicting a sibling from the project.

    Returns the ``previous id -> new id`` mapping of every revision this moved,
    which is what the provenance pointers are renumbered through.

    A revision the domain created holds an id allocated above everything loaded --
    and the database is free to hand that very number to *another* revision, which
    is what happens as soon as the sequence catches up. Re-keying the dictionary
    naively would then drop the sibling that held it: gone from ``project.revisions``,
    unsaveable, and (had it been saved later under that id) a write onto the row
    the number now designates. It is pushed onto a fresh id instead, restoring the
    property the whole adapter rests on -- a domain-allocated id never collides
    with a stored one.
    """
    renumbered = {revision.id: revision_id}
    displaced = project.revisions.get(revision_id)
    revision.id = revision_id
    if displaced is not None and displaced is not revision:
        fresh = _next_id(project.revisions)
        renumbered[displaced.id] = fresh
        displaced.id = fresh
        for node in displaced.nodes.values():
            node.revision_id = fresh
    # Re-keyed by identity, exactly as the nodes and the facets above are: every
    # revision lands on the id it now carries, and no entry can be written over
    # another, the two that shared a number having just been told apart.
    project.revisions = {entry.id: entry for entry in project.revisions.values()}
    project.revisions[revision_id] = revision
    return renumbered


def _stored_revision_status(db: Session, project_id: int) -> dict[int, str]:
    """Stored status of every revision of the project, by id.

    The key set answers "is this revision stored at all?" and the value answers
    "does the database still consider it writable?" (INV-03) -- one query for the
    two questions :func:`save_revision` asks before touching anything.
    """
    return {
        row.id: row.status
        for row in db.query(tables.ProjectRevision.id, tables.ProjectRevision.status)
        .filter(tables.ProjectRevision.project_id == project_id)
        .all()
    }


def _stored_work_item_kinds(db: Session, project_id: int) -> dict[int, str]:
    """Stored kind of every work item of the project, by id, read before any write."""
    return {
        row.id: row.kind
        for row in db.query(tables.WorkItem.id, tables.WorkItem.kind)
        .filter(tables.WorkItem.project_id == project_id)
        .all()
    }


def _save_work_items(db: Session, project: domain.Project) -> dict[int, int]:
    """Insert the work items the domain created; refresh the ones it edited.

    A work item is never deleted here: it is the identity of an element of work
    across the versions of the project, and dropping a node in one revision says
    nothing about the others. Its ``kind`` is never *updated* either, and the
    comparison below leaves it out for that reason:
    :func:`_check_stored_work_item_kinds` has already refused a state that changes
    it (INV-13), so an update would be unreachable rather than merely unwanted.
    """
    stored = {
        row.id: row
        for row in db.query(tables.WorkItem).filter(tables.WorkItem.project_id == project.id).all()
    }
    inserted: list[tuple[int, tables.WorkItem]] = []
    mapping: dict[int, int] = {}
    now = _now()
    for item in sorted(project.work_items.values(), key=lambda entry: entry.id):
        row = stored.get(item.id)
        if row is None:
            row = tables.WorkItem(
                project_id=project.id,
                kind=item.kind.value,
                description=item.description,
                external_uid=item.external_uid,
                created_at=item.created_at or now,
                updated_at=item.updated_at or now,
            )
            db.add(row)
            inserted.append((item.id, row))
            continue
        mapping[item.id] = row.id
        if (row.description, row.external_uid) == (item.description, item.external_uid):
            continue
        row.description = item.description
        row.external_uid = item.external_uid
        row.updated_at = now
    db.flush()
    for domain_id, row in inserted:
        mapping[domain_id] = row.id
    return mapping


def _save_revision_row(
    db: Session,
    project: domain.Project,
    revision: domain.ProjectRevision,
    stored_status: Mapping[int, str],
) -> int:
    row = db.get(tables.ProjectRevision, revision.id) if revision.id in stored_status else None
    if row is None:
        row = tables.ProjectRevision(project_id=project.id, version_number=revision.version_number)
        db.add(row)
    row.version_number = revision.version_number
    row.kind = revision.kind.value
    row.status = revision.status.value
    row.source_revision_id = revision.source_revision_id
    row.currency_code = revision.currency_code
    row.lock_version = revision.lock_version
    row.note = revision.note
    row.created_at = revision.created_at or _now()
    row.validated_at = revision.validated_at
    db.flush()
    return row.id


def _save_tree(
    db: Session,
    project: domain.Project,
    revision: domain.ProjectRevision,
    revision_id: int,
    stored: _StoredRows,
    work_item_ids: Mapping[int, int],
) -> dict[int, int]:
    _delete_removed(db, revision, stored)
    _push_moved_nodes_aside(db, revision, stored.nodes)
    return _write_node_positions(db, project, revision, revision_id, stored, work_item_ids)


def _delete_removed(db: Session, revision: domain.ProjectRevision, stored: _StoredRows) -> None:
    """Drop what the domain no longer holds, children before parents.

    The precedence links of a deleted node go with it (INV-02); the ones between
    nodes that stay are left to :func:`_save_links`, which diffs them. ``stored``
    is emptied of every row deleted here, so the rest of the write never reads a
    row that no longer exists.
    """
    removed = set(stored.nodes) - set(revision.nodes)
    dropped_links = [
        key
        for key, link in stored.links.items()
        if link.node_id in removed or link.predecessor_node_id in removed
    ]
    dropped_plans = [
        node_id
        for node_id in stored.plan_facets
        if node_id in removed or node_id not in revision.plan_facets
    ]
    dropped_costs = [
        node_id
        for node_id in stored.cost_facets
        if node_id in removed or node_id not in revision.cost_facets
    ]
    for key in dropped_links:
        db.delete(stored.links.pop(key))
    for node_id in dropped_plans:
        db.delete(stored.plan_facets.pop(node_id))
    for node_id in dropped_costs:
        db.delete(stored.cost_facets.pop(node_id))
    db.flush()
    _delete_removed_nodes(db, stored, removed)


def _delete_removed_nodes(db: Session, stored: _StoredRows, removed: set[int]) -> None:
    """Delete the nodes the domain dropped, one flush per depth, deepest first.

    The unit of work batches the deletes of a single table into one executemany,
    which drops the order they were issued in -- and a parent deleted before its
    child breaks `fk_wf_revision_node_parent`.
    """
    by_depth: dict[int, list[int]] = {}
    for node_id in removed:
        by_depth.setdefault(_stored_depth(stored.nodes, node_id), []).append(node_id)
    for depth in sorted(by_depth, reverse=True):
        for node_id in by_depth[depth]:
            db.delete(stored.nodes.pop(node_id))
        db.flush()


def _stored_depth(stored: Mapping[int, tables.RevisionNode], node_id: int) -> int:
    """Depth of a *stored* node, stopping on a parent cycle rather than looping forever.

    INV-06 is not expressible in SQL -- ``fk_wf_revision_node_parent`` happily
    accepts a set of rows hanging off itself -- so a stored cycle is reachable by
    a manual repair or by a future faulty write path, and this walk is the one
    place that would then hang instead of failing. It runs on rows the domain
    dropped, so the reachability check of :func:`_check_reachable` (which refuses
    a cycle the revision still holds) says nothing about them.

    Guarded exactly as :func:`~waterfall.domain.revision.structure.ancestors_of`
    guards the same walk on the domain side; the depth returned for a cyclic node
    is then meaningless but finite, and the delete it orders is attempted rather
    than hung on.

    Termination is what the guard buys, and it holds for **any** stored cycle, of
    any length. Whether the delete then succeeds is a separate question, and only
    the self-parent cycle answers it yes: from two nodes upwards each row of the
    cycle references another one that the same statement deletes, so
    ``fk_wf_revision_node_parent`` refuses the batch on either dialect and in
    either order, and :func:`save_revision` ends on an ``IntegrityError`` instead
    of hanging. Repairing such a revision means breaking the cycle first --
    ``UPDATE wf_revision_node SET parent_id = NULL`` on one of its rows -- after
    which the delete goes through.
    """
    depth = 0
    seen = {node_id}
    current = stored[node_id].parent_id
    while current is not None and current in stored and current not in seen:
        seen.add(current)
        depth += 1
        current = stored[current].parent_id
    return depth


def _push_moved_nodes_aside(
    db: Session,
    revision: domain.ProjectRevision,
    stored: Mapping[int, tables.RevisionNode],
) -> None:
    """Park every node whose slot changes in a position band nothing else uses.

    Without this, writing a reordered sibling set row by row would break
    ``uq_wf_revision_node_sibling_position`` on a transient state -- exchanging
    two siblings is the minimal example. Adding a constant to a position keeps
    the parked positions distinct from one another, and the band is far above
    any position a real sibling set reaches.

    A node whose new parent is itself a *new* node compares unequal here, as it
    must: a freshly allocated domain id is always above every id that was
    loaded, so it can never be mistaken for a stored parent id.

    Every remaining stored row has a counterpart in the revision:
    :func:`_delete_removed` ran first and dropped the ones the domain no longer
    holds, from the database and from ``stored`` alike.
    """
    for node_id, row in stored.items():
        node = revision.nodes[node_id]
        if (row.parent_id, row.position) == (node.parent_id, node.position):
            continue
        row.position += _POSITION_BAND
    db.flush()


def _mapped_parent(node: domain.RevisionNode, node_ids: Mapping[int, int]) -> int | None:
    """The database id of ``node``'s parent, or ``None`` for a root.

    Bare subscript, under a precondition two steps establish together:
    :func:`_check_reachable` has refused any node whose parent the revision does
    not hold, and :func:`_write_node_positions` walks the tree level by level, so
    the parent has been written -- and entered in ``node_ids`` -- before its
    children are looked at. A missing key would be a defect of this module.
    """
    if node.parent_id is None:
        return None
    return node_ids[node.parent_id]


def _write_node_positions(
    db: Session,
    project: domain.Project,
    revision: domain.ProjectRevision,
    revision_id: int,
    stored: _StoredRows,
    work_item_ids: Mapping[int, int],
) -> dict[int, int]:
    """Insert the new nodes depth by depth, and place every node at its final slot.

    Depth by depth because a new node needs its parent's database id, which only
    a flush hands back; and a parent is always one level above its children.

    Every lookup below is a plain subscript on purpose: :func:`_validate_before_write`
    has already established that each node designates a work item of the project
    and carries exactly one facet, so a missing key here would be a defect of this
    module, not a state a caller can produce.

    The seed below is unfiltered for the same kind of reason: :func:`_delete_removed`
    ran first and took every row the revision no longer holds out of ``stored.nodes``
    as it deleted it, so what remains is exactly the stored half of the revision.
    """
    node_ids = {node_id: node_id for node_id in stored.nodes}
    for level in domain.levels(revision):
        pending: list[tuple[int, tables.RevisionNode]] = []
        for node in level:
            row = stored.nodes.get(node.id)
            if row is None:
                row = tables.RevisionNode(revision_id=revision_id)
                db.add(row)
                pending.append((node.id, row))
            row.work_item_id = work_item_ids[node.work_item_id]
            row.kind = _node_kind(project, revision, node)
            row.parent_id = _mapped_parent(node, node_ids)
            row.position = node.position
        db.flush()
        for domain_id, row in pending:
            node_ids[domain_id] = row.id
    return node_ids


def _node_kind(
    project: domain.Project, revision: domain.ProjectRevision, node: domain.RevisionNode
) -> str:
    """The node's kind, denormalised onto the node row (INV-11, INV-13).

    Read from the **work item**, which INV-13 makes the authority on the kind of
    an element of work across every revision; the facet carried only has to agree
    with it. Deducing the kind from the facet instead would turn a facet that does
    not match its work item into an opaque foreign-key violation on
    `fk_wf_revision_node_work_item`, and would silently pick one of the two when a
    node carries both.
    """
    plan = node.id in revision.plan_facets
    cost = node.id in revision.cost_facets
    if plan and cost:
        raise RevisionStoreError(
            f"Node {node.id} carries both a planning and a cost facet; a node carries exactly "
            "one (INV-11)"
        )
    if not plan and not cost:
        raise RevisionStoreError(f"Node {node.id} carries no facet at all (INV-11)")
    work_item = _work_item_of(project, node)
    carried = domain.WorkItemKind.TASK if plan else domain.WorkItemKind.COST
    if work_item.kind is not carried:
        raise RevisionStoreError(
            f"Node {node.id} carries a {carried.value} facet while its work item "
            f"{work_item.id} is of kind {work_item.kind.value}; the kind of an element of "
            "work never changes from one revision to the next (INV-13)"
        )
    return work_item.kind.value


def _save_facets(
    db: Session,
    revision: domain.ProjectRevision,
    stored: _StoredRows,
    node_ids: Mapping[int, int],
) -> None:
    for domain_node_id, facet in sorted(revision.plan_facets.items()):
        _write_plan_facet(db, stored.plan_facets, node_ids[domain_node_id], facet)
    for domain_node_id, cost in sorted(revision.cost_facets.items()):
        _write_cost_facet(db, stored.cost_facets, node_ids[domain_node_id], cost)
    db.flush()


def _facet_calendar(facet: domain.PlanFacet) -> tuple[int, str]:
    """The calendar of a planning facet, refused when it carries none (INV-15)."""
    if facet.calendar_id is None or facet.calendar_source is None:
        raise RevisionStoreError(
            f"Planning facet of node {facet.node_id} carries no calendar; a task is always "
            "schedulable (INV-15)"
        )
    return facet.calendar_id, facet.calendar_source.value


def _write_plan_facet(
    db: Session,
    stored: Mapping[int, tables.RevisionPlanFacet],
    node_id: int,
    facet: domain.PlanFacet,
) -> None:
    calendar_id, calendar_source = _facet_calendar(facet)
    row = stored.get(node_id)
    if row is None:
        row = tables.RevisionPlanFacet(node_id=node_id, node_kind=domain.WorkItemKind.TASK.value)
        db.add(row)
    row.name = facet.name
    row.calendar_id = calendar_id
    row.calendar_source = calendar_source
    row.is_milestone = facet.is_milestone
    row.duration_minutes = facet.duration_minutes
    row.duration_format = facet.duration_format
    row.start_at = facet.start_at
    row.finish_at = facet.finish_at
    row.work_minutes = facet.work_minutes
    row.percent_complete = facet.percent_complete
    row.is_manual = facet.is_manual


def _write_cost_facet(
    db: Session,
    stored: Mapping[int, tables.RevisionCostFacet],
    node_id: int,
    facet: domain.CostFacet,
) -> None:
    row = stored.get(node_id)
    if row is None:
        row = tables.RevisionCostFacet(node_id=node_id, node_kind=domain.WorkItemKind.COST.value)
        db.add(row)
    row.nature = facet.nature.value
    row.label = facet.label
    row.quantity = facet.quantity
    row.role_id = facet.role_id
    row.hours = facet.hours
    row.cost_type_id = facet.cost_type_id
    row.cost_category_id = facet.cost_category_id
    row.unit_cost = facet.unit_cost
    row.supply_status = None if facet.supply_status is None else facet.supply_status.value
    row.planned_date = facet.planned_date
    row.cost_code_id = facet.cost_code_id
    row.comment = facet.comment


def _save_links(
    db: Session,
    revision: domain.ProjectRevision,
    revision_id: int,
    stored: _StoredRows,
    node_ids: Mapping[int, int],
) -> None:
    """Insert the links the domain added, drop the ones it removed, keep the rest.

    Diffed on the ``(node, predecessor, type)`` triple -- the identity a link has
    in the domain, and what ``uq_wf_revision_node_link`` states in the database --
    rather than deleted and rewritten wholesale: renaming one task would otherwise
    re-issue every link of the revision, one statement per row, and hand every
    link a new id in the process. Two links of equal triple collapse into one, as
    that same constraint requires.

    The links of a node the domain deleted are already gone: :func:`_delete_removed`
    drops them, because the node cannot be deleted while they reference it.
    """
    wanted = {
        _link_key(node_ids[link.node_id], node_ids[link.predecessor_node_id], link.link_type): link
        for link in revision.links
    }
    for key, row in stored.links.items():
        if key not in wanted:
            db.delete(row)
    for key, link in sorted(wanted.items()):
        row = stored.links.get(key)
        if row is None:
            node_id, predecessor_node_id, link_type = key
            row = tables.RevisionNodeLink(
                revision_id=revision_id,
                node_id=node_id,
                predecessor_node_id=predecessor_node_id,
                link_type=link_type,
            )
            db.add(row)
        row.lag_tenth_minute = link.lag_tenth_minute
        row.lag_format = link.lag_format
