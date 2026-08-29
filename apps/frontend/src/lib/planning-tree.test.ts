import { describe, expect, it } from "vitest";

import type { Task } from "./backend";
import {
  computeIndentCommand,
  computeOutdentCommand,
  computeReorderCommand,
  normalizeSelectionToRoots,
} from "./planning-tree";

function task(overrides: Partial<Task>): Task {
  return {
    id: overrides.uid ?? 1,
    project_id: 1,
    uid: 1,
    id_display: null,
    structure_key: null,
    structure_kind: null,
    parent_uid: null,
    position: 1,
    name: "Tâche",
    outline_number: null,
    outline_level: null,
    start_at: null,
    finish_at: null,
    percent_complete: 0,
    is_summary: false,
    is_milestone: false,
    is_manual: true,
    description: null,
    predecessor_links: [],
    ...overrides,
  };
}

// A(1) > [B(1.1), C(1.2)], D(2)
const tasks: Task[] = [
  task({ uid: 1, name: "A", parent_uid: null, position: 1 }),
  task({ uid: 2, name: "B", parent_uid: 1, position: 1 }),
  task({ uid: 3, name: "C", parent_uid: 1, position: 2 }),
  task({ uid: 4, name: "D", parent_uid: null, position: 2 }),
];

describe("normalizeSelectionToRoots", () => {
  it("drops a descendant when its ancestor is also selected", () => {
    const roots = normalizeSelectionToRoots(tasks, new Set([1, 2]));
    expect(roots.map((t) => t.uid)).toEqual([1]);
  });

  it("keeps disjoint selections in tree order", () => {
    const roots = normalizeSelectionToRoots(tasks, new Set([4, 2]));
    expect(roots.map((t) => t.uid)).toEqual([2, 4]);
  });
});

describe("computeIndentCommand", () => {
  it("makes the selection a child of its previous sibling", () => {
    const command = computeIndentCommand(tasks, new Set([4]));
    expect(command).toEqual({ task_uids: [4], target_parent_uid: 1, position: 3 });
  });

  it("returns null when there is no previous sibling", () => {
    expect(computeIndentCommand(tasks, new Set([1]))).toBeNull();
  });
});

describe("computeOutdentCommand", () => {
  it("moves the selection next to its former parent", () => {
    const command = computeOutdentCommand(tasks, new Set([3]));
    expect(command).toEqual({ task_uids: [3], target_parent_uid: null, position: 2 });
  });

  it("returns null for a root task", () => {
    expect(computeOutdentCommand(tasks, new Set([1]))).toBeNull();
  });
});

describe("computeReorderCommand", () => {
  it("moves a task before its previous sibling", () => {
    const command = computeReorderCommand(tasks, new Set([3]), "up");
    expect(command).toEqual({ task_uids: [3], target_parent_uid: 1, position: 1 });
  });

  it("moves a task after its next sibling", () => {
    const command = computeReorderCommand(tasks, new Set([2]), "down");
    expect(command).toEqual({ task_uids: [2], target_parent_uid: 1, position: 2 });
  });

  it("returns null when already first and moving up", () => {
    expect(computeReorderCommand(tasks, new Set([2]), "up")).toBeNull();
  });

  it("returns null when already last and moving down", () => {
    expect(computeReorderCommand(tasks, new Set([3]), "down")).toBeNull();
  });

  it("returns null for a non-contiguous multi-selection", () => {
    expect(computeReorderCommand(tasks, new Set([1, 3]), "up")).toBeNull();
  });

  it("returns null when selection spans different parents", () => {
    expect(computeReorderCommand(tasks, new Set([2, 4]), "up")).toBeNull();
  });
});
