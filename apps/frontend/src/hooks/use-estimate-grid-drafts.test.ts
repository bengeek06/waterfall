import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RevisionNode } from "@/lib/backend";
import { buildRevisionTreeRows } from "@/lib/revision-tree";
import type { RevisionCostGridRow } from "@/lib/revision-cost-grid";
import { useEstimateGridDrafts } from "@/hooks/use-estimate-grid-drafts";

function taskRow(nodeId = 1, name = "Terrassement"): RevisionCostGridRow {
  const node: RevisionNode = {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "task",
    parent_id: null,
    position: 1,
    row_number: nodeId,
    level: 1,
    external_uid: null,
    description: null,
    planning: {
      name,
      calendar_id: null,
      calendar_source: null,
      is_milestone: false,
      duration_minutes: 480,
      duration_format: null,
      start_at: null,
      finish_at: null,
      work_minutes: null,
      percent_complete: 0,
      is_manual: true,
    },
    cost: null,
    predecessors: [],
  };
  return buildRevisionTreeRows([node])[0];
}

function costRow(
  options: { nodeId?: number; nature?: "labor" | "non_labor"; label?: string; quantity?: string; hours?: string | null; unitCost?: string | null } = {},
): RevisionCostGridRow {
  const nature = options.nature ?? "non_labor";
  const nodeId = options.nodeId ?? 2;
  const node: RevisionNode = {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "cost",
    parent_id: null,
    position: 1,
    row_number: nodeId,
    level: 1,
    external_uid: null,
    description: null,
    planning: null,
    cost: {
      nature,
      label: options.label ?? "Béton",
      // Deliberately in the "2.00" shape the API really serialises Decimals in: a commit must
      // compare numbers, not strings, or every blur would re-send an unchanged value.
      quantity: options.quantity ?? "2.00",
      role_id: nature === "labor" ? 7 : null,
      hours: nature === "labor" ? (options.hours ?? "10.00") : null,
      cost_type_id: nature === "labor" ? null : 1,
      cost_category_id: nature === "labor" ? null : 4,
      unit_cost: nature === "labor" ? null : (options.unitCost ?? "50.00"),
      supply_status: null,
      planned_date: null,
      cost_code_id: null,
      comment: null,
      bearing_task_node_id: null,
      bearing_task_name: null,
    },
    predecessors: [],
  };
  return buildRevisionTreeRows([node])[0];
}

describe("useEstimateGridDrafts", () => {
  it("renames a task through its planning facet, on the node the row is", async () => {
    const onUpdatePlanning = vi.fn().mockResolvedValue(true);
    const row = taskRow(11, "Terrassement");
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdatePlanning }));

    act(() => result.current.updateDraftField(row, "label", "Terrassement lot 2"));
    await act(async () => {
      await result.current.commitLabel(row);
    });

    expect(onUpdatePlanning).toHaveBeenCalledWith(11, { name: "Terrassement lot 2" });
  });

  it("edits a cost line's label through its cost facet instead", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow({ nodeId: 12, label: "Béton" });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "label", "Béton armé"));
    await act(async () => {
      await result.current.commitLabel(row);
    });

    expect(onUpdateCost).toHaveBeenCalledWith(12, { label: "Béton armé" });
  });

  it("sends only the field that was left, never the whole row", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow({ nodeId: 12 });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "unitCost", "75"));
    await act(async () => {
      await result.current.commitUnitCost(row);
    });

    expect(onUpdateCost).toHaveBeenCalledWith(12, { unit_cost: 75 });
  });

  it("does not write a quantité the contract refuses, and keeps what was typed on screen", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow();
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "quantity", "0"));
    await act(async () => {
      await result.current.commitQuantity(row);
    });

    expect(onUpdateCost).not.toHaveBeenCalled();
    expect(result.current.draftFor(row).quantity).toBe("0");
  });

  it("does not re-send a value the user retyped identically", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow({ quantity: "2.00" });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "quantity", "2"));
    await act(async () => {
      await result.current.commitQuantity(row);
    });

    expect(onUpdateCost).not.toHaveBeenCalled();
  });

  // INV-19 / INV-20: the two natures have disjoint attribute sets, and a commit must not write a
  // field the row's nature forbids even if a stale draft holds one.
  it("never writes heures on a non-MO line", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow({ nature: "non_labor" });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "hours", "8"));
    await act(async () => {
      await result.current.commitHours(row);
    });

    expect(onUpdateCost).not.toHaveBeenCalled();
  });

  it("never writes a débours on an MO line", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow({ nature: "labor" });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "unitCost", "75"));
    await act(async () => {
      await result.current.commitUnitCost(row);
    });

    expect(onUpdateCost).not.toHaveBeenCalled();
  });

  it("writes heures on an MO line", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow({ nodeId: 13, nature: "labor", hours: "10.00" });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "hours", "8"));
    await act(async () => {
      await result.current.commitHours(row);
    });

    expect(onUpdateCost).toHaveBeenCalledWith(13, { hours: 8 });
  });

  it("keeps the draft on a refused write instead of falling back to the stale stored value", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(false);
    const row = costRow({ label: "Béton" });
    const { result } = renderHook(() => useEstimateGridDrafts({ mutationBusy: false, onUpdateCost }));

    act(() => result.current.updateDraftField(row, "label", "Béton armé"));
    await act(async () => {
      await result.current.commitLabel(row);
    });

    expect(result.current.draftFor(row).label).toBe("Béton armé");
  });

  it("does not commit while a mutation is already in flight", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const row = costRow();
    const { result, rerender } = renderHook(
      ({ mutationBusy }: { mutationBusy: boolean }) => useEstimateGridDrafts({ mutationBusy, onUpdateCost }),
      { initialProps: { mutationBusy: false } },
    );

    act(() => result.current.updateDraftField(row, "label", "Béton armé"));
    rerender({ mutationBusy: true });
    await act(async () => {
      await result.current.commitLabel(row);
    });

    expect(onUpdateCost).not.toHaveBeenCalled();
  });
});
