import { describe, expect, it } from "vitest";

import type { CostCategory, CostRate, ResourceNode, ResourceRole, RevisionNode } from "@/lib/backend";
import { buildRevisionTreeRows } from "@/lib/revision-tree";
import {
  computeRevisionCostGridTotals,
  costNumber,
  derivedCostCategory,
  dept1Options,
  dept2Options,
  gridRowDeleteLabel,
  isCostRow,
  resolveDeptColumns,
  roleCascadeOf,
  roleOptions,
  rowAmount,
  rowCostCategory,
  rowHourlyRate,
  rowRateYear,
  taskRowTypeLabel,
  type RevisionCostGridContext,
  type RevisionCostRow,
} from "@/lib/revision-cost-grid";

function taskNode(
  nodeId: number,
  options: {
    parentId?: number | null;
    position?: number;
    level?: number;
    name?: string;
    startAt?: string | null;
    finishAt?: string | null;
    milestone?: boolean;
  } = {},
): RevisionNode {
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "task",
    parent_id: options.parentId ?? null,
    position: options.position ?? 1,
    row_number: nodeId,
    level: options.level ?? 1,
    external_uid: null,
    description: null,
    planning: {
      name: options.name ?? `T${nodeId}`,
      calendar_id: null,
      calendar_source: null,
      is_milestone: options.milestone ?? false,
      duration_minutes: 480,
      duration_format: null,
      start_at: options.startAt ?? null,
      finish_at: options.finishAt ?? null,
      work_minutes: null,
      percent_complete: 0,
      is_manual: true,
    },
    cost: null,
    predecessors: [],
  };
}

function costNode(
  nodeId: number,
  options: {
    parentId?: number | null;
    position?: number;
    level?: number;
    label?: string;
    nature?: "labor" | "non_labor";
    quantity?: string;
    hours?: string | null;
    unitCost?: string | null;
    roleId?: number | null;
    categoryId?: number | null;
    bearingNodeId?: number | null;
    plannedDate?: string | null;
  } = {},
): RevisionNode {
  const {
    nature = "non_labor",
    parentId = null,
    position = 1,
    level = 1,
    label = `L${nodeId}`,
    quantity = "2.00",
    hours = "10.00",
    unitCost = "50.00",
    roleId = 7,
    categoryId = 4,
    bearingNodeId = parentId,
  } = options;
  // The two natures carry disjoint attribute sets (INV-19 / INV-20), so the fixture builds one or
  // the other outright rather than nulling six fields inline -- a facet shaped like neither is not
  // a case any of these tests should be able to express by accident.
  const facet =
    nature === "labor"
      ? { role_id: roleId, hours, cost_type_id: null, cost_category_id: null, unit_cost: null }
      : { role_id: null, hours: null, cost_type_id: 1, cost_category_id: categoryId, unit_cost: unitCost };
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "cost",
    parent_id: parentId,
    position,
    row_number: nodeId,
    level,
    external_uid: null,
    description: null,
    planning: null,
    cost: {
      nature,
      label,
      quantity,
      ...facet,
      supply_status: null,
      planned_date: options.plannedDate ?? null,
      cost_code_id: null,
      comment: null,
      bearing_task_node_id: bearingNodeId,
      bearing_task_name: null,
    },
    predecessors: [],
  };
}

const nodes: ResourceNode[] = [
  { id: 1, parent_id: null, code: "DIR", name: "Direction", is_active: true, created_at: "", updated_at: "" } as never,
  { id: 2, parent_id: 1, code: "ETU", name: "Études", is_active: true, created_at: "", updated_at: "" } as never,
  { id: 3, parent_id: 1, code: "TRV", name: "Travaux", is_active: true, created_at: "", updated_at: "" } as never,
  { id: 4, parent_id: null, code: "EXP", name: "Exploitation", is_active: true, created_at: "", updated_at: "" } as never,
];

const roles: ResourceRole[] = [
  { id: 7, node_id: 2, cost_category_id: 40, name: "Ingénieur" } as never,
  { id: 8, node_id: 3, cost_category_id: 41, name: "Chef de chantier" } as never,
];

const categories: CostCategory[] = [
  { id: 40, cost_type_id: 1, accounting_code: "601", category_code: null, name: "Études" } as never,
  { id: 41, cost_type_id: 2, accounting_code: "602", category_code: null, name: "Chantier" } as never,
  { id: 4, cost_type_id: 2, accounting_code: "604", category_code: null, name: "Fournitures" } as never,
];

