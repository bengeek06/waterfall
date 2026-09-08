import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Planning } from "@/lib/backend";
import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  setDisplayedPlanning: vi.fn(),
  createPlanning: vi.fn(),
  listPlannings: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    setDisplayedPlanning: mocks.setDisplayedPlanning,
    createPlanning: mocks.createPlanning,
    listPlannings: mocks.listPlannings,
  };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import { usePlanningTreeMutations } from "@/hooks/use-planning-tree-mutations";

const session = { accessToken: "test-token" };

function baseParams(overrides: Partial<Parameters<typeof usePlanningTreeMutations>[0]> = {}) {
  const router = { push: vi.fn() };
  return {
    session,
    projectId: 1,
    setProject: vi.fn(),
    setPlannings: vi.fn(),
    selectedPlanningId: 1,
    selectedPlanning: { id: 1, status: "validated" } as Planning,
    isReadOnlyProject: false,
    planningDetail: null,
    setPlanningDetail: vi.fn(),
    selectedPlanningIdRef: { current: 1 },
    updateSelectedPlanningId: vi.fn(),
    setHistoryByPlanningId: vi.fn(),
    planningConflictByPlanningId: {},
    setPlanningConflictByPlanningId: vi.fn(),
    onSessionRefresh: vi.fn(),
    router: router as never,
    setError: vi.fn(),
    setRetryableAction: vi.fn(),
    setRetryableError: vi.fn(),
    setPlanningBusy: vi.fn(),
    setPlanningDetailBusy: vi.fn(),
    setPlanningMutationBusy: vi.fn(),
    setStructureDraft: vi.fn(),
    setStructureOpen: vi.fn(),
    ...overrides,
  };
}

describe("usePlanningTreeMutations", () => {
  beforeEach(() => {
    mocks.setDisplayedPlanning.mockReset();
    mocks.createPlanning.mockReset();
    mocks.listPlannings.mockReset();
    mocks.clearSession.mockReset();
  });

  // Regression tests for #216: a refresh can succeed yet the retried request still
  // come back 401 (account disabled/deleted between the two calls, server-side
  // race) -- authFetch then rejects with a plain ApiError, not a
  // SessionExpiredError. Every mutation handler in this hook must still detect
  // that as a session expiry (clearSession + redirect), not surface it as a
  // generic business error. `selectPlanning` is exercised here as the
  // shared/reusable path for the 10 similarly-shaped top-level catch blocks in
  // this file.
  it("clears the session and redirects to login on a post-refresh 401 ApiError (selectPlanning), instead of showing a generic error", async () => {
    mocks.setDisplayedPlanning.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const params = baseParams({ selectedPlanningId: 1, selectedPlanning: { id: 1, status: "draft" } as Planning });
    const { result } = renderHook(() => usePlanningTreeMutations(params));

    await act(async () => {
      await result.current.selectPlanning(2);
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect((params.router as unknown as { push: ReturnType<typeof vi.fn> }).push).toHaveBeenCalledWith("/login");
    expect(params.setError).not.toHaveBeenCalledWith("Impossible de sélectionner le planning.");
  });

  // Covers the one nested try/catch in this file (`refreshCause`, inside
  // createPlanningVersionFromSelected's best-effort listPlannings retry): it must
  // detect a post-refresh 401 ApiError the same way as every other site.
  it("clears the session and redirects to login on a post-refresh 401 ApiError from the nested listPlannings retry (createPlanningVersionFromSelected)", async () => {
    mocks.createPlanning.mockResolvedValue({ id: 2, revision: 1, tasks: [], links: [] });
    mocks.setDisplayedPlanning.mockRejectedValue(new Error("displayed-planning-network-error"));
    mocks.listPlannings.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const params = baseParams({ selectedPlanning: { id: 1, status: "validated" } as Planning });
    const { result } = renderHook(() => usePlanningTreeMutations(params));

    await act(async () => {
      await result.current.createPlanningVersionFromSelected();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect((params.router as unknown as { push: ReturnType<typeof vi.fn> }).push).toHaveBeenCalledWith("/login");
    expect(params.setError).not.toHaveBeenCalledWith(
      "Le brouillon a été créé mais son affichage a échoué : sélectionne-le manuellement dans la liste des versions.",
    );
  });
});
