import type {
  CostCategory,
  CostRate,
  ResourceNode,
  ResourceRole,
  RevisionCostFacet,
  RevisionNode,
} from "./backend";
import { resolveIndicativeHourlyRate } from "./estimate-role-assignment";
import type { RevisionTreeRow } from "./revision-tree";

// E14-11 (#337): everything the devis grid *derives* from a revision node, and nothing it renders.
//
// The grid shows one tree -- tasks and cost lines are nodes of the same tree, not two lists glued
// back together by a negative uid -- so its rows are `buildRevisionTreeRows(nodes)` called with no
// kind filter at all, and its identity for the shared editable-tree base is
// `revisionNodeRowIdentity` **as is**: unlike the planning table, this grid selects every kind of
// row, because moving a task from the devis is the same operation as moving it from the planning.
//
// What is left here is the derivation the cost facet does not store, and INV-19 is the reason
// there is any: an MO line carries a role and no accounting category, so its category is worked
// out from the role every time it is displayed and is never written back (see
// `derivedCostCategory`). The same goes for its Dpt 1er/2eme niveau columns, which are the role's
// two topmost ancestors in the resource tree, and for its hourly rate, which is the rate of the
// role's category for the year the engine spreads its hours over (see `rowRateYear`).

/** A row of the devis grid: any node of the revision, whatever facet it carries. */
export type RevisionCostGridRow = RevisionTreeRow;

/** A cost row, i.e. one whose cost facet is therefore never null. */
export type RevisionCostRow = RevisionTreeRow & { cost: RevisionCostFacet };

export function isCostRow(row: RevisionCostGridRow): row is RevisionCostRow {
  return row.kind === "cost" && row.cost !== null;
}

/**
 * Parses a decimal the API serialises as a string (`quantity`, `hours`, `unit_cost`).
 *
 * Returns 0 for anything unparseable rather than letting a single `NaN` poison a whole column of
 * subtotals -- the same guard `describeCostLosses` applies to an import's amounts.
 */