const rates: CostRate[] = [
  { id: 1, cost_category_id: 40, year: 2031, hourly_rate: 100, currency_code: "EUR" } as never,
];

function context(overrides: Partial<RevisionCostGridContext> = {}): RevisionCostGridContext {
  return {
    nodesById: new Map(),
    resourceRoles: roles,
    costCategories: categories,
    costRates: rates,
    ...overrides,
  };
}

function costRowOf(node: RevisionNode): RevisionCostRow {
  const row = buildRevisionTreeRows([node])[0];
  if (!isCostRow(row)) {
    throw new Error("fixture is not a cost row");
  }
  return row;
}

describe("costNumber", () => {
  it("reads the decimals the API serialises as strings", () => {
    expect(costNumber("12.50")).toBe(12.5);
  });

  it("answers 0 for an absent or unparseable amount rather than poisoning a whole subtotal", () => {
    expect(costNumber(null)).toBe(0);
    expect(costNumber("n/a")).toBe(0);
  });
});

describe("the Dpt 1er niveau / Dpt 2eme niveau cascade (#315)", () => {
  it("offers the roots of the resource tree as Dpt 1er niveau", () => {
    expect(dept1Options(nodes).map((node) => node.name)).toEqual(["Direction", "Exploitation"]);
  });

  it("restricts Dpt 2eme niveau to the direct children of the chosen Dpt 1er niveau", () => {
    expect(dept2Options(nodes, "1").map((node) => node.name)).toEqual(["Études", "Travaux"]);
    expect(dept2Options(nodes, "4")).toEqual([]);
  });

  it("offers nothing at the second level until a first one is chosen", () => {
    expect(dept2Options(nodes, "")).toEqual([]);
  });

  it("restricts the roles to the chosen Dpt 2eme niveau", () => {
    expect(roleOptions(roles, "2").map((role) => role.name)).toEqual(["Ingénieur"]);
    expect(roleOptions(roles, "")).toEqual([]);
  });

  it("reads an existing line's own department path back from its role", () => {
    expect(roleCascadeOf(8, roles, nodes)).toEqual({ dept1Id: "1", dept2Id: "3", roleId: "8" });
  });

  it("opens empty for a line carrying no role, and for a role the referential no longer holds", () => {
    expect(roleCascadeOf(null, roles, nodes)).toEqual({ dept1Id: "", dept2Id: "", roleId: "" });
    expect(roleCascadeOf(99, roles, nodes)).toEqual({ dept1Id: "", dept2Id: "", roleId: "" });
  });

  it("shows the two topmost ancestors of the role's node in the two Dpt columns", () => {
    expect(resolveDeptColumns(2, nodes)).toEqual(["Direction", "Études"]);
    expect(resolveDeptColumns(null, nodes)).toEqual(["-", "-"]);
  });

  it("does not hang on a referential whose parent chain loops", () => {
    const looping: ResourceNode[] = [
      { id: 1, parent_id: 2, code: "A", name: "A", is_active: true, created_at: "", updated_at: "" } as never,
      { id: 2, parent_id: 1, code: "B", name: "B", is_active: true, created_at: "", updated_at: "" } as never,
    ];
    expect(resolveDeptColumns(1, looping)).toEqual(["B", "A"]);
  });
});

describe("the accounting category of a line", () => {
  // The amendment to #337: INV-19 forbids a labour facet from carrying a category at all, so
  // choosing a role must *derive* it, never write it.
  it("derives an MO line's category from its role", () => {
    expect(derivedCostCategory(7, roles, categories)?.name).toBe("Études");
    expect(derivedCostCategory(8, roles, categories)?.name).toBe("Chantier");
  });

  it("has no category to derive for a line with no role", () => {
    expect(derivedCostCategory(null, roles, categories)).toBeNull();
  });

  it("reads a non-MO line's category off the facet, where it is actually stored", () => {
    const row = costRowOf(costNode(5, { nature: "non_labor", categoryId: 4 }));
    expect(rowCostCategory(row, roles, categories)?.name).toBe("Fournitures");
  });

  it("reads an MO line's category through its role and not off the facet", () => {
    const row = costRowOf(costNode(5, { nature: "labor", roleId: 8 }));
    expect(row.cost.cost_category_id).toBeNull();
    expect(rowCostCategory(row, roles, categories)?.name).toBe("Chantier");
  });
});

