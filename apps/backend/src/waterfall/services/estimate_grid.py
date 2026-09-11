"""Devis grid node tree: freely reorderable positions for cost lines and labor
role assignments of a single `Estimate` (E12-07, issue #289).

Structurally mirrors `services.planning_tree`'s own task-hierarchy operations
(`move_planning_tasks`/`create_planning_task`), but over `EstimateGridNode`
instead of `WfPlanningTaskSnapshot`: every node's `uid` is either a positive
`MsTask.id` (a task belonging to this estimate's own `EstimateTaskRow`s,
never itself moved or created here) or a negative `EstimateGridNode.uid`
(another grid node of the same estimate) -- see `EstimateGridNode`'s own
docstring in `models/resources.py`.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from waterfall.models.resources import (
    Estimate,
    EstimateCostLine,
    EstimateGridNode,
    EstimateRoleAssignment,
    EstimateTaskRow,
)
from waterfall.schemas.projects import EstimateGridNodeMove


class EstimateGridMoveError(ValueError):
    """A grid node mutation command violates the devis grid tree contract."""


class EstimateGridInvariantError(EstimateGridMoveError):
    """The grid node hierarchy would violate a structural invariant."""


class EstimateGridMoveNotFoundError(EstimateGridMoveError):
    """A node or task addressed by a grid mutation command does not exist."""


def next_estimate_grid_node_uid(db: Session, estimate_id: int) -> int:
    """Allocate the next node uid for `estimate_id`: `MIN(uid) - 1`, or `-1` if no
    node exists yet -- deliberately negative and decreasing so it can never
    collide with a positive `MsTask.id`, the same integer space a node's own
    `parent_uid` also draws from when attached directly under a task."""
    min_uid = (
        db.query(func.min(EstimateGridNode.uid))
        .filter(EstimateGridNode.estimate_id == estimate_id)
        .scalar()
    )
    return (min_uid - 1) if min_uid is not None else -1


def _node_order(node: EstimateGridNode) -> tuple[int, int]:
    return (node.position, node.id)


def _validate_tree(nodes_by_uid: dict[int, EstimateGridNode]) -> None:
    for node in nodes_by_uid.values():
        if (
            node.parent_uid is not None
            and node.parent_uid < 0
            and node.parent_uid not in nodes_by_uid
        ):
            raise EstimateGridInvariantError(f"Node {node.uid} has an orphaned parent")

    visited: set[int] = set()
    visiting: set[int] = set()

    def visit(uid: int) -> None:
        if uid in visiting:
            raise EstimateGridInvariantError("Grid node hierarchy contains a cycle")
        if uid in visited:
            return
        visiting.add(uid)
        parent_uid = nodes_by_uid[uid].parent_uid
        if parent_uid is not None and parent_uid < 0:
            visit(parent_uid)
        visiting.remove(uid)
        visited.add(uid)

    for uid in nodes_by_uid:
        visit(uid)


def _depth_first_node_uids(
    nodes_by_uid: dict[int, EstimateGridNode], selected_uids: set[int]
) -> list[int]:
    """Order `selected_uids` in a stable, depth-first, top-to-bottom document
    order -- mirrors `planning_tree._depth_first_task_uids`, generalized to
    start from every distinct parent (not just the devis root `None`), since a
    grid node's parent can also be a task outside this module's own tree.
    """
    children_by_parent: dict[int | None, list[EstimateGridNode]] = defaultdict(list)
    for node in nodes_by_uid.values():
        children_by_parent[node.parent_uid].append(node)
    for siblings in children_by_parent.values():
        siblings.sort(key=_node_order)

    ordered_uids: list[int] = []
    visited_parents: set[int | None] = set()

    def visit(parent_uid: int | None) -> None:
        if parent_uid in visited_parents:
            return
        visited_parents.add(parent_uid)
        for node in children_by_parent[parent_uid]:
            if node.uid in selected_uids:
                ordered_uids.append(node.uid)
            visit(node.uid)

    visit(None)
    for parent_uid in sorted(parent for parent in children_by_parent if parent is not None):
        visit(parent_uid)
    return ordered_uids


def _selected_roots(node_uids: list[int], nodes_by_uid: dict[int, EstimateGridNode]) -> list[int]:
    if len(set(node_uids)) != len(node_uids):
        raise EstimateGridMoveError("node_uids must not contain duplicates")
    missing = [uid for uid in node_uids if uid not in nodes_by_uid]
    if missing:
        raise EstimateGridMoveNotFoundError(f"Node not found: {missing[0]}")

    selected = set(node_uids)
    roots: list[int] = []
    for uid in node_uids:
        parent_uid = nodes_by_uid[uid].parent_uid
        while parent_uid is not None and parent_uid < 0:
            if parent_uid in selected:
                break
            parent_uid = nodes_by_uid[parent_uid].parent_uid
        else:
            roots.append(uid)
    return _depth_first_node_uids(nodes_by_uid, set(roots))


def _task_row_exists(db: Session, estimate_id: int, task_id: int) -> bool:
    return (
        db.query(EstimateTaskRow.id)
        .filter(EstimateTaskRow.estimate_id == estimate_id)
        .filter(EstimateTaskRow.task_id == task_id)
        .first()
        is not None
    )


def _validate_target_parent(
    db: Session,
    estimate_id: int,
    target_parent_uid: int | None,
    selected_roots: list[int],
    nodes_by_uid: dict[int, EstimateGridNode],
) -> None:
    if target_parent_uid is None:
        return
    if target_parent_uid > 0:
        if not _task_row_exists(db, estimate_id, target_parent_uid):
            raise EstimateGridMoveNotFoundError(f"Task not found: {target_parent_uid}")
        return

    if target_parent_uid not in nodes_by_uid:
        raise EstimateGridMoveNotFoundError(f"Node not found: {target_parent_uid}")
    if target_parent_uid in selected_roots:
        raise EstimateGridInvariantError("A node cannot be moved under itself")

    selected_root_set = set(selected_roots)
    parent_uid: int | None = target_parent_uid
    while parent_uid is not None and parent_uid < 0:
        if parent_uid in selected_root_set:
            raise EstimateGridInvariantError("A node cannot be moved under its descendant")
        parent_uid = nodes_by_uid[parent_uid].parent_uid


def _resolve_ancestor_task_id(
    parent_uid: int | None, nodes_by_uid: dict[int, EstimateGridNode]
) -> int | None:
    """Walk `parent_uid` up through the node chain (negative uids) until either a
    positive task uid or the devis root (`None`) is reached."""
    while parent_uid is not None and parent_uid < 0:
        parent_uid = nodes_by_uid[parent_uid].parent_uid
    return parent_uid


def _recompute_task_ids(
    db: Session,
    nodes_by_uid: dict[int, EstimateGridNode],
    moved_root_uids: list[int],
) -> None:
    """Recompute `EstimateCostLine.task_id`/`EstimateRoleAssignment.task_id` for
    every node in the subtree of each moved root -- a moved root's own
    ancestor chain always changed; a descendant's may have changed too, since
    its nearest ancestor task is resolved by walking up through its own
    ancestors, which now include the moved root at a new position.
    """
    children_by_parent: dict[int, list[EstimateGridNode]] = defaultdict(list)
    for node in nodes_by_uid.values():
        if node.parent_uid is not None and node.parent_uid < 0:
            children_by_parent[node.parent_uid].append(node)

    affected_uids: set[int] = set()

    def collect(uid: int) -> None:
        affected_uids.add(uid)
        for child in children_by_parent.get(uid, []):
            collect(child.uid)

    for root_uid in moved_root_uids:
        collect(root_uid)

    for uid in affected_uids:
        node = nodes_by_uid[uid]
        resolved_task_id = _resolve_ancestor_task_id(node.parent_uid, nodes_by_uid)
        if node.kind == "cost_line":
            line = db.query(EstimateCostLine).filter(EstimateCostLine.node_id == node.id).one()
            line.task_id = resolved_task_id
        else:
            assignment = (
                db.query(EstimateRoleAssignment)
                .filter(EstimateRoleAssignment.node_id == node.id)
                .one()
            )
            assignment.task_id = resolved_task_id


def move_estimate_grid_nodes(
    db: Session, estimate: Estimate, command: EstimateGridNodeMove
) -> None:
    """Move/reorder a selection of `estimate`'s grid nodes (E12-07, issue #289).

    Mirrors `planning_tree.move_planning_tasks`: normalizes the selection to
    its top-level roots, validates the target parent, splices the moved roots
    into the target's sibling group at `command.position`, renumbers every
    affected sibling group, then recomputes `task_id` on every
    `EstimateCostLine`/`EstimateRoleAssignment` whose owning node's nearest
    ancestor task may have changed.
    """
    nodes = db.query(EstimateGridNode).filter(EstimateGridNode.estimate_id == estimate.id).all()
    nodes_by_uid = {node.uid: node for node in nodes}
    _validate_tree(nodes_by_uid)
    selected_roots = _selected_roots(command.node_uids, nodes_by_uid)
    _validate_target_parent(
        db, estimate.id, command.target_parent_uid, selected_roots, nodes_by_uid
    )
    selected_root_set = set(selected_roots)

    siblings_by_parent: dict[int | None, list[EstimateGridNode]] = defaultdict(list)
    for node in nodes:
        if node.uid not in selected_root_set:
            siblings_by_parent[node.parent_uid].append(node)
    for siblings in siblings_by_parent.values():
        siblings.sort(key=_node_order)

    moved = [nodes_by_uid[uid] for uid in selected_roots]
    target_siblings = siblings_by_parent[command.target_parent_uid]
    if command.position > len(target_siblings) + 1:
        raise EstimateGridMoveError("position is outside the target sibling range")
    target_siblings[command.position - 1 : command.position - 1] = moved
    for node in moved:
        node.parent_uid = command.target_parent_uid

    for siblings in siblings_by_parent.values():
        for position, node in enumerate(siblings, start=1):
            node.position = position

    _recompute_task_ids(db, nodes_by_uid, selected_roots)


def create_estimate_grid_node(
    db: Session,
    estimate: Estimate,
    *,
    kind: str,
    target_parent_uid: int | None,
    insert_after_uid: int | None,
) -> EstimateGridNode:
    """Insert a single new grid node at an explicit position (E12-07, issue #289).

    Mirrors `planning_tree.create_planning_task`'s `target_parent_uid`/
    `insert_after_uid` contract, except the default when both are absent:
    unlike a planning task (which lands as the *first* child), a new devis
    grid node lands as the *last* child of the resolved parent -- last child
    of the devis root when `target_parent_uid` is also absent, matching this
    grid's pre-existing "always append" behaviour (see e.g.
    `_create_estimate_planning_task`'s own `max_position` comment in
    `api/routes/estimates.py`).
    """
    nodes = db.query(EstimateGridNode).filter(EstimateGridNode.estimate_id == estimate.id).all()
    nodes_by_uid = {node.uid: node for node in nodes}

    if target_parent_uid is not None:
        if target_parent_uid > 0:
            if not _task_row_exists(db, estimate.id, target_parent_uid):
                raise EstimateGridMoveNotFoundError(f"Task not found: {target_parent_uid}")
        elif target_parent_uid not in nodes_by_uid:
            raise EstimateGridMoveNotFoundError(f"Node not found: {target_parent_uid}")

    siblings = sorted(
        (node for node in nodes if node.parent_uid == target_parent_uid), key=_node_order
    )

    if insert_after_uid is None:
        insert_index = len(siblings)
    else:
        if insert_after_uid not in nodes_by_uid:
            raise EstimateGridMoveNotFoundError(f"Node not found: {insert_after_uid}")
        sibling_uids = [node.uid for node in siblings]
        if insert_after_uid not in sibling_uids:
            raise EstimateGridMoveError(
                f"Node {insert_after_uid} is not a sibling of the target parent"
            )
        insert_index = sibling_uids.index(insert_after_uid) + 1

    new_node = EstimateGridNode(
        estimate_id=estimate.id,
        uid=next_estimate_grid_node_uid(db, estimate.id),
        parent_uid=target_parent_uid,
        position=insert_index + 1,
        kind=kind,
    )
    db.add(new_node)
    # Session is autoflush=False (see db.session.get_session_factory); the caller
    # needs new_node.id populated immediately to set the owning cost line/role
    # assignment's node_id in the same transaction.
    db.flush()

    siblings.insert(insert_index, new_node)
    for position, node in enumerate(siblings, start=1):
        node.position = position

    return new_node
