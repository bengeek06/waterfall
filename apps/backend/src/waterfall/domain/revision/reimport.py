"""Re-import of a planning into a draft revision, expressed as a diff (Rule 3).

Knows nothing about MS Project: the caller hands over an already-parsed list of
:class:`ImportedTask`, keyed by the *external* uid -- the import/export layer's
identifier, never a key of the domain.

Rule 3: a task that disappeared from the file disappears from the draft, with
both its facets and its whole subtree. The mandatory safeguard is
:func:`plan_reimport`, which names every cost-bearing node the confirmation would
destroy, with its label, its MO/non-MO nature and its current amount, *before*
anything is applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from waterfall.domain.revision.calendar_rule import resynchronize_from_node
from waterfall.domain.revision.entities import (
    PlanFacet,
    Project,
    ProjectRevision,
    RevisionNode,
    WorkItem,
    WorkItemKind,
)
from waterfall.domain.revision.errors import (
    ImportStructureError,
    NotFoundError,
    TreeCycleError,
)
from waterfall.domain.revision.guards import require_draft, touch
from waterfall.domain.revision.pricing import AmountResolver, default_amount
from waterfall.domain.revision.structure import children_of, is_plan_node
from waterfall.domain.revision.tree import (
    CostLoss,
    cost_losses_of,
    create_work_item,
    delete_nodes,
    insert_node,
)


@dataclass(frozen=True)
class ImportedTask:
    """One task read from the external file, in its file order."""

    external_uid: int
    name: str
    parent_external_uid: int | None = None
    duration_minutes: int | None = None
    duration_format: int | None = None
    is_milestone: bool = False
    start_at: datetime | None = None
    finish_at: datetime | None = None
    work_minutes: int | None = None
    percent_complete: int = 0
    is_manual: bool = False


@dataclass(frozen=True)
class ImportDiffItem:
    """One structural change the re-import would apply."""

    external_uid: int
    name: str
    node_id: int | None


@dataclass(frozen=True)
class ImportDiff:
    """What a re-import changes, computed before it is applied."""

    added: tuple[ImportDiffItem, ...]
    moved: tuple[ImportDiffItem, ...]
    removed: tuple[ImportDiffItem, ...]
    cost_losses: tuple[CostLoss, ...]


def _existing_by_external_uid(
    project: Project, revision: ProjectRevision
) -> dict[int, RevisionNode]:
    """Planning nodes of ``revision`` reachable by their work item's ``external_uid``."""
    mapping: dict[int, RevisionNode] = {}
    for node in revision.nodes.values():
        if not is_plan_node(revision, node.id):
            continue
        work_item = project.work_items.get(node.work_item_id)
        if work_item is not None and work_item.external_uid is not None:
            mapping[work_item.external_uid] = node
    return mapping


def _external_uid_of(project: Project, node: RevisionNode) -> int | None:
    work_item = project.work_items.get(node.work_item_id)
    return None if work_item is None else work_item.external_uid


def _has_moved(
    revision: ProjectRevision,
    existing: dict[int, RevisionNode],
    node: RevisionNode,
    task: ImportedTask,
    file_rank: dict[int, int],
) -> bool:
    """Whether the file puts ``node`` under another parent, or at another rank.

    The comparison is made on the expected *parent node*, resolved from
    ``existing``, never on a pair of external uids: a parent created in Waterfall
    and never exported has no uid, so comparing uids would read "no parent" for
    both "at the root" and "under a local parent" and would under-report the move
    the apply step really performs.

    The rank compares planning siblings only -- a cost line never appears in the
    file. A task whose own parent and rank are unchanged but which the file
    pushes down because a *new* sibling is inserted before it does count as
    moved: its displayed position genuinely changes.
    """
    if task.parent_external_uid is None:
        expected_parent_id = None
    else:
        expected_parent = existing.get(task.parent_external_uid)
        if expected_parent is None:
            # The file hangs it under a task the same file creates: a move for sure.
            return True
        expected_parent_id = expected_parent.id
    if node.parent_id != expected_parent_id:
        return True
    plan_siblings = [
        sibling
        for sibling in children_of(revision, node.parent_id)
        if is_plan_node(revision, sibling.id)
    ]
    current_rank = [sibling.id for sibling in plan_siblings].index(node.id)
    return current_rank != file_rank[task.external_uid]