describe("the year a line is priced at", () => {
  // `rowRateYear` mirrors the engine's `_bearing_years`
  // (`apps/backend/src/waterfall/services/estimate_calculation.py`) branch for branch, and the four
  // cases below are that function's four cases. The engine is the reference and not
  // `_unpriceable_facet`, which only records after the fact what `_bearing_years` decided: a facet
  // is priced at whatever years `_bearing_years` answers, at the current year when it bears no
  // task at all, and at none when that function answers `None`.
  //
  // The classification has to coincide because the "Lignes non valorisables" panel sits right
  // above this grid and publishes the engine's: a line named there and priced here -- or counted
  // in a total here and left blank there -- makes the two halves of one screen disagree on a sum
  // in euros.
  const currentYear = new Date().getUTCFullYear();

  it("takes the year its bearing task starts", () => {
    const bearing = taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: "2031-11-01T00:00:00Z" });
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1 }));
    expect(rowRateYear(row, new Map([[1, bearing]]))).toBe(2031);
  });

  it("keeps the first year alone of a task spanning several", () => {
    // A deliberate divergence, and the only one: the engine spreads the hours over 2031, 2032 and
    // 2033 with inflation, this column is a single-rate preview. What must not diverge is whether
    // the line is priced at all, not by how much -- see `rowHourlyRate`.
    const bearing = taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: "2033-11-01T00:00:00Z" });
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1 }));
    expect(rowRateYear(row, new Map([[1, bearing]]))).toBe(2031);
  });

  it("prices a line carrying no bearing task at the current year, as the engine does", () => {
    // `_bearing_years(None)` answers `[datetime.now(UTC).year]`: INV-01's project-wide global cost
    // is one line at the current year, "never dropped from a total" -- backend
    // `test_a_cost_facet_at_the_root_counts_towards_the_total`, where a root MO line is worth
    // 1 000 € and enters `total_unburdened_cost`. Criterion 5 of #337 rests on exactly that: a
    // line outdented up to the root stays counted.
    const row = costRowOf(costNode(5, { parentId: null, bearingNodeId: null }));
    expect(rowRateYear(row, new Map())).toBe(currentYear);
  });

  it("has no year when its bearing task carries no date at all", () => {
    const bearing = taskNode(1, { startAt: null, finishAt: null });
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1 }));
    expect(rowRateYear(row, new Map([[1, bearing]]))).toBeNull();
  });

  it("has no year when its bearing task is dated at one end only", () => {
    // `_bearing_years` answers `None` as soon as either bound is missing, and half-dated is a
    // reachable state rather than a theoretical one: `buildManualPayload` can send
    // `finish_at: null`, and an MSPDI import can produce it.
    const startOnly = taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: null });
    const finishOnly = taskNode(1, { startAt: null, finishAt: "2031-11-01T00:00:00Z" });
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1 }));
    expect(rowRateYear(row, new Map([[1, startOnly]]))).toBeNull();
    expect(rowRateYear(row, new Map([[1, finishOnly]]))).toBeNull();
  });

  it("has no year when its bearing task finishes before it starts", () => {
    // `range(2031, 2030 + 1)` is empty, and `_bearing_years` answers `None` for it rather than
    // dividing the hours by zero years. Nothing on the write side forbids the state today, so the
    // grid meets it too.
    const inverted = taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: "2030-11-01T00:00:00Z" });
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1 }));
    expect(rowRateYear(row, new Map([[1, inverted]]))).toBeNull();
  });

  it("has no year when the loaded tree does not hold the bearing task the line names", () => {
    // Not the root case: the line *has* a bearing task, whose dates this render simply does not
    // know. Pricing it at the current year would invent a figure out of a partially applied local
    // state.
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1 }));
    expect(rowRateYear(row, new Map())).toBeNull();
  });

  it("does not take the year off the line's own forecast cash-out date", () => {
    // 2031 on purpose: the referential holds a rate for that year, so an implementation that fell
    // back on `planned_date` would answer 2031 here and price the line, not merely fail to find a
    // rate. The engine never reads `planned_date`, so neither may this.
    const bearing = taskNode(1, { startAt: null });
    const row = costRowOf(costNode(5, { parentId: 1, bearingNodeId: 1, plannedDate: "2031-07-01" }));
    expect(rowRateYear(row, new Map([[1, bearing]]))).toBeNull();
  });

  it("prices exactly the lines the engine prices, in every shape its bearing task takes", () => {
    // The referential holds three rates, so that no assertion below can pass for want of one: the
    // **current** year at 100 €/h (the root case must produce a real amount, not a "—"), 2031 at
    // 100 €/h (a dated bearing task) and 2032 at 150 €/h (the year the lines' own `planned_date`
    // falls in, priced differently so that a fallback on it is visible in the figure).
    const priced = context({
      costRates: [
        ...rates,
        { id: 2, cost_category_id: 40, year: currentYear, hourly_rate: 100, currency_code: "EUR" } as never,
        { id: 3, cost_category_id: 40, year: 2032, hourly_rate: 150, currency_code: "EUR" } as never,
      ],
    });
    /** The same MO line -- 2 x 10 h on role 7, category 40 -- with its facet amended case by case. */
    function labourLine(overrides: Partial<NonNullable<RevisionNode["cost"]>> = {}): RevisionCostRow {
      const node = costNode(5, { nature: "labor", roleId: 7, quantity: "2", hours: "10", parentId: 1 });
      return costRowOf({ ...node, cost: { ...node.cost!, ...overrides } });
    }

    // No bearing task: priced at the current year and counted, INV-01's global cost.
    const rootLine = labourLine({ bearing_task_node_id: null });
    expect(rowRateYear(rootLine, priced.nodesById)).toBe(currentYear);
    expect(rowHourlyRate(rootLine, priced)).toBe(100);
    expect(rowAmount(rootLine, priced)).toBe(2 * 10 * 100);
    // ... and the two reasons a cell shows "—" stay distinguishable: with no rate for the current
    // year the very same line is unpriced, without that making it a line with no year.
    expect(rowHourlyRate(rootLine, context({ costRates: [] }))).toBeNull();
    expect(rowAmount(rootLine, context({ costRates: [] }))).toBeNull();
    // Its own forecast cash-out date does not displace that year: 2032 would price it 3 000 €.
    const rootSelfDated = labourLine({ bearing_task_node_id: null, planned_date: "2032-07-01" });
    expect(rowAmount(rootSelfDated, priced)).toBe(2 * 10 * 100);

    // An undated, a half-dated and an inverted bearing task: the engine prices none of them, so
    // neither Taux horaire nor PRU may show a figure -- the panel above names these lines as
    // counted nowhere, and 2 000 € beside such a line is worse than a 0, which gets noticed.
    const underTask = labourLine();
    for (const bearing of [
      taskNode(1, { startAt: null, finishAt: null }),
      taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: null }),
      taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: "2030-11-01T00:00:00Z" }),
    ]) {
      const withBearing = { ...priced, nodesById: new Map([[1, bearing]]) };
      expect(rowHourlyRate(underTask, withBearing)).toBeNull();
      expect(rowAmount(underTask, withBearing)).toBeNull();
      // Same three shapes, for the line an import dated by itself in a year the referential does
      // hold a rate for: still nothing, or 3 000 € would appear here and in the subtotal above.
      const selfDated = labourLine({ planned_date: "2032-07-01" });
      expect(rowHourlyRate(selfDated, withBearing)).toBeNull();
      expect(rowAmount(selfDated, withBearing)).toBeNull();
    }

    // And the control: the very same line under a fully dated task is priced at 2031's rate, so
    // what the assertions above observe is the engine's refusal and not a missing rate.
    const dated = new Map([[1, taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: "2031-11-01T00:00:00Z" })]]);
    // The year is asserted alongside the amount: both years carry a 100 €/h rate, so the figure
    // alone would not tell the task's year from the current one.
    expect(rowRateYear(underTask, dated)).toBe(2031);
    expect(rowAmount(underTask, { ...priced, nodesById: dated })).toBe(2 * 10 * 100);
  });
});

