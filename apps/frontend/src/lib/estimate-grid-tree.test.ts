import { describe, expect, it } from "vitest";

import type { EstimateCostLine, EstimateRoleAssignment, EstimateTaskRow } from "@/lib/backend";
import {
  buildEstimateGridTreeRows,
  computeEstimateGridRowTotals,
  filterVisibleEstimateGridRows,
} from "@/lib/estimate-grid-tree";

function makeTaskRow(overrides: Partial<EstimateTaskRow> = {}): EstimateTaskRow {
  return {
    id: 1,
    estimate_id: 1,
    task_id: 1,
    task_uid: 1,
    row_number: 1,
    parent_task_id: null,
    position: 1,
    task_name: "Terrassement",
    outline_number: "1",
    outline_level: 0,
    is_milestone: false,
    ...overrides,
  };
}

function makeLine(overrides: Partial<EstimateCostLine> = {}): EstimateCostLine {
  return {
    id: 1,
    estimate_id: 1,
    task_id: null,
    cost_type_id: 1,
    cost_category_id: 1,
    accounting_code: "6011",
    label: "Ligne",
    quantity: 1,
    unit_cost: 1,
    purchase_cost: 1,
    uid: -1,
    parent_uid: null,
    position: 1,
    row_number: 1,
    ...overrides,
  } as EstimateCostLine;
}

function makeAssignment(overrides: Partial<EstimateRoleAssignment> = {}): EstimateRoleAssignment {
  return {
    id: 1,
    estimate_id: 1,
    task_id: null,
    role_id: 1,
    role_code: "DEV",
    role_name: "Développeur",
    cost_category_id: 1,
    accounting_code: "6410",
    quantity: 1,
    hours: 8,
    uid: -2,
    parent_uid: null,
    position: 1,
    row_number: 2,
    ...overrides,
  } as EstimateRoleAssignment;
}

describe("buildEstimateGridTreeRows", () => {
  it("returns nothing for an empty estimate", () => {
    expect(buildEstimateGridTreeRows([], [], [])).toEqual([]);
  });

  it("orders rows by the backend's own row_number, regardless of array order", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2 });

    const rows = buildEstimateGridTreeRows([task], [line], []);

    expect(rows.map((row) => row.rowNumber)).toEqual([1, 2]);
    expect(rows[0].kind).toBe("task");
    expect(rows[1].kind).toBe("line");
  });

  it("nests a cost line under its attached task with depth 1 and marks the task as having children", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2 });

    const rows = buildEstimateGridTreeRows([task], [line], []);

    const taskRow = rows.find((row) => row.kind === "task")!;
    const lineRow = rows.find((row) => row.kind === "line")!;
    expect(taskRow.hasChildren).toBe(true);
    expect(taskRow.depth).toBe(0);
    expect(lineRow.depth).toBe(1);
    expect(lineRow.parentUid).toBe(10);
  });

  it("nests a grid node under another grid node (a cost line's own child line)", () => {
    const parentLine = makeLine({ id: 100, uid: -1, parent_uid: null, row_number: 1 });
    const childLine = makeLine({ id: 101, uid: -2, parent_uid: -1, row_number: 2 });

    const rows = buildEstimateGridTreeRows([], [parentLine, childLine], []);

    expect(rows.find((row) => row.uid === -1)?.hasChildren).toBe(true);
    expect(rows.find((row) => row.uid === -2)?.depth).toBe(1);
  });

  it("treats a role assignment/cost line whose parent_uid resolves to nothing as a root", () => {
    const orphan = makeLine({ id: 100, uid: -1, parent_uid: 999, row_number: 1 });

    const rows = buildEstimateGridTreeRows([], [orphan], []);

    expect(rows[0].depth).toBe(0);
    expect(rows[0].parentUid).toBe(null);
  });

  it("keeps a task row with no task_id (no MsTask twin) visible as a root with a null uid/row_number", () => {
    const orphanTaskRow = makeTaskRow({ id: 1, task_id: null, row_number: null });

    const rows = buildEstimateGridTreeRows([orphanTaskRow], [], []);

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: "task", uid: null, rowNumber: null, depth: 0, hasChildren: false });
  });
});

describe("filterVisibleEstimateGridRows", () => {
  it("hides every descendant of a collapsed row", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2 });
    const childLine = makeLine({ id: 101, uid: -2, parent_uid: -1, row_number: 3 });
    const rows = buildEstimateGridTreeRows([task], [line, childLine], []);

    const visible = filterVisibleEstimateGridRows(rows, new Set([10]));

    expect(visible.map((row) => row.uid)).toEqual([10]);
  });

  it("shows every row when nothing is collapsed", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2 });
    const rows = buildEstimateGridTreeRows([task], [line], []);

    expect(filterVisibleEstimateGridRows(rows, new Set())).toHaveLength(2);
  });
});

describe("computeEstimateGridRowTotals", () => {
  it("sums a summary task's direct cost-line/role-assignment children", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2, quantity: 2, unit_cost: 5, purchase_cost: 10 });
    const assignment = makeAssignment({ id: 200, uid: -2, parent_uid: 10, row_number: 3, quantity: 1, hours: 4 });
    const rows = buildEstimateGridTreeRows([task], [line], [assignment]);

    // No CostRate loaded -> the labor row's own indicative cost can't be resolved, contributes 0
    // to the PRU sum (see this module's own doc comment) while quantity/hours still add up.
    const totals = computeEstimateGridRowTotals(rows, [], []);

    expect(totals.get(10)).toEqual({ quantity: 3, hours: 4, debours: 5, pru: 10 });
  });

  it("sums direct AND indirect descendants through a nested summary task, without double counting", () => {
    const outer = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const inner = makeTaskRow({ id: 2, task_id: 20, parent_task_id: 10, row_number: 2 });
    const outerLine = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 3, quantity: 1, unit_cost: 1, purchase_cost: 1 });
    const innerLine = makeLine({ id: 101, uid: -2, parent_uid: 20, row_number: 4, quantity: 10, unit_cost: 2, purchase_cost: 20 });

    const rows = buildEstimateGridTreeRows([outer, inner], [outerLine, innerLine], []);
    const totals = computeEstimateGridRowTotals(rows, [], []);

    expect(totals.get(20)).toEqual({ quantity: 10, hours: 0, debours: 2, pru: 20 });
    // The outer task's own total folds in both its direct line AND its child task's already
    // -computed total -- never the inner task's own subtotal counted a second time on top.
    expect(totals.get(10)).toEqual({ quantity: 11, hours: 0, debours: 3, pru: 21 });
  });

  it("does not compute a total at all for a row with no children (a leaf task)", () => {
    const leaf = makeTaskRow({ id: 1, task_id: 10, row_number: 1 });
    const rows = buildEstimateGridTreeRows([leaf], [], []);

    expect(computeEstimateGridRowTotals(rows, [], []).has(10)).toBe(false);
  });
});
