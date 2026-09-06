import type { Task, TaskLinkWrite } from "./backend";

// Pure predecessor-link domain helpers extracted from planning-tree-table.tsx (E4-12 / #152):
// shared by the tree table's own "Prédécesseurs" column and the use-planning-task-links hook /
// planning-task-links-dialog component.

// MS Project standard predecessor link type codes (see wf_planning_link_snapshot check constraint).
export const LINK_TYPE_LABELS: Record<number, string> = { 0: "FF", 1: "FS", 2: "SF", 3: "SS" };
export const LINK_TYPE_OPTIONS = Object.entries(LINK_TYPE_LABELS).map(
  ([value, label]) => [Number(value), label] as const,
);

export type MspdiLagFormat = NonNullable<TaskLinkWrite["lag_format"]>;
const MSPDI_LAG_FORMATS: ReadonlySet<number> = new Set([
  3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 19, 20, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 51, 52,
]);
// A value outside the known MSPDI LagFormat codes falls back to null (elapsed), matching the
// backend's own "an absent LagFormat is treated as elapsed" convention (see
// waterfall.services.planning_tree._is_elapsed_lag_format) instead of forcing an unrecognized
// legacy/foreign value into the write contract's stricter literal type.
export function normalizeLagFormat(value: number | null | undefined): MspdiLagFormat | null {
  return value !== null && value !== undefined && MSPDI_LAG_FORMATS.has(value)
    ? (value as MspdiLagFormat)
    : null;
}

// Local editing state for one row of the predecessor links dialog; converted to a TaskLinkWrite on submit.
export type LinkRowDraft = {
  rowId: string;
  predecessorUid: number | null;
  linkType: number;
  lagMinutes: string;
  // Preserved from the loaded link's lag_format (7=working-time day, 8/null=elapsed) so
  // editing one row of a task's links does not silently rewrite the lag semantics of every
  // link on that task. Only defaulted to 7 for a brand-new row, which has no prior value.
  lagFormat: MspdiLagFormat | null;
};

let nextLinkRowId = 0;
export function createLinkRowDraft(link?: {
  predecessor_uid: number;
  link_type: number;
  lag_tenth_minute?: number | null;
  lag_format?: number | null;
}): LinkRowDraft {
  nextLinkRowId += 1;
  return {
    rowId: `link-row-${nextLinkRowId}`,
    predecessorUid: link?.predecessor_uid ?? null,
    linkType: link?.link_type ?? 1,
    lagMinutes: link?.lag_tenth_minute ? String(link.lag_tenth_minute / 10) : "",
    lagFormat: link ? normalizeLagFormat(link.lag_format) : 7,
  };
}

export function predecessorsLabel(task: Task): string {
  if (!task.predecessor_links?.length) {
    return "-";
  }
  return task.predecessor_links
    .map((link) => {
      const type = LINK_TYPE_LABELS[link.link_type] ?? String(link.link_type);
      const lagMinutes = link.lag_tenth_minute ? link.lag_tenth_minute / 10 : 0;
      const lagSign = lagMinutes > 0 ? "+" : "";
      const lag = lagMinutes ? ` ${lagSign}${lagMinutes}min` : "";
      return `${link.predecessor_uid} (${type}${lag})`;
    })
    .join(", ");
}