describe("the computed Taux horaire and PRU cells", () => {
  const bearing = taskNode(1, { startAt: "2031-03-01T00:00:00Z", finishAt: "2031-09-01T00:00:00Z" });
  const nodesById = new Map([[1, bearing]]);

  it("prices an MO line at its role's category rate for that year", () => {
    const row = costRowOf(costNode(5, { nature: "labor", roleId: 7, quantity: "2", hours: "10", parentId: 1 }));
    expect(rowHourlyRate(row, context({ nodesById }))).toBe(100);
    expect(rowAmount(row, context({ nodesById }))).toBe(2 * 10 * 100);
  });

  it("answers null -- never 0 -- when no rate is configured for that category and year", () => {
    // Role 8's category (41) has no rate: a deliberate zero rate and a missing one must not look
    // alike, which is why the cell shows "—" rather than 0 €.
    const row = costRowOf(costNode(5, { nature: "labor", roleId: 8, parentId: 1 }));
    expect(rowHourlyRate(row, context({ nodesById }))).toBeNull();
    expect(rowAmount(row, context({ nodesById }))).toBeNull();
  });

  it("prices a non-MO line as quantité x débours, with no rate involved", () => {
    const row = costRowOf(costNode(5, { nature: "non_labor", quantity: "3", unitCost: "50" }));
    expect(rowHourlyRate(row, context({ nodesById }))).toBeNull();
    expect(rowAmount(row, context({ nodesById }))).toBe(150);
  });
});

