import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EstimateTaskRow } from "@/lib/backend";
import type { EstimateGridTaskRow } from "@/lib/estimate-grid-tree";
import { useEstimateGridDrafts } from "@/hooks/use-estimate-grid-drafts";

function makeTaskRow(overrides: Partial<EstimateTaskRow> = {}): EstimateGridTaskRow {
  const taskRow = {
    id: 1,
    estimate_id: 1,
    task_id: 42,
    task_uid: 99,
    parent_task_id: null,
    position: 1,
    task_name: "Terrassement",
    outline_number: "1.1",
    outline_level: 1,
    is_milestone: false,
    ...overrides,
  } as EstimateTaskRow;
  return {
    kind: "task",
    uid: taskRow.task_id ?? null,
    parentUid: null,
    rowNumber: 1,
    depth: 0,
    hasChildren: false,
    taskRow,
  };
}

// Critique review finding on #292: this tree's own `uid` (row.uid, built from `task_id` --
// `MsTask.id`, the global PK, see lib/estimate-grid-tree.ts's own doc comment) is deliberately
// NOT the identifier the rename endpoint (`onRenameTask` -> updateTaskName ->
// `PATCH .../tasks/{taskUid}`) resolves against -- that's `task_uid`, the project-scoped
// business identifier `EstimateTaskRowRead` exposes separately. `commitLabel` must always call
// `onRenameTask` with `taskRow.task_uid`, never `row.uid`.
describe("useEstimateGridDrafts commitLabel (task rows)", () => {
  it("commits with the row's task_uid, not its tree uid (task_id), when the two differ", async () => {
    const onRenameTask = vi.fn().mockResolvedValue(true);
    const row = makeTaskRow({ task_id: 42, task_uid: 99 });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onRenameTask }));

    act(() => {
      result.current.updateDraftField(row, "label", "Terrassement lot 2");
    });

    await act(async () => {
      await result.current.commitLabel(row);
    });

    // Would have been called with 42 (row.uid / task_id) before the fix -- asserting the
    // negative too so a regression back to `row.uid` fails loudly instead of passing by
    // coincidence (task_id and task_uid can collide for the very first task ever created).
    expect(onRenameTask).toHaveBeenCalledWith(99, "Terrassement lot 2");
    expect(onRenameTask).not.toHaveBeenCalledWith(42, expect.anything());
  });

  it("clears the draft without calling onRenameTask when the row has no task_uid", async () => {
    const onRenameTask = vi.fn();
    const row = makeTaskRow({ task_id: 42, task_uid: null });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onRenameTask }));

    act(() => {
      result.current.updateDraftField(row, "label", "Terrassement lot 2");
    });

    await act(async () => {
      await result.current.commitLabel(row);
    });

    expect(onRenameTask).not.toHaveBeenCalled();
    expect(result.current.draftFor(row).label).toBe(row.taskRow.task_name);
  });

  it("does not commit, and keeps the draft pending, while a mutation is already in flight", async () => {
    const onRenameTask = vi.fn().mockResolvedValue(true);
    const row = makeTaskRow();
    const { result, rerender } = renderHook(
      ({ mutationBusy }: { mutationBusy: boolean }) => useEstimateGridDrafts({ mutationBusy, onRenameTask }),
      { initialProps: { mutationBusy: false } },
    );

    act(() => {
      result.current.updateDraftField(row, "label", "Terrassement lot 2");
    });
    rerender({ mutationBusy: true });

    await act(async () => {
      await result.current.commitLabel(row);
    });

    expect(onRenameTask).not.toHaveBeenCalled();
  });
});
