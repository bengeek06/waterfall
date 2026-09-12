"""The single tree service of the revision model (E14-04, issue #330).

One piece for what `planning_tree.py` and `estimate_grid.py` solve twice today,
with divergent move semantics and two incompatible ``uid`` spaces: insertion,
move (up, down, indent, outdent, to the root), cascade delete, contiguous
renumbering, bearing-task resolution and the creation of a revision from an
existing one, all on `wf_revision_node`.

**It holds no tree logic at all.** Every operation here is the same three steps:
load the revision through :mod:`waterfall.services.revision_store`, call *one*
operation of the pure domain of E14-02, write the result back. Walking a tree,
computing a position, deciding whether a move is legal or detecting a cycle is
the domain's business -- an AST architecture test (#328) keeps that module free
of SQLAlchemy, and this module free-riding on it is what keeps the two halves
separable. A primitive missing from the domain is added *to the domain*, with its
own tests, never written here.

Additive by design (EPIC #326, "additif d'abord, destruction en dernier"): the
legacy services and their two mirror lock helpers stay in place and keep serving
their current consumers until E14-12 (#339) removes them, once #331, #332 and
#333 have migrated every caller onto this one.

Errors
------

This is a service layer, not a route: it raises no ``HTTPException`` and knows no
HTTP status code. Three families reach the caller, and E14-05/E14-07 map them:

* the **domain** errors of :mod:`waterfall.domain.revision` -- a refused move, a
  cycle, an empty selection, a write on a validated revision;
* the **store** errors of :mod:`waterfall.services.revision_store` -- a revision
  that does not exist, a state that cannot be written back;
* :class:`RevisionLockConflictError`, of this layer, and of this layer alone.

One caveat for whoever maps these onto HTTP statuses (#331, #333): **INV-03 comes
out under two exception classes**, not one. The service guard and the domain's
``require_draft`` both raise
:class:`~waterfall.domain.revision.ImmutableRevisionError`, while the store's own
last-ditch refusal (``_refuse_a_frozen_revision``, reached only by a caller
bypassing this service) raises
:class:`~waterfall.services.revision_store.FrozenRevisionError`. The messages
still differ -- they describe three different vantage points on the same
invariant -- but the *classes* no longer have to be guessed at: E14-05 (#331)
split that second refusal out of the bare ``RevisionStoreError`` it used to share
with refusals that have nothing to do with INV-03, and
:func:`waterfall.api.revision_errors.revision_http_exception` is the one place
either class is turned into a response.

Transactions and the optimistic lock
------------------------------------

Every write takes an ``expected_lock_version`` and refuses the write if the
stored counter has moved. See :func:`_claim_revision` for what the guard
guarantees, and for what it does not.

Like :func:`~waterfall.services.revision_store.save_revision`, nothing here
commits: the caller owns the transaction, and the row lock this service takes is
held until the caller commits or rolls back.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TypeVar

from sqlalchemy.orm import Session

from waterfall.domain import revision as domain
from waterfall.models import revision as tables
from waterfall.services.revision_store import (
    LoadedRevision,
    RevisionNotFoundError,
    SaveOutcome,
    load_revision,
    save_revision,
)

_T = TypeVar("_T")


class RevisionTreeError(RuntimeError):
    """A tree operation could not be carried out on the stored revision.

    Deliberately *not* a :class:`~waterfall.services.revision_store.RevisionStoreError`
    and deliberately not a domain error: the two say "this state is wrong", this
    one says "the state was right, but not any more".

    Never raised directly, and carrying a single subclass today: it is the base a
    caller catches to mean "this service refused the write", and the seam a second
    concurrency failure of this layer would be added under. An ``except
    RevisionTreeError`` is therefore *not* dead code, even though only
    :class:`RevisionLockConflictError` reaches it.
    """


class RevisionLockConflictError(RevisionTreeError):
    """The revision moved on since the caller read it (optimistic lock).

    The single lock mechanism of the new model, replacing the two mirror helpers
    ``raise_on_planning_revision_conflict`` / ``raise_on_estimate_revision_conflict``
    and the three lock-helper variants #260 reported -- there is one tree, so
    there is one counter. The attributes are what a 409 response body is built
    from, which is why they are carried rather than only formatted into the
    message.
    """

    def __init__(
        self, revision_id: int, expected_lock_version: int, current_lock_version: int
    ) -> None:
        super().__init__(
            f"Revision {revision_id} is at lock_version {current_lock_version}, not the "
            f"{expected_lock_version} this write expected: it was written by somebody else "
            "since it was read. Reload the revision and apply the change again"
        )
        self.revision_id: int = revision_id
        self.expected_lock_version: int = expected_lock_version
        self.current_lock_version: int = current_lock_version


@dataclass(frozen=True)
class TreeWrite:
    """What a successful write left in the database.

    ``lock_version`` is the value the revision now carries -- the one the caller
    hands back as ``expected_lock_version`` on its next write.
    """

    revision_id: int
    lock_version: int


@dataclass(frozen=True)
class InsertedNode(TreeWrite):
    """The database ids of a node the service just created."""

    node_id: int
    work_item_id: int


@dataclass(frozen=True)
class DeletedNodes(TreeWrite):
    """What a cascade delete removed, and the chiffrage it took away with it.

    ``cost_losses`` is the domain's own report (Rule 3's safeguard): the labels,
    natures, amounts and bearing task of every cost facet that disappeared, so a
    caller can name them rather than let them vanish silently.
    """

    removed_node_ids: tuple[int, ...]
    cost_losses: tuple[domain.CostLoss, ...]


@dataclass(frozen=True)
class CompactedPositions(TreeWrite):
    """The nodes a compaction actually moved; empty when the tree was already contiguous.

    ``moved_node_ids`` holds database ids, for the same reason as
    :attr:`DeletedNodes.removed_node_ids` and said here rather than left to be
    rediscovered: a node whose position is renumbered is a node that was loaded,
    so its domain id *is* its row id. Nothing is created, so nothing has to be
    translated through :class:`~waterfall.services.revision_store.SaveOutcome`.
    """

    moved_node_ids: tuple[int, ...]


@dataclass(frozen=True)
class CreatedRevision(TreeWrite):
    """The draft revision a copy produced (INV-07).

    ``lock_version`` is the *copy's* counter, which starts at 0: copying reads the
    source and writes a new revision, so the source's own counter is left exactly
    where it was.
    """

    source_revision_id: int
    version_number: int


@dataclass(frozen=True)
class BearingTask:
    """The task a cost node hangs under (INV-01), resolved and never stored."""

    node_id: int
    work_item_id: int
    name: str


@dataclass(frozen=True)
class TreeRow:
    """One node of a revision, as a read hands it out.

    ``row_number`` and ``level`` are **computed here and stored nowhere** -- the
    principle E9 (#145-#149) settled for the legacy planning and which the node
    model makes structural rather than conventional: a positional identifier that
    a move would have to renumber is a positional identifier that drifts, so it is
    derived from the depth-first walk on every read instead. Both are 1-based:
    ``row_number`` is the rank in that walk, ``level`` the depth of the node, a
    root being at level 1.
    """

    node_id: int
    work_item_id: int
    kind: domain.WorkItemKind
    parent_id: int | None
    position: int
    row_number: int
    level: int
    external_uid: int | None
    description: str | None
    plan: domain.PlanFacet | None
    cost: domain.CostFacet | None
    predecessors: tuple[domain.NodeLink, ...]


@dataclass(frozen=True)
class RevisionTree:
    """A whole revision, read: its header and its nodes in depth-first order."""

    revision_id: int
    project_id: int
    version_number: int
    kind: domain.RevisionKind
    status: domain.RevisionStatus
    lock_version: int
    note: str | None
    rows: tuple[TreeRow, ...]


def _now() -> datetime:
    """The service may read a clock; the domain it drives may not.

    Word for word :func:`waterfall.services.revision_store._now`, and kept
    separate rather than imported: that one is private, and reaching into it
    would trade a duplicated one-liner for a cross-module private dependency
    between the two halves E14-12 has to keep separable.
    """
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------
# The optimistic lock
# --------------------------------------------------------------------------------------


def _claim_revision(db: Session, revision_id: int, expected_lock_version: int) -> None:
    """Take the revision's row lock, then check it is writable and still at the expected version.

    Order matters, and it is the whole guard:

    1. ``SELECT ... FOR UPDATE`` on `wf_revision`. On PostgreSQL under READ
       COMMITTED, this either takes the row lock immediately or **blocks** until
       the transaction holding it ends, and then re-reads the row as that
       transaction left it. A competing writer is therefore never merely "read
       past": it is waited for, and its result is seen;
    2. the status is checked **before** the counter. A validated revision can
       never be written whatever version the caller holds, so answering "reload
       and retry" would be a lie -- the retry would fail forever. It gets the same
       :class:`~waterfall.domain.revision.ImmutableRevisionError` the domain
       raises (INV-03: one error, whichever facet the write was aimed at);
    3. the counter is compared. Only then is the tree read, so nothing committed
       between the check and the read can slip through: any writer that could have
       changed the tree had to hold this very lock, and releasing it means it had
       already bumped the counter this step just compared.

    The lock is held for the rest of the caller's transaction, so the read, the
    domain operation and the write back are serialised against every other writer
    of the same revision.

    What this does **not** guarantee
    --------------------------------

    * **Only writers that come through here are serialised.** A write issued
      straight against `wf_revision_node` -- the legacy services of #339, a manual
      repair -- takes no such lock and is invisible to this guard;
    * **on SQLite, there is no row lock at all**: SQLAlchemy's dialect drops
      ``FOR UPDATE`` silently. A counter another transaction has already committed
      is still caught, but "already committed" is all that is caught; two genuinely
      concurrent transactions are serialised by SQLite's own database-level write
      lock, not by this one. The concurrency guarantee is proven on PostgreSQL,
      which is the production dialect;
    * **the session must not already hold the rows of this revision** from an
      earlier read in the same transaction: SQLAlchemy would serve them from its
      identity map, and the tree read below would then predate the lock. A route
      gets a fresh session per request (``get_db``), which is the case this holds
      in; a caller reusing a session across operations should ``commit()`` (or
      ``expire_all()``) between them;
    * **nothing is guaranteed until the caller commits.** This service flushes;
      a caller that rolls back undoes the write *and* the counter with it;
    * **revisions are locked one at a time.** Two revisions of the same project
      written concurrently do not block each other, and only the database
      constraints stand between them on the project-wide rows they share
      (`wf_work_item`). :func:`create_revision_from` is the operation this bites,
      and its docstring spells out how;
    * **a write that leaves the counter alone is not idempotent.** The guard
      refuses a *stale* version, not a repeat: an operation that does not bump the
      revision it was given -- again :func:`create_revision_from`, which writes a
      new revision and leaves the source's counter where it was -- can be replayed
      with the very same ``expected_lock_version`` and will succeed again. What
      stops a double submission there belongs to the route (#352).
    """
    row = _lock_revision_row(db, revision_id)
    if row.status != domain.RevisionStatus.DRAFT.value:
        raise domain.ImmutableRevisionError(
            f"Revision {revision_id} is {row.status} and refuses every write, whichever facet "
            "it is aimed at (INV-03); create a draft copy of it with create_revision_from() "
            "to make any change"
        )
    _check_lock_version(row, expected_lock_version)


def _lock_revision_row(db: Session, revision_id: int) -> tables.ProjectRevision:
    """The revision row, locked for update and re-read from the database.

    ``populate_existing()`` is not decoration: without it SQLAlchemy would serve
    an instance the session already holds from its identity map, attributes
    included -- and the lock would then be checked against a ``lock_version`` read
    before the lock was taken, which is exactly the race this guard exists to
    close.
    """
    row = (
        db.query(tables.ProjectRevision)
        .filter(tables.ProjectRevision.id == revision_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise RevisionNotFoundError(f"Revision {revision_id} does not exist")
    return row


def _check_lock_version(row: tables.ProjectRevision, expected_lock_version: int) -> None:
    if row.lock_version != expected_lock_version:
        raise RevisionLockConflictError(row.id, expected_lock_version, row.lock_version)


# --------------------------------------------------------------------------------------
# Load, delegate, write back
# --------------------------------------------------------------------------------------


def _write(
    db: Session,
    revision_id: int,
    expected_lock_version: int,
    operation: Callable[[domain.Project, domain.ProjectRevision], _T],
) -> tuple[_T, LoadedRevision, SaveOutcome]:
    """Claim the revision, run one domain operation on it, write the result back.

    The three steps of this module, in one place. ``operation`` is expected to be
    a single domain call: each of them bumps the lock counter exactly once
    (:func:`~waterfall.domain.revision.guards.touch`), so composing two here would
    make one service call consume two versions and leave the caller's next
    ``expected_lock_version`` off by one.
    """
    _claim_revision(db, revision_id, expected_lock_version)
    loaded = load_revision(db, revision_id)
    produced = operation(loaded.project, loaded.revision)
    outcome = save_revision(db, loaded)
    return produced, loaded, outcome


def _mutate(
    db: Session,
    revision_id: int,
    expected_lock_version: int,
    operation: Callable[[domain.Project, domain.ProjectRevision], None],
) -> TreeWrite:
    """:func:`_write` for the operations whose only result is the new tree itself."""
    _, loaded, outcome = _write(db, revision_id, expected_lock_version, operation)
    return TreeWrite(revision_id=outcome.revision_id, lock_version=loaded.revision.lock_version)


def _created_ids(node: domain.RevisionNode) -> tuple[int, int]:
    """``(node id, work item id)`` of a freshly created node, read before the write back.

    Read *now* and not after the save: writing back renumbers the domain objects
    onto the ids the database allocated, so ``node.id`` afterwards is no longer
    the key :class:`~waterfall.services.revision_store.SaveOutcome` is indexed by
    (see its docstring).
    """
    return node.id, node.work_item_id


def _insert(
    db: Session,
    revision_id: int,
    expected_lock_version: int,
    create: Callable[[domain.Project, domain.ProjectRevision], domain.RevisionNode],
) -> InsertedNode:
    ids, loaded, outcome = _write(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: _created_ids(create(project, revision)),
    )
    domain_node_id, domain_work_item_id = ids
    return InsertedNode(
        revision_id=outcome.revision_id,
        lock_version=loaded.revision.lock_version,
        node_id=outcome.node_ids[domain_node_id],
        work_item_id=outcome.work_item_ids[domain_work_item_id],
    )


# --------------------------------------------------------------------------------------
# Insertion
# --------------------------------------------------------------------------------------


def add_task(
    db: Session,
    revision_id: int,
    *,
    expected_lock_version: int,
    name: str,
    parent_id: int | None = None,
    position: int | None = None,
    description: str | None = None,
    external_uid: int | None = None,
    duration_minutes: int | None = None,
    is_milestone: bool = False,
    start_at: datetime | None = None,
    finish_at: datetime | None = None,
    calendar_id: int | None = None,
    calendar_source: domain.CalendarSource | None = None,
) -> InsertedNode:
    """Insert a planning node: a new ``work_item`` of kind ``task`` and its plan facet.

    ``position`` defaults to "last child of ``parent_id``", ``parent_id=None``
    to the root. The calendar follows Règle 1 when none is named: the project's,
    recorded as inherited rather than pinned (INV-15).
    """
    return _insert(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.add_task(
            project,
            revision,
            name=name,
            parent_id=parent_id,
            position=position,
            external_uid=external_uid,
            description=description,
            duration_minutes=duration_minutes,
            is_milestone=is_milestone,
            start_at=start_at,
            finish_at=finish_at,
            calendar_id=calendar_id,
            calendar_source=calendar_source,
            now=_now(),
        ),
    )


def add_cost_line(
    db: Session,
    revision_id: int,
    *,
    expected_lock_version: int,
    nature: domain.CostNature,
    label: str,
    parent_id: int | None = None,
    position: int | None = None,
    quantity: Decimal = Decimal("1"),
    role_id: int | None = None,
    hours: Decimal | None = None,
    cost_type_id: int | None = None,
    cost_category_id: int | None = None,
    unit_cost: Decimal | None = None,
    supply_status: domain.SupplyStatus | None = None,
    planned_date: date | None = None,
    cost_code_id: int | None = None,
    comment: str | None = None,
    description: str | None = None,
) -> InsertedNode:
    """Insert a cost node: a new ``work_item`` of kind ``cost`` and its cost facet.

    ``parent_id=None`` puts the line at the root, where it is a project-wide cost
    with no bearing task -- explicitly allowed by INV-01. A labour line carries a
    role and hours, a non-labour one a cost type, a category and a disbursement
    (INV-19, INV-20); the domain refuses any other shape.
    """
    return _insert(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.add_cost_line(
            project,
            revision,
            nature=nature,
            label=label,
            parent_id=parent_id,
            position=position,
            quantity=quantity,
            role_id=role_id,
            hours=hours,
            cost_type_id=cost_type_id,
            cost_category_id=cost_category_id,
            unit_cost=unit_cost,
            supply_status=supply_status,
            planned_date=planned_date,
            cost_code_id=cost_code_id,
            comment=comment,
            description=description,
            now=_now(),
        ),
    )


# --------------------------------------------------------------------------------------
# Moving a selection
# --------------------------------------------------------------------------------------


def move_nodes(
    db: Session,
    revision_id: int,
    node_ids: Sequence[int],
    *,
    expected_lock_version: int,
    target_parent_id: int | None = None,
    position: int | None = None,
) -> TreeWrite:
    """Move a selection under ``target_parent_id``, ``None`` meaning the root.

    Each selected node takes its whole subtree and both facets with it, in its
    relative display order: there is only one tree, so moving a cost line is a
    move of the tree, and so is moving a task. A node whose ancestor is also
    selected is carried by that ancestor rather than moved twice.
    """
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.move_nodes(
            project,
            revision,
            list(node_ids),
            target_parent_id=target_parent_id,
            position=position,
        ),
    )


def move_nodes_up(
    db: Session, revision_id: int, node_ids: Sequence[int], *, expected_lock_version: int
) -> TreeWrite:
    """Move a contiguous block of siblings one position up."""
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.move_nodes_up(project, revision, list(node_ids)),
    )


def move_nodes_down(
    db: Session, revision_id: int, node_ids: Sequence[int], *, expected_lock_version: int
) -> TreeWrite:
    """Move a contiguous block of siblings one position down."""
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.move_nodes_down(project, revision, list(node_ids)),
    )


def indent_nodes(
    db: Session, revision_id: int, node_ids: Sequence[int], *, expected_lock_version: int
) -> TreeWrite:
    """Indent a contiguous block of siblings under its immediately preceding sibling."""
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.indent_nodes(project, revision, list(node_ids)),
    )


def outdent_nodes(
    db: Session, revision_id: int, node_ids: Sequence[int], *, expected_lock_version: int
) -> TreeWrite:
    """Outdent a block of siblings to its grandparent, up to the root included."""
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.outdent_nodes(project, revision, list(node_ids)),
    )


# --------------------------------------------------------------------------------------
# Deleting, renumbering
# --------------------------------------------------------------------------------------


def delete_nodes(
    db: Session, revision_id: int, node_ids: Sequence[int], *, expected_lock_version: int
) -> DeletedNodes:
    """Delete a selection, its whole subtree, and both facets of every node removed.

    INV-02, in one write: no descendant, no planning facet, no cost facet and no
    precedence link of a removed node survives, and the siblings of each removed
    node are renumbered contiguously. The removed ids are database ids -- a node
    being deleted is a node that was loaded, so its domain id *is* its row id.
    """
    report, loaded, outcome = _write(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.delete_nodes(project, revision, list(node_ids)),
    )
    return DeletedNodes(
        revision_id=outcome.revision_id,
        lock_version=loaded.revision.lock_version,
        removed_node_ids=report.removed_node_ids,
        cost_losses=report.cost_losses,
    )


def compact_positions(
    db: Session, revision_id: int, *, expected_lock_version: int
) -> CompactedPositions:
    """Renumber every sibling set of the revision as contiguous positions 1..n (INV-05).

    A repair, not a routine step: every other operation of this service already
    leaves the positions contiguous. What it is for is a tree this service did not
    write -- rows inserted straight into the tables, or the legacy services #339
    has yet to remove.

    What it cannot repair
    ---------------------

    It is a *domain* operation on a loaded revision, so it only reaches what the
    store agrees to load and to write back, and two corruptions sit outside that:

    * **a position parked in the band.** A position at or above the
      ``1_000_000`` band :mod:`~waterfall.services.revision_store` moves a node
      through is the residue of an interrupted write, and the store refuses to
      touch a revision holding one (``_check_position_band``) -- which means this
      call fails on exactly the accident the band's own docstring describes.
      Bringing such a row back under the band takes a direct ``UPDATE`` (or a
      restore); this can only be run afterwards;
    * **an orphan node.** A node whose parent the revision does not hold (INV-09)
      is renumbered in memory among its fellow orphans, but the write back is
      refused by ``_check_reachable`` -- the tree has to be reattached first,
      through a direct ``UPDATE`` of ``parent_id`` or a delete of the orphans.

    Both refusals arrive as a
    :class:`~waterfall.services.revision_store.RevisionStoreError` naming the
    offending node, and both leave the revision exactly as it was.
    """
    moved, loaded, outcome = _write(
        db,
        revision_id,
        expected_lock_version,
        lambda _project, revision: domain.compact_positions(revision),
    )
    return CompactedPositions(
        revision_id=outcome.revision_id,
        lock_version=loaded.revision.lock_version,
        moved_node_ids=moved,
    )


# --------------------------------------------------------------------------------------
# Reading the bearing task, copying a revision
# --------------------------------------------------------------------------------------


def read_revision_tree(db: Session, revision_id: int) -> RevisionTree:
    """The whole tree of ``revision_id``, depth-first, with both facets and the links.

    Read-only, so no lock and no ``expected_lock_version`` -- but the
    ``lock_version`` it reports *is* the value the caller hands back on its next
    write, which is why the header carries it.

    A node the revision holds but no root reaches (INV-09) is absent from
    :attr:`RevisionTree.rows`: the depth-first walk of the domain is what produces
    the order, and it lists only what it reaches. That is the same thing
    :func:`~waterfall.domain.revision.structure.depth_first` already does
    everywhere else, and the alternative -- inventing a position for an orphan --
    would hand a client a tree the server cannot write back.
    """
    loaded = load_revision(db, revision_id)
    revision = loaded.revision
    ordered = domain.depth_first(revision)
    level_of = {
        node.id: depth
        for depth, level in enumerate(domain.levels(revision), start=1)
        for node in level
    }
    predecessors: dict[int, list[domain.NodeLink]] = {}
    for link in revision.links:
        predecessors.setdefault(link.node_id, []).append(link)
    rows = tuple(
        TreeRow(
            node_id=node.id,
            work_item_id=node.work_item_id,
            kind=loaded.project.work_items[node.work_item_id].kind,
            parent_id=node.parent_id,
            position=node.position,
            row_number=row_number,
            level=level_of[node.id],
            external_uid=loaded.project.work_items[node.work_item_id].external_uid,
            description=loaded.project.work_items[node.work_item_id].description,
            plan=revision.plan_facets.get(node.id),
            cost=revision.cost_facets.get(node.id),
            predecessors=tuple(
                sorted(
                    predecessors.get(node.id, []),
                    key=lambda link: (link.predecessor_node_id, link.link_type),
                )
            ),
        )
        for row_number, node in enumerate(ordered, start=1)
    )
    return RevisionTree(
        revision_id=revision.id,
        project_id=revision.project_id,
        version_number=revision.version_number,
        kind=revision.kind,
        status=revision.status,
        lock_version=revision.lock_version,
        note=revision.note,
        rows=rows,
    )


def update_plan_facet(
    db: Session,
    revision_id: int,
    node_id: int,
    *,
    expected_lock_version: int,
    name: str | domain.Unset = domain.UNSET,
    duration_minutes: int | None | domain.Unset = domain.UNSET,
    duration_format: int | None | domain.Unset = domain.UNSET,
    start_at: datetime | None | domain.Unset = domain.UNSET,
    finish_at: datetime | None | domain.Unset = domain.UNSET,
    work_minutes: int | None | domain.Unset = domain.UNSET,
    percent_complete: int | domain.Unset = domain.UNSET,
    is_milestone: bool | domain.Unset = domain.UNSET,
    is_manual: bool | domain.Unset = domain.UNSET,
    calendar_id: int | None | domain.Unset = domain.UNSET,
) -> TreeWrite:
    """Edit the planning facet of one node: duration, dates, avancement, calendar.

    One domain call, therefore one ``lock_version`` bump, whatever the number of
    attributes the request carries -- see
    :func:`~waterfall.domain.revision.facets.update_plan_facet` for why that is not
    a detail. ``calendar_id=None`` drops an explicit calendar choice and lets Règle
    1 pick one again; leaving it out touches neither the calendar nor its
    provenance.
    """
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda project, revision: domain.update_plan_facet(
            project,
            revision,
            node_id,
            name=name,
            duration_minutes=duration_minutes,
            duration_format=duration_format,
            start_at=start_at,
            finish_at=finish_at,
            work_minutes=work_minutes,
            percent_complete=percent_complete,
            is_milestone=is_milestone,
            is_manual=is_manual,
            calendar_id=calendar_id,
        ),
    )


def replace_predecessors(
    db: Session,
    revision_id: int,
    node_id: int,
    predecessors: Sequence[domain.NodeLink],
    *,
    expected_lock_version: int,
) -> TreeWrite:
    """Replace every precedence link arriving at ``node_id`` with ``predecessors``.

    A predecessor the revision does not hold is refused as a
    :class:`~waterfall.domain.revision.CrossRevisionError` (INV-08): a node id is
    unique across revisions, so "not in this revision" and "belongs to another
    revision" are the same refusal.
    """
    return _mutate(
        db,
        revision_id,
        expected_lock_version,
        lambda _project, revision: domain.replace_predecessors(revision, node_id, predecessors),
    )


def resolve_bearing_task(db: Session, revision_id: int, node_id: int) -> BearingTask | None:
    """The bearing task of ``node_id``: its nearest ancestor carrying a plan facet.

    ``None`` when the root is reached without meeting one -- the node is then a
    project-wide global cost (INV-01). Never stored anywhere, always resolved,
    which is precisely why moving a cost line under another task is enough to
    change what it hangs under: there is nothing else to update.

    An unknown node is refused rather than answered ``None``:
    :func:`~waterfall.domain.revision.resolve_bearing_task` is total by design --
    the invariant checker runs it on deliberately invalid states -- so telling
    "no bearing task" from "no such node" is a separate question, and
    :func:`~waterfall.domain.revision.require_node` is the domain's answer to it.
    Asking it here rather than testing the membership in place is what keeps the
    decision in the domain.

    Read-only, and therefore takes no lock and no ``expected_lock_version``.
    """
    loaded = load_revision(db, revision_id)
    domain.require_node(loaded.revision, node_id)
    bearing = domain.resolve_bearing_task(loaded.revision, node_id)
    if bearing is None:
        return None
    return BearingTask(
        node_id=bearing.id,
        work_item_id=bearing.work_item_id,
        name=loaded.revision.plan_facets[bearing.id].name,
    )


def create_revision_from(
    db: Session,
    source_revision_id: int,
    *,
    expected_lock_version: int,
    kind: domain.RevisionKind | None = None,
    version_number: int | None = None,
    note: str | None = None,
) -> CreatedRevision:
    """Create a new draft revision reproducing ``source_revision_id`` (INV-07).

    Same tree, same depth-first order, same facet values, and every node of the
    copy designates the **same** ``work_item`` as its counterpart -- which is what
    makes two revisions comparable element by element. No node identity is shared,
    the precedence links are retranslated onto the copy's own nodes (INV-08), and
    the frozen lines of a validated source are not copied: a draft carries none
    (INV-24).

    Whatever the source's status, ``validated`` included: copying **is** how a
    validated revision is edited, and it is the only way (INV-03). The source is
    read, never written -- its own ``lock_version`` comes out unchanged -- and
    ``expected_lock_version`` therefore guards *what is copied* rather than what
    is modified: a source that moved on since the caller read it would produce a
    copy of a tree the caller never saw.

    Two limits follow from that, and they are the reason #352 exists:

    * **it is not idempotent.** Copying leaves the source's counter untouched, so
      two calls carrying the same ``expected_lock_version`` both pass the check
      and produce **two identical copies** -- a double-clicked button is enough.
      The guard catches a stale read, not a repeat;
    * **two copies of the same project race on ``version_number``.** Concurrent
      calls from *different* sources of one project lock different rows, so they
      never wait for each other, and each allocates its version number from the
      revisions it can see. They then collide on
      ``uq_wf_revision_project_version`` as a raw ``IntegrityError``, which leaves
      the session unusable rather than raising a refusal a caller can act on.

    Both are the route's to close (idempotency key, or a project-level lock):
    nothing in this signature can, since the contention is not on the row this
    call locks.
    """
    # The one write that does not go through :func:`_claim_revision`: the source
    # is locked and version-checked like any other, but *not* required to be a
    # draft -- refusing a validated source here would refuse the only operation
    # that can edit one.
    _check_lock_version(_lock_revision_row(db, source_revision_id), expected_lock_version)

    loaded = load_revision(db, source_revision_id)
    copy = domain.copy_revision(
        loaded.project,
        loaded.revision,
        kind=kind,
        version_number=version_number,
        note=note,
        now=_now(),
    )
    outcome = save_revision(db, loaded, copy)
    return CreatedRevision(
        revision_id=outcome.revision_id,
        lock_version=copy.lock_version,
        source_revision_id=source_revision_id,
        version_number=copy.version_number,
    )
