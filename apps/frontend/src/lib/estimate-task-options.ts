import type { EstimateTaskRow } from "@/lib/backend";

export type EstimateTaskOption = { value: string; label: string };

// Builds the "Tâche" <select> options shared by cost-line-form.tsx (create) and
// cost-lines-table.tsx (inline edit) (E12-04/#276): only EstimateTaskRow entries carrying a
// non-null `task_id` can receive a cost line -- a snapshot-only row with no MsTask twin can't,
// see EstimateTaskRow's own doc comment in lib/backend.ts -- sorted by `position` (the
// planning's own depth-first order, the same convention already used for EstimateTaskRow
// elsewhere in this codebase) and indented per `outline_level` so the hierarchy stays legible in
// a flat `<select>`, same `"  ".repeat(depth)` prefix convention already used by
// organization-tree.tsx's own parent-node selector.
export function buildAttachableTaskOptions(estimateTaskRows: EstimateTaskRow[]): EstimateTaskOption[] {
  return estimateTaskRows
    .filter((row) => row.task_id != null)
    .sort((a, b) => a.position - b.position)
    .map((row) => ({
      value: String(row.task_id),
      label: `${"  ".repeat(row.outline_level ?? 0)}${row.task_name}`,
    }));
}