export function costNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined) {
    return 0;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * The two topmost ancestors of the resource node a role hangs on, as the grid's "Dpt 1er niveau"
 * and "Dpt 2eme niveau" columns show them.
 *
 * Lifted verbatim from the grid it used to be buried in, cycle guard included: an organisation
 * tree read through a stale referential can name a parent that is also a descendant, and walking
 * it without a `seen` set hangs the render.
 */
export function resolveDeptColumns(
  nodeId: number | null | undefined,
  nodes: readonly ResourceNode[],
): [string, string] {
  if (nodeId == null) {
    return ["-", "-"];
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const segments: string[] = [];
  const seen = new Set<number>();
  let current = byId.get(nodeId);
  while (current && !seen.has(current.id)) {
    segments.unshift(current.name);
    seen.add(current.id);
    current = current.parent_id != null ? byId.get(current.parent_id) : undefined;
  }
  return [segments[0] ?? "-", segments[1] ?? "-"];
}

// --------------------------------------------------------------------------------------------
// The Dpt 1er niveau -> Dpt 2eme niveau -> Rôle cascade (#315)
//
// Lifted from estimate-role-assignment-dialog.tsx, which is where it was livré and where it was
// of no use: #292 specified it for the *grid*'s cells and #315 recorded that only the dialog ever
// got it. The rule itself is unchanged -- a Dpt 1er niveau is a root of the resource tree, a Dpt
// 2eme niveau is one of its direct children, a role hangs on a Dpt 2eme niveau.
// --------------------------------------------------------------------------------------------

/** The roots of the resource tree: the "Dpt 1er niveau" options. */
export function dept1Options(nodes: readonly ResourceNode[]): ResourceNode[] {
  return nodes.filter((node) => node.parent_id == null);
}

/** The direct children of `dept1Id`: the "Dpt 2eme niveau" options. Empty until one is chosen. */
export function dept2Options(nodes: readonly ResourceNode[], dept1Id: string): ResourceNode[] {
  return dept1Id ? nodes.filter((node) => String(node.parent_id) === dept1Id) : [];
}

/**
 * The roles attached to `dept2Id`.
 *
 * Filtered client-side out of the complete referential the page already loads, rather than re-read
 * per node the way the dialog did: the grid can have a cascade open on any row, and one request
 * per dept selection would make an inline edit wait on the network before its next `<select>`
 * could even be populated.
 */
export function roleOptions(roles: readonly ResourceRole[], dept2Id: string): ResourceRole[] {
  return dept2Id ? roles.filter((role) => String(role.node_id) === dept2Id) : [];
}

/** Where a row's cascade selects sit, as `<select>` values ("" = nothing chosen). */
export type RoleCascadeSelection = { dept1Id: string; dept2Id: string; roleId: string };

export const EMPTY_ROLE_CASCADE: RoleCascadeSelection = { dept1Id: "", dept2Id: "", roleId: "" };

/**
 * The cascade a labour row *already* sits on, read back from its `role_id`.
 *
 * This is what makes the three selects show the row's current department and role instead of
 * opening empty -- the difference between "changer le rôle d'une ligne MO existante" (impossible
 * before #315) and re-entering the whole path from scratch.
 */
export function roleCascadeOf(
  roleId: number | null | undefined,
  roles: readonly ResourceRole[],
  nodes: readonly ResourceNode[],
): RoleCascadeSelection {
  if (roleId == null) {
    return EMPTY_ROLE_CASCADE;
  }
  const role = roles.find((candidate) => candidate.id === roleId);
  if (!role) {
    return EMPTY_ROLE_CASCADE;
  }
  const dept2 = nodes.find((node) => node.id === role.node_id);
  return {
    dept1Id: dept2?.parent_id != null ? String(dept2.parent_id) : "",
    dept2Id: String(role.node_id),
    roleId: String(role.id),
  };
}

/**
 * The accounting category an MO line is charged to: **the category of its role**, derived here and
 * never stored on the facet.
 *
 * INV-19 forbids a labour facet from carrying a `cost_category_id` at all, so "le choix du rôle
 * renseigne la catégorie comptable" is honoured by reading it back from the role at display time.
 * Any attempt to write it would be refused by `check_cost_facet_shape`, creation included.
 */
export function derivedCostCategory(
  roleId: number | null | undefined,
  roles: readonly ResourceRole[],
  categories: readonly CostCategory[],
): CostCategory | null {
  if (roleId == null) {
    return null;
  }
  const role = roles.find((candidate) => candidate.id === roleId);
  if (!role) {
    return null;
  }
  return categories.find((category) => category.id === role.cost_category_id) ?? null;
}

/** How a category is named in a cell: its name, or its accounting code when it has no name. */
export function costCategoryLabel(category: CostCategory | null): string {
  if (!category) {
    return "-";
  }
  return category.name ?? category.accounting_code;
}

/**
 * The accounting category a row is charged to, MO or not: derived from the role for a labour
 * line, read off the facet for a disbursement.
 */
export function rowCostCategory(
  row: RevisionCostRow,
  roles: readonly ResourceRole[],
  categories: readonly CostCategory[],
): CostCategory | null {
  if (row.cost.nature === "labor") {
    return derivedCostCategory(row.cost.role_id, roles, categories);
  }
  return categories.find((category) => category.id === row.cost.cost_category_id) ?? null;
}

/**
 * The calendar year of an ISO timestamp the API serialises as a string, or null when there is none
 * to read. UTC, like every date this model stores.
 */
function isoYear(value: string | null | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.getUTCFullYear();
}

/**
 * The calendar year a row's indicative hourly rate is read at, or **null when the engine spreads
 * its hours over no year at all**.
 *
 * A mirror of the revision engine's `_bearing_years`
 * (`apps/backend/src/waterfall/services/estimate_calculation.py`), case for case:
 *
 * * **no bearing task -> the current year.** A cost line at the root is INV-01's project-wide
 *   global cost, and the engine gives it one line at `datetime.now(UTC).year`, "never dropped from
 *   a total" -- backend test `test_a_cost_facet_at_the_root_counts_towards_the_total`, where a
 *   root MO line is worth 1 000 € and enters `total_unburdened_cost`. It is also criterion 5 of
 *   #337: a line outdented up to the root stays counted. Answering null here would print "—" in
 *   Taux horaire and in PRU for a line the "Total MO" above nonetheless includes, and would count
 *   it as 0 in its ancestor's subtotal;
 * * **a bearing task missing `start_at` or `finish_at` -> null.** The engine answers `None` for a
 *   half-dated task exactly as for a fully undated one, and a facet it answers `None` for enters
 *   no total. Half-dated is a reachable state, not a theoretical one: `buildManualPayload` can
 *   send `finish_at: null`, and an MSPDI import can produce it;
 * * **a bearing task whose finish year precedes its start year -> null**, the engine's empty
 *   `range(...)`, which nothing on the write side forbids today;
 * * **a dated bearing task -> the year it starts.**
 *
 * Only the *classification* is mirrored, never the arithmetic. The engine spreads a multi-year
 * task's hours over every year it touches and applies inflation; this column is an indicative
 * single-rate preview and deliberately keeps the first year alone (see `rowHourlyRate`). What must
 * not diverge is **which** lines carry a figure at all, because the grid and the "Lignes non
 * valorisables" panel right above it are read as one screen: a line named there and priced here --
 * or counted in a total here and blank -- makes the two halves contradict each other on a sum in
 * euros.
 *
 * The bearing task is resolved on read by the backend (`bearing_task_node_id`) and stored in no
 * column, so a line moved under another task changes year with nothing else to update -- which is
 * what makes a move from the devis grid visible in the planning at once.
 *
 * No branch falls back on the line's own `planned_date`. That is a correction rather than a
 * simplification: the comment this derivation inherited from `estimate-role-assignment.ts` claimed
 * such a fallback matched the backend, and no engine, pre- or post-revision, ever read
 * `planned_date` for pricing. It keeps its own meaning -- the line's forecast cash-out date -- and
 * is round-tripped untouched by this screen's edits. No editor here writes one, but an import can,
 * which is precisely why the branch had to go rather than be left unreachable.
 */
export function rowRateYear(
  row: RevisionCostRow,
  nodesById: ReadonlyMap<number, RevisionNode>,
): number | null {
  if (row.cost.bearing_task_node_id == null) {
    // `datetime.now(UTC).year` on the engine's side, so UTC here too: on 31 December a local-time
    // year would price the line one year off the totals published above it.
    return new Date().getUTCFullYear();
  }
  // A bearing task the loaded tree does not hold is *not* the root case: its dates are unknown, so
  // its year is unknown, and an unknown year prices nothing.
  const bearing = nodesById.get(row.cost.bearing_task_node_id);
  const startYear = isoYear(bearing?.planning?.start_at);
  const finishYear = isoYear(bearing?.planning?.finish_at);
  if (startYear === null || finishYear === null || finishYear < startYear) {
    return null;
  }
  return startYear;
}

/** Everything a row's four computed cells need, resolved once per render of the grid. */
export type RevisionCostGridContext = {
  nodesById: ReadonlyMap<number, RevisionNode>;
  resourceRoles: readonly ResourceRole[];
  costCategories: readonly CostCategory[];
  costRates: readonly CostRate[];
};

/**
 * The indicative hourly rate of a labour row, or null when none is configured for its (category,
 * year) pair.
 *
 * Indicative, and only that: the backend's own engine prices a validated revision, spreading a
 * labour line over every year its bearing task spans and applying inflation. This single-rate
 * preview must never be mistaken for it -- hence a cell that says "—" rather than 0 when no rate
 * is found, a deliberate zero rate being otherwise indistinguishable from a missing one.
 */
export function rowHourlyRate(row: RevisionCostRow, context: RevisionCostGridContext): number | null {
  if (row.cost.nature !== "labor") {
    return null;
  }
  const category = derivedCostCategory(row.cost.role_id, context.resourceRoles, context.costCategories);
  if (!category) {
    return null;
  }
  // No year, no rate: the engine prices this facet into nothing (see rowRateYear), so the cell
  // says "—" rather than quoting a rate the published totals will not use.
  const year = rowRateYear(row, context.nodesById);
  if (year === null) {
    return null;
  }
  const rate = resolveIndicativeHourlyRate(category.id, year, [...context.costRates]);
  return rate ? rate.hourly_rate : null;
}

/**
 * The indicative PRU of a cost row: `quantité x heures x taux` for MO, `quantité x débours`
 * otherwise. Null for an MO row whose rate is unknown -- see `rowHourlyRate`.
 */
export function rowAmount(row: RevisionCostRow, context: RevisionCostGridContext): number | null {
  if (row.cost.nature !== "labor") {
    return costNumber(row.cost.quantity) * costNumber(row.cost.unit_cost);
  }
  const hourlyRate = rowHourlyRate(row, context);
  if (hourlyRate === null) {
    return null;
  }
  return costNumber(row.cost.quantity) * costNumber(row.cost.hours) * hourlyRate;
}

export type RevisionCostGridTotals = { quantity: number; hours: number; debours: number; pru: number };

/**
 * Qté/Heures/Débours/PRU summed over every direct **and** indirect cost descendant of each row
 * that has children -- the grid's subtotals on its récapitulatif rows.
 *
 * Computed bottom-up over a parent index so a deeply nested branch is walked once rather than once
 * per ancestor, and so a grandchild's amounts are never counted twice. An MO row whose rate is
 * unknown contributes 0 to the PRU column instead of making the whole subtotal unresolvable: the
 * same convention its own cell applies by showing "—".
 */
export function computeRevisionCostGridTotals(
  rows: readonly RevisionCostGridRow[],
  context: RevisionCostGridContext,
): Map<number, RevisionCostGridTotals> {
  const childrenByParent = new Map<number, RevisionCostGridRow[]>();
  for (const row of rows) {
    if (row.parent_id !== null) {
      const children = childrenByParent.get(row.parent_id) ?? [];
      children.push(row);
      childrenByParent.set(row.parent_id, children);
    }
  }

  const totals = new Map<number, RevisionCostGridTotals>();

  function computeFor(nodeId: number, guard: ReadonlySet<number>): RevisionCostGridTotals {
    const cached = totals.get(nodeId);
    if (cached) {
      return cached;
    }
    const result: RevisionCostGridTotals = { quantity: 0, hours: 0, debours: 0, pru: 0 };
    for (const child of childrenByParent.get(nodeId) ?? []) {
      if (isCostRow(child)) {
        result.quantity += costNumber(child.cost.quantity);
        result.hours += costNumber(child.cost.hours);
        result.debours += costNumber(child.cost.unit_cost);
        result.pru += rowAmount(child, context) ?? 0;
      }
      // A cost line can itself carry cost lines (only a *task* under a cost node is refused, by
      // INV-14), so the recursion is not limited to task rows. A leaf is skipped outright so the
      // map holds an entry for exactly the rows that display a subtotal -- a leaf's cell shows its
      // own value, and an all-zero entry there would be indistinguishable from a real zero.
      // `guard` stops a parent chain that loops back on itself -- impossible on a tree the backend
      // answered, cheap insurance against a partially-applied local state.
      if (child.hasChildren && !guard.has(child.node_id)) {
        const childTotals = computeFor(child.node_id, new Set(guard).add(child.node_id));
        result.quantity += childTotals.quantity;
        result.hours += childTotals.hours;
        result.debours += childTotals.debours;
        result.pru += childTotals.pru;
      }
    }
    totals.set(nodeId, result);
    return result;
  }

  for (const row of rows) {
    if (row.hasChildren) {
      computeFor(row.node_id, new Set([row.node_id]));
    }
  }
  return totals;
}

/**
 * What a task row's "Type" cell says. A task carrying task children is a récapitulatif -- the
 * revision model stores no `is_summary`, the tree already says it -- and a task carrying only cost
 * lines is not one.
 */
export function taskRowTypeLabel(row: RevisionCostGridRow, rows: readonly RevisionCostGridRow[]): string {
  if (row.planning?.is_milestone) {
    return "Jalon";
  }
  return rows.some((candidate) => candidate.parent_id === row.node_id && candidate.kind === "task")
    ? "Récapitulatif"
    : "Tâche";
}

/** The label a row is designated by in a dialog, a menu or an accessible name. */
export function gridRowLabel(row: RevisionCostGridRow): string {
  return row.kind === "task" ? (row.planning?.name ?? "") : (row.cost?.label ?? "");
}

/** "12 - Étude", the label the delete confirmation lists a selected row under. */
export function gridRowDeleteLabel(row: RevisionCostGridRow): string {
  return `${row.row_number} - ${gridRowLabel(row)}`;
}

/** Amounts are shown in euros, the currency every published figure of a revision is in. */
export function formatEuros(value: number): string {
  return value.toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
}
