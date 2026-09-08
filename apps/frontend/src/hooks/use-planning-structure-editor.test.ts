import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  savePlanningStructureDraft: vi.fn(),
  skipPlanningStructure: vi.fn(),
  listPlannings: vi.fn(),
  getPlanning: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    savePlanningStructureDraft: mocks.savePlanningStructureDraft,
    skipPlanningStructure: mocks.skipPlanningStructure,
    listPlannings: mocks.listPlannings,
    getPlanning: mocks.getPlanning,
  };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import { usePlanningStructureEditor } from "@/hooks/use-planning-structure-editor";

const session = { accessToken: "test-token" };

function baseParams(overrides: Partial<Parameters<typeof usePlanningStructureEditor>[0]> = {}) {
  const router = { push: vi.fn() };
  return {
    session,
    projectId: 1,
    isReadOnlyProject: false,
    onSessionRefresh: vi.fn(),
    router: router as never,
    setError: vi.fn(),
    setProject: vi.fn(),
    setPlannings: vi.fn(),
    updateSelectedPlanningId: vi.fn(),
    setPlanningDetail: vi.fn(),
    setStructureOpen: vi.fn(),
    ...overrides,
  };
}

// Fills in the default single draft row (post/lot/deliverable) so
// `getPlanningStructurePayload`'s completeness guard doesn't short-circuit
// before the network call this file's regression tests exercise.
function fillDraftRow(result: { current: ReturnType<typeof usePlanningStructureEditor> }) {
  act(() => {
    result.current.updatePostField("post-1", "postName", "Poste 1");
    result.current.updateLotField("row-1", "lotName", "Lot 1");
    result.current.updateDeliverable("row-1", 0, "Livrable 1");
  });
}

describe("usePlanningStructureEditor", () => {
  beforeEach(() => {
    mocks.savePlanningStructureDraft.mockReset();
    mocks.skipPlanningStructure.mockReset();
    mocks.listPlannings.mockReset();
    mocks.getPlanning.mockReset();
    mocks.clearSession.mockReset();
  });

  // Regression test for #216: a refresh can succeed yet the retried request still
  // come back 401 (account disabled/deleted between the two calls, server-side
  // race) -- authFetch then rejects with a plain ApiError, not a
  // SessionExpiredError. `savePlanningStructure` must still detect that as a
  // session expiry (clearSession + redirect), not surface it as a generic error.
  it("clears the session and redirects to login on a post-refresh 401 ApiError (savePlanningStructure), instead of showing a generic error", async () => {
    mocks.savePlanningStructureDraft.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const params = baseParams();
    const { result } = renderHook(() => usePlanningStructureEditor(params));
    fillDraftRow(result);

    await act(async () => {
      await result.current.savePlanningStructure();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect((params.router as unknown as { push: ReturnType<typeof vi.fn> }).push).toHaveBeenCalledWith("/login");
    expect(params.setError).not.toHaveBeenCalledWith("Impossible d'enregistrer la structure.");
  });

  // Covers the one nested try/catch in this file (`refreshCause`, inside
  // skipStructure's best-effort post-skip planning reload): it must detect a
  // post-refresh 401 ApiError the same way as every other site.
  it("clears the session and redirects to login on a post-refresh 401 ApiError from the nested listPlannings retry (skipStructure)", async () => {
    mocks.skipPlanningStructure.mockResolvedValue({ id: 1, displayed_planning_id: null });
    mocks.listPlannings.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const params = baseParams();
    const { result } = renderHook(() => usePlanningStructureEditor(params));

    await act(async () => {
      await result.current.skipStructure();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect((params.router as unknown as { push: ReturnType<typeof vi.fn> }).push).toHaveBeenCalledWith("/login");
    expect(params.setError).not.toHaveBeenCalledWith(
      "Passage effectué, mais impossible de recharger le planning. Recharge la page.",
    );
  });
});
