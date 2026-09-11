import type { EstimateGridTreeRow } from "@/lib/estimate-grid-tree";

export type EstimateGridMoveCommand = {
  node_uids: number[];
  target_parent_uid: number | null;
  position: number;
};

// E12-10/#292: only cost-line/role-assignment ("grid node") rows are reorderable from this
// toolbar -- task ordering stays out of scope for this EPIC (dictated by the Planning, see
// PlanningTreeTable's own move actions instead). Mirrors lib/planning-tree.ts's own
// computeIndentCommand/computeOutdentCommand/computeReorderCommand, scoped to grid nodes: sibling
// order/local position is always read from each grid node's own `position` field (matching the
// backend's `move_estimate_grid_nodes`, whose `siblings_by_parent` is built purely from
// `EstimateGridNode` rows -- a task's own `position`/`EstimateTaskRow.position` numbering is a
// different, unrelated counter and never participates in this ordering, see
// services/estimate_grid.py's module doc comment).
function gridNodePosition(row: EstimateGridTreeRow): number {
  if (row.kind === "line") {
    return row.line.position;
  }
  if (row.kind === "labor") {
    return row.assignment.position;
  }
  return 0;
}

function buildUidIndex(rows: EstimateGridTreeRow[]): Map<number, EstimateGridTreeRow> {
  const byUid = new Map<number, EstimateGridTreeRow>();
  for (const row of rows) {
    if (row.uid != null) {
      byUid.set(row.uid, row);
    }
  }
  return byUid;
}

function hasSelectedAncestor(
  row: EstimateGridTreeRow,
  byUid: Map<number, EstimateGridTreeRow>,
  selectedUids: ReadonlySet<number>,
): boolean {
  let parentUid = row.parentUid;
  while (parentUid != null) {
    if (selectedUids.has(parentUid)) {
      return true;
    }
    parentUid = byUid.get(parentUid)?.parentUid ?? null;
  }
  return false;
}

// Normalizes a selection to its top-level roots (a descendant is dropped when an ancestor is
// also selected, since it moves implicitly with it) -- mirrors
// lib/planning-tree.ts's normalizeSelectionToRoots. `rows` is already in depth-first document
// order (row_number), so a plain filter preserves that same order for the roots -- no separate
// re-traversal needed, unlike the planning-tree.ts original (which orders a plain Task[], not
// already row_number-sorted).
export function normalizeGridSelectionToRoots(
  rows: EstimateGridTreeRow[],
  selectedUids: ReadonlySet<number>,
): EstimateGridTreeRow[] {
  const byUid = buildUidIndex(rows);
  return rows.filter(
    (row) => row.uid != null && selectedUids.has(row.uid) && !hasSelectedAncestor(row, byUid, selectedUids),
  );
}

// Indent: nests the selected root(s) as the last grid-node child of the row immediately above
// the first selected root, in the full (row_number-ordered) row list -- that preceding row may be
// a task (attaching the selection to it, uid = its positive task_id) or another grid node,
// matching `target_parent_uid`'s own "positive = task, negative = grid node" convention as-is.
// Deliberately "the row immediately above" rather than planning-tree.ts's own "the previous
// same-parent sibling": a devis grid node's siblings, per the backend's own model, are always
// other grid nodes (never a task), so a same-parent-sibling rule could never target a task at
// all -- yet attaching a cost line/labor row to a task is a normal, expected outcome of indenting
// it under that task's row.
export function computeGridIndentCommand(
  rows: EstimateGridTreeRow[],
  selectedUids: ReadonlySet<number>,
): EstimateGridMoveCommand | null {
  const roots = normalizeGridSelectionToRoots(rows, selectedUids);
  if (!roots.length) {
    return null;
  }
  const firstIndex = rows.findIndex((row) => row.uid === roots[0].uid && row.kind === roots[0].kind);
  const previous = firstIndex > 0 ? rows[firstIndex - 1] : null;
  if (!previous || previous.uid == null) {
    return null;
  }
  const rootUids = new Set(roots.map((root) => root.uid));
  if (rootUids.has(previous.uid)) {
    return null;
  }
  const existingChildren = rows.filter(
    (row) => row.kind !== "task" && row.parentUid === previous.uid && !rootUids.has(row.uid),
  ).length;
  return { node_uids: roots.map((root) => root.uid as number), target_parent_uid: previous.uid, position: existingChildren + 1 };
}