def _reject_parent_cycles(tasks: list[ImportedTask]) -> None:
    """Refuse a file whose ``parent_external_uid`` chains close a cycle (INV-06)."""
    parents = {task.external_uid: task.parent_external_uid for task in tasks}
    for external_uid in parents:
        seen: set[int] = {external_uid}
        current = parents[external_uid]
        while current is not None and current in parents:
            if current in seen:
                raise TreeCycleError(
                    f"Imported task {external_uid} is its own ancestor through task "
                    f"{current}: the file's parent chain closes a cycle (INV-06)"
                )
            seen.add(current)
            current = parents[current]


def _validate_import_structure(
    existing: dict[int, RevisionNode], tasks: list[ImportedTask]
) -> None:
    """Refuse a file that cannot be applied, *before* a single node is touched.

    Four shapes are rejected, all of which a valid MSPDI export never produces:

    * a parent chain closing a cycle (:class:`TreeCycleError`, INV-06);
    * a task naming as parent a task the file lists only *after* it -- MS Project
      writes a depth-first file, so this signals a malformed source rather than
      something to reorder silently. The parent *is* in the file, so the fault is
      its order, not its absence: :class:`ImportStructureError`, never
      :class:`NotFoundError`, or the transport layer would answer 404 to a file
      that is merely badly ordered;
    * a task naming as parent a node the revision holds but the file does **not**
      list (:class:`ImportStructureError`). That parent is about to be removed by
      this very import, so applying it would reparent a survivor under a doomed
      subtree and destroy chiffrage the diff never announced -- exactly what
      Rule 3's safeguard forbids;
    * a task naming as parent a uid neither the file nor the revision knows: that
      one is genuinely missing (:class:`NotFoundError`).
    """
    _reject_parent_cycles(tasks)
    incoming = {task.external_uid for task in tasks}
    defined: set[int] = set()
    for task in tasks:
        parent_uid = task.parent_external_uid
        if parent_uid is not None and parent_uid not in defined:
            if parent_uid in incoming:
                raise ImportStructureError(
                    f"Imported task {task.external_uid} names parent {parent_uid}, which the "
                    "file lists only after it: a depth-first export never does, and the order "
                    "is not silently repaired"
                )
            if parent_uid in existing:
                raise ImportStructureError(
                    f"Imported task {task.external_uid} names parent {parent_uid}, which the "
                    "file itself does not list: this re-import would remove that parent and "
                    "everything below it, silently taking away the chiffrage of the task it "
                    "claims to keep"
                )
            raise NotFoundError(
                f"Imported task {task.external_uid} names parent {parent_uid}, "
                "which is neither in the file nor in the revision"
            )
        defined.add(task.external_uid)


def plan_reimport(
    project: Project,
    revision: ProjectRevision,
    tasks: list[ImportedTask],
    *,
    amount_of: AmountResolver = default_amount,
) -> ImportDiff:
    """Compute the diff of re-importing ``tasks`` into ``revision``, changing nothing.

    A planning node whose work item carries **no** ``external_uid`` -- created in
    Waterfall and never exported -- is never reported as removed: its absence
    from the file carries no information, since it was never in it.

    The whole structure of the file is validated here, so that
    :func:`apply_reimport` only ever writes behind a diff that is both complete
    and applicable: it never starts mutating a revision and gives up halfway.
    """
    existing = _existing_by_external_uid(project, revision)
    _validate_import_structure(existing, tasks)
    incoming = {task.external_uid: task for task in tasks}

    file_rank: dict[int, int] = {}
    counters: dict[int | None, int] = {}
    for task in tasks:
        rank = counters.get(task.parent_external_uid, 0)
        file_rank[task.external_uid] = rank
        counters[task.parent_external_uid] = rank + 1

    added = tuple(
        ImportDiffItem(external_uid=task.external_uid, name=task.name, node_id=None)
        for task in tasks
        if task.external_uid not in existing
    )
    moved = tuple(
        ImportDiffItem(
            external_uid=task.external_uid,
            name=task.name,
            node_id=existing[task.external_uid].id,
        )
        for task in tasks
        if task.external_uid in existing
        and _has_moved(revision, existing, existing[task.external_uid], task, file_rank)
    )
    removed_nodes = [
        (external_uid, node)
        for external_uid, node in sorted(existing.items())
        if external_uid not in incoming
    ]
    removed = tuple(
        ImportDiffItem(
            external_uid=external_uid,
            name=revision.plan_facets[node.id].name,
            node_id=node.id,
        )
        for external_uid, node in removed_nodes
    )
    doomed = [
        node_id
        for _, node in removed_nodes
        for node_id in _doomed_node_ids(project, revision, node.id, incoming)
    ]
    losses = cost_losses_of(project, revision, doomed, amount_of=amount_of)
    return ImportDiff(added=added, moved=moved, removed=removed, cost_losses=tuple(losses))


