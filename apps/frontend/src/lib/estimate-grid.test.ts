import { describe, expect, it } from "vitest";

import { buildEstimateGridEntries } from "@/lib/estimate-grid";
import type { EstimateCostLine, EstimateRoleAssignment, EstimateTaskRow } from "@/lib/backend";

function makeTaskRow(overrides: Partial<EstimateTaskRow> = {}): EstimateTaskRow {
  return {
    id: 1,
    estimate_id: 1,
    task_id: 1,
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
    accounting_code: "6011",
    label: "Ligne",
    quantity: "1",
    unit_cost: "1",
    purchase_cost: "1",
    task_id: null,
    ...overrides,
  } as EstimateCostLine;
}

function makeAssignment(overrides: Partial<EstimateRoleAssignment> = {}): EstimateRoleAssignment {
  return {
    id: 1,
    estimate_id: 1,
    task_id: 42,
    role_id: 1,
    role_code: "DEV",
    role_name: "Développeur",
    cost_category_id: 1,
    accounting_code: "6410",
    quantity: 1,
    hours: 8,
    ...overrides,
  } as EstimateRoleAssignment;
}

describe("buildEstimateGridEntries", () => {
  it("returns nothing for an empty estimate", () => {
    expect(buildEstimateGridEntries([], [])).toEqual([]);
  });

  it("lists task rows sorted by position, regardless of array order", () => {
    const second = makeTaskRow({ id: 2, task_id: 20, position: 2, task_name: "Second" });
    const first = makeTaskRow({ id: 1, task_id: 10, position: 1, task_name: "First" });

    const entries = buildEstimateGridEntries([], [second, first]);

    expect(entries).toEqual([
      { kind: "task", taskRow: first },
      { kind: "task", taskRow: second },
    ]);
  });

  it("groups a cost line right after the task row it is attached to, indented one level deeper", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42, outline_level: 1 });
    const line = makeLine({ id: 100, task_id: 42 });

    const entries = buildEstimateGridEntries([line], [taskRow]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "line", line, indentLevel: 2 },
    ]);
  });

  it("preserves the attachment order of multiple cost lines under the same task", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const firstLine = makeLine({ id: 100, task_id: 42, label: "MO" });
    const secondLine = makeLine({ id: 101, task_id: 42, label: "Fourniture" });

    const entries = buildEstimateGridEntries([firstLine, secondLine], [taskRow]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "line", line: firstLine, indentLevel: 1 },
      { kind: "line", line: secondLine, indentLevel: 1 },
    ]);
  });

  it("never attaches a cost line under a task row with no task_id (no MsTask twin)", () => {
    const orphanTaskRow = makeTaskRow({ id: 1, task_id: null });

    const entries = buildEstimateGridEntries([], [orphanTaskRow]);

    expect(entries).toEqual([{ kind: "task", taskRow: orphanTaskRow }]);
  });

  it("places a cost line with no task attachment in a trailing global-header section", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const globalLine = makeLine({ id: 100, task_id: null });

    const entries = buildEstimateGridEntries([globalLine], [taskRow]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "global-header" },
      { kind: "line", line: globalLine, indentLevel: 0 },
    ]);
  });

  it("omits the global-header section entirely when every cost line is attached to a task", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const attachedLine = makeLine({ id: 100, task_id: 42 });

    const entries = buildEstimateGridEntries([attachedLine], [taskRow]);

    expect(entries.some((entry) => entry.kind === "global-header")).toBe(false);
  });

  // Defensive fallback, not expected in practice (see buildEstimateGridEntries's own doc
  // comment): a cost line's task_id that doesn't match any task row of this estimate must not
  // silently disappear from the grid.
  it("falls back a cost line with an unmatched task_id into the global section, instead of dropping it", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const orphanedLine = makeLine({ id: 100, task_id: 999 });

    const entries = buildEstimateGridEntries([orphanedLine], [taskRow]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "global-header" },
      { kind: "line", line: orphanedLine, indentLevel: 0 },
    ]);
  });
});

