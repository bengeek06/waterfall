import type { EstimateCostLine, EstimateRoleAssignment, EstimateTaskRow } from "@/lib/backend";

export type EstimateGridEntry =
  | { kind: "task"; taskRow: EstimateTaskRow }
  | { kind: "labor"; assignment: EstimateRoleAssignment; indentLevel: number }
  | { kind: "line"; line: EstimateCostLine; indentLevel: number }
  | { kind: "global-header" };

// Groups `items` by their (non-null) `task_id`, in encounter order within each group -- shared
// by the cost-line and role-assignment grouping below, both of which need the exact same
// "bucket by task_id" shape.
function groupByTaskId<T extends { task_id?: number | null }>(items: T[]): Map<number, T[]> {
  const byTaskId = new Map<number, T[]>();
  for (const item of items) {
    if (item.task_id == null) {
      continue;
    }
    const existing = byTaskId.get(item.task_id);
    if (existing) {
      existing.push(item);
    } else {
      byTaskId.set(item.task_id, [item]);
    }
  }
  return byTaskId;
}

// Splits `costLines` into those attached to one of `attachableTaskIds` (grouped by task_id) and
// the rest (a line with no task_id, or one whose task_id doesn't match any task row of this
// estimate -- in practice unreachable, since the "Tâche" selector only ever offers task rows from
// the same estimate, see buildAttachableTaskOptions -- falls back here too, rather than silently
// disappearing from the grid).
function splitCostLinesByAttachment(
  costLines: EstimateCostLine[],
  attachableTaskIds: Set<number>,
): { linesByTaskId: Map<number, EstimateCostLine[]>; globalLines: EstimateCostLine[] } {
  const attached = costLines.filter((line) => line.task_id != null && attachableTaskIds.has(line.task_id));
  const globalLines = costLines.filter((line) => !(line.task_id != null && attachableTaskIds.has(line.task_id)));
  return { linesByTaskId: groupByTaskId(attached), globalLines };
}

// Builds the Devis grid's row order (E12-04/#276, E12-06/#278, docs/devis-v0.1-specification.md's
// "Grille de devis" section):
//   1. this estimate's task rows, sorted by `position` (the planning's own depth-first order,
//      the same convention already used for EstimateTaskRow elsewhere in this codebase);
//   2. immediately under each task row, its EstimateRoleAssignment ("labor") rows, then its
//      EstimateCostLine ("non-labor") rows attached to it, both indented one level deeper than
//      the task -- labor is listed first as a deliberate (not spec-mandated) choice: it is the
//      base cost most devis build up from, with purchased-supply lines layered on top;
//   3. a trailing "lignes globales" section for every EstimateCostLine with no task attachment.
//      An EstimateRoleAssignment is created directly against an MsTask.id in every flow the
//      current UI exposes (see EstimateRoleAssignmentCreate) and so, in practice, always carries a
//      task_id today -- there is no UI yet to create or move a labor line to the estimate's root
//      (that lands with E12-10/#292). However, an assignment whose task_id doesn't match any
//      EstimateTaskRow of *this* estimate version (an orphan, e.g. left behind by a planning
//      change that removed/replaced the task after the assignment was created -- a data-integrity
//      edge case, not something reachable from the current UI) must still be rendered somewhere:
//      silently dropping an MO row from the grid would hide real cost. Rather than invent a
//      separate section for what should be a rare case, these orphans are folded into this same
//      "Lignes globales" section (Haute finding #2/E12-06/#278) -- they're visually indistinguishable
//      from a global cost line there (same header, indentLevel 0), which is an acceptable tradeoff
//      given how narrow the case is.
//
//      E12-07/#289: the backend's EstimateRoleAssignmentRead.task_id is now nullable (a "root"
//      labor line with no attached task). The same orphan fallback above already applies here: a
//      null task_id is treated exactly like an unmatched one and folded into "Lignes globales",
//      rather than silently vanishing from the grid. This is not new product behavior -- it's the
//      pre-existing orphan-fallback code path, just triggered by one more condition -- so it still
//      renders with the same generic labor-row markup as any other row, ahead of E12-10's own
//      dedicated "root" UI.
//
// A task row with `task_id: null` (a snapshot-only row with no MsTask twin, see EstimateTaskRow's
// own doc comment in lib/backend.ts) can never have a cost line or a role assignment attached to
// it, so it never gets an attached-rows section below it.
export function buildEstimateGridEntries(
  costLines: EstimateCostLine[],
  estimateTaskRows: EstimateTaskRow[],
  estimateRoleAssignments: EstimateRoleAssignment[] = [],
): EstimateGridEntry[] {
  const sortedTaskRows = [...estimateTaskRows].sort((a, b) => a.position - b.position);
  const attachableTaskIds = new Set(
    sortedTaskRows.filter((row) => row.task_id != null).map((row) => row.task_id as number),
  );
  const { linesByTaskId, globalLines } = splitCostLinesByAttachment(costLines, attachableTaskIds);
  const assignmentsByTaskId = groupByTaskId(estimateRoleAssignments);

  const entries: EstimateGridEntry[] = [];
  for (const taskRow of sortedTaskRows) {
    entries.push({ kind: "task", taskRow });
    if (taskRow.task_id == null) {
      continue;
    }
    const indentLevel = (taskRow.outline_level ?? 0) + 1;
    for (const assignment of assignmentsByTaskId.get(taskRow.task_id) ?? []) {
      entries.push({ kind: "labor", assignment, indentLevel });
    }
    // Consumed as we go so that whatever is left in the map once every task row has been visited
    // is, by construction, an orphan (task_id matching no task row of this estimate) -- see below.
    assignmentsByTaskId.delete(taskRow.task_id);
    for (const line of linesByTaskId.get(taskRow.task_id) ?? []) {
      entries.push({ kind: "line", line, indentLevel });
    }
  }
  // A root assignment (task_id: null, E12-07/#289) was never inserted into assignmentsByTaskId
  // (groupByTaskId skips null keys) and so can't be consumed by the task-row loop above -- fold it
  // into the same orphan fallback rather than dropping it.
  const rootAssignments = estimateRoleAssignments.filter((assignment) => assignment.task_id == null);
  const orphanAssignments = [...rootAssignments, ...[...assignmentsByTaskId.values()].flat()];
  if (globalLines.length || orphanAssignments.length) {
    entries.push({ kind: "global-header" });
    for (const assignment of orphanAssignments) {
      entries.push({ kind: "labor", assignment, indentLevel: 0 });
    }
    for (const line of globalLines) {
      entries.push({ kind: "line", line, indentLevel: 0 });
    }
  }
  return entries;
}
