import { useTreeColumnWidths, type TreeColumnWidthsConfig } from "@/hooks/use-tree-column-widths";

export type EstimateColumnKey =
  | "rowNumber"
  | "label"
  | "type"
  | "dept1"
  | "dept2"
  | "role"
  | "quantity"
  | "hours"
  | "debours"
  | "hourlyRate"
  | "pru";

export const ESTIMATE_COLUMN_ORDER: EstimateColumnKey[] = [
  "rowNumber",
  "label",
  "type",
  "dept1",
  "dept2",
  "role",
  "quantity",
  "hours",
  "debours",
  "hourlyRate",
  "pru",
];

export const ESTIMATE_COLUMN_LABELS: Readonly<Record<EstimateColumnKey, string>> = {
  rowNumber: "Numéro",
  label: "Libellé",
  type: "Type",
  dept1: "Dpt 1er niveau",
  dept2: "Dpt 2eme niveau",
  role: "Rôle",
  quantity: "Qté",
  hours: "Heures",
  debours: "Débours",
  hourlyRate: "Taux horaire",
  pru: "PRU",
};

// Per-column floor, on the same reasoning as the planning preset's (see
// use-planning-column-widths.ts for the full rationale, which is not repeated here):
//
// * `label` is the widest floor of the set, because it is the only cell that also hosts a
//   non-shrinking `size-6` chevron, a `gap-1`, and the row's uncapped tree indentation ahead of
//   its `<Input>`;
// * `type`, `dept1`, `dept2` and `role` host `<select>` elements whose options are department and
//   role names -- they truncate, but below roughly this width the drop-down arrow eats the text
//   entirely. `type` is the widest of the four: it stacks the MO/non-MO select, the category
//   select or the derived-category line, and the pending-switch hint;
// * the four numeric columns host a `type="number"` `<Input>`, whose native spinner takes room on
//   top of the digits.
export const ESTIMATE_MIN_COLUMN_WIDTHS: Readonly<Record<EstimateColumnKey, number>> = {
  rowNumber: 60,
  label: 164,
  type: 150,
  dept1: 120,
  dept2: 120,
  role: 120,
  quantity: 90,
  hours: 90,
  debours: 90,
  hourlyRate: 100,
  pru: 100,
};

export const ESTIMATE_MAX_COLUMN_WIDTH = 480;

export const DEFAULT_ESTIMATE_COLUMN_WIDTHS: Readonly<Record<EstimateColumnKey, number>> = {
  rowNumber: 72,
  label: 260,
  type: 180,
  dept1: 150,
  dept2: 150,
  role: 150,
  quantity: 96,
  hours: 96,
  debours: 104,
  hourlyRate: 116,
  pru: 116,
};

// E14-11 (#337): the devis grid's own preset over the shared useTreeColumnWidths (#335) -- the
// capability #316 listed as a planning-only divergence, now available to the second table that
// shares the base. Module-level, never rebuilt per render: the hook creates its store lazily from
// this very object and reads it from memoized callbacks.
export const ESTIMATE_COLUMN_WIDTHS_CONFIG: TreeColumnWidthsConfig<EstimateColumnKey> = {
  storageKey: "waterfall:estimate-grid-tree-table:column-widths",
  order: ESTIMATE_COLUMN_ORDER,
  defaults: DEFAULT_ESTIMATE_COLUMN_WIDTHS,
  minWidths: ESTIMATE_MIN_COLUMN_WIDTHS,
  maxWidth: ESTIMATE_MAX_COLUMN_WIDTH,
};

export function useEstimateColumnWidths() {
  return useTreeColumnWidths(ESTIMATE_COLUMN_WIDTHS_CONFIG);
}
