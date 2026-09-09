import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EstimateCostLine, Project, ProjectCostCode, ProjectEstimate } from "@/lib/backend";
import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  createProjectEstimate: vi.fn(),
  updateEstimateCostLine: vi.fn(),
  deleteEstimateCostLine: vi.fn(),
  getProjectCostCodes: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    createProjectEstimate: mocks.createProjectEstimate,
    updateEstimateCostLine: mocks.updateEstimateCostLine,
    deleteEstimateCostLine: mocks.deleteEstimateCostLine,
    getProjectCostCodes: mocks.getProjectCostCodes,
  };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import { useEstimateCostLines } from "@/hooks/use-estimate-cost-lines";

const session = { accessToken: "test-token" };
const project = { id: 1, name: "Projet A", currency_code: "EUR" } as Project;

type SetCostLines = (updater: (previous: EstimateCostLine[]) => EstimateCostLine[]) => void;

function setup(overrides: { selectedEstimateId?: number | null } = {}) {
  const router = { push: vi.fn() };
  const setError = vi.fn();
  const setCostLines = vi.fn<SetCostLines>();
  const { result, rerender } = renderHook(
    (props: { selectedEstimateId: number | null }) =>
      useEstimateCostLines({
        session,
        project,
        projectId: 1,
        selectedEstimateId: props.selectedEstimateId,
        estimates: [] as ProjectEstimate[],
        setEstimates: vi.fn(),
        setSelectedEstimateId: vi.fn(),
        setActiveTab: vi.fn(),
        setCostLines,
        onSessionRefresh: vi.fn(),
        router: router as never,
        setError,
      }),
    { initialProps: { selectedEstimateId: overrides.selectedEstimateId ?? null } },
  );
  return { result, rerender, router, setError, setCostLines };
}

