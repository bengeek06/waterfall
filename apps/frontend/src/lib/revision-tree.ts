import type { RevisionNode, RevisionNodeKind, RevisionTree } from "./backend";
import type { TreeRowIdentity } from "./tree-rows";

// E14-10 (#336): how the shared editable-tree base (lib/tree-rows.ts, hooks/use-tree-*) reads a
// node of a revision -- the row shape **both** tables now render, the planning table here and the
// devis grid in E14-11 (#337), which reuses this module as-is rather than restating it.
//
// Everything that used to be rebuilt client-side comes off the wire already done: `GET
// .../revisions/{id}/nodes` answers the whole tree in depth-first order, each node carrying its
// `row_number` (its positional identifier) and its `level` (depth, roots at 1), both computed on
// read and stored in no column. So there is no flattening pass here and no `buildPlanningTreeRows`
// any more: the single thing a row needs that the payload does not carry is whether it has
// children, which only a look at the following nodes can tell.

/** A node of the tree plus the one derived flag the fold/unfold affordance needs. */
export type RevisionTreeRow = RevisionNode & { hasChildren: boolean };

/**
 * The identity of a revision row for the shared base, and the only thing it ever needs to know
 * about one.
 *
 * Deliberately carries no `isSelectable`: whether a given kind of row may enter the selection is
 * a rule of the table that renders it, not of the node. A table that needs one spreads this object
 * and adds its own (`{ ...revisionNodeRowIdentity, isSelectable: (row) => row.kind === "cost" }`)
 * rather than forking the module.
 *
 * **That spread has to live at module level, never in a component body.**
 * `useTreeTableSelection` lists `identity` in the dependencies of its four `useMemo`s, so an
 * object rebuilt on every render invalidates all of them -- the visible rows, both navigation
 * indexes and the selectable rows are then recomputed on every keystroke anywhere in the page.
 * The planning table passes this very constant and therefore has no such cost; a table that
 * narrows it must hoist its own constant the same way.
 */
export const revisionNodeRowIdentity: TreeRowIdentity<RevisionTreeRow> = {
  uidOf: (row) => row.node_id,
  parentUidOf: (row) => row.parent_id,
  hasChildrenOf: (row) => row.hasChildren,
};

/**
 * Turns the nodes of a revision into rows, optionally keeping only some kinds.
 *
 * `kinds` is what lets one payload feed two tables: the planning table keeps `task` nodes only,
 * the devis grid keeps both. Filtering is safe for the order and the levels because the planning
 * layer is upward-closed (INV-14) -- a task's ancestors are tasks -- so dropping the cost nodes
 * removes leaves of the task tree and never re-parents anything. `hasChildren` is recomputed over
 * the rows actually kept: a task whose only children are cost lines has nothing to unfold *in the
 * planning table*, and showing a chevron there would open an empty branch.
 *
 * `row_number` and `level` are left exactly as the server computed them, over the **whole** tree:
 * they are the identifiers the user reads and the ones every other screen shows, so a filtered
 * view must not renumber them into a second, private numbering.
 */
export function buildRevisionTreeRows(
  nodes: readonly RevisionNode[],
  kinds?: readonly RevisionNodeKind[],
): RevisionTreeRow[] {
  const kept = kinds ? nodes.filter((node) => kinds.includes(node.kind)) : [...nodes];
  const parentsWithChildren = new Set<number>();
  const keptIds = new Set(kept.map((node) => node.node_id));
  for (const node of kept) {
    if (node.parent_id !== null && keptIds.has(node.parent_id)) {
      parentsWithChildren.add(node.parent_id);
    }
  }
  return kept.map((node) => ({ ...node, hasChildren: parentsWithChildren.has(node.node_id) }));
}

/** The least a row must carry to be ranked among its siblings the way the backend ranks it. */
type SiblingOrdered = { node_id: number; parent_id: number | null; position: number };

/** A node's 1-based rank among its siblings, and how many siblings that set holds. */
export type SiblingRank = { position: number; total: number };

/**
 * Groups rows by parent, each group ordered by `(position, node_id)` -- the exact order the
 * backend's `children_of()` produces.
 *
 * **The sibling set this answers is exactly the set of rows handed to it, and choosing that set
 * is the caller's whole decision.** The two consumers deliberately pass different ones, and
 * getting them the wrong way round is a defect in both directions:
 *
 * * deciding whether a move command is legal (`planningMoveAvailability`) passes the **complete**
 *   tree, every kind included, because that is the set the backend decides on: `children_of()`
 *   sorts tasks and cost nodes alike and INV-05 numbers `position` 1..n over all of them. A task
 *   may perfectly well carry both sub-tasks and cost lines, so a kind-filtered set yields ranks
 *   the server does not share -- and a command the toolbar believes legal comes back a 400;
 * * announcing a row's rank to assistive technology (`aria-posinset`/`aria-setsize`) passes the
 *   **rendered** rows, because both attributes must count in one and the same space: a row that
 *   is not rendered is not part of the set the user is being told about (#380).
 */
export function siblingsByParent<TRow extends SiblingOrdered>(
  rows: readonly TRow[],
): Map<number | null, TRow[]> {
  const groups = new Map<number | null, TRow[]>();
  for (const row of rows) {
    const group = groups.get(row.parent_id);
    if (group) {
      group.push(row);
    } else {
      groups.set(row.parent_id, [row]);
    }
  }
  for (const group of groups.values()) {
    group.sort((left, right) => left.position - right.position || left.node_id - right.node_id);
  }
  return groups;
}

/**
 * node_id -> its rank among the siblings **`rows` itself** exposes, for the rows of `rows` only.
 *
 * The ARIA half of `siblingsByParent` above: `position` and `total` are derived from one single
 * pass over one single set, which is what keeps `aria-posinset <= aria-setsize` true. Deriving
 * `posinset` from the stored `node.position` instead would mix two counting spaces and announce
 * "3 of 2" as soon as a cost node sits between two task rows the planning table renders.
 */
export function siblingRanks<TRow extends SiblingOrdered>(
  rows: readonly TRow[],
): Map<number, SiblingRank> {
  const ranks = new Map<number, SiblingRank>();
  for (const group of siblingsByParent(rows).values()) {
    group.forEach((row, index) => ranks.set(row.node_id, { position: index + 1, total: group.length }));
  }
  return ranks;
}

/**
 * node_id -> row_number, for every node of the tree (not just the rows one table kept).
 *
 * A predecessor link designates its predecessor by node id and never by a positional identifier,
 * so the "Prédécesseurs" column resolves it here to show the same number as the ID column. Built
 * from the full node list because a predecessor may well be collapsed, off-screen, or -- once the
 * devis grid shares this tree -- filtered out of the rows being rendered.
 */
export function rowNumberByNodeId(nodes: readonly RevisionNode[]): Map<number, number> {
  return new Map(nodes.map((node) => [node.node_id, node.row_number]));
}

/** A revision is editable only while it is a draft: INV-03 refuses every write on the others. */
export function isRevisionEditable(tree: RevisionTree | null): boolean {
  return tree?.status === "draft";
}
