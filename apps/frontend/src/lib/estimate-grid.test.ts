import { describe, expect, it } from "vitest";

import { buildEstimateGridEntries } from "@/lib/estimate-grid";
import type { EstimateCostLine, EstimateTaskRow } from "@/lib/backend";

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