describe("the subtotals of a récapitulatif row", () => {
  const tree: RevisionNode[] = [
    taskNode(1, { name: "Poste", startAt: "2031-03-01T00:00:00Z", finishAt: "2031-09-01T00:00:00Z" }),
    taskNode(2, { name: "Lot", parentId: 1, level: 2, startAt: "2031-03-01T00:00:00Z", finishAt: "2031-09-01T00:00:00Z" }),
    costNode(3, { parentId: 2, level: 3, nature: "labor", roleId: 7, quantity: "2", hours: "10", bearingNodeId: 2 }),
    costNode(4, { parentId: 1, position: 2, level: 2, nature: "non_labor", quantity: "3", unitCost: "50", bearingNodeId: 1 }),
  ];
  const rows = buildRevisionTreeRows(tree);
  const totals = computeRevisionCostGridTotals(rows, context({ nodesById: new Map(tree.map((node) => [node.node_id, node])) }));

  it("folds a grandchild's amounts into the ancestor exactly once", () => {
    expect(totals.get(1)).toEqual({ quantity: 5, hours: 10, debours: 50, pru: 2000 + 150 });
    expect(totals.get(2)).toEqual({ quantity: 2, hours: 10, debours: 0, pru: 2000 });
  });

  it("computes nothing for a row with no children", () => {
    expect(totals.get(3)).toBeUndefined();
  });

  it("counts an unpriceable MO line as 0 in the PRU column instead of losing the whole subtotal", () => {
    const unpriceable: RevisionNode[] = [
      taskNode(1),
      costNode(2, { parentId: 1, level: 2, nature: "labor", roleId: 8, quantity: "2", hours: "10" }),
    ];
    const unpriceableTotals = computeRevisionCostGridTotals(buildRevisionTreeRows(unpriceable), context());
    expect(unpriceableTotals.get(1)).toEqual({ quantity: 2, hours: 10, debours: 0, pru: 0 });
  });
});

describe("what a task row's Type cell says", () => {
  const tree = [
    taskNode(1, { name: "Poste" }),
    taskNode(2, { name: "Lot", parentId: 1, level: 2 }),
    taskNode(3, { name: "Jalon", position: 2, milestone: true }),
    taskNode(4, { name: "Chiffrée", position: 3 }),
    costNode(5, { parentId: 4, level: 2 }),
  ];
  const rows = buildRevisionTreeRows(tree);

  it("names a task carrying task children a récapitulatif", () => {
    expect(taskRowTypeLabel(rows[0], rows)).toBe("Récapitulatif");
  });

  it("names a milestone a jalon", () => {
    expect(taskRowTypeLabel(rows[2], rows)).toBe("Jalon");
  });

  it("does not make a récapitulatif of a task that only carries cost lines", () => {
    expect(taskRowTypeLabel(rows[3], rows)).toBe("Tâche");
    expect(taskRowTypeLabel(rows[1], rows)).toBe("Tâche");
  });
});

describe("gridRowDeleteLabel", () => {
  it("designates a row by the number the user reads, whichever facet it carries", () => {
    const rows = buildRevisionTreeRows([taskNode(1, { name: "Poste" }), costNode(2, { label: "Béton" })]);
    expect(gridRowDeleteLabel(rows[0])).toBe("1 - Poste");
    expect(gridRowDeleteLabel(rows[1])).toBe("2 - Béton");
  });
});
