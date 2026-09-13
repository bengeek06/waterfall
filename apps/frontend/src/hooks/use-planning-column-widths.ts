import { useTreeColumnWidths, type TreeColumnWidthsConfig } from "@/hooks/use-tree-column-widths";

export type PlanningColumnKey =
  | "uid"
  | "name"
  | "type"
  | "start"
  | "end"
  | "duration"
  | "mode"
  | "predecessors";

export type PlanningColumnWidths = Record<PlanningColumnKey, number>;

export const PLANNING_COLUMN_ORDER: PlanningColumnKey[] = [
  "uid",
  "name",
  "type",
  "start",
  "end",
  "duration",
  "mode",
  "predecessors",
];

export const PLANNING_COLUMN_WIDTHS_STORAGE_KEY = "waterfall:planning-tree-table:column-widths";

// Per-column floor, not a single shared constant: a couple of columns host content that cannot
// truncate/wrap cleanly (see Table's `whitespace-nowrap` default on TableCell) -- start/end show a
// fixed-format date, type shows a short but non-abbreviatable label, and mode hosts a `w-fit`
// Select trigger -- so their minimum must stay wide enough to avoid painting over the next column.
// Predecessors can shrink further than those because it truncates/wraps its content instead. Name
// also truncates its text, but its floor still ends up the highest of all: unlike the others, it
// has to additionally budget for a non-shrinking chevron plus tree indentation ahead of that text
// (see the dedicated comment below), which the shallower columns don't carry.
//
// `mode`'s floor is measured, not guessed, because its intrinsic content (the "sm" SelectTrigger
// in ui/select.tsx, `w-fit whitespace-nowrap`) cannot shrink below its own content width: 16px
// TableCell padding (p-2) + 2px trigger border + 18px trigger padding (pl-2.5 + pr-2) + 6px
// value/icon gap (gap-1.5) + 16px chevron icon (size-4) + ~78px for its longest option's label,
// "Automatique", at text-sm ≈ 136px, rounded up for safety.
//
// `name`'s floor also has to be measured rather than guessed, even though its text itself truncates
// cleanly: the cell also hosts a `shrink-0` expand/collapse chevron (`size-6` = 24px) plus a
// `gap-1` (4px) before that text, and the row's tree indentation (`row.depth * 1.25rem` = depth *
// 20px) sits in front of both. None of the chevron, the gap, or the indentation can shrink, so if
// the column narrows below their combined width the chevron itself gets clipped by the cell's
// `overflow-hidden` -- not just the text -- making the expand/collapse control invisible/unusable
// for deeply nested rows. Budget: 16px TableCell padding (p-2) + 24px chevron + 4px gap = 44px,
// plus indentation headroom up to a typical nesting depth of 4 (one level past the
// Lot > Sous-lot > Tâche > Sous-tâche example that originally exposed this) = 4 * 20px = 80px,
// plus a 40px margin so a few characters of the truncated name plus an ellipsis remain visible
// even at the floor. Total: 44 + 80 + 40 = 164.
//
// This floor is comfortable through that depth-4 example, not a hard guarantee for arbitrary
// nesting: the tree builder allows deeper nesting (a real MS Project import can exceed depth 4),
// and the row's indentation itself is intentionally left uncapped (see PlanningTreeTable's Name
// cell, `row.depth * 1.25rem`) so the visual nesting cue always reflects the actual hierarchy
// rather than flattening past some arbitrary depth. A tree nested deep enough can therefore still
// push the chevron/text past what this floor budgets for at the column's minimum width -- the
// expected fix at that point is for the user to widen the Name column with its resize handle
// (the very capability this hook exists to provide), not a lower ceiling on how deep the
// indentation is allowed to visually represent.

export const PLANNING_MIN_COLUMN_WIDTHS: PlanningColumnWidths = {
  uid: 60,
  name: 164,
  type: 90,
  start: 100,
  end: 100,
  duration: 80,
  mode: 140,
  predecessors: 90,
};

// Single shared ceiling: unlike the per-column minimum, every column's default width comfortably
// fits under one generous maximum, and there is no equivalent overflow risk on the wide end that
// would call for a narrower, column-specific cap.
export const PLANNING_MAX_COLUMN_WIDTH = 480;

export const DEFAULT_PLANNING_COLUMN_WIDTHS: PlanningColumnWidths = {
  uid: 64,
  name: 220,
  type: 96,
  start: 112,
  end: 112,
  duration: 88,
  mode: 150,
  predecessors: 240,
};

// E14-09 (#335): the planning table's own preset over the shared, table-agnostic
// useTreeColumnWidths (hooks/use-tree-column-widths.ts). The mechanism -- drag/keyboard resizing,
// clamping, localStorage persistence, hydration-safe snapshotting -- lives there and is available
// to any other tree table; only the column set, floors, defaults and storage key are planning's.
//
// Module-level (not rebuilt per render) because useTreeColumnWidths creates its store lazily from
// this object and reads it inside memoized callbacks.
export const PLANNING_COLUMN_WIDTHS_CONFIG: TreeColumnWidthsConfig<PlanningColumnKey> = {
  storageKey: PLANNING_COLUMN_WIDTHS_STORAGE_KEY,
  order: PLANNING_COLUMN_ORDER,
  defaults: DEFAULT_PLANNING_COLUMN_WIDTHS,
  minWidths: PLANNING_MIN_COLUMN_WIDTHS,
  maxWidth: PLANNING_MAX_COLUMN_WIDTH,
};

export function usePlanningColumnWidths() {
  return useTreeColumnWidths(PLANNING_COLUMN_WIDTHS_CONFIG);
}
