"""Tree operations of a revision: insert, move, indent, outdent, delete.

Single home of the tree logic (E14-02/E14-04 architecture rule): the future
persistence service loads a revision, delegates here, and writes the result back.
Nothing in this module knows about a database, a session or a request.

Every operation refuses a command that *would* violate an invariant -- moving a
node under one of its own descendants (INV-06), indenting a task under a cost
line (INV-14), writing on a validated revision (INV-03) -- by raising a domain
exception *before* touching the state, rather than producing an invalid state for
:func:`~waterfall.domain.revision.invariants.check_invariants` to report
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from waterfall.domain.revision.calendar_rule import resynchronize_from_node
from waterfall.domain.revision.entities import (
    CalendarSource,
    CostFacet,
    CostNature,
    NodeLink,
    PlanFacet,
    Project,
    ProjectRevision,
    RevisionNode,
    SupplyStatus,
    WorkItem,
    WorkItemKind,
)
from waterfall.domain.revision.errors import (
    CrossRevisionError,
    DuplicateWorkItemError,
    ExternalUidError,
    FacetContractError,
    FacetPlacementError,
    LinkError,
    NotFoundError,
    PositionError,
    ProjectMismatchError,
    SelectionError,
    TreeCycleError,
    WorkBreakdownError,
)
from waterfall.domain.revision.guards import require_draft, touch
from waterfall.domain.revision.invariants import check_cost_facet_shape
from waterfall.domain.revision.pricing import AmountResolver, default_amount
from waterfall.domain.revision.structure import (
    children_of,
    depth_first,
    is_cost_node,
    is_plan_node,
    resolve_bearing_task,
    subtree_ids,
)


@dataclass(frozen=True)
class CostLoss:
    """A cost facet about to disappear, named explicitly for the user to confirm.

    Feeds the mandatory safeguard of Rule 3: a re-import (or any cascade delete)
    must never silently drop chiffrage. Carries the label, the MO/non-MO nature
    and the current amount of the line, plus the bearing task it hangs under.
    """

    node_id: int
    work_item_id: int
    label: str
    nature: CostNature
    amount: Decimal
    bearing_task_name: str | None


@dataclass(frozen=True)
class DeletionReport:
    """What a cascade delete removed, as computed before the removal itself."""

    removed_node_ids: tuple[int, ...]
    cost_losses: tuple[CostLoss, ...]


def check_external_uid_available(
    project: Project, kind: WorkItemKind, external_uid: int | None
) -> None:
    """Refuse an ``external_uid`` a cost item may not carry or the project already uses.

    Public so a creation helper can run the check *before* allocating anything:
    a refused creation must leave ``project.work_items`` and its id counter
    untouched, or the very same input could never be retried (INV-25).
    """
    if external_uid is None:
        return
    if kind is WorkItemKind.COST:
        raise ExternalUidError("A cost work item never carries an external_uid (INV-25)")
    clashing = [
        item.id for item in project.work_items.values() if item.external_uid == external_uid
    ]
    if clashing:
        raise ExternalUidError(
            f"external_uid {external_uid} is already used by work_item {clashing[0]} "
            f"of project {project.id} (INV-25)"
        )


def _check_breakdown_entry_available(
    project: Project, kind: WorkItemKind, breakdown_entry_id: int | None
) -> None:
    """Refuse a hook a cost item may not carry or the project already resolves elsewhere.

    The symmetric of :func:`check_external_uid_available`, and deliberately a
    **creation guard rather than an invariant**: Règle 4 is provisoire, and an
    INV-27 erected on it would make the checker depend on a rule the maquettage
    lot can still change. What the guard buys is that the hook stays an
    *identity*: the generation resolves an entry to **one** work item, so a second
    one carrying the same entry would be unreachable from the moment it is
    created -- not the benign orphan of an entry dropped from the lotissement, but
    an identity nothing can ever land on again.
    """
    if breakdown_entry_id is None:
        return
    if kind is WorkItemKind.COST:
        raise WorkBreakdownError(
            "A cost work item is never generated from a lotissement entry: "
            "breakdown_entry_id hooks a task onto the lotissement (Règle 4)"
        )
    clashing = [
        item.id
        for item in sorted(project.work_items.values(), key=lambda item: item.id)
        if item.breakdown_entry_id == breakdown_entry_id
    ]
    if clashing:
        raise WorkBreakdownError(
            f"Lotissement entry {breakdown_entry_id} is already hooked onto work_item "
            f"{clashing[0]} of project {project.id}: a second one could never be "
            "resolved from the entry again (Règle 4)"
        )


def create_work_item(
    project: Project,
    kind: WorkItemKind,
    *,
    description: str | None = None,
    external_uid: int | None = None,
    breakdown_entry_id: int | None = None,
    now: datetime | None = None,
) -> WorkItem:
    """Register a new ``work_item`` in ``project`` and return it.

    ``breakdown_entry_id`` is the hook a regeneration finds the very same identity
    through (Règle 4); it is read back by
    :func:`~waterfall.domain.revision.work_breakdown.generate_skeleton`, which
    never creates a second work item for an entry the project already knows.
    Guarded like ``external_uid`` is -- refused on a ``cost`` item, unique per
    project -- because it is an identity hook, not a free-form field. In practice
    the skeleton generation is its only writer, but nothing *asserts* that: the
    guard is a creation guard, and Règle 4 is provisoire (see the attribute table
    of ``docs/revision-v0.1-specification.md``).

    ``now`` is passed in, never read from a clock: the domain stays pure.
    """
    check_external_uid_available(project, kind, external_uid)
    _check_breakdown_entry_available(project, kind, breakdown_entry_id)
    work_item = WorkItem(
        id=project.next_work_item_id,
        project_id=project.id,
        kind=kind,
        description=description,
        external_uid=external_uid,
        breakdown_entry_id=breakdown_entry_id,
        created_at=now,
        updated_at=now,
    )
    project.next_work_item_id += 1
    project.work_items[work_item.id] = work_item
    return work_item


def _resolve_work_item(project: Project, revision: ProjectRevision, work_item_id: int) -> WorkItem:
    work_item = project.work_items.get(work_item_id)
    if work_item is None:
        raise NotFoundError(f"Work item {work_item_id} does not exist in project {project.id}")
    if work_item.project_id != revision.project_id:
        raise ProjectMismatchError(
            f"Work item {work_item_id} belongs to project {work_item.project_id}, "
            f"revision {revision.id} to project {revision.project_id} (INV-10)"
        )
    for node in revision.nodes.values():
        if node.work_item_id == work_item_id:
            raise DuplicateWorkItemError(
                f"Work item {work_item_id} already occupies node {node.id} of "
                f"revision {revision.id} (INV-04)"
            )
    return work_item


def _validate_facet_shape(plan: PlanFacet | None, cost: CostFacet | None) -> None:
    """Checks that need no ``work_item``: INV-11, plus INV-19/INV-20 on a cost facet."""
    if (plan is None) == (cost is None):
        raise FacetContractError(
            "A node carries exactly one facet: planning or cost, never both, never none (INV-11)"
        )
    manual_without_calendar = (
        plan is not None
        and plan.calendar_id is None
        and plan.calendar_source is CalendarSource.MANUAL
    )
    if manual_without_calendar:
        # Refused rather than quietly downgraded to ``project``: ``manual`` means
        # "the user pinned this calendar", so there has to be one. Silently
        # correcting it would hand back a facet the caller never asked for, and
        # the next role assignment would overwrite it without warning (Rule 1).
        raise FacetContractError(
            "calendar_source 'manual' names a calendar the user pinned: calendar_id cannot be "
            "left empty (INV-15)"
        )
    if cost is not None:
        violations = check_cost_facet_shape(cost.node_id, cost)
        if violations:
            raise FacetContractError("; ".join(str(violation) for violation in violations))


def _validate_facet_pair(
    work_item: WorkItem, plan: PlanFacet | None, cost: CostFacet | None
) -> None:
    _validate_facet_shape(plan, cost)
    expected = WorkItemKind.TASK if plan is not None else WorkItemKind.COST
    if work_item.kind is not expected:
        raise FacetContractError(
            f"Work item {work_item.id} is of kind {work_item.kind.value}, it cannot carry a "
            f"{expected.value} facet (INV-13)"
        )


def _resolve_parent(revision: ProjectRevision, parent_id: int | None) -> None:
    if parent_id is not None and parent_id not in revision.nodes:
        raise NotFoundError(f"Node {parent_id} does not exist in revision {revision.id}")


def _resolve_position(
    revision: ProjectRevision, parent_id: int | None, position: int | None
) -> int:
    slots = len(children_of(revision, parent_id)) + 1
    if position is None:
        return slots
    if position < 1 or position > slots:
        raise PositionError(
            f"position {position} is outside the target sibling range 1..{slots} (INV-05)"
        )
    return position


def _validate_insert_slot(
    revision: ProjectRevision,
    *,
    plan: PlanFacet | None,
    parent_id: int | None,
    position: int | None,
) -> int:
    """Every placement guard of an insertion, run before anything is allocated.

    Returns the resolved position. Side-effect free on purpose: the creation
    helpers call it *before* registering a ``work_item``, so a refused insertion
    leaves the project exactly as it was.
    """
    _resolve_parent(revision, parent_id)
    if plan is not None and parent_id is not None and is_cost_node(revision, parent_id):
        raise FacetPlacementError(
            f"Node {parent_id} carries a cost facet and cannot hold a task (INV-14)"
        )
    return _resolve_position(revision, parent_id, position)


def _renumber_children(revision: ProjectRevision, parent_id: int | None) -> None:
    """Renumber the children of ``parent_id`` as contiguous positions 1..n (INV-05).

    **Private on purpose.** It writes -- it rewrites positions -- and it carries no
    ``require_draft``, because every caller in this module has already run one.
    Exposed on the package surface it would be a way to mutate a validated
    revision without INV-03 ever being consulted, so it is not exposed at all.
    """
    for index, node in enumerate(children_of(revision, parent_id), start=1):
        node.position = index


def compact_positions(revision: ProjectRevision) -> tuple[int, ...]:
    """Renumber **every** sibling set of the revision as contiguous positions 1..n (INV-05).

    The public counterpart of :func:`_renumber_children`, and the only renumbering
    exposed on the package surface: it carries a ``require_draft`` of its own,
    which is exactly what the private helper cannot -- its callers have already
    run one, whereas this one is reachable from outside.

    Every operation of this module already leaves the positions contiguous, so a
    revision built through the domain alone never needs it. What does need it is a
    tree the domain did not write: rows inserted straight into the tables, a
    manual repair, or the legacy services E14-12 (#339) has yet to remove -- all of
    which can leave a hole in a sibling set that no later operation closes on its
    own, because each one only renumbers the parents it touched.

    Returns the ids of the nodes whose position actually changed, sorted, so a
    caller can tell a repair from a no-op. The lock counter is bumped either way:
    "a write happened" is what :func:`touch` records, and making that conditional
    would hand two callers holding the same ``lock_version`` a way to both succeed.

    A node whose parent the revision does not hold (INV-09) is renumbered within
    the set of its fellow orphans rather than skipped -- the same totality
    :mod:`~waterfall.domain.revision.structure` maintains on a deliberately
    invalid state. Such a revision is refused at write time anyway.
    """
    require_draft(revision)
    moved: list[int] = []
    for parent_id in {node.parent_id for node in revision.nodes.values()}:
        for index, node in enumerate(children_of(revision, parent_id), start=1):
            if node.position != index:
                node.position = index
                moved.append(node.id)
    touch(revision)
    return tuple(sorted(moved))


def _apply_calendar_defaults(project: Project, plan: PlanFacet) -> None:
    """Initialise a brand new planning facet's calendar (Rule 1, INV-15).

    "No calendar" can only mean "none was asked for": ``_validate_facet_shape``
    has already refused an explicit ``manual`` source without a calendar to pin.
    """
    if plan.calendar_id is None:
        plan.calendar_id = project.calendar_id
        plan.calendar_source = CalendarSource.PROJECT
    elif plan.calendar_source is None:
        plan.calendar_source = CalendarSource.MANUAL


def insert_node(
    project: Project,
    revision: ProjectRevision,
    *,
    work_item_id: int,
    plan: PlanFacet | None = None,
    cost: CostFacet | None = None,
    parent_id: int | None = None,
    position: int | None = None,
) -> RevisionNode:
    """Insert a node carrying exactly one facet, at ``position`` under ``parent_id``.

    ``position`` defaults to "last child". The facet objects are stored as given
    (their ``node_id`` is overwritten with the freshly allocated node id).
    """
    require_draft(revision)
    work_item = _resolve_work_item(project, revision, work_item_id)
    _validate_facet_pair(work_item, plan, cost)
    target_position = _validate_insert_slot(
        revision, plan=plan, parent_id=parent_id, position=position
    )

    node = RevisionNode(
        id=project.next_node_id,
        revision_id=revision.id,
        work_item_id=work_item_id,
        parent_id=parent_id,
        position=target_position,
    )
    project.next_node_id += 1
    for sibling in children_of(revision, parent_id):
        if sibling.position >= target_position:
            sibling.position += 1
    revision.nodes[node.id] = node
    if plan is not None:
        plan.node_id = node.id
        _apply_calendar_defaults(project, plan)
        revision.plan_facets[node.id] = plan
    if cost is not None:
        cost.node_id = node.id
        revision.cost_facets[node.id] = cost
    _renumber_children(revision, parent_id)
    if cost is not None:
        # Rule 1 only triggers on a change to the set of MO assignments carried by
        # a subtree: inserting a task adds none (its own calendar was just
        # initialised above), so nothing upstream needs resynchronising.
        resynchronize_from_node(project, revision, node.id)
    touch(revision)
    return node


def add_task(
    project: Project,
    revision: ProjectRevision,
    *,
    name: str,
    parent_id: int | None = None,
    position: int | None = None,
    external_uid: int | None = None,
    description: str | None = None,
    duration_minutes: int | None = None,
    is_milestone: bool = False,
    start_at: datetime | None = None,
    finish_at: datetime | None = None,
    calendar_id: int | None = None,
    calendar_source: CalendarSource | None = None,
    now: datetime | None = None,
) -> RevisionNode:
    """Create a ``task`` work item and insert a node carrying its planning facet.

    Every guard runs *before* the ``work_item`` is allocated: a refused creation
    leaves ``project.work_items`` and ``next_work_item_id`` untouched, so the very
    same input can be corrected and retried.
    """
    plan = PlanFacet(
        node_id=0,
        name=name,
        calendar_id=calendar_id,
        calendar_source=calendar_source,
        is_milestone=is_milestone,
        duration_minutes=duration_minutes,
        start_at=start_at,
        finish_at=finish_at,
    )
    # Deliberate pre-validation: every one of these four guards runs again inside
    # ``create_work_item``/``insert_node``, which own the contract and refuse the
    # same inputs when called directly. Repeating them here is what makes a
    # *refusal allocate nothing* -- no ``work_item``, no bumped id counter -- so
    # the very same input can be corrected and retried. Cost: four side-effect
    # free checks on the happy path.
    require_draft(revision)
    _validate_facet_shape(plan, None)
    _validate_insert_slot(revision, plan=plan, parent_id=parent_id, position=position)
    check_external_uid_available(project, WorkItemKind.TASK, external_uid)
    work_item = create_work_item(
        project, WorkItemKind.TASK, description=description, external_uid=external_uid, now=now
    )
    return insert_node(
        project,
        revision,
        work_item_id=work_item.id,
        plan=plan,
        parent_id=parent_id,
        position=position,
    )


def add_cost_line(
    project: Project,
    revision: ProjectRevision,
    *,
    nature: CostNature,
    label: str,
    parent_id: int | None = None,
    position: int | None = None,
    quantity: Decimal = Decimal("1"),
    role_id: int | None = None,
    hours: Decimal | None = None,
    cost_type_id: int | None = None,
    cost_category_id: int | None = None,
    unit_cost: Decimal | None = None,
    supply_status: SupplyStatus | None = None,
    planned_date: date | None = None,
    cost_code_id: int | None = None,
    comment: str | None = None,
    description: str | None = None,
    now: datetime | None = None,
) -> RevisionNode:
    """Create a ``cost`` work item and insert a node carrying its cost facet.

    ``parent_id=None`` places the line at the root: a global project cost, whose
    bearing task is undefined (INV-01) and which is explicitly allowed.

    ``planned_date`` is the forecast cash-out date, independent of the bearing
    task's dates; it is what a frozen line's ``year`` is copied from. As for
    :func:`add_task`, every guard runs before the ``work_item`` is allocated.
    """
    cost = CostFacet(
        node_id=0,
        nature=nature,
        label=label,
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
    )
    # Deliberate pre-validation, for the same reason as in :func:`add_task`:
    # ``insert_node`` re-runs both guards, but a refusal must leave the project
    # exactly as it was rather than an orphan ``work_item`` behind.
    require_draft(revision)
    _validate_facet_shape(None, cost)
    _validate_insert_slot(revision, plan=None, parent_id=parent_id, position=position)
    work_item = create_work_item(project, WorkItemKind.COST, description=description, now=now)
    return insert_node(
        project,
        revision,
        work_item_id=work_item.id,
        cost=cost,
        parent_id=parent_id,
        position=position,
    )


def require_node(revision: ProjectRevision, node_id: int) -> RevisionNode:
    """The node ``node_id`` designates, refused when the revision does not hold it.

    The public addressing guard of the tree, and the reason it is public: the
    read-only helpers of :mod:`~waterfall.domain.revision.structure` are
    deliberately **total** -- :func:`~waterfall.domain.revision.structure.resolve_bearing_task`
    answers ``None`` for an unknown node exactly as it does for a global cost,
    because the invariant checker calls them on states built to be invalid. A
    caller that does need the two told apart (a route resolving a node id it was
    handed, say) has to ask, and asking is this function; writing the membership
    test itself would put a decision about the tree outside the domain.

    Raises rather than returning ``None`` so the refusal is the one every other
    operation gives, message included -- :func:`_require_nodes` is this function
    in a loop.
    """
    node = revision.nodes.get(node_id)
    if node is None:
        raise NotFoundError(f"Node {node_id} does not exist in revision {revision.id}")
    return node


def _require_nodes(revision: ProjectRevision, node_ids: list[int]) -> None:
    if not node_ids:
        raise SelectionError("The selection is empty")
    if len(set(node_ids)) != len(node_ids):
        raise SelectionError("The selection contains duplicates")
    for node_id in node_ids:
        require_node(revision, node_id)


def selection_roots(revision: ProjectRevision, node_ids: list[int]) -> list[RevisionNode]:
    """Normalise a selection to its roots, in depth-first display order.

    A node whose ancestor is also selected is dropped: moving or deleting the
    ancestor already carries it along.
    """
    _require_nodes(revision, node_ids)
    selected = set(node_ids)
    roots: set[int] = set()
    for node_id in node_ids:
        parent_id = revision.nodes[node_id].parent_id
        while parent_id is not None and parent_id not in selected:
            parent_id = revision.nodes[parent_id].parent_id
        if parent_id is None:
            roots.add(node_id)
    return [node for node in depth_first(revision) if node.id in roots]


def _validate_move_target(
    revision: ProjectRevision, roots: list[RevisionNode], target_parent_id: int | None
) -> None:
    if target_parent_id is None:
        return
    if target_parent_id not in revision.nodes:
        raise NotFoundError(f"Node {target_parent_id} does not exist in revision {revision.id}")
    moved: set[int] = set()
    for root in roots:
        moved.update(subtree_ids(revision, root.id))
    if target_parent_id in moved:
        raise TreeCycleError(
            f"Node {target_parent_id} belongs to the moved selection: a node cannot become "
            "its own descendant's child (INV-06)"
        )
    if is_cost_node(revision, target_parent_id) and any(
        is_plan_node(revision, root.id) for root in roots
    ):
        raise FacetPlacementError(
            f"Node {target_parent_id} carries a cost facet and cannot hold a task (INV-14)"
        )


def carries_labor(revision: ProjectRevision, roots: list[RevisionNode]) -> bool:
    """Whether the subtree of any selected root carries an MO cost facet (Rule 1)."""
    for root in roots:
        for node_id in subtree_ids(revision, root.id):
            facet = revision.cost_facets.get(node_id)
            if facet is not None and facet.nature is CostNature.LABOR:
                return True
    return False


def move_nodes(
    project: Project,
    revision: ProjectRevision,
    node_ids: list[int],
    *,
    target_parent_id: int | None = None,
    position: int | None = None,
) -> None:
    """Move a selection under ``target_parent_id``, inserting it at ``position``.

    The selection keeps its relative display order, its subtrees and both facets
    of every node it carries: an edit on one facet is an edit on the tree, and
    therefore on the other facet, because there is only one tree.
    """
    require_draft(revision)
    roots = selection_roots(revision, node_ids)
    _validate_move_target(revision, roots, target_parent_id)

    root_ids = {root.id for root in roots}
    former_parents = {root.parent_id for root in roots}
    siblings = [node for node in children_of(revision, target_parent_id) if node.id not in root_ids]
    slots = len(siblings) + 1
    target_position = slots if position is None else position
    if target_position < 1 or target_position > slots:
        raise PositionError(
            f"position {target_position} is outside the target sibling range 1..{slots} (INV-05)"
        )

    for root in roots:
        root.parent_id = target_parent_id
    ordered = siblings[: target_position - 1] + roots + siblings[target_position - 1 :]
    for index, node in enumerate(ordered, start=1):
        node.position = index
    for parent_id in former_parents:
        if parent_id != target_parent_id:
            _renumber_children(revision, parent_id)

    # Rule 1: a move changes the set of MO assignments carried by the subtree of
    # both the former and the new ancestors -- but only if the selection carries
    # an MO assignment at all, which spares a whole-subtree walk on the common
    # case of a plain planning reorganisation.
    if carries_labor(revision, roots):
        for parent_id in former_parents | {target_parent_id}:
            if parent_id is not None and parent_id in revision.nodes:
                resynchronize_from_node(project, revision, parent_id)
    touch(revision)


def _common_parent(roots: list[RevisionNode]) -> int | None:
    parents = {root.parent_id for root in roots}
    if len(parents) != 1:
        raise SelectionError("Indenting or outdenting requires a selection sharing a single parent")
    return parents.pop()


def _contiguous_indexes(siblings: list[RevisionNode], root_ids: set[int]) -> list[int]:
    """Indexes of the selected siblings, refusing a selection with a hole in it.

    Every sibling-level command -- up, down, indent, outdent -- requires a
    contiguous block: reordering the unselected siblings a gap contains would
    make two unrelated nodes swap their display order for what the user asked to
    be a mere indentation.
    """
    indexes = [index for index, node in enumerate(siblings) if node.id in root_ids]
    if indexes != list(range(min(indexes), min(indexes) + len(indexes))):
        raise SelectionError(
            "Only a contiguous block of siblings can be moved, indented or outdented together"
        )
    return indexes


def indent_nodes(project: Project, revision: ProjectRevision, node_ids: list[int]) -> None:
    """Indent a contiguous block of siblings under its immediately preceding sibling."""
    require_draft(revision)
    roots = selection_roots(revision, node_ids)
    parent_id = _common_parent(roots)
    siblings = children_of(revision, parent_id)
    first_index = min(_contiguous_indexes(siblings, {root.id for root in roots}))
    if first_index == 0:
        raise SelectionError("The first child of a parent has no sibling to be indented under")
    # The preceding sibling is never part of the selection: ``first_index`` is the
    # lowest selected index, so ``first_index - 1`` is by construction unselected.
    new_parent = siblings[first_index - 1]
    move_nodes(project, revision, [root.id for root in roots], target_parent_id=new_parent.id)


def outdent_nodes(project: Project, revision: ProjectRevision, node_ids: list[int]) -> None:
    """Outdent a contiguous block of siblings to its grandparent, after its former parent.

    Outdenting a child of a root node moves it up to the root itself.
    """
    require_draft(revision)
    roots = selection_roots(revision, node_ids)
    parent_id = _common_parent(roots)
    if parent_id is None:
        raise SelectionError("A root node cannot be outdented further")
    _contiguous_indexes(children_of(revision, parent_id), {root.id for root in roots})
    parent = revision.nodes[parent_id]
    move_nodes(
        project,
        revision,
        [root.id for root in roots],
        target_parent_id=parent.parent_id,
        position=parent.position + 1,
    )


def _shift_within_siblings(
    project: Project, revision: ProjectRevision, node_ids: list[int], offset: int
) -> None:
    roots = selection_roots(revision, node_ids)
    parent_id = _common_parent(roots)
    siblings = children_of(revision, parent_id)
    indexes = _contiguous_indexes(siblings, {root.id for root in roots})
    target = min(indexes) + offset if offset < 0 else max(indexes) + offset - len(indexes) + 1
    # Only one of the two bounds can be breached for a given direction -- moving
    # up can only run past the first sibling, moving down past the last one --
    # but both are stated so the guard reads the same whatever the offset.
    runs_past_first = min(indexes) + offset < 0
    runs_past_last = max(indexes) + offset > len(siblings) - 1
    if runs_past_first or runs_past_last:
        raise SelectionError("The selection is already at the edge of its sibling range")
    move_nodes(
        project,
        revision,
        [root.id for root in roots],
        target_parent_id=parent_id,
        position=target + 1,
    )


def move_nodes_up(project: Project, revision: ProjectRevision, node_ids: list[int]) -> None:
    """Move a contiguous block of siblings one position up."""
    require_draft(revision)
    _shift_within_siblings(project, revision, node_ids, -1)


def move_nodes_down(project: Project, revision: ProjectRevision, node_ids: list[int]) -> None:
    """Move a contiguous block of siblings one position down."""
    require_draft(revision)
    _shift_within_siblings(project, revision, node_ids, 1)


def describe_cost_losses(
    project: Project,
    revision: ProjectRevision,
    node_ids: list[int],
    *,
    amount_of: AmountResolver = default_amount,
) -> list[CostLoss]:
    """Name every cost facet that deleting ``node_ids`` would take away.

    The mandatory safeguard of Rule 3: chiffrage is never dropped silently. The
    domain produces the information; E14-06 surfaces it in the import diff.
    """
    expanded = [
        descendant_id for node_id in node_ids for descendant_id in subtree_ids(revision, node_id)
    ]
    return cost_losses_of(project, revision, expanded, amount_of=amount_of)


def cost_losses_of(
    project: Project,
    revision: ProjectRevision,
    node_ids: list[int],
    *,
    amount_of: AmountResolver = default_amount,
) -> list[CostLoss]:
    """Name the cost facet of each node of ``node_ids``, *without* expanding subtrees.

    Used by the re-import, which computes the exact set of doomed nodes itself:
    the subtree of a vanished task minus the branches the file keeps elsewhere.
    """
    losses: list[CostLoss] = []
    seen: set[int] = set()
    for descendant_id in node_ids:
        if descendant_id in seen:
            continue
        seen.add(descendant_id)
        facet = revision.cost_facets.get(descendant_id)
        if facet is not None:
            bearing = resolve_bearing_task(revision, descendant_id)
            bearing_facet = None if bearing is None else revision.plan_facets.get(bearing.id)
            losses.append(
                CostLoss(
                    node_id=descendant_id,
                    work_item_id=revision.nodes[descendant_id].work_item_id,
                    label=facet.label,
                    nature=facet.nature,
                    amount=amount_of(project, facet),
                    bearing_task_name=None if bearing_facet is None else bearing_facet.name,
                )
            )
    return losses


def delete_nodes(
    project: Project,
    revision: ProjectRevision,
    node_ids: list[int],
    *,
    amount_of: AmountResolver = default_amount,
) -> DeletionReport:
    """Delete a selection, its whole subtree and both facets of every node removed.

    Precedence links touching any removed node go with them, and the siblings of
    each removed node are renumbered contiguously (INV-02, INV-05).
    """
    require_draft(revision)
    roots = selection_roots(revision, node_ids)
    losses = describe_cost_losses(
        project, revision, [root.id for root in roots], amount_of=amount_of
    )

    removed: set[int] = set()
    parents: set[int | None] = set()
    for root in roots:
        removed.update(subtree_ids(revision, root.id))
        parents.add(root.parent_id)

    for node_id in removed:
        revision.nodes.pop(node_id, None)
        revision.plan_facets.pop(node_id, None)
        revision.cost_facets.pop(node_id, None)
    revision.links = [
        link
        for link in revision.links
        if link.node_id not in removed and link.predecessor_node_id not in removed
    ]
    removed_labor = any(loss.nature is CostNature.LABOR for loss in losses)
    for parent_id in parents:
        _renumber_children(revision, parent_id)
        # Rule 1: removing an MO assignment can send the task back to the project
        # calendar -- an unpriced task stays datable (INV-15).
        if removed_labor and parent_id is not None and parent_id in revision.nodes:
            resynchronize_from_node(project, revision, parent_id)
    touch(revision)
    return DeletionReport(
        removed_node_ids=tuple(sorted(removed)),
        cost_losses=tuple(losses),
    )


def _would_cycle(revision: ProjectRevision, node_id: int, predecessor_node_id: int) -> bool:
    """Whether adding ``predecessor -> node`` closes a precedence cycle (INV-18)."""
    successors: dict[int, list[int]] = {}
    for link in revision.links:
        successors.setdefault(link.predecessor_node_id, []).append(link.node_id)
    stack = [node_id]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current == predecessor_node_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(successors.get(current, []))
    return False


def add_link(
    revision: ProjectRevision,
    *,
    node_id: int,
    predecessor_node_id: int,
    link_type: int = 1,
    lag_tenth_minute: int = 0,
    lag_format: int | None = None,
) -> None:
    """Add a precedence link between two planning nodes of the same revision."""
    require_draft(revision)
    if node_id == predecessor_node_id:
        raise LinkError(f"Node {node_id} cannot be its own predecessor (INV-16)")
    for candidate in (node_id, predecessor_node_id):
        if candidate not in revision.nodes:
            raise CrossRevisionError(
                f"Node {candidate} does not belong to revision {revision.id} (INV-08)"
            )
        if not is_plan_node(revision, candidate):
            raise LinkError(
                f"Node {candidate} carries no planning facet: a cost line has neither "
                "predecessor nor successor (INV-17)"
            )
    if _would_cycle(revision, node_id, predecessor_node_id):
        raise LinkError(
            f"Link {predecessor_node_id} -> {node_id} would close a precedence cycle (INV-18)"
        )
    revision.links.append(
        NodeLink(
            node_id=node_id,
            predecessor_node_id=predecessor_node_id,
            link_type=link_type,
            lag_tenth_minute=lag_tenth_minute,
            lag_format=lag_format,
        )
    )
    touch(revision)


def links_of(revision: ProjectRevision, node_id: int) -> list[tuple[int, int, int]]:
    """``(predecessor_node_id, link_type, lag_tenth_minute)`` of ``node_id``, sorted."""
    return sorted(
        (link.predecessor_node_id, link.link_type, link.lag_tenth_minute)
        for link in revision.links
        if link.node_id == node_id
    )
