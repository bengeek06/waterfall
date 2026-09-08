import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project, ProjectEstimate } from "@/lib/backend";
import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  createProjectEstimate: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return { ...actual, createProjectEstimate: mocks.createProjectEstimate };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import { useEstimateCostLines } from "@/hooks/use-estimate-cost-lines";

const session = { accessToken: "test-token" };
const project = { id: 1, name: "Projet A", currency_code: "EUR" } as Project;

function setup() {
  const router = { push: vi.fn() };
  const setError = vi.fn();
  const { result } = renderHook(() =>
    useEstimateCostLines({
      session,
      project,
      projectId: 1,
      selectedEstimateId: null,
      estimates: [] as ProjectEstimate[],
      setEstimates: vi.fn(),
      setSelectedEstimateId: vi.fn(),
      setActiveTab: vi.fn(),
      setCostLines: vi.fn(),
      onSessionRefresh: vi.fn(),
      router: router as never,
      setError,
    }),
  );
  return { result, router, setError };
}

describe("useEstimateCostLines createDraftEstimate", () => {
  beforeEach(() => {
    mocks.createProjectEstimate.mockReset();
    mocks.clearSession.mockReset();
  });

  // Regression test for #216: a refresh can succeed yet the retried request still
  // come back 401 (account disabled/deleted between the two calls, server-side
  // race) -- authFetch then rejects with a plain ApiError, not a
  // SessionExpiredError. Every mutation handler in this hook must still detect
  // that as a session expiry (clearSession + redirect), not surface it as a
  // generic business error. `createDraftEstimate` is exercised here as the
  // shared/reusable path for the 6 identical catch blocks in this file.
  it("clears the session and redirects to login on a post-refresh 401 ApiError, instead of showing a generic error", async () => {
    mocks.createProjectEstimate.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const { result, router, setError } = setup();

    await act(async () => {
      await result.current.createDraftEstimate();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
    expect(setError).not.toHaveBeenCalledWith("Impossible de créer le devis.");
  });
});
