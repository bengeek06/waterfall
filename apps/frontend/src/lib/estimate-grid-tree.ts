import type { CostRate, EstimateCostLine, EstimateRoleAssignment, EstimateTaskRow, Task } from "@/lib/backend";
import { computeIndicativeLaborCost, resolveIndicativeHourlyRate, resolveRoleAssignmentYear } from "@/lib/estimate-role-assignment";

// E12-10/#292: replaces the old fixed task-grouping (lib/estimate-grid.ts's
// buildEstimateGridEntries) with a real tree, built directly from the merged tasks + grid-node
// tree the backend now exposes on every row (`row_number`/`uid`/`parent_uid`/`position`, E12-07/
// #289 + E12-08/#290 + E12-09/#291) -- see EstimateGridTreeTable for the component that
// renders it.
//
// Node identity is shared across kinds, exactly like the backend's own `EstimateGridNode.uid`
// convention (see `services/estimate_grid.py`'s module doc comment): a task node's "uid" in this
// merged tree is its `task_id` (an `MsTask.id`, not the same as `EstimateTaskRowRead.task_uid`,
// which is a different, project-scoped identifier this tree never uses), positive; a cost-line/
// role-assignment node's `uid` is its own `EstimateGridNode.uid`, always negative. A grid node's
// `parent_uid` is expressed in that same shared space (positive = a task, negative = another grid
// node, null/undefined = the devis root) -- reused as-is, never re-derived, as both this tree's
// own `parentUid` and (unchanged) the payload a caller sends to `POST .../grid-nodes/move`.
export type EstimateGridTaskRow = {
  kind: "task";
  uid: number | null;
  parentUid: number | null;
  rowNumber: number | null;
  depth: number;
  hasChildren: boolean;
  taskRow: EstimateTaskRow;
};

export type EstimateGridLineRow = {
  kind: "line";
  uid: number;
  parentUid: number | null;
  rowNumber: number;
  depth: number;
  hasChildren: boolean;
  line: EstimateCostLine;
};

export type EstimateGridLaborRow = {
  kind: "labor";
  uid: number;
  parentUid: number | null;
  rowNumber: number;
  depth: number;
  hasChildren: boolean;
  assignment: EstimateRoleAssignment;
};

export type EstimateGridTreeRow = EstimateGridTaskRow | EstimateGridLineRow | EstimateGridLaborRow;

type RawNode = {
  kind: EstimateGridTreeRow["kind"];
  uid: number | null;
  parentUid: number | null;
  rowNumber: number | null;
  sortKey: number;
  tieBreakId: number;
  taskRow?: EstimateTaskRow;
  line?: EstimateCostLine;
  assignment?: EstimateRoleAssignment;
};

// A task row with no `task_id` (a snapshot-only row with no `MsTask` twin, see EstimateTaskRow's
// own doc comment in lib/backend.ts) never gets a `row_number` from the backend either (it is
// skipped from the merged-tree ordering entirely, see `_load_estimate_grid_context` in
// api/routes/estimates.py) -- sorted after every properly ranked row, by its own stored
// `position`, so it stays visible (never silently dropped) instead of crashing the sort.
const UNRANKED_SORT_KEY = Number.MAX_SAFE_INTEGER;

function buildRawNodes(
  taskRows: EstimateTaskRow[],
  costLines: EstimateCostLine[],
  roleAssignments: EstimateRoleAssignment[],
): RawNode[] {
  const nodes: RawNode[] = [];
  for (const taskRow of taskRows) {
    nodes.push({
      kind: "task",
      uid: taskRow.task_id ?? null,
      parentUid: taskRow.parent_task_id ?? null,
      rowNumber: taskRow.row_number ?? null,
      sortKey: taskRow.row_number ?? UNRANKED_SORT_KEY + taskRow.position,
      tieBreakId: taskRow.id,
      taskRow,
    });
  }
  for (const line of costLines) {
    nodes.push({
      kind: "line",
      uid: line.uid,
      parentUid: line.parent_uid ?? null,
      rowNumber: line.row_number,
      sortKey: line.row_number,
      tieBreakId: line.id,
      line,
    });
  }
  for (const assignment of roleAssignments) {
    nodes.push({
      kind: "labor",
      uid: assignment.uid,
      parentUid: assignment.parent_uid ?? null,
      rowNumber: assignment.row_number,
      sortKey: assignment.row_number,
      tieBreakId: assignment.id,
      assignment,
    });
  }
  nodes.sort((left, right) => left.sortKey - right.sortKey || left.tieBreakId - right.tieBreakId);
  return nodes;
}

function toTreeRow(node: RawNode, parentUid: number | null, depth: number, hasChildren: boolean): EstimateGridTreeRow {
  if (node.kind === "task") {
    return { kind: "task", uid: node.uid, parentUid, rowNumber: node.rowNumber, depth, hasChildren, taskRow: node.taskRow! };
  }
  if (node.kind === "line") {
    return { kind: "line", uid: node.uid as number, parentUid, rowNumber: node.rowNumber as number, depth, hasChildren, line: node.line! };
  }
  return {
    kind: "labor",
    uid: node.uid as number,
    parentUid,
    rowNumber: node.rowNumber as number,
    depth,
    hasChildren,
    assignment: node.assignment!,
  };
}

