import { describe, expect, it } from "vitest";

import type { EstimateCostLine, EstimateRoleAssignment, EstimateTaskRow } from "@/lib/backend";
import { buildEstimateGridTreeRows } from "@/lib/estimate-grid-tree";
import { computeGridIndentCommand, computeGridOutdentCommand, computeGridReorderCommand } from "@/lib/estimate-grid-move";

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

describe("computeGridIndentCommand", () => {
  it("nests a root cost line under the task row immediately above it", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1, position: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: null, row_number: 2, position: 1 });
    const rows = buildEstimateGridTreeRows([task], [line], []);

    const command = computeGridIndentCommand(rows, new Set([-1]));

    expect(command).toEqual({ node_uids: [-1], target_parent_uid: 10, position: 1 });
  });

  it("appends after any existing grid-node children when indenting under a row that already has some", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1, position: 1 });
    const sibling = makeLine({ id: 99, uid: -3, parent_uid: 10, row_number: 2, position: 1 });
    const existingChild = makeLine({ id: 100, uid: -1, parent_uid: -3, row_number: 3, position: 1 });
    const line = makeLine({ id: 101, uid: -2, parent_uid: 10, row_number: 4, position: 2 });
    const rows = buildEstimateGridTreeRows([task], [sibling, existingChild, line], []);

    // "line" sits right after "existingChild" in row_number order -- indenting it nests it under
    // "existingChild" (the row immediately above it, see computeGridIndentCommand's own doc
    // comment), appended after that row's own pre-existing grid-node child.
    const command = computeGridIndentCommand(rows, new Set([-2]));

    expect(command).toEqual({ node_uids: [-2], target_parent_uid: -1, position: 1 });
  });


  it("returns null for the very first visible row (nothing above it to indent under)", () => {
    const line = makeLine({ id: 100, uid: -1, parent_uid: null, row_number: 1, position: 1 });
    const rows = buildEstimateGridTreeRows([], [line], []);

    expect(computeGridIndentCommand(rows, new Set([-1]))).toBeNull();
  });

  it("returns null when nothing is selected", () => {
    const rows = buildEstimateGridTreeRows([], [], []);
    expect(computeGridIndentCommand(rows, new Set())).toBeNull();
  });
});

describe("computeGridOutdentCommand", () => {
  it("returns null for a root grid node (nothing to outdent from)", () => {
    const line = makeLine({ id: 100, uid: -1, parent_uid: null, row_number: 1, position: 1 });
    const rows = buildEstimateGridTreeRows([], [line], []);

    expect(computeGridOutdentCommand(rows, new Set([-1]))).toBeNull();
  });

  it("moves a line out from under its task to the task's own parent task", () => {
    const outer = makeTaskRow({ id: 1, task_id: 10, row_number: 1, position: 1 });
    const inner = makeTaskRow({ id: 2, task_id: 20, parent_task_id: 10, row_number: 2, position: 2 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 20, row_number: 3, position: 1 });
    const rows = buildEstimateGridTreeRows([outer, inner], [line], []);

    const command = computeGridOutdentCommand(rows, new Set([-1]));

    expect(command).toEqual({ node_uids: [-1], target_parent_uid: 10, position: 1 });
  });

  it("moves a line out to the devis root when its parent task has no parent task", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1, position: 1 });
    const line = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2, position: 1 });
    const rows = buildEstimateGridTreeRows([task], [line], []);

    const command = computeGridOutdentCommand(rows, new Set([-1]));

    expect(command).toEqual({ node_uids: [-1], target_parent_uid: null, position: 1 });
  });
});

describe("computeGridReorderCommand", () => {
  it("swaps a line up with its preceding sibling under the same task", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1, position: 1 });
    const first = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2, position: 1 });
    const second = makeLine({ id: 101, uid: -2, parent_uid: 10, row_number: 3, position: 2 });
    const rows = buildEstimateGridTreeRows([task], [first, second], []);

    const command = computeGridReorderCommand(rows, new Set([-2]), "up");

    expect(command).toEqual({ node_uids: [-2], target_parent_uid: 10, position: 1 });
  });

  it("returns null moving the first sibling further up", () => {
    const task = makeTaskRow({ id: 1, task_id: 10, row_number: 1, position: 1 });
    const first = makeLine({ id: 100, uid: -1, parent_uid: 10, row_number: 2, position: 1 });
    const rows = buildEstimateGridTreeRows([task], [first], []);

    expect(computeGridReorderCommand(rows, new Set([-1]), "up")).toBeNull();
  });

  it("moves a labor row down past its next sibling", () => {
    const assignment = makeAssignment({ id: 1, uid: -1, parent_uid: null, row_number: 1, position: 1 });
    const line = makeLine({ id: 100, uid: -2, parent_uid: null, row_number: 2, position: 2 });
    const rows = buildEstimateGridTreeRows([], [line], [assignment]);

    const command = computeGridReorderCommand(rows, new Set([-1]), "down");

    expect(command).toEqual({ node_uids: [-1], target_parent_uid: null, position: 2 });
  });
});
