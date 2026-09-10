import type { EstimateCostLine, EstimateTaskRow } from "@/lib/backend";

export type EstimateGridEntry =
  | { kind: "task"; taskRow: EstimateTaskRow }
  | { kind: "line"; line: EstimateCostLine; indentLevel: number }
  | { kind: "global-header" };

// Builds the Devis grid's row order (E12-04/#276, docs/devis-v0.1-specification.md's "Grille de
// devis" section):
//   1. this estimate's task rows, sorted by `position` (the planning's own depth-first order,
//      the same convention already used for EstimateTaskRow elsewhere in this codebase);
//   2. immediately under each task row, the EstimateCostLine rows attached to it
//      (`line.task_id === taskRow.task_id`), indented one level deeper than the task;
//   3. a trailing "lignes globales" section for every EstimateCostLine with no task attachment.
//
// A task row with `task_id: null` (a snapshot-only row with no MsTask twin, see EstimateTaskRow's
// own doc comment in lib/backend.ts) can never have a cost line attached to it, so it never gets
// an attached-lines section below it.
//
// A cost line whose `task_id` doesn't match any task row in this estimate -- which shouldn't
// happen in practice, since the "Tâche" selector only ever offers task rows from the same
// estimate (buildAttachableTaskOptions) -- falls back into the global section too, rather than
// silently disappearing from the grid.
export function buildEstimateGridEntries(
  costLines: EstimateCostLine[],
  estimateTaskRows: EstimateTaskRow[],
): EstimateGridEntry[] {
  const sortedTaskRows = [...estimateTaskRows].sort((a, b) => a.position - b.position);
  const attachableTaskIds = new Set(
    sortedTaskRows.filter((row) => row.task_id != null).map((row) => row.task_id as number),
  );

  const linesByTaskId = new Map<number, EstimateCostLine[]>();
  const globalLines: EstimateCostLine[] = [];
  for (const line of costLines) {
    if (line.task_id != null && attachableTaskIds.has(line.task_id)) {
      const existing = linesByTaskId.get(line.task_id);
      if (existing) {
        existing.push(line);
      } else {
        linesByTaskId.set(line.task_id, [line]);
      }
      continue;
    }
    globalLines.push(line);
  }

  const entries: EstimateGridEntry[] = [];
  for (const taskRow of sortedTaskRows) {
    entries.push({ kind: "task", taskRow });
    if (taskRow.task_id == null) {
      continue;
    }
    const attachedLines = linesByTaskId.get(taskRow.task_id) ?? [];
    for (const line of attachedLines) {
      entries.push({ kind: "line", line, indentLevel: (taskRow.outline_level ?? 0) + 1 });
    }
  }
  if (globalLines.length) {
    entries.push({ kind: "global-header" });
    for (const line of globalLines) {
      entries.push({ kind: "line", line, indentLevel: 0 });
    }
  }
  return entries;
}
