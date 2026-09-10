import { describe, expect, it } from "vitest";

import { buildAttachableTaskOptions } from "@/lib/estimate-task-options";
import type { EstimateTaskRow } from "@/lib/backend";

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

describe("buildAttachableTaskOptions", () => {
  it("excludes a task row with no task_id (no MsTask twin)", () => {
    const rows = [makeTaskRow({ id: 1, task_id: null, task_name: "Sans jumeau" })];

    expect(buildAttachableTaskOptions(rows)).toEqual([]);
  });

  it("includes a task row with a task_id, keyed on the task_id (not the row id)", () => {
    const rows = [makeTaskRow({ id: 5, task_id: 99, task_name: "Terrassement" })];

    expect(buildAttachableTaskOptions(rows)).toEqual([{ value: "99", label: "Terrassement" }]);
  });

  it("sorts options by position, regardless of array order", () => {
    const rows = [
      makeTaskRow({ id: 2, task_id: 20, position: 2, task_name: "Second" }),
      makeTaskRow({ id: 1, task_id: 10, position: 1, task_name: "First" }),
    ];

    expect(buildAttachableTaskOptions(rows).map((option) => option.label)).toEqual(["First", "Second"]);
  });

  it("indents an option's label by its outline_level", () => {
    const rows = [makeTaskRow({ id: 1, task_id: 10, outline_level: 2, task_name: "Sous-tâche" })];

    expect(buildAttachableTaskOptions(rows)).toEqual([{ value: "10", label: "    Sous-tâche" }]);
  });

  it("treats a null outline_level as depth 0 (no indentation)", () => {
    const rows = [makeTaskRow({ id: 1, task_id: 10, outline_level: null, task_name: "Racine" })];

    expect(buildAttachableTaskOptions(rows)).toEqual([{ value: "10", label: "Racine" }]);
  });
});