// Builds the devis grid's full row list (E12-10/#292), sorted by the backend's own `row_number`
// -- already the correct depth-first document order, see this module's own doc comment -- with
// each row's `depth`/`hasChildren` derived from the shared `uid`/`parentUid` space. A row whose
// `parentUid` doesn't resolve to any other row of this same estimate (an orphan -- e.g. a task
// row with no `task_id`, or a role assignment/cost line left behind by a planning change) is
// treated as a root (`depth: 0`), the same graceful fallback the old fixed-grouping
// buildEstimateGridEntries already applied, rather than throwing or silently disappearing.
export function buildEstimateGridTreeRows(
  taskRows: EstimateTaskRow[],
  costLines: EstimateCostLine[],
  roleAssignments: EstimateRoleAssignment[],
): EstimateGridTreeRow[] {
  const raw = buildRawNodes(taskRows, costLines, roleAssignments);
  const byUid = new Map<number, RawNode>();
  for (const node of raw) {
    if (node.uid != null) {
      byUid.set(node.uid, node);
    }
  }

  function resolveParentUid(node: RawNode): number | null {
    return node.parentUid != null && byUid.has(node.parentUid) ? node.parentUid : null;
  }

  const childCount = new Map<number, number>();
  for (const node of raw) {
    const parentUid = resolveParentUid(node);
    if (parentUid != null) {
      childCount.set(parentUid, (childCount.get(parentUid) ?? 0) + 1);
    }
  }

  const depthByUid = new Map<number, number>();
  function computeDepth(node: RawNode, guard: Set<number>): number {
    if (node.uid != null && depthByUid.has(node.uid)) {
      return depthByUid.get(node.uid)!;
    }
    const parentUid = resolveParentUid(node);
    const depth = parentUid == null || guard.has(parentUid) ? 0 : computeDepth(byUid.get(parentUid)!, new Set(guard).add(parentUid)) + 1;
    if (node.uid != null) {
      depthByUid.set(node.uid, depth);
    }
    return depth;
  }

  return raw.map((node) => {
    const parentUid = resolveParentUid(node);
    const depth = computeDepth(node, new Set(node.uid != null ? [node.uid] : []));
    const hasChildren = node.uid != null && (childCount.get(node.uid) ?? 0) > 0;
    return toTreeRow(node, parentUid, depth, hasChildren);
  });
}

// Filters `rows` (already in depth-first document order, see buildEstimateGridTreeRows) down to
// the rows currently visible given `collapsedUids` -- a single forward pass works because a
// parent always precedes its own descendants in that order: once a collapsed row is seen, every
// following row whose `parentUid` chain passes through it is hidden too.
export function filterVisibleEstimateGridRows(
  rows: EstimateGridTreeRow[],
  collapsedUids: ReadonlySet<number>,
): EstimateGridTreeRow[] {
  const hiddenUids = new Set<number>();
  const visible: EstimateGridTreeRow[] = [];
  for (const row of rows) {
    if (row.parentUid != null && hiddenUids.has(row.parentUid)) {
      if (row.uid != null) {
        hiddenUids.add(row.uid);
      }
      continue;
    }
    visible.push(row);
    if (row.hasChildren && row.uid != null && collapsedUids.has(row.uid)) {
      hiddenUids.add(row.uid);
    }
  }
  return visible;
}

export type EstimateGridRowTotals = { quantity: number; hours: number; debours: number; pru: number };

// Sums Qté/Heures/Débours/PRU over every direct *and* indirect cost-line/role-assignment
// descendant of each summary row (`hasChildren: true`) in `rows` -- point 8 of E12-10/#292's own
// spec. Computed bottom-up (a task's own totals fold in its child tasks' already-computed totals)
// so a deeply nested task's totals never double-count a grandchild's costs, and so this stays
// O(rows) instead of re-walking each subtree from scratch for every ancestor.
//
// "PRU" mixes a non-labor line's `purchase_cost` (always present) with a labor row's *indicative*
// cost (`computeIndicativeLaborCost`, the same client-side preview already used for a single
// labor row's own PRU cell -- never a second calculation engine, see
// lib/estimate-role-assignment.ts's own doc comment). A labor row whose (cost category, year)
// has no configured `CostRate` contributes 0 to the sum rather than making the whole subtotal
// unresolvable: the same convention already applied to a single labor row's own PRU cell, which
// shows "—" instead of blocking on a missing rate.
export function computeEstimateGridRowTotals(
  rows: EstimateGridTreeRow[],
  costRates: CostRate[],
  planningTasks: Task[],
): Map<number, EstimateGridRowTotals> {
  const childrenByParentUid = new Map<number, EstimateGridTreeRow[]>();
  for (const row of rows) {
    if (row.parentUid != null) {
      const children = childrenByParentUid.get(row.parentUid) ?? [];
      children.push(row);
      childrenByParentUid.set(row.parentUid, children);
    }
  }

  const totals = new Map<number, EstimateGridRowTotals>();

  function computeForUid(uid: number): EstimateGridRowTotals {
    const cached = totals.get(uid);
    if (cached) {
      return cached;
    }
    let quantity = 0;
    let hours = 0;
    let debours = 0;
    let pru = 0;
    for (const child of childrenByParentUid.get(uid) ?? []) {
      if (child.kind === "line") {
        quantity += child.line.quantity;
        debours += child.line.unit_cost;
        pru += child.line.purchase_cost;
      } else if (child.kind === "labor") {
        quantity += child.assignment.quantity;
        hours += child.assignment.hours;
        const year = resolveRoleAssignmentYear(child.assignment.task_id, planningTasks);
        const hourlyRate = resolveIndicativeHourlyRate(child.assignment.cost_category_id, year, costRates);
        pru += computeIndicativeLaborCost(child.assignment, hourlyRate) ?? 0;
      } else if (child.uid != null) {
        const childTotals = computeForUid(child.uid);
        quantity += childTotals.quantity;
        hours += childTotals.hours;
        debours += childTotals.debours;
        pru += childTotals.pru;
      }
    }
    const result = { quantity, hours, debours, pru };
    totals.set(uid, result);
    return result;
  }

  for (const row of rows) {
    if (row.uid != null && row.hasChildren) {
      computeForUid(row.uid);
    }
  }
  return totals;
}
