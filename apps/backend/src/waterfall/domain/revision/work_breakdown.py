"""The lotissement, and the skeleton it can seed a planning with (Règle 4).

Product decision transcribed here: the **lotissement** -- postes, lots,
livrables -- lives at **project** level, *outside* any revision. It is not
versioned, it has no history, and a validated revision does not freeze it
(INV-26). Editing it propagates **nothing** to the planning: no node created,
modified or deleted.

The skeleton generated from it is only a way not to start from a blank page --
one of the three equivalent and optional ways of starting a planning, next to
the blank page itself and to an MS Project import. A regeneration is offered only
while the generated tree has **not been touched**, which is decided by comparing
the tree part of the :class:`~waterfall.domain.revision.entities.SkeletonFingerprint`
the revision carries with the tree as it stands now.

Immutability is not bent for any of this: a regeneration writes, so it targets a
**draft** like every other write (INV-03). Editing the lotissement of a project
whose revision is validated is accepted precisely *because* the lotissement is
not part of that revision.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime

from waterfall.domain.revision.entities import (
    BreakdownEntry,
    CalendarSource,
    PlanFacet,
    Project,
    ProjectRevision,
    ProjectStatus,
    RevisionStatus,
    SkeletonFingerprint,
    WorkItem,
    WorkItemKind,
)
from waterfall.domain.revision.errors import FacetContractError, WorkBreakdownError
from waterfall.domain.revision.guards import require_draft
from waterfall.domain.revision.structure import children_of, depth_first
from waterfall.domain.revision.tree import create_work_item, delete_nodes, insert_node


def _validate_breakdown(entries: list[BreakdownEntry]) -> None:
    """Refuse a lotissement that cannot be read as a tree, before storing any of it.

    Same contract as an imported file (Rule 3 c): an entry names a parent the
    list defines **before** it, so the order is already depth-first and a parent
    chain can never close a cycle.
    """
    defined: set[int] = set()
    for entry in entries:
        if entry.id in defined:
            raise WorkBreakdownError(
                f"Lotissement entry {entry.id} is listed twice: an entry id is unique per project"
            )
        if entry.parent_id is not None and entry.parent_id not in defined:
            raise WorkBreakdownError(
                f"Lotissement entry {entry.id} names parent {entry.parent_id}, which the "
                "lotissement does not define before it"
            )
        defined.add(entry.id)


def save_work_breakdown(project: Project, entries: Iterable[BreakdownEntry]) -> None:
    """Record the lotissement of ``project``, replacing whatever it held.

    Accepted whatever the status of any revision of the project, validated ones
    included: the lotissement is project data (INV-26). It propagates **nothing**
    -- not one node of any revision is created, modified or deleted by this call.

    Saving is the **only** trigger of the ``cree`` -> ``initialise`` transition;
    any other status is left as it is.
    """
    listed = list(entries)
    _validate_breakdown(listed)
    project.work_breakdown = tuple(listed)
    if project.status is ProjectStatus.CREE:
        project.status = ProjectStatus.INITIALISE


def _digest(canonical: str) -> str:
    """Non-reversible condensate of a canonical rendering.

    What a revision carries of a skeleton is an **empreinte**, not its content --
    not a serialised lotissement, and not the labels either (INV-26). A validated
    revision would otherwise freeze them, which is exactly what Règle 4 refuses;
    and a marker only ever gets compared for equality, so a digest loses nothing.
    """
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _breakdown_digest(project: Project) -> str:
    """Condensate of the lotissement: its entries, in order, with their parent."""
    return _digest(
        repr(
            [
                (entry.id, entry.parent_id, entry.kind.value, entry.name)
                for entry in project.work_breakdown
            ]
        )
    )


def _plan_marks(plan: PlanFacet) -> tuple[object, ...]:
    """What the fingerprint watches on a planning facet: the planner's own typing.

    The criterion is "could this field hold work the user would be furious to lose
    to a regeneration?", and a planner's normal work on a fresh skeleton is
    exactly this: durations, dates, charge, milestones, progress, manual
    scheduling -- none of which a rename covers.

    ``calendar_id`` is watched **only** while ``calendar_source`` is ``manual``,
    i.e. while it holds a calendar the user pinned himself. The ``project`` and
    ``role`` sources are *derived*: Rule 1 recomputes them from the MO assignments
    a subtree carries, so watching them could report a skeleton nobody touched as
    touched. Nothing is lost by that restriction -- an MO assignment requires a
    cost line, which the signature already sees as a node of its own.
    """
    pinned_calendar = plan.calendar_id if plan.calendar_source is CalendarSource.MANUAL else None
    return (
        plan.name,
        plan.is_milestone,
        plan.duration_minutes,
        plan.duration_format,
        plan.start_at,
        plan.finish_at,
        plan.work_minutes,
        plan.percent_complete,
        plan.is_manual,
        pinned_calendar,
    )


def _tree_signature(revision: ProjectRevision) -> str:
    """Canonical form of a tree: shape, labels, planning values and links, never ids.

    Node ids are deliberately left out -- of the nodes *and* of the precedence
    links, which are retranslated into the position paths of their two ends:
    copying a revision (INV-07) reproduces the very same tree under fresh ids, and
    such a copy is still the untouched skeleton.

    What counts as a touch is anything the user can have put into the tree:
    a change of shape, a rename, a cost line hung under a skeleton task, a
    precedence link, or any of the planning values :func:`_plan_marks` lists.
    Of a cost facet only the label is watched, because a generated skeleton is a
    tree of **tasks**: the mere presence of a cost node already tells the
    signature apart from the stamped one, whatever its other fields hold.
    """
    path: dict[int, tuple[int, ...]] = {}
    signature: list[tuple[tuple[int, ...], str, tuple[object, ...]]] = []
    for node in depth_first(revision):
        prefix = () if node.parent_id is None else path.get(node.parent_id, ())
        path[node.id] = (*prefix, node.position)
        plan = revision.plan_facets.get(node.id)
        cost = revision.cost_facets.get(node.id)
        if plan is not None:
            signature.append((path[node.id], "task", _plan_marks(plan)))
        elif cost is not None:
            signature.append((path[node.id], "cost", (cost.label,)))
        else:  # pragma: no cover - a facet-less node is reported by INV-11
            signature.append((path[node.id], "none", ()))
    links = sorted(
        (
            (
                path.get(link.node_id),
                path.get(link.predecessor_node_id),
                link.link_type,
                link.lag_tenth_minute,
                link.lag_format,
            )
            for link in revision.links
        ),
        # Sorted on the rendering rather than on the values: two links can differ
        # by a ``None`` lag format alone, which no ordering of tuples accepts.
        key=repr,
    )
    return repr((signature, links))


def _tree_digest(revision: ProjectRevision) -> str:
    """Condensate of :func:`_tree_signature`, which is what the revision stores.

    The signature itself spells the labels out, so storing it would put a copy of
    every lot name onto the revision -- the very smuggling INV-26 forbids, only
    serialised. Condensing it keeps the marker and keeps nothing else.
    """
    return _digest(_tree_signature(revision))


def skeleton_fingerprint_of(project: Project, revision: ProjectRevision) -> SkeletonFingerprint:
    """The fingerprint ``revision`` would be stamped with if generated right now."""
    return SkeletonFingerprint(
        breakdown_digest=_breakdown_digest(project),
        tree_digest=_tree_digest(revision),
    )


def breakdown_changed_since_generation(project: Project, revision: ProjectRevision) -> bool:
    """Whether the lotissement changed since the skeleton of ``revision`` was generated.

    The one and only reader of the ``breakdown_digest`` half of the fingerprint,
    and it authorises nothing: a caller may use it to tell the user "the
    lotissement has changed since this skeleton was generated", never to allow or
    refuse a regeneration -- :func:`can_regenerate_skeleton` alone decides that
    (Règle 4 c). ``False`` on a revision that never carried a skeleton: nothing
    was generated, so nothing can have gone stale.
    """
    fingerprint = revision.skeleton_fingerprint
    return fingerprint is not None and fingerprint.breakdown_digest != _breakdown_digest(project)


def can_regenerate_skeleton(project: Project, revision: ProjectRevision) -> bool:
    """Whether regenerating the skeleton of ``revision`` may be offered at all.

    Three conditions, and the marker is the third: the project has a lotissement,
    the revision is a draft -- a validated one refuses every write (INV-03) -- and
    the revision carries a skeleton whose tree has not been touched since it was
    generated.

    The ``breakdown_digest`` half of the fingerprint is deliberately *not*
    compared: a lotissement edited since the generation is the normal reason to
    regenerate, not a reason to forbid it. See
    :func:`breakdown_changed_since_generation`, which reports that staleness
    without deciding anything.
    """
    fingerprint = revision.skeleton_fingerprint
    return (
        bool(project.work_breakdown)
        and revision.status is RevisionStatus.DRAFT
        and fingerprint is not None
        and fingerprint.tree_digest == _tree_digest(revision)
    )


def _work_item_of_entry(project: Project, entry: BreakdownEntry) -> WorkItem | None:
    """The project's ``work_item`` for ``entry``, or ``None``. Reads, never writes.

    Deliberately the same mechanism as
    :func:`~waterfall.domain.revision.reimport._work_item_for`, which hooks a
    re-imported task onto ``external_uid``: the generation hooks onto the identity
    of the **project**, by lotissement entry, so that generating the skeleton of
    the same lot twice -- into a second revision, or again after a regeneration --
    lands on the very same work item. Anything else would leave the frozen lines
    of a validated revision, and the reconciliation that joins on ``work_item_id``
    and on nothing else, pointing at identities no node carries any more.

    The work item carries **no** ``external_uid``: a skeleton task was never in an
    MS Project file, so a later import leaves it alone (Rule 3 a) instead of
    reading its absence from the file as a removal.
    """
    for work_item in sorted(project.work_items.values(), key=lambda item: item.id):
        if work_item.breakdown_entry_id == entry.id:
            return work_item
    return None


def _resolve_skeleton_work_items(project: Project) -> dict[int, WorkItem | None]:
    """The work item every lotissement entry already owns, checked before any write.

    Deliberate pre-validation, exactly like the one
    :func:`~waterfall.domain.revision.tree.add_task` carries and for the same
    reason: a refusal must *write nothing*. Resolving the hooks entry by entry as
    the tree is built would create tasks up to the offending entry and allocate
    their work items, then raise -- leaving a partial tree that jams the revision
    for good, since :func:`generate_skeleton` then refuses a non-empty tree and
    :func:`regenerate_skeleton` refuses a tree that carries no fingerprint.

    The one refusal this pass can raise is an entry hooked onto a work item of
    kind ``cost``, which no facet of a skeleton task could ever be inserted under
    (INV-13). The creation surface already refuses to build such a hook, so
    reaching it takes a hand-written state -- which is precisely why the check is
    here rather than assumed away.
    """
    resolved: dict[int, WorkItem | None] = {}
    for entry in project.work_breakdown:
        work_item = _work_item_of_entry(project, entry)
        if work_item is not None and work_item.kind is not WorkItemKind.TASK:
            raise FacetContractError(
                f"Work item {work_item.id} is of kind {work_item.kind.value}, it cannot carry a "
                f"task facet (INV-13): lotissement entry {entry.id} hooks onto it"
            )
        resolved[entry.id] = work_item
    return resolved


def _write_skeleton(
    project: Project,
    revision: ProjectRevision,
    resolved: dict[int, WorkItem | None],
    now: datetime | None,
) -> dict[int, int]:
    """Create one task per lotissement entry and stamp the resulting fingerprint.

    Takes the hooks :func:`_resolve_skeleton_work_items` established *before* the
    first write, so that the only allocations left here are the ones for entries
    the project does not know yet, and none of them can be refused.
    """
    node_by_entry: dict[int, int] = {}
    for entry in project.work_breakdown:
        parent_id = None if entry.parent_id is None else node_by_entry[entry.parent_id]
        hooked = resolved[entry.id]
        work_item = (
            hooked
            if hooked is not None
            else create_work_item(project, WorkItemKind.TASK, breakdown_entry_id=entry.id, now=now)
        )
        node = insert_node(
            project,
            revision,
            work_item_id=work_item.id,
            plan=PlanFacet(node_id=0, name=entry.name),
            parent_id=parent_id,
        )
        node_by_entry[entry.id] = node.id
    revision.skeleton_fingerprint = skeleton_fingerprint_of(project, revision)
    return node_by_entry


def generate_skeleton(
    project: Project, revision: ProjectRevision, *, now: datetime | None = None
) -> dict[int, int]:
    """Seed an empty draft with one task per lotissement entry, and return the mapping.

    One of the three ways of starting a planning, and the only one this module
    knows about. Refused on a revision that already holds nodes: overwriting an
    existing tree is :func:`regenerate_skeleton`'s decision to take, and it is the
    one that checks the tree was not touched.

    Every guard runs *before* the first node is inserted: a refused generation
    leaves the revision empty and the project's work items untouched, so the very
    same call can be retried once the lotissement or the hooks are corrected.
    """
    require_draft(revision)
    if not project.work_breakdown:
        raise WorkBreakdownError(
            f"Project {project.id} has no lotissement to generate a skeleton from: "
            "save one first, or start the planning from a blank page or an MS Project import"
        )
    if revision.nodes:
        raise WorkBreakdownError(
            f"Revision {revision.id} already carries {len(revision.nodes)} nodes: "
            "use regenerate_skeleton, which refuses to overwrite a tree that was touched"
        )
    return _write_skeleton(project, revision, _resolve_skeleton_work_items(project), now)


def regenerate_skeleton(
    project: Project, revision: ProjectRevision, *, now: datetime | None = None
) -> dict[int, int]:
    """Rebuild the skeleton of a draft from the current lotissement.

    Offered -- and accepted -- only while :func:`can_regenerate_skeleton` holds:
    a tree touched since its generation is the user's work, and this operation
    would silently replace it.

    The rebuilt tasks keep the ``work_item`` of the lotissement entry they come
    from (:func:`_work_item_of_entry`), and that is not an optimisation: "not
    touched" compares a **state**, not a history. Undoing an edit -- deleting the
    one cost line that had been hung under a skeleton task -- makes a
    regeneration available again on a tree whose identities a validated revision
    already froze. Reallocating them would leave that revision's frozen lines,
    and the reconciliation that joins on ``work_item_id`` and on nothing else,
    with nothing left to join on.
    """
    require_draft(revision)
    if not can_regenerate_skeleton(project, revision):
        raise WorkBreakdownError(
            f"Revision {revision.id} carries no untouched skeleton: regenerating would "
            "overwrite a tree that was edited since it was generated"
        )
    # Resolved *before* the deletion, not after: this pass is the one that can
    # refuse, and a refusal once the old tree is gone would be worse than a
    # partial write -- it would leave the revision with nothing at all.
    resolved = _resolve_skeleton_work_items(project)
    # Being regenerable implies a non-empty tree: the fingerprint is stamped right
    # after one task per lotissement entry was created, and a skeleton is never
    # generated from an empty lotissement. ``delete_nodes`` refuses an empty
    # selection, and is never handed one here.
    delete_nodes(project, revision, [node.id for node in children_of(revision, None)])
    return _write_skeleton(project, revision, resolved, now)