// E12-06/#278: merges EstimateRoleAssignment ("labor") rows under their attached task, alongside
// the non-labor cost lines already merged above.
describe("buildEstimateGridEntries with role assignments (E12-06)", () => {
  it("groups a role assignment right after the task row it is attached to, indented one level deeper", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42, outline_level: 1 });
    const assignment = makeAssignment({ task_id: 42 });

    const entries = buildEstimateGridEntries([], [taskRow], [assignment]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "labor", assignment, indentLevel: 2 },
    ]);
  });

  it("lists a task's role assignments ahead of its non-labor cost lines", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const assignment = makeAssignment({ task_id: 42 });
    const line = makeLine({ id: 100, task_id: 42 });

    const entries = buildEstimateGridEntries([line], [taskRow], [assignment]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "labor", assignment, indentLevel: 1 },
      { kind: "line", line, indentLevel: 1 },
    ]);
  });

  it("never attaches a role assignment under a task row with no task_id (no MsTask twin)", () => {
    const orphanTaskRow = makeTaskRow({ id: 1, task_id: null });
    const assignment = makeAssignment({ task_id: 42 });

    const entries = buildEstimateGridEntries([], [orphanTaskRow], [assignment]);

    // The assignment doesn't attach under orphanTaskRow (task_id: null), and since no other task
    // row of this estimate carries task_id 42 either, it now falls into the orphan fallback (see
    // the next describe block) instead of disappearing.
    expect(entries).toEqual([
      { kind: "task", taskRow: orphanTaskRow },
      { kind: "global-header" },
      { kind: "labor", assignment, indentLevel: 0 },
    ]);
  });

  it("has no 'global labor' section: a role assignment can never appear in the trailing global section", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const globalLine = makeLine({ id: 100, task_id: null });
    const assignment = makeAssignment({ task_id: 42 });

    const entries = buildEstimateGridEntries([globalLine], [taskRow], [assignment]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "labor", assignment, indentLevel: 1 },
      { kind: "global-header" },
      { kind: "line", line: globalLine, indentLevel: 0 },
    ]);
  });

  it("defaults to no role assignments merged at all when the third argument is omitted", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });

    const entries = buildEstimateGridEntries([], [taskRow]);

    expect(entries).toEqual([{ kind: "task", taskRow }]);
  });

  // Moyenne finding #2 (E12-06/#278): an EstimateRoleAssignment whose task_id matches no
  // EstimateTaskRow of this estimate version must never silently disappear from the grid, unlike
  // what happened before this fix (it stayed in the internal grouping map and was never read
  // back out). It is now folded into the trailing "Lignes globales" section, the same fallback
  // already used for an unattached/orphaned cost line above.
  it("falls back a role assignment with an unmatched task_id into the global section, instead of dropping it", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const orphanedAssignment = makeAssignment({ task_id: 999 });

    const entries = buildEstimateGridEntries([], [taskRow], [orphanedAssignment]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "global-header" },
      { kind: "labor", assignment: orphanedAssignment, indentLevel: 0 },
    ]);
  });

  // E12-07/#289: EstimateRoleAssignmentRead.task_id is now nullable (a "root" labor line with no
  // attached task). There's no UI yet to create one (that's E12-10/#292's scope), but the grid
  // must not silently drop it if the backend ever returns one -- same orphan fallback as above.
  it("falls back a role assignment with a null task_id into the global section, instead of dropping it", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const rootAssignment = makeAssignment({ task_id: null });

    const entries = buildEstimateGridEntries([], [taskRow], [rootAssignment]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "global-header" },
      { kind: "labor", assignment: rootAssignment, indentLevel: 0 },
    ]);
  });

  it("lists an orphaned role assignment ahead of global cost lines within the same global section", () => {
    const taskRow = makeTaskRow({ id: 1, task_id: 42 });
    const orphanedAssignment = makeAssignment({ task_id: 999 });
    const globalLine = makeLine({ id: 100, task_id: null });

    const entries = buildEstimateGridEntries([globalLine], [taskRow], [orphanedAssignment]);

    expect(entries).toEqual([
      { kind: "task", taskRow },
      { kind: "global-header" },
      { kind: "labor", assignment: orphanedAssignment, indentLevel: 0 },
      { kind: "line", line: globalLine, indentLevel: 0 },
    ]);
  });
});
