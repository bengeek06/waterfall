import { describe, expect, it } from "vitest";

import {
  canRedo,
  canUndo,
  commitRedo,
  commitUndo,
  createEmptyPlanningHistory,
  getPlanningHistory,
  peekRedo,
  peekUndo,
  pushCommand,
  MAX_PLANNING_HISTORY_DEPTH,
  resetPlanningHistory,
  setPlanningHistory,
  snapshotFromPlanningDetail,
  type PlanningCommand,
} from "./planning-history";
import type { PlanningDetail } from "./backend";

function makeCommand(id: string): PlanningCommand {
  return {
    id,
    kind: "move",
    label: `Command ${id}`,
    before: { tasks: [], links: [] },
    after: { tasks: [], links: [] },
  };
}

describe("planning-history stacks", () => {
  it("starts empty", () => {
    const history = createEmptyPlanningHistory();
    expect(canUndo(history)).toBe(false);
    expect(canRedo(history)).toBe(false);
  });

  it("pushes a command onto the undo stack and clears any redo stack", () => {
    let history = createEmptyPlanningHistory();
    history = pushCommand(history, makeCommand("a"));
    history = commitUndo(history);
    expect(canRedo(history)).toBe(true);

    history = pushCommand(history, makeCommand("b"));
    expect(canUndo(history)).toBe(true);
    expect(canRedo(history)).toBe(false);
  });

  it("moves the top undo command to redo, and back, in LIFO order", () => {
    let history = createEmptyPlanningHistory();
    history = pushCommand(history, makeCommand("a"));
    history = pushCommand(history, makeCommand("b"));

    expect(peekUndo(history)?.id).toBe("b");
    history = commitUndo(history);
    expect(peekUndo(history)?.id).toBe("a");
    expect(peekRedo(history)?.id).toBe("b");

    history = commitRedo(history);
    expect(peekUndo(history)?.id).toBe("b");
    expect(canRedo(history)).toBe(false);
  });

  it("is a no-op when undoing/redoing an empty stack", () => {
    const history = createEmptyPlanningHistory();
    expect(commitUndo(history)).toBe(history);
    expect(commitRedo(history)).toBe(history);
  });

  it("isolates history per planning_id", () => {
    let byPlanning = {};
    byPlanning = setPlanningHistory(
      byPlanning,
      2,
      pushCommand(createEmptyPlanningHistory(), makeCommand("a")),
    );

    expect(canUndo(getPlanningHistory(byPlanning, 2))).toBe(true);
    expect(canUndo(getPlanningHistory(byPlanning, 6))).toBe(false);

    byPlanning = resetPlanningHistory(byPlanning, 2);
    expect(canUndo(getPlanningHistory(byPlanning, 2))).toBe(false);
  });

  it("keeps only the newest commands when the history exceeds its depth limit", () => {
    let history = createEmptyPlanningHistory();
    for (let index = 0; index <= MAX_PLANNING_HISTORY_DEPTH; index += 1) {
      history = pushCommand(history, makeCommand(String(index)));
    }

    expect(history.undoStack).toHaveLength(MAX_PLANNING_HISTORY_DEPTH);
    expect(history.undoStack[0].id).toBe("1");
    expect(peekUndo(history)?.id).toBe(String(MAX_PLANNING_HISTORY_DEPTH));
  });
});

describe("snapshotFromPlanningDetail", () => {
  it("captures every raw field a restore needs, including ones TaskRead names differently", () => {
    const detail = {
      tasks: [
        {
          id: 1,
          project_id: 1,
          uid: 10,
          id_display: 10,
          structure_key: "1",
          structure_kind: "task",
          parent_uid: null,
          position: 1,
          name: "Task",
          outline_number: "1",
          outline_level: 1,
          wbs: "1",
          start_at: "2026-01-01T08:00:00",
          finish_at: "2026-01-02T08:00:00",
          duration_minutes: 480,
          duration_format: 7,
          work_minutes: 480,
          percent_complete: 0,
          is_summary: false,
          is_milestone: false,
          is_manual: true,
          calendar_uid: null,
          description: "Some notes",
          predecessor_links: [],
        },
      ],
      links: [{ task_uid: 10, predecessor_uid: 5, link_type: 1, lag_tenth_minute: 0, lag_format: 7 }],
    } as unknown as PlanningDetail;

    const snapshot = snapshotFromPlanningDetail(detail);

    expect(snapshot.tasks).toEqual([
      {
        uid: 10,
        id_display: 10,
        structure_key: "1",
        structure_kind: "task",
        parent_uid: null,
        position: 1,
        name: "Task",
        outline_number: "1",
        outline_level: 1,
        wbs: "1",
        start_at: "2026-01-01T08:00:00",
        finish_at: "2026-01-02T08:00:00",
        duration_minutes: 480,
        duration_format: 7,
        work_minutes: 480,
        task_type: null,
        percent_complete: 0,
        is_summary: false,
        is_milestone: false,
        is_manual: true,
        calendar_uid: null,
        notes: "Some notes",
      },
    ]);
    expect(snapshot.links).toEqual([
      { task_uid: 10, predecessor_uid: 5, link_type: 1, lag_tenth_minute: 0, lag_format: 7 },
    ]);
  });
});