def _doomed_node_ids(
    project: Project,
    revision: ProjectRevision,
    root_id: int,
    incoming: dict[int, ImportedTask],
) -> list[int]:
    """Nodes the removal of ``root_id`` really takes away.

    The subtree of a vanished task, minus the branches the file keeps elsewhere:
    a task still present in the file under another parent is reparented by the
    re-import, not destroyed, and neither is its own subtree. Without that
    subtraction the safeguard would announce the loss of chiffrage that in fact
    survives, and the applied result would contradict the confirmed diff.
    """
    doomed: list[int] = [root_id]
    for child in children_of(revision, root_id):
        external_uid = _external_uid_of(project, child)
        if external_uid is not None and external_uid in incoming:
            continue
        doomed.extend(_doomed_node_ids(project, revision, child.id, incoming))
    return doomed


def _parent_node_id(existing: dict[int, RevisionNode], task: ImportedTask) -> int | None:
    """Node id of ``task``'s parent, ``None`` at the root.

    Total by construction: :func:`_validate_import_structure` has already proved
    that every ``parent_external_uid`` names a task the file defines before this
    one, and the creation pass walks the file in that same order.
    """
    if task.parent_external_uid is None:
        return None
    return existing[task.parent_external_uid].id


def _work_item_for(project: Project, external_uid: int, now: datetime | None) -> WorkItem:
    """The project's ``work_item`` for ``external_uid``, created only if it has none.

    The re-import hooks onto the identity of the **project**, not of the revision:
    ``external_uid`` is unique per project (INV-25), and the ``work_item`` is the
    only link between two revisions of the same project. Importing the same file
    into a second revision must therefore land on the very same work items --
    otherwise the reconciliation of a forecast against its budget, which joins on
    ``work_item_id`` and on nothing else, would have nothing left to join on.
    """
    for work_item in sorted(project.work_items.values(), key=lambda item: item.id):
        if work_item.external_uid == external_uid:
            return work_item
    return create_work_item(project, WorkItemKind.TASK, external_uid=external_uid, now=now)


def _create_missing_nodes(
    project: Project,
    revision: ProjectRevision,
    tasks: list[ImportedTask],
    existing: dict[int, RevisionNode],
    now: datetime | None,
) -> None:
    for task in tasks:
        if task.external_uid in existing:
            continue
        parent_id = _parent_node_id(existing, task)
        work_item = _work_item_for(project, task.external_uid, now)
        node = insert_node(
            project,
            revision,
            work_item_id=work_item.id,
            plan=PlanFacet(node_id=0, name=task.name),
            parent_id=parent_id,
        )
        existing[task.external_uid] = node


def _apply_plan_facet(revision: ProjectRevision, node_id: int, task: ImportedTask) -> None:
    facet = revision.plan_facets[node_id]
    facet.name = task.name
    facet.is_milestone = task.is_milestone
    facet.duration_minutes = task.duration_minutes
    facet.duration_format = task.duration_format
    facet.start_at = task.start_at
    facet.finish_at = task.finish_at
    facet.work_minutes = task.work_minutes
    facet.percent_complete = task.percent_complete
    facet.is_manual = task.is_manual


def _reparent_and_refresh(
    revision: ProjectRevision,
    tasks: list[ImportedTask],
    existing: dict[int, RevisionNode],
) -> tuple[set[int | None], dict[int | None, list[int]]]:
    """Hang every task the file still carries where the file puts it, and refresh it.

    Returns the parents whose children the re-import touched -- the root always
    among them -- and, for each of them, the node ids the file lists under it in
    file order.
    """
    touched_parents: set[int | None] = {None}
    file_children: dict[int | None, list[int]] = {}
    for task in tasks:
        node = existing[task.external_uid]
        parent_id = _parent_node_id(existing, task)
        touched_parents.add(node.parent_id)
        node.parent_id = parent_id
        touched_parents.add(parent_id)
        file_children.setdefault(parent_id, []).append(node.id)
        _apply_plan_facet(revision, node.id, task)
    return touched_parents, file_children