// Outdent: moves the selected root(s) out from under their current parent, appended as the last
// grid-node child of that parent's own parent ("grandparent") -- null/root if there is none.
// Always appended at the end (not spliced back in "right after the former parent", unlike
// planning-tree.ts's own computeOutdentCommand): the former parent may itself be a task, which
// never participates in the grid-node-only `position` counter at all (see gridNodePosition's own
// doc comment), so "right after it" has no well-defined index to compute -- appending at the end
// is an unambiguous, always-valid fallback the user can still fine-tune with Monter/Descendre.
export function computeGridOutdentCommand(
  rows: EstimateGridTreeRow[],
  selectedUids: ReadonlySet<number>,
): EstimateGridMoveCommand | null {
  const roots = normalizeGridSelectionToRoots(rows, selectedUids);
  if (!roots.length) {
    return null;
  }
  const first = roots[0];
  if (first.parentUid == null) {
    return null;
  }
  const byUid = buildUidIndex(rows);
  const parent = byUid.get(first.parentUid);
  const grandParentUid = parent?.parentUid ?? null;
  const rootUids = new Set(roots.map((root) => root.uid));
  const existingChildren = rows.filter(
    (row) => row.kind !== "task" && row.parentUid === grandParentUid && !rootUids.has(row.uid),
  ).length;
  return { node_uids: roots.map((root) => root.uid as number), target_parent_uid: grandParentUid, position: existingChildren + 1 };
}

// Monter/Descendre: reorders a contiguous block of selected roots one slot up/down among its own
// grid-node siblings (same parent_uid) -- mirrors lib/planning-tree.ts's own
// computeReorderCommand, scoped to grid nodes and using each node's own `position` field (see
// gridNodePosition) for sibling order instead of row_number (which also ranks task siblings that
// never participate in this grid-node-only ordering).
export function computeGridReorderCommand(
  rows: EstimateGridTreeRow[],
  selectedUids: ReadonlySet<number>,
  direction: "up" | "down",
): EstimateGridMoveCommand | null {
  const roots = normalizeGridSelectionToRoots(rows, selectedUids);
  if (!roots.length) {
    return null;
  }
  const parentUid = roots[0].parentUid;
  if (roots.some((root) => root.parentUid !== parentUid)) {
    return null;
  }
  const siblings = rows
    .filter((row) => row.kind !== "task" && row.parentUid === parentUid)
    .sort((left, right) => gridNodePosition(left) - gridNodePosition(right));
  const rootUids = new Set(roots.map((root) => root.uid));
  const indices = siblings
    .map((sibling, index) => (rootUids.has(sibling.uid) ? index : -1))
    .filter((index) => index >= 0);
  const minIndex = Math.min(...indices);
  const maxIndex = Math.max(...indices);
  if (maxIndex - minIndex + 1 !== indices.length) {
    return null;
  }
  const remaining = siblings.filter((sibling) => !rootUids.has(sibling.uid));

  if (direction === "up") {
    const anchorBefore = siblings[minIndex - 1];
    if (!anchorBefore) {
      return null;
    }
    const anchorIndex = remaining.findIndex((sibling) => sibling.uid === anchorBefore.uid);
    return { node_uids: roots.map((root) => root.uid as number), target_parent_uid: parentUid, position: anchorIndex + 1 };
  }

  const anchorAfter = siblings[maxIndex + 1];
  if (!anchorAfter) {
    return null;
  }
  const anchorIndex = remaining.findIndex((sibling) => sibling.uid === anchorAfter.uid);
  return { node_uids: roots.map((root) => root.uid as number), target_parent_uid: parentUid, position: anchorIndex + 2 };
}
