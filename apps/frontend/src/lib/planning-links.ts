import type { MspdiLagFormat, RevisionPredecessor, RevisionPredecessorWrite } from "./backend";
import { formatCalendarDuration, type ProjectCalendar } from "./planning-calendar";

// Pure predecessor-link domain helpers extracted from planning-tree-table.tsx (E4-12 / #152):
// shared by the tree table's own "Prédécesseurs" column and the use-planning-task-links hook /
// planning-task-links-dialog component.

// MS Project standard predecessor link type codes, as `wf_revision_node_link.link_type` constrains
// them (E14-10 / #336: the link now designates a node, never an uid).
export const LINK_TYPE_LABELS: Record<number, string> = { 0: "FF", 1: "FS", 2: "SF", 3: "SS" };
export const LINK_TYPE_OPTIONS = Object.entries(LINK_TYPE_LABELS).map(
  ([value, label]) => [Number(value), label] as const,
);

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

// Local editing state for one row of the predecessor links dialog; converted to a
// RevisionPredecessorWrite on submit.
export type LinkRowDraft = {
  rowId: string;
  predecessorNodeId: number | null;
  linkType: number;
  lagMinutes: string;
  // Preserved from the loaded link's lag_format (7=working-time day, 8/null=elapsed) so
  // editing one row of a task's links does not silently rewrite the lag semantics of every
  // link on that task. Only defaulted to 7 for a brand-new row, which has no prior value.
  lagFormat: MspdiLagFormat | null;
};

let nextLinkRowId = 0;
export function createLinkRowDraft(link?: RevisionPredecessor): LinkRowDraft {
  nextLinkRowId += 1;
  return {
    rowId: `link-row-${nextLinkRowId}`,
    predecessorNodeId: link?.predecessor_node_id ?? null,
    linkType: link?.link_type ?? 1,
    lagMinutes: link?.lag_tenth_minute ? String(link.lag_tenth_minute / 10) : "",
    lagFormat: link ? normalizeLagFormat(link.lag_format) : 7,
  };
}

/** Turns a dialog row back into the write shape, once its predecessor has actually been picked. */
export function linkRowToPredecessorWrite(row: LinkRowDraft): RevisionPredecessorWrite | null {
  if (row.predecessorNodeId === null) {
    return null;
  }
  const lagMinutes = row.lagMinutes.trim() === "" ? 0 : Number(row.lagMinutes);
  if (!Number.isFinite(lagMinutes)) {
    return null;
  }
  return {
    predecessor_node_id: row.predecessorNodeId,
    link_type: row.linkType,
    // The wire unit is the tenth of a minute (a 6-second resolution the MSPDI format carries);
    // the field edits plain minutes, which is what a user types.
    lag_tenth_minute: Math.round(lagMinutes * 10),
    lag_format: row.lagFormat,
  };
}

// `rowNumberByNodeId` resolves each link's technical `predecessor_node_id` (a stable identifier,
// never shown to the user) to the predecessor's current positional `row_number` (E9): the only
// identifier the "Prédécesseurs" column may display. Built once by the caller from the whole tree
// (see lib/revision-tree.ts), not recomputed per link/row. A missing entry should never happen in
// practice, but falls back to "?" rather than showing the technical id or throwing.
export function predecessorsLabel(
  predecessors: readonly RevisionPredecessor[],
  calendar: ProjectCalendar,
  rowNumberByNodeId: Map<number, number>,
): string {
  if (!predecessors.length) {
    return "-";
  }
  return predecessors
    .map((link) => {
      const type = LINK_TYPE_LABELS[link.link_type] ?? String(link.link_type);
      const lagMinutes = link.lag_tenth_minute ? link.lag_tenth_minute / 10 : 0;
      // The sign is applied around the calendar-formatted absolute value, mirroring the
      // pre-#142 lagSign/lagMinutes split: formatCalendarDuration itself only ever formats a
      // non-negative duration (see its own doc comment).
      const lagSign = lagMinutes > 0 ? "+" : lagMinutes < 0 ? "-" : "";
      const lag = lagMinutes ? ` ${lagSign}${formatCalendarDuration(Math.abs(lagMinutes), calendar)}` : "";
      const rowNumber = rowNumberByNodeId.get(link.predecessor_node_id) ?? "?";
      return `${rowNumber} (${type}${lag})`;
    })
    .join(", ");
}