def _apply_removals(
    project: Project,
    revision: ProjectRevision,
    diff: ImportDiff,
    touched_parents: set[int | None],
    amount_of: AmountResolver,
) -> None:
    """Delete the vanished tasks, their subtree and both facets (Rule 3 / INV-02)."""
    removed_node_ids = [item.node_id for item in diff.removed if item.node_id is not None]
    if not removed_node_ids:
        return
    for node_id in removed_node_ids:
        touched_parents.add(revision.nodes[node_id].parent_id)
    delete_nodes(project, revision, removed_node_ids, amount_of=amount_of)


def _surviving_parents(
    revision: ProjectRevision, touched_parents: set[int | None]
) -> list[int | None]:
    """The touched parents the re-import did not delete, in a deterministic order."""
    parents: list[int | None] = [None] if None in touched_parents else []
    parents.extend(
        sorted(
            parent_id
            for parent_id in touched_parents
            if parent_id is not None and parent_id in revision.nodes
        )
    )
    return parents


def _reorder_children(
    revision: ProjectRevision, parent_id: int | None, file_order: list[int]
) -> None:
    """Order the planning children as the file does, then keep the cost lines after them.

    The file says nothing about where a cost line sits among its siblings, so the
    cost children of a parent keep their relative order and follow the tasks. The
    same call with an empty ``file_order`` -- a parent the file gives no child --
    is a plain contiguous renumbering. Positions stay contiguous from 1 (INV-05).
    """
    children = children_of(revision, parent_id)
    ranked = [node_id for node_id in file_order if node_id in revision.nodes]
    ranked_ids = set(ranked)
    remaining = [node.id for node in children if node.id not in ranked_ids]
    for index, node_id in enumerate(ranked + remaining, start=1):
        revision.nodes[node_id].position = index


def _recompute_derived_state(
    project: Project, revision: ProjectRevision, parents: list[int | None]
) -> None:
    """Terminal step: recompute what the tree *derives* from its own final shape.

    Runs last, on the tree as it will be left, and **without a guard**. Both
    conditions are load-bearing and neither is an optimisation that may be put
    back:

    * *last*, because Rule 1 resolves a task's calendar on the **first** MO facet
      in depth-first order. The order of the siblings is therefore an input of the
      rule, and it is not settled until :func:`_reorder_children` has run;
    * *after the deletions*, so a doomed MO line never gets to refresh the
      calendar of a survivor;
    * *unguarded*, because "does this file move chiffrage around" is not the
      question. A re-import that changes nothing at all still reorders the
      siblings -- the file's tasks come before the local ones and before the cost
      lines -- and reordering alone changes which MO facet Rule 1 resolves to,
      without changing the *set* of assignments one bit. No state invariant
      catches the stale result either: INV-15 checks that a calendar is present,
      never that it is fresh.
    """
    for parent_id in parents:
        if parent_id is not None:
            resynchronize_from_node(project, revision, parent_id)


def apply_reimport(
    project: Project,
    revision: ProjectRevision,
    tasks: list[ImportedTask],
    *,
    now: datetime | None = None,
    amount_of: AmountResolver = default_amount,
) -> ImportDiff:
    """Apply a re-import to a draft and return the diff it applied.

    Five phases, in this order and for these reasons:

    1. create the tasks the file adds;
    2. reparent and refresh every task the file still carries;
    3. **then** delete the vanished ones with their subtree and both facets
       (Rule 3 / INV-02). Deleting after the reparenting is what makes a "summary
       removed, children kept elsewhere" edit behave: the surviving children have
       already left the doomed subtree, so they keep their node, their
       ``work_item`` and their cost lines instead of being recreated from scratch;
    4. reorder each surviving touched parent to match the file;
    5. recompute the derived state of those parents -- see
       :func:`_recompute_derived_state`, which owns the reasons it comes last.

    Atomic: :func:`plan_reimport` validates the whole file first, so the revision
    is either fully re-imported or rigorously untouched.
    """
    require_draft(revision)
    diff = plan_reimport(project, revision, tasks, amount_of=amount_of)

    existing = _existing_by_external_uid(project, revision)
    _create_missing_nodes(project, revision, tasks, existing, now)
    touched_parents, file_children = _reparent_and_refresh(revision, tasks, existing)
    _apply_removals(project, revision, diff, touched_parents, amount_of)

    parents = _surviving_parents(revision, touched_parents)
    for parent_id in parents:
        _reorder_children(revision, parent_id, file_children.get(parent_id, []))
    _recompute_derived_state(project, revision, parents)

    touch(revision)
    return diff
