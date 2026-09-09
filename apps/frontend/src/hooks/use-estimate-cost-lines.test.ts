import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EstimateCostLine, Project, ProjectCostCode, ProjectEstimate } from "@/lib/backend";
import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  createProjectEstimate: vi.fn(),
  createEstimateCostLine: vi.fn(),
  updateEstimateCostLine: vi.fn(),
  deleteEstimateCostLine: vi.fn(),
  getProjectCostCodes: vi.fn(),
  validateProjectEstimate: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    createProjectEstimate: mocks.createProjectEstimate,
    createEstimateCostLine: mocks.createEstimateCostLine,
    updateEstimateCostLine: mocks.updateEstimateCostLine,
    deleteEstimateCostLine: mocks.deleteEstimateCostLine,
    getProjectCostCodes: mocks.getProjectCostCodes,
    validateProjectEstimate: mocks.validateProjectEstimate,
  };
});

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
}));

import { useEstimateCostLines } from "@/hooks/use-estimate-cost-lines";

const session = { accessToken: "test-token" };
const project = { id: 1, name: "Projet A", currency_code: "EUR" } as Project;

type SetCostLines = (updater: (previous: EstimateCostLine[]) => EstimateCostLine[]) => void;

type SetEstimates = (updater: (previous: ProjectEstimate[]) => ProjectEstimate[]) => void;

function setup(overrides: { selectedEstimateId?: number | null } = {}) {
  const router = { push: vi.fn() };
  const setError = vi.fn();
  const setCostLines = vi.fn<SetCostLines>();
  const setEstimates = vi.fn<SetEstimates>();
  const { result, rerender } = renderHook(
    (props: { selectedEstimateId: number | null }) =>
      useEstimateCostLines({
        session,
        project,
        projectId: 1,
        selectedEstimateId: props.selectedEstimateId,
        estimates: [] as ProjectEstimate[],
        setEstimates,
        setSelectedEstimateId: vi.fn(),
        setActiveTab: vi.fn(),
        setCostLines,
        onSessionRefresh: vi.fn(),
        router: router as never,
        setError,
      }),
    { initialProps: { selectedEstimateId: overrides.selectedEstimateId ?? null } },
  );
  return { result, rerender, router, setError, setCostLines, setEstimates };
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

// #66 (E6-05): `planned_date` is editable in both the add-cost-line form and the cost-line edit
// row, entirely independent from `task_id`.
describe("useEstimateCostLines addCostLine planned date (E6-05)", () => {
  beforeEach(() => {
    mocks.createEstimateCostLine.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
  });

  function fillValidDraft(result: { current: ReturnType<typeof useEstimateCostLines> }) {
    act(() => {
      result.current.updateCostLineDraftCategory("3");
      result.current.updateCostLineDraftLabel("Achat licences");
      result.current.updateCostLineDraftQuantity("2");
      result.current.updateCostLineDraftUnitCost("150");
    });
  }

  it("sends the chosen planned date in the create payload", async () => {
    mocks.createEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });
    fillValidDraft(result);
    act(() => {
      result.current.updateCostLineDraftPlannedDate("2026-10-01");
    });

    await act(async () => {
      await result.current.addCostLine();
    });

    expect(mocks.createEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      expect.objectContaining({ planned_date: "2026-10-01T00:00:00Z" }),
      session,
      expect.any(Function),
    );
  });

  it("sends a null planned date, and does not block the add, when the field is left blank", async () => {
    mocks.createEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });
    fillValidDraft(result);

    await act(async () => {
      await result.current.addCostLine();
    });

    expect(mocks.createEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      expect.objectContaining({ planned_date: null }),
      session,
      expect.any(Function),
    );
  });

  // Regression test for a review finding on #66: nothing disables the estimate-version
  // selector while a request is in flight (same gap as bulkAssignCostCode/validateEstimate,
  // #64/#65), so a late-resolving create must never land on whatever version the user has
  // since navigated away from.
  it("does not add the created line if the estimate version changed while the request was in flight", async () => {
    let resolveCreate!: (line: EstimateCostLine) => void;
    mocks.createEstimateCostLine.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const { result, rerender, setCostLines, setError } = setup({ selectedEstimateId: 1 });
    fillValidDraft(result);

    let addPromise!: Promise<void>;
    act(() => {
      addPromise = result.current.addCostLine();
    });

    rerender({ selectedEstimateId: 2 });

    resolveCreate(makeLine(1));
    await act(async () => {
      await addPromise;
    });

    expect(setCostLines).not.toHaveBeenCalled();
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("ajouter"));
  });
});