describe("useEstimateCostLines createDraftEstimate", () => {
  beforeEach(() => {
    mocks.createProjectEstimate.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
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

function makeLine(id: number, overrides: Partial<EstimateCostLine> = {}): EstimateCostLine {
  return { id, label: `Ligne ${id}`, cost_code_id: null, ...overrides } as EstimateCostLine;
}

const costCodes = [{ id: 10, code: "1.1", name: "Terrassement" }] as ProjectCostCode[];

describe("useEstimateCostLines bulkAssignCostCode", () => {
  beforeEach(() => {
    mocks.updateEstimateCostLine.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue(costCodes);
  });

  it("loads the project's cost codes once, exposed for the bulk-assignment selector", async () => {
    const { result } = setup({ selectedEstimateId: 1 });

    await waitFor(() => expect(result.current.projectCostCodes).toEqual(costCodes));
    expect(mocks.getProjectCostCodes).toHaveBeenCalledWith(1, session, expect.any(Function));
  });

  it("assigns the chosen cost code to every selected line via one PATCH each, and updates costLines for each success", async () => {
    mocks.updateEstimateCostLine.mockImplementation((_projectId, _estimateId, lineId) =>
      Promise.resolve(makeLine(lineId, { cost_code_id: 10 })),
    );
    const { result, setCostLines } = setup({ selectedEstimateId: 1 });
    await waitFor(() => expect(result.current.projectCostCodes).toEqual(costCodes));

    act(() => {
      result.current.setSelectedCostLineIds(new Set([1, 2]));
      result.current.updateBulkCostCodeId("10");
    });

    await act(async () => {
      await result.current.bulkAssignCostCode();
    });

    expect(mocks.updateEstimateCostLine).toHaveBeenCalledTimes(2);
    expect(mocks.updateEstimateCostLine).toHaveBeenCalledWith(1, 1, 1, { cost_code_id: 10 }, session, expect.any(Function));
    expect(mocks.updateEstimateCostLine).toHaveBeenCalledWith(1, 1, 2, { cost_code_id: 10 }, session, expect.any(Function));

    // Every successful update is folded into `costLines` via the same
    // `setCostLines((previous) => ...)` updater pattern as `saveCostLine`.
    let lines = [makeLine(1), makeLine(2), makeLine(3)];
    for (const call of setCostLines.mock.calls) {
      const updater = call[0] as (previous: EstimateCostLine[]) => EstimateCostLine[];
      lines = updater(lines);
    }
    expect(lines.find((line) => line.id === 1)?.cost_code_id).toBe(10);
    expect(lines.find((line) => line.id === 2)?.cost_code_id).toBe(10);
    expect(lines.find((line) => line.id === 3)?.cost_code_id).toBeNull();

    // The selection is cleared after the operation, whether it fully or partially succeeded.
    expect(result.current.selectedCostLineIds.size).toBe(0);
  });

  it("reports a partial failure without discarding the lines that did succeed", async () => {
    mocks.updateEstimateCostLine.mockImplementation((_projectId, _estimateId, lineId) => {
      if (lineId === 2) {
        return Promise.reject(new ApiError(409, "Ligne verrouillée"));
      }
      return Promise.resolve(makeLine(lineId, { cost_code_id: 10 }));
    });
    const { result, setError } = setup({ selectedEstimateId: 1 });
    await waitFor(() => expect(result.current.projectCostCodes).toEqual(costCodes));

    act(() => {
      result.current.setSelectedCostLineIds(new Set([1, 2]));
      result.current.updateBulkCostCodeId("10");
    });

    await act(async () => {
      await result.current.bulkAssignCostCode();
    });

    expect(setError).toHaveBeenCalledWith("1/2 lignes affectées, 1 échec.");
    expect(result.current.selectedCostLineIds.size).toBe(0);
  });

  it("clears the session and redirects to login when a bulk assignment fails with a post-refresh 401", async () => {
    mocks.updateEstimateCostLine.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const { result, router, setError } = setup({ selectedEstimateId: 1 });
    await waitFor(() => expect(result.current.projectCostCodes).toEqual(costCodes));

    act(() => {
      result.current.setSelectedCostLineIds(new Set([1]));
      result.current.updateBulkCostCodeId("10");
    });

    await act(async () => {
      await result.current.bulkAssignCostCode();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("échec"));
  });

  // Regression test for a review finding on #64: nothing disables the estimate-version
  // selector while a bulk assignment is in flight, so the user can switch versions
  // before the batch resolves. A stale batch must never wipe whatever selection the
  // user has since made on the new version, nor report a success/failure banner for a
  // version that's no longer displayed.
  it("does not clear a fresh selection or report a banner if the estimate version changed while the batch was in flight", async () => {
    let resolveUpdate!: (line: EstimateCostLine) => void;
    mocks.updateEstimateCostLine.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    const { result, rerender, setError } = setup({ selectedEstimateId: 1 });
    await waitFor(() => expect(result.current.projectCostCodes).toEqual(costCodes));

    act(() => {
      result.current.setSelectedCostLineIds(new Set([1]));
      result.current.updateBulkCostCodeId("10");
    });

    let bulkAssignPromise!: Promise<void>;
    act(() => {
      bulkAssignPromise = result.current.bulkAssignCostCode();
    });

    // The user switches to a different estimate version while the PATCH is still in
    // flight, then makes a fresh selection there.
    rerender({ selectedEstimateId: 2 });
    act(() => {
      result.current.setSelectedCostLineIds(new Set([5]));
    });

    resolveUpdate(makeLine(1, { cost_code_id: 10 }));
    await act(async () => {
      await bulkAssignPromise;
    });

    expect(result.current.selectedCostLineIds).toEqual(new Set([5]));
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("échec"));
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("affectée"));
  });
});

describe("useEstimateCostLines removeCostLine", () => {
  beforeEach(() => {
    mocks.deleteEstimateCostLine.mockReset().mockResolvedValue(undefined);
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
  });

  // Regression test for a review finding on #64: a deleted line must not linger in a
  // pending bulk-assignment selection, or "Affecter" would send a doomed PATCH for a
  // line that no longer exists.
  it("removes a deleted line from the bulk-assignment selection", async () => {
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.setSelectedCostLineIds(new Set([1, 2]));
    });

    await act(async () => {
      await result.current.removeCostLine(makeLine(1));
    });

    expect(mocks.deleteEstimateCostLine).toHaveBeenCalled();
    expect(result.current.selectedCostLineIds).toEqual(new Set([2]));
  });
});
