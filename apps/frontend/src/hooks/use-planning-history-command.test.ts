import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/backend";
import type { Planning, PlanningDetail } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  restorePlanningSnapshot: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return { ...actual, restorePlanningSnapshot: mocks.restorePlanningSnapshot };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import {
  buildPlanningHistoryErrorMessage,
  canApplyPlanningHistoryCommand,
  usePlanningHistoryCommand,
} from "@/hooks/use-planning-history-command";

const session = { accessToken: "test-token" };

function makePlanning(overrides: Partial<Planning> = {}): Planning {
  return { id: 1, status: "draft", ...overrides } as Planning;
}

function makeDetail(overrides: Partial<PlanningDetail> = {}): PlanningDetail {
  return { id: 1, revision: 1, ...overrides } as PlanningDetail;
}

describe("canApplyPlanningHistoryCommand", () => {
  it("is true when the session exists, the selected planning is a draft, the project isn't read-only and the detail matches", () => {
    const result = canApplyPlanningHistoryCommand({
      session,
      selectedPlanning: makePlanning(),
      isReadOnlyProject: false,
      planningDetail: makeDetail(),
    });

    expect(result).toBe(true);
  });

  it("is false when there is no session", () => {
    const result = canApplyPlanningHistoryCommand({
      session: null,
      selectedPlanning: makePlanning(),
      isReadOnlyProject: false,
      planningDetail: makeDetail(),
    });

    expect(result).toBe(false);
  });

  it("is false when there is no selected planning", () => {
    const result = canApplyPlanningHistoryCommand({
      session,
      selectedPlanning: null,
      isReadOnlyProject: false,
      planningDetail: makeDetail(),
    });

    expect(result).toBe(false);
  });

  it("is false when the selected planning isn't a draft", () => {
    const result = canApplyPlanningHistoryCommand({
      session,
      selectedPlanning: makePlanning({ status: "validated" }),
      isReadOnlyProject: false,
      planningDetail: makeDetail(),
    });

    expect(result).toBe(false);
  });

  it("is false when the project is read-only", () => {
    const result = canApplyPlanningHistoryCommand({
      session,
      selectedPlanning: makePlanning(),
      isReadOnlyProject: true,
      planningDetail: makeDetail(),
    });

    expect(result).toBe(false);
  });

  it("is false when there is no loaded planning detail", () => {
    const result = canApplyPlanningHistoryCommand({
      session,
      selectedPlanning: makePlanning(),
      isReadOnlyProject: false,
      planningDetail: null,
    });

    expect(result).toBe(false);
  });

  it("is false when the loaded planning detail doesn't match the selected planning", () => {
    const result = canApplyPlanningHistoryCommand({
      session,
      selectedPlanning: makePlanning({ id: 1 }),
      isReadOnlyProject: false,
      planningDetail: makeDetail({ id: 2 }),
    });

    expect(result).toBe(false);
  });
});

describe("buildPlanningHistoryErrorMessage", () => {
  it("returns the backend's message when the failure is an ApiError", () => {
    const cause = new ApiError(409, "Le planning a été verrouillé.");

    expect(buildPlanningHistoryErrorMessage(cause, "undo")).toBe("Le planning a été verrouillé.");
  });

  it("returns the generic undo message for a non-ApiError failure in the undo direction", () => {
    const cause = new Error("network down");

    expect(buildPlanningHistoryErrorMessage(cause, "undo")).toBe(
      "Impossible d'annuler la dernière modification.",
    );
  });

  it("returns the generic redo message for a non-ApiError failure in the redo direction", () => {
    const cause = new Error("network down");

    expect(buildPlanningHistoryErrorMessage(cause, "redo")).toBe(
      "Impossible de rétablir la modification annulée.",
    );
  });
});

describe("usePlanningHistoryCommand applyPlanningHistoryCommand", () => {
  beforeEach(() => {
    mocks.restorePlanningSnapshot.mockReset();
    mocks.clearSession.mockReset();
  });

  // Regression test for #216: a refresh can succeed yet the retried request still
  // come back 401 (account disabled/deleted between the two calls, server-side
  // race) -- authFetch then rejects with a plain ApiError, not a
  // SessionExpiredError. applyPlanningHistoryCommand must still detect that as a
  // session expiry (clearSession + redirect), not surface it as a generic error.
  it("clears the session and redirects to login on a post-refresh 401 ApiError, instead of showing a generic error", async () => {
    mocks.restorePlanningSnapshot.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const router = { push: vi.fn() };
    const setRetryableError = vi.fn();
    const historyByPlanningId = {
      1: {
        undoStack: [
          {
            id: "cmd-1",
            kind: "move" as const,
            label: "Déplacement",
            before: { tasks: [], links: [] },
            after: { tasks: [], links: [] },
          },
        ],
        redoStack: [],
        revision: 1,
      },
    };

    const { result } = renderHook(() =>
      usePlanningHistoryCommand({
        session,
        selectedPlanning: makePlanning(),
        isReadOnlyProject: false,
        planningDetail: makeDetail(),
        historyByPlanningId,
        projectId: 1,
        onSessionRefresh: vi.fn(),
        router: router as never,
        selectedPlanningIdRef: { current: 1 },
        setPlanningMutationBusy: vi.fn(),
        setError: vi.fn(),
        setRetryableAction: vi.fn(),
        setPlanningDetail: vi.fn(),
        setPlanningConflictByPlanningId: vi.fn(),
        setHistoryByPlanningId: vi.fn(),
        setRetryableError,
      }),
    );

    await act(async () => {
      await result.current("undo");
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
    expect(setRetryableError).not.toHaveBeenCalled();
  });
});