describe("useEstimateCostLines saveCostLine planned date (E6-05)", () => {
  beforeEach(() => {
    mocks.updateEstimateCostLine.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
  });

  it("updates only the planned date while leaving the other fields intact", async () => {
    mocks.updateEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(makeLine(1, { label: "Achat licences", quantity: 2, unit_cost: 150 } as never));
      result.current.updateEditingLineDraftPlannedDate("2026-11-15");
    });

    await act(async () => {
      await result.current.saveCostLine(makeLine(1));
    });

    expect(mocks.updateEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      1,
      {
        label: "Achat licences",
        quantity: 2,
        unit_cost: 150,
        planned_date: "2026-11-15T00:00:00Z",
      },
      session,
      expect.any(Function),
    );
  });

  // Regression test for a review finding on #66: same stale-response gap as addCostLine
  // above.
  it("does not apply the updated line if the estimate version changed while the request was in flight", async () => {
    let resolveUpdate!: (line: EstimateCostLine) => void;
    mocks.updateEstimateCostLine.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    const { result, rerender, setCostLines, setError } = setup({ selectedEstimateId: 1 });
    act(() => {
      result.current.startEditCostLine(makeLine(1, { label: "Achat licences", quantity: 2, unit_cost: 150 } as never));
    });

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.saveCostLine(makeLine(1));
    });

    rerender({ selectedEstimateId: 2 });

    resolveUpdate(makeLine(1));
    await act(async () => {
      await savePromise;
    });

    expect(setCostLines).not.toHaveBeenCalled();
    expect(result.current.editingLineId).toBe(1);
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("modifier"));
  });
});

describe("useEstimateCostLines startEditCostLine planned date (E6-05)", () => {
  beforeEach(() => {
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
  });

  it("pre-fills the planned date input from the line's existing ISO datetime", () => {
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(makeLine(1, { planned_date: "2026-10-01T00:00:00+00:00" } as never));
    });

    expect(result.current.editingLineDraft.plannedDate).toBe("2026-10-01");
  });

  it("pre-fills an empty planned date when the line has none", () => {
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(makeLine(1, { planned_date: null } as never));
    });

    expect(result.current.editingLineDraft.plannedDate).toBe("");
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

function makeEstimate(id: number, overrides: Partial<ProjectEstimate> = {}): ProjectEstimate {
  return { id, kind: "initial", version_number: 1, currency_code: "EUR", status: "validated", ...overrides } as ProjectEstimate;
}

// #65 (E6-04): the validate endpoint now returns `warnings` (unassigned real tasks),
// purely informative and never blocking -- see estimate-tab.tsx for the banner itself.
describe("useEstimateCostLines validateEstimate", () => {
  beforeEach(() => {
    mocks.validateProjectEstimate.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
  });

  it("exposes the warnings returned by a validation that finds unassigned tasks", async () => {
    const warnings = [{ task_uid: 12, task_name: "Terrassement lot 3" }];
    mocks.validateProjectEstimate.mockResolvedValue(makeEstimate(1, { warnings } as never));
    const { result, setEstimates } = setup({ selectedEstimateId: 1 });

    await act(async () => {
      await result.current.validateEstimate();
    });

    expect(result.current.validationWarnings).toEqual(warnings);
    // The estimate itself is still folded into `estimates` -- the warnings never block
    // the validation from succeeding.
    expect(setEstimates).toHaveBeenCalled();
  });

  it("leaves validationWarnings empty when the validation finds nothing to warn about", async () => {
    mocks.validateProjectEstimate.mockResolvedValue(makeEstimate(1, { warnings: [] } as never));
    const { result } = setup({ selectedEstimateId: 1 });

    await act(async () => {
      await result.current.validateEstimate();
    });

    expect(result.current.validationWarnings).toEqual([]);
  });

  it("clears validationWarnings once acknowledged via dismissValidationWarnings", async () => {
    const warnings = [{ task_uid: 12, task_name: "Terrassement lot 3" }];
    mocks.validateProjectEstimate.mockResolvedValue(makeEstimate(1, { warnings } as never));
    const { result } = setup({ selectedEstimateId: 1 });

    await act(async () => {
      await result.current.validateEstimate();
    });
    expect(result.current.validationWarnings).toEqual(warnings);

    act(() => {
      result.current.dismissValidationWarnings();
    });

    expect(result.current.validationWarnings).toEqual([]);
  });

  it("resets validationWarnings when the selected estimate version changes", async () => {
    const warnings = [{ task_uid: 12, task_name: "Terrassement lot 3" }];
    mocks.validateProjectEstimate.mockResolvedValue(makeEstimate(1, { warnings } as never));
    const { result, rerender } = setup({ selectedEstimateId: 1 });

    await act(async () => {
      await result.current.validateEstimate();
    });
    expect(result.current.validationWarnings).toEqual(warnings);

    rerender({ selectedEstimateId: 2 });

    expect(result.current.validationWarnings).toEqual([]);
  });

  // Regression test for a review finding on #65: nothing disables the estimate-version
  // selector while a validation is in flight (same gap as bulkAssignCostCode, #64), so a
  // late-resolving response for a version the user has since navigated away from must
  // never repopulate the warning banner with stale data.
  it("does not repopulate the warning banner from a stale response after the estimate version changed", async () => {
    let resolveValidate!: (estimate: ProjectEstimate) => void;
    mocks.validateProjectEstimate.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveValidate = resolve;
        }),
    );
    const { result, rerender, setError } = setup({ selectedEstimateId: 1 });

    let validatePromise!: Promise<void>;
    act(() => {
      validatePromise = result.current.validateEstimate();
    });

    // The user switches to a different estimate version while the request is still in
    // flight (nothing disables the version selector while busy).
    rerender({ selectedEstimateId: 2 });

    const warnings = [{ task_uid: 12, task_name: "Terrassement lot 3" }];
    resolveValidate(makeEstimate(1, { warnings } as never));
    await act(async () => {
      await validatePromise;
    });

    expect(result.current.validationWarnings).toEqual([]);
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("valider"));
  });
});
