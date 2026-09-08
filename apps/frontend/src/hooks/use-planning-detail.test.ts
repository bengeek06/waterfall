import { describe, expect, it, vi } from "vitest";

import type { PlanningDetail, PlanningStructureDraftRead } from "@/lib/backend";
import { createEmptyPlanningHistory, type PlanningHistoryState } from "@/lib/planning-history";

import {
  deriveStructureDraftRows,
  isPlanningLoadResultCurrent,
  isPlanningLoadStillActive,
  recordRevisionConflictIfAny,
  type PlanningRevisionConflict,
} from "@/hooks/use-planning-detail";

function makeDetail(overrides: Partial<PlanningDetail> = {}): PlanningDetail {
  return { revision: 1, tasks: [], links: [], ...overrides } as PlanningDetail;
}

function makeTask(overrides: Partial<PlanningDetail["tasks"][number]>): PlanningDetail["tasks"][number] {
  return {
    id: 1,
    project_id: 1,
    uid: 1,
    name: "",
    is_summary: false,
    is_milestone: false,
    ...overrides,
  } as PlanningDetail["tasks"][number];
}

function makeDraft(deliverables: { key: string; name: string }[]): PlanningStructureDraftRead {
  return {
    planning_id: 1,
    structure: {
      posts: [
        {
          key: "P1",
          name: "Post 1",
          lots: [
            {
              key: "L1",
              name: "Lot 1",
              deliverables,
            },
          ],
        },
      ],
    },
  } as PlanningStructureDraftRead;
}

describe("deriveStructureDraftRows", () => {
  it("uses the saved draft's rows when a saved draft is present and complete", () => {
    const draft = makeDraft([{ key: "D1", name: "Livrable 1" }]);
    const detail = makeDetail();

    const rows = deriveStructureDraftRows(draft, detail);

    expect(rows).not.toBeNull();
    expect(rows).toEqual([
      {
        rowId: "P1/L1",
        postKey: "P1",
        postName: "Post 1",
        lotKey: "L1",
        lotName: "Lot 1",
        deliverables: "Livrable 1",
        deliverableKeys: { "Livrable 1": "D1" },
      },
    ]);
  });

  it("falls back to the rows inferred from the planning detail when there is no saved draft", () => {
    const detail = makeDetail({
      tasks: [
        makeTask({ uid: 1, name: "Post 1", structure_kind: "poste", structure_key: "P1" }),
        makeTask({ uid: 2, name: "Lot 1", structure_kind: "lot", structure_key: "P1/L1" }),
        makeTask({ uid: 3, name: "Livrable 1", structure_kind: "livrable", structure_key: "P1/L1/D1" }),
      ],
    });

    const rows = deriveStructureDraftRows(null, detail);

    expect(rows).not.toBeNull();
    expect(rows).toEqual([
      {
        rowId: "P1/L1",
        postKey: "P1",
        postName: "Post 1",
        lotKey: "L1",
        lotName: "Lot 1",
        deliverables: "Livrable 1",
        deliverableKeys: { "Livrable 1": "D1" },
      },
    ]);
  });

  it("returns null when there is no saved draft and no tasks to infer rows from", () => {
    const detail = makeDetail({ tasks: [] });

    const rows = deriveStructureDraftRows(null, detail);

    expect(rows).toBeNull();
  });

  it("returns null (leaving the current draft untouched) when a row is incomplete", () => {
    const draft = makeDraft([]);
    const detail = makeDetail();

    const rows = deriveStructureDraftRows(draft, detail);

    expect(rows).toBeNull();
  });
});

describe("recordRevisionConflictIfAny", () => {
  it("records a conflict when the tracked history revision differs from the detail's revision", () => {
    const history: PlanningHistoryState = { ...createEmptyPlanningHistory(), revision: 3 };
    const detail = makeDetail({ revision: 5 });
    const setPlanningConflictByPlanningId = vi.fn();

    recordRevisionConflictIfAny(history, detail, 7, 1, setPlanningConflictByPlanningId);

    expect(setPlanningConflictByPlanningId).toHaveBeenCalledTimes(1);
    const updater = setPlanningConflictByPlanningId.mock.calls[0][0] as (
      previous: Record<number, PlanningRevisionConflict>,
    ) => Record<number, PlanningRevisionConflict>;
    expect(updater({})).toEqual({
      7: {
        projectId: 1,
        expectedRevision: 3,
        currentRevision: 5,
        message: "Ce planning a été modifié entre-temps : recharge-le avant de continuer.",
      },
    });
  });

  it("does not record a conflict when the revisions match", () => {
    const history: PlanningHistoryState = { ...createEmptyPlanningHistory(), revision: 5 };
    const detail = makeDetail({ revision: 5 });
    const setPlanningConflictByPlanningId = vi.fn();

    recordRevisionConflictIfAny(history, detail, 7, 1, setPlanningConflictByPlanningId);

    expect(setPlanningConflictByPlanningId).not.toHaveBeenCalled();
  });

  it("does not record a conflict when the history has no tracked revision yet", () => {
    const history = createEmptyPlanningHistory();
    const detail = makeDetail({ revision: 5 });
    const setPlanningConflictByPlanningId = vi.fn();

    recordRevisionConflictIfAny(history, detail, 7, 1, setPlanningConflictByPlanningId);

    expect(setPlanningConflictByPlanningId).not.toHaveBeenCalled();
  });
});

describe("isPlanningLoadStillActive", () => {
  it("is true when not cancelled and the generation still matches", () => {
    expect(isPlanningLoadStillActive(false, 2, 2)).toBe(true);
  });

  it("is false when cancelled", () => {
    expect(isPlanningLoadStillActive(true, 2, 2)).toBe(false);
  });

  it("is false when the generation no longer matches", () => {
    expect(isPlanningLoadStillActive(false, 2, 3)).toBe(false);
  });
});

describe("isPlanningLoadResultCurrent", () => {
  it("is true when not cancelled, the generation matches and the selection hasn't moved on", () => {
    expect(isPlanningLoadResultCurrent(false, 2, 2, 9, 9)).toBe(true);
  });

  it("is false when cancelled", () => {
    expect(isPlanningLoadResultCurrent(true, 2, 2, 9, 9)).toBe(false);
  });

  it("is false when the generation no longer matches", () => {
    expect(isPlanningLoadResultCurrent(false, 2, 3, 9, 9)).toBe(false);
  });

  it("is false when the selection has moved on to a different planning", () => {
    expect(isPlanningLoadResultCurrent(false, 2, 2, 11, 9)).toBe(false);
  });
});
