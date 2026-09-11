"""Read-only tree helpers shared by the operations and the invariant checker.

Every function here is total and side-effect free: it must stay usable on a
*deliberately invalid* state (the invariant checker calls it on states built to
violate an invariant), so each walk is guarded against a missing parent and
against a parent cycle instead of assuming a well-formed tree.
"""

from __future__ import annotations

from waterfall.domain.revision.entities import ProjectRevision, RevisionNode


def is_plan_node(revision: ProjectRevision, node_id: int) -> bool:
    """Whether ``node_id`` carries a planning facet in ``revision``."""
    return node_id in revision.plan_facets


def is_cost_node(revision: ProjectRevision, node_id: int) -> bool:
    """Whether ``node_id`` carries a cost facet in ``revision``."""
    return node_id in revision.cost_facets


def children_of(revision: ProjectRevision, parent_id: int | None) -> list[RevisionNode]:
    """Children of ``parent_id`` (``None`` for the root siblings), in display order.

    Sorted by ``position`` then ``id`` so the order stays deterministic even on a
    state whose positions are duplicated or non contiguous (INV-05 violated).
    """
    return sorted(
        (node for node in revision.nodes.values() if node.parent_id == parent_id),
        key=lambda node: (node.position, node.id),
    )


def depth_first(revision: ProjectRevision, parent_id: int | None = None) -> list[RevisionNode]:
    """Depth-first display order of the subtree under ``parent_id``, excluding it.

    Nodes whose ``parent_id`` points at a node absent from the revision are
    unreachable and therefore not listed -- they are reported by INV-09.
    """
    ordered: list[RevisionNode] = []
    visited: set[int] = set()

    def visit(current_id: int | None) -> None:
        for child in children_of(revision, current_id):
            if child.id in visited:
                continue
            visited.add(child.id)
            ordered.append(child)
            visit(child.id)

    visit(parent_id)
    return ordered


def levels(revision: ProjectRevision) -> list[list[RevisionNode]]:
    """The nodes of the tree grouped by depth, roots first, each level in display order.

    A node no root reaches -- its parent is missing (INV-09) or its parent chain
    cycles (INV-06) -- belongs to no level and is therefore absent from the
    result; :func:`unreachable_node_ids` is what names those.

    Level order is what a writer needs that :func:`depth_first` does not give it:
    a parent is always in a strictly earlier level than its children, so a store
    that has to allocate an identity for a parent before its children can write
    the tree one level at a time.
    """
    grouped: list[list[RevisionNode]] = []
    visited: set[int] = set()
    current = children_of(revision, None)
    while current:
        grouped.append(current)
        visited.update(node.id for node in current)
        current = [
            child
            for node in current
            for child in children_of(revision, node.id)
            if child.id not in visited
        ]
    return grouped


def unreachable_node_ids(revision: ProjectRevision) -> list[int]:
    """Ids of the nodes no root reaches, sorted: the nodes :func:`levels` leaves out.

    Non-empty exactly when the parent graph is not a forest: either a node hangs
    from a parent absent from the revision (INV-09), or a set of nodes hangs off
    itself (INV-06).
    """
    reached = {node.id for level in levels(revision) for node in level}
    return sorted(set(revision.nodes) - reached)


def ancestors_of(revision: ProjectRevision, node_id: int) -> list[RevisionNode]:
    """Strict ancestors of ``node_id``, nearest first.

    Stops on a missing parent (INV-09) or on a parent cycle (INV-06) instead of
    looping forever.
    """
    chain: list[RevisionNode] = []
    seen: set[int] = {node_id}
    node = revision.nodes.get(node_id)
    while node is not None and node.parent_id is not None:
        if node.parent_id in seen:
            break
        parent = revision.nodes.get(node.parent_id)
        if parent is None:
            break
        seen.add(parent.id)
        chain.append(parent)
        node = parent
    return chain


def subtree_ids(revision: ProjectRevision, node_id: int) -> list[int]:
    """``node_id`` followed by every descendant id, in depth-first order."""
    if node_id not in revision.nodes:
        return []
    return [node_id] + [node.id for node in depth_first(revision, node_id)]


def resolve_bearing_task(revision: ProjectRevision, node_id: int) -> RevisionNode | None:
    """The bearing task of ``node_id``: its first strict ancestor carrying a plan facet.

    ``None`` when the root is reached without meeting one -- the node is then a
    project-wide global cost (INV-01). Never stored anywhere: always resolved.
    """
    for ancestor in ancestors_of(revision, node_id):
        if is_plan_node(revision, ancestor.id):
            return ancestor
    return None


def bearing_work_item_id(revision: ProjectRevision, node_id: int) -> int | None:
    """``work_item_id`` of the bearing task of ``node_id``, ``None`` for a global cost."""
    bearing = resolve_bearing_task(revision, node_id)
    return None if bearing is None else bearing.work_item_id


def node_by_work_item(revision: ProjectRevision, work_item_id: int) -> RevisionNode | None:
    """The node occupied by ``work_item_id`` in ``revision``, if any.

    Unambiguous as long as INV-04 holds; on a state that violates it, the lowest
    node id wins so the result stays deterministic.
    """
    matches = [node for node in revision.nodes.values() if node.work_item_id == work_item_id]
    return min(matches, key=lambda node: node.id) if matches else None
