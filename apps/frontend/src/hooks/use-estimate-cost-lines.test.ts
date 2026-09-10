import { act, renderHook, waitFor } from "@testing-library/react";
import { useRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EstimateCostLine, EstimateTaskRow, PlanningDetail, Project, ProjectCostCode, ProjectEstimate } from "@/lib/backend";
import { ApiError } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  createProjectEstimate: vi.fn(),
  createEstimateCostLine: vi.fn(),
  createEstimateTask: vi.fn(),
  applyEstimateCostLineMilestoneTemplate: vi.fn(),
  updateEstimateCostLine: vi.fn(),
  deleteEstimateCostLine: vi.fn(),
  getProjectCostCodes: vi.fn(),
  getPlanning: vi.fn(),
  listEstimateTaskRows: vi.fn(),
  validateProjectEstimate: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    createProjectEstimate: mocks.createProjectEstimate,
    createEstimateCostLine: mocks.createEstimateCostLine,
    createEstimateTask: mocks.createEstimateTask,
    applyEstimateCostLineMilestoneTemplate: mocks.applyEstimateCostLineMilestoneTemplate,
    updateEstimateCostLine: mocks.updateEstimateCostLine,
    deleteEstimateCostLine: mocks.deleteEstimateCostLine,
    getProjectCostCodes: mocks.getProjectCostCodes,
    getPlanning: mocks.getPlanning,
    listEstimateTaskRows: mocks.listEstimateTaskRows,
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

type SetEstimateTaskRows = (rows: EstimateTaskRow[]) => void;

function setup(
  overrides: { selectedEstimateId?: number | null; selectedPlanningId?: number | null } = {},
) {
  const router = { push: vi.fn() };
  const setError = vi.fn();
  const setCostLines = vi.fn<SetCostLines>();
  const setEstimates = vi.fn<SetEstimates>();
  const setEstimateTaskRows = vi.fn<SetEstimateTaskRows>();
  const setPlanningDetail = vi.fn<(detail: PlanningDetail | null) => void>();
  const { result, rerender } = renderHook(
    (props: { selectedEstimateId: number | null; selectedPlanningId?: number | null }) => {
      const selectedPlanningId = props.selectedPlanningId ?? null;
      const selectedPlanningIdRef = useRef(selectedPlanningId);
      selectedPlanningIdRef.current = selectedPlanningId;
      return useEstimateCostLines({
        session,
        project,
        projectId: 1,
        selectedEstimateId: props.selectedEstimateId,
        estimates: [] as ProjectEstimate[],
        setEstimates,
        setSelectedEstimateId: vi.fn(),
        setActiveTab: vi.fn(),
        setCostLines,
        setEstimateTaskRows,
        selectedPlanningId,
        selectedPlanningIdRef,
        setPlanningDetail,
        onSessionRefresh: vi.fn(),
        router: router as never,
        setError,
      });
    },
    {
      initialProps: {
        selectedEstimateId: overrides.selectedEstimateId ?? null,
        selectedPlanningId: overrides.selectedPlanningId ?? null,
      },
    },
  );
  return {
    result,
    rerender,
    router,
    setError,
    setCostLines,
    setEstimates,
    setEstimateTaskRows,
    setPlanningDetail,
  };
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
    rerender({ selectedEstimateId: 2, selectedPlanningId: null });
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

    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

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
        task_id: null,
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

    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

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

// E12-04/#276: task_id is optional, independent from every other field, and round-trips through
// the same empty-string-means-null convention as planned_date above.
describe("useEstimateCostLines task attachment (E12-04)", () => {
  beforeEach(() => {
    mocks.createEstimateCostLine.mockReset();
    mocks.updateEstimateCostLine.mockReset();
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

  it("sends the chosen task_id in the create payload", async () => {
    mocks.createEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });
    fillValidDraft(result);
    act(() => {
      result.current.updateCostLineDraftTaskId("42");
    });

    await act(async () => {
      await result.current.addCostLine();
    });

    expect(mocks.createEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      expect.objectContaining({ task_id: 42 }),
      session,
      expect.any(Function),
    );
  });

  it("sends a null task_id, and does not block the add, when no task is chosen", async () => {
    mocks.createEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });
    fillValidDraft(result);

    await act(async () => {
      await result.current.addCostLine();
    });

    expect(mocks.createEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      expect.objectContaining({ task_id: null }),
      session,
      expect.any(Function),
    );
  });

  it("pre-fills the edited line's task selector from the line's existing task_id", () => {
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(makeLine(1, { task_id: 42 } as never));
    });

    expect(result.current.editingLineDraft.taskId).toBe("42");
  });

  it("pre-fills an empty task selector when the line has no attachment", () => {
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(makeLine(1, { task_id: null } as never));
    });

    expect(result.current.editingLineDraft.taskId).toBe("");
  });

  it("sends the newly chosen task_id in the update payload", async () => {
    mocks.updateEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(makeLine(1, { label: "Achat licences", quantity: 2, unit_cost: 150, task_id: null } as never));
      result.current.updateEditingLineDraftTaskId("42");
    });

    await act(async () => {
      await result.current.saveCostLine(makeLine(1));
    });

    expect(mocks.updateEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      1,
      expect.objectContaining({ task_id: 42 }),
      session,
      expect.any(Function),
    );
  });

  it("sends a null task_id in the update payload when the task attachment is removed", async () => {
    mocks.updateEstimateCostLine.mockResolvedValue(makeLine(1));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.startEditCostLine(
        makeLine(1, { label: "Achat licences", quantity: 2, unit_cost: 150, task_id: 42 } as never),
      );
      result.current.updateEditingLineDraftTaskId("");
    });

    await act(async () => {
      await result.current.saveCostLine(makeLine(1));
    });

    expect(mocks.updateEstimateCostLine).toHaveBeenCalledWith(
      1,
      1,
      1,
      expect.objectContaining({ task_id: null }),
      session,
      expect.any(Function),
    );
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

    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

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
    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

    const warnings = [{ task_uid: 12, task_name: "Terrassement lot 3" }];
    resolveValidate(makeEstimate(1, { warnings } as never));
    await act(async () => {
      await validatePromise;
    });

    expect(result.current.validationWarnings).toEqual([]);
    expect(setError).not.toHaveBeenCalledWith(expect.stringContaining("valider"));
  });
});

function makeTaskRow(overrides: Partial<{ id: number; task_name: string }> = {}) {
  return {
    id: 1,
    estimate_id: 1,
    task_id: 42,
    parent_task_id: null,
    position: 1,
    task_name: "Terrassement",
    outline_number: "1.1",
    outline_level: 1,
    is_milestone: false,
    ...overrides,
  };
}

// E6-06/#67: "add a task to the planning" dialog, submitted from the Devis tab.
describe("useEstimateCostLines submitCreateTask", () => {
  beforeEach(() => {
    mocks.createEstimateTask.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
    mocks.getPlanning.mockReset();
    mocks.listEstimateTaskRows.mockReset().mockResolvedValue([]);
  });

  it("requires a non-empty name and never calls the backend for a blank one", async () => {
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
    });
    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(mocks.createEstimateTask).not.toHaveBeenCalled();
    expect(result.current.taskCreateError).toBe("Le nom de la tâche est obligatoire.");
  });

  // E12-04/#276: this used to bump an approximate `estimateTaskRowCount` by 1 -- it now refetches
  // the exact task-row list instead, which the Devis grid needs in full (names/hierarchy/
  // position), not just a count.
  it("creates the task, refetches the task-row list, and closes the dialog on success", async () => {
    mocks.createEstimateTask.mockResolvedValue(makeTaskRow());
    const freshTaskRows = [makeTaskRow(), makeTaskRow({ id: 2 })];
    mocks.listEstimateTaskRows.mockResolvedValue(freshTaskRows);
    const { result, setEstimateTaskRows } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
      result.current.updateTaskDraftParentUid("5");
      result.current.updateTaskDraftIsMilestone(true);
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(mocks.createEstimateTask).toHaveBeenCalledWith(
      1,
      1,
      { name: "Terrassement", is_milestone: true, target_parent_uid: 5 },
      session,
      expect.any(Function),
    );
    expect(mocks.listEstimateTaskRows).toHaveBeenCalledWith(1, 1, session, expect.any(Function));
    expect(setEstimateTaskRows).toHaveBeenCalledWith(freshTaskRows);
    expect(result.current.taskDialogOpen).toBe(false);
  });

  // E12-04/#276: same stale-response guard as the planning refetch below, applied to the new
  // task-row refetch -- the estimate version can switch while this request is in flight
  // (nothing currently disables the version selector while busy), and a stale response must
  // never overwrite whatever version's task rows are displayed once it resolves.
  it("does not apply the task-row refetch if the estimate version changed while it was in flight", async () => {
    mocks.createEstimateTask.mockResolvedValue(makeTaskRow());
    let resolveListTaskRows!: (rows: ReturnType<typeof makeTaskRow>[]) => void;
    mocks.listEstimateTaskRows.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveListTaskRows = resolve;
        }),
    );
    const { result, rerender, setEstimateTaskRows } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    let submitPromise!: Promise<void>;
    act(() => {
      submitPromise = result.current.submitCreateTask();
    });

    await waitFor(() => expect(mocks.listEstimateTaskRows).toHaveBeenCalled());

    // The user switches to a different estimate version while the task-row refetch triggered
    // by the task creation is still in flight.
    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

    resolveListTaskRows([makeTaskRow()]);
    await act(async () => {
      await submitPromise;
    });

    expect(setEstimateTaskRows).not.toHaveBeenCalled();
  });

  // Haute review finding on #67: without this refetch, planningDetail (and therefore the
  // "Tâche parente" selector fed from it in page.tsx) never learns about the task the backend
  // just attached to the displayed planning -- a full page reload would be the only way to see
  // it, which defeats building a hierarchy across several consecutive additions from the Devis
  // tab.
  it("refetches the displayed planning and applies the fresh detail once the task is created", async () => {
    mocks.createEstimateTask.mockResolvedValue(makeTaskRow());
    const freshDetail = { id: 3, tasks: [{ uid: 99, name: "Terrassement" }] } as never;
    mocks.getPlanning.mockResolvedValue(freshDetail);
    const { result, setPlanningDetail } = setup({ selectedEstimateId: 1, selectedPlanningId: 3 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(mocks.getPlanning).toHaveBeenCalledWith(1, 3, session, expect.any(Function));
    expect(setPlanningDetail).toHaveBeenCalledWith(freshDetail);
  });

  it("does not apply the planning refetch if the displayed planning changed while it was in flight", async () => {
    mocks.createEstimateTask.mockResolvedValue(makeTaskRow());
    let resolveGetPlanning!: (detail: unknown) => void;
    mocks.getPlanning.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGetPlanning = resolve;
        }),
    );
    const { result, rerender, setPlanningDetail } = setup({ selectedEstimateId: 1, selectedPlanningId: 3 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    let submitPromise!: Promise<void>;
    act(() => {
      submitPromise = result.current.submitCreateTask();
    });

    // createEstimateTask itself resolves immediately (unlike the manually-paused mocks used by
    // this file's other stale-response tests), so the refetch's own `getPlanning` call only
    // fires a few microtasks later -- wait for it before switching the displayed planning,
    // otherwise `resolveGetPlanning` would still be unassigned.
    await waitFor(() => expect(mocks.getPlanning).toHaveBeenCalled());

    // The user switches to a different displayed planning while the refetch triggered by the
    // task creation is still in flight.
    rerender({ selectedEstimateId: 1, selectedPlanningId: 4 });

    resolveGetPlanning({ id: 3, tasks: [] });
    await act(async () => {
      await submitPromise;
    });

    expect(setPlanningDetail).not.toHaveBeenCalled();
  });

  it("logs out when the post-creation planning refetch fails with a post-refresh 401", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.createEstimateTask.mockResolvedValue(makeTaskRow());
    mocks.getPlanning.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const { result, router } = setup({ selectedEstimateId: 1, selectedPlanningId: 3 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
  });

  it("does not treat a non-session planning refetch failure as a task-creation failure", async () => {
    mocks.createEstimateTask.mockResolvedValue(makeTaskRow());
    mocks.getPlanning.mockRejectedValue(new Error("network down"));
    const { result, setEstimateTaskRows } = setup({ selectedEstimateId: 1, selectedPlanningId: 3 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    // The task itself was created successfully -- a failed refresh must not resurrect the
    // dialog or report a creation error.
    expect(setEstimateTaskRows).toHaveBeenCalled();
    expect(result.current.taskDialogOpen).toBe(false);
    expect(result.current.taskCreateError).toBeNull();
  });

  it("shows an explicit reopen-the-structure message and flag on the draft-required 409", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.createEstimateTask.mockRejectedValue(
      new ApiError(
        409,
        "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.",
        { code: "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT" },
      ),
    );
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(result.current.taskCreateRequiresPlanningDraft).toBe(true);
    expect(result.current.taskCreateError).toBe(
      "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.",
    );
    expect(result.current.taskDialogOpen).toBe(true);
  });

  it("shows a distinct message for a generic 409 (estimate/planning no longer a draft)", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.createEstimateTask.mockRejectedValue(new ApiError(409, "Une erreur est survenue."));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(result.current.taskCreateRequiresPlanningDraft).toBe(false);
    expect(result.current.taskCreateError).toBe("Ce devis ou le planning affiché ne sont plus modifiables.");
  });

  it("clears the session and redirects to login on a post-refresh 401", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.createEstimateTask.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const { result, router } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    await act(async () => {
      await result.current.submitCreateTask();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
  });

  // Same stale-response guard as addCostLine/bulkAssignCostCode/validateEstimate above: the
  // user could switch estimate version while this request is in flight.
  it("does not apply a stale success/error result if the estimate version changed while the request was in flight", async () => {
    let resolveCreate!: (row: ReturnType<typeof makeTaskRow>) => void;
    mocks.createEstimateTask.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const { result, rerender, setEstimateTaskRows } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openCreateTaskDialog();
      result.current.updateTaskDraftName("Terrassement");
    });

    let submitPromise!: Promise<void>;
    act(() => {
      submitPromise = result.current.submitCreateTask();
    });

    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

    resolveCreate(makeTaskRow());
    await act(async () => {
      await submitPromise;
    });

    expect(setEstimateTaskRows).not.toHaveBeenCalled();
    expect(result.current.taskDialogOpen).toBe(true);
  });
});

function makeMilestoneRows(count: number) {
  return Array.from({ length: count }, (_unused, index) => makeTaskRow({ id: index + 1 }));
}

// E6-07/#68: "apply a milestone template" dialog, submitted from a single cost-line row.
describe("useEstimateCostLines submitMilestoneTemplate", () => {
  beforeEach(() => {
    mocks.applyEstimateCostLineMilestoneTemplate.mockReset();
    mocks.clearSession.mockReset();
    mocks.getProjectCostCodes.mockReset().mockResolvedValue([]);
    mocks.getPlanning.mockReset();
    mocks.listEstimateTaskRows.mockReset().mockResolvedValue([]);
  });

  // E12-04/#276: this used to bump an approximate `estimateTaskRowCount` by however many
  // milestones were created -- it now refetches the exact task-row list instead, same as
  // submitCreateTask above.
  it("applies the fourniture template with the default zero intermediate count and lag, then refetches the task-row list", async () => {
    mocks.applyEstimateCostLineMilestoneTemplate.mockResolvedValue(makeMilestoneRows(2));
    const freshTaskRows = makeMilestoneRows(5);
    mocks.listEstimateTaskRows.mockResolvedValue(freshTaskRows);
    const { result, setEstimateTaskRows } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3, { label: "Ascenseur" }));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(mocks.applyEstimateCostLineMilestoneTemplate).toHaveBeenCalledWith(
      1,
      1,
      3,
      { template: "fourniture", intermediate_milestones_count: 0, lag_minutes: 0 },
      session,
      expect.any(Function),
    );
    expect(mocks.listEstimateTaskRows).toHaveBeenCalledWith(1, 1, session, expect.any(Function));
    expect(setEstimateTaskRows).toHaveBeenCalledWith(freshTaskRows);
    expect(result.current.milestoneDialogOpen).toBe(false);
  });

  // E12-04/#276: same stale-response guard as submitCreateTask's own task-row refetch above.
  it("does not apply the task-row refetch if the estimate version changed while it was in flight", async () => {
    mocks.applyEstimateCostLineMilestoneTemplate.mockResolvedValue(makeMilestoneRows(2));
    let resolveListTaskRows!: (rows: ReturnType<typeof makeMilestoneRows>) => void;
    mocks.listEstimateTaskRows.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveListTaskRows = resolve;
        }),
    );
    const { result, rerender, setEstimateTaskRows } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    let submitPromise!: Promise<void>;
    act(() => {
      submitPromise = result.current.submitMilestoneTemplate();
    });

    await waitFor(() => expect(mocks.listEstimateTaskRows).toHaveBeenCalled());

    // The user switches to a different estimate version while the task-row refetch triggered
    // by the milestone template application is still in flight.
    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

    resolveListTaskRows(makeMilestoneRows(1));
    await act(async () => {
      await submitPromise;
    });

    expect(setEstimateTaskRows).not.toHaveBeenCalled();
  });

  it("applies the sous_traitance template with the chosen intermediate count and lag", async () => {
    mocks.applyEstimateCostLineMilestoneTemplate.mockResolvedValue(makeMilestoneRows(5));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3, { label: "Ascenseur" }));
      result.current.updateMilestoneTemplate("sous_traitance");
      result.current.updateMilestoneIntermediateCount("3");
      result.current.updateMilestoneLagMinutes("120");
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(mocks.applyEstimateCostLineMilestoneTemplate).toHaveBeenCalledWith(
      1,
      1,
      3,
      { template: "sous_traitance", intermediate_milestones_count: 3, lag_minutes: 120 },
      session,
      expect.any(Function),
    );
  });

  // Regression-style guard: switching back to "fourniture" must reset any previously-entered
  // intermediate count, since the backend rejects a non-zero value for that template with a 400.
  it("resets the intermediate count to 0 when switching back to the fourniture template", async () => {
    mocks.applyEstimateCostLineMilestoneTemplate.mockResolvedValue(makeMilestoneRows(2));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
      result.current.updateMilestoneTemplate("sous_traitance");
      result.current.updateMilestoneIntermediateCount("4");
      result.current.updateMilestoneTemplate("fourniture");
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(mocks.applyEstimateCostLineMilestoneTemplate).toHaveBeenCalledWith(
      1,
      1,
      3,
      { template: "fourniture", intermediate_milestones_count: 0, lag_minutes: 0 },
      session,
      expect.any(Function),
    );
  });

  it("refetches the displayed planning and applies the fresh detail once the milestones are created", async () => {
    mocks.applyEstimateCostLineMilestoneTemplate.mockResolvedValue(makeMilestoneRows(2));
    const freshDetail = { id: 3, tasks: [{ uid: 99, name: "Commande" }] } as never;
    mocks.getPlanning.mockResolvedValue(freshDetail);
    const { result, setPlanningDetail } = setup({ selectedEstimateId: 1, selectedPlanningId: 3 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(mocks.getPlanning).toHaveBeenCalledWith(1, 3, session, expect.any(Function));
    expect(setPlanningDetail).toHaveBeenCalledWith(freshDetail);
  });

  it("shows an explicit reopen-the-structure message and flag on the draft-required 409", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.applyEstimateCostLineMilestoneTemplate.mockRejectedValue(
      new ApiError(
        409,
        "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.",
        { code: "ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT" },
      ),
    );
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(result.current.milestoneRequiresPlanningDraft).toBe(true);
    expect(result.current.milestoneError).toBe(
      "Le planning affiché n'est plus un brouillon : rouvre sa structure depuis l'onglet Planning avant d'ajouter une tâche depuis le devis.",
    );
    expect(result.current.milestoneDialogOpen).toBe(true);
  });

  it("shows a distinct message for a generic 409 (estimate/planning no longer a draft)", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.applyEstimateCostLineMilestoneTemplate.mockRejectedValue(new ApiError(409, "Une erreur est survenue."));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(result.current.milestoneRequiresPlanningDraft).toBe(false);
    expect(result.current.milestoneError).toBe("Ce devis ou le planning affiché ne sont plus modifiables.");
  });

  it("shows a distinct message for a 404 (cost line not found)", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.applyEstimateCostLineMilestoneTemplate.mockRejectedValue(new ApiError(404, "Une erreur est survenue."));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(result.current.milestoneError).toBe("Cette ligne de coût est introuvable dans ce devis.");
  });

  // The backend rejects a labor cost line with an unstructured 400 (see
  // describeMilestoneTemplateError's doc comment) -- the only case a 400 can mean here, since
  // updateMilestoneTemplate always resets the intermediate count to 0 for "fourniture".
  it("shows a distinct message for a 400 (labor cost line)", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.applyEstimateCostLineMilestoneTemplate.mockRejectedValue(new ApiError(400, "Une erreur est survenue."));
    const { result } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(result.current.milestoneError).toBe(
      "Ce gabarit de jalons ne s'applique qu'aux lignes de coût qui ne sont pas de la main d'œuvre.",
    );
  });

  it("clears the session and redirects to login on a post-refresh 401", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
    mocks.applyEstimateCostLineMilestoneTemplate.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const { result, router } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    await act(async () => {
      await result.current.submitMilestoneTemplate();
    });

    expect(mocks.clearSession).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/login");
  });

  // Same stale-response guard as submitCreateTask/addCostLine/bulkAssignCostCode/validateEstimate
  // above: the user could switch estimate version while this request is in flight (nothing
  // currently disables the version selector while busy) -- this is the exact class of bug the
  // review flagged 3 times before #67, so it's exercised here too.
  it("does not apply a stale success/error result if the estimate version changed while the request was in flight", async () => {
    let resolveApply!: (rows: ReturnType<typeof makeMilestoneRows>) => void;
    mocks.applyEstimateCostLineMilestoneTemplate.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveApply = resolve;
        }),
    );
    const { result, rerender, setEstimateTaskRows } = setup({ selectedEstimateId: 1 });

    act(() => {
      result.current.openMilestoneDialog(makeLine(3));
    });

    let submitPromise!: Promise<void>;
    act(() => {
      submitPromise = result.current.submitMilestoneTemplate();
    });

    rerender({ selectedEstimateId: 2, selectedPlanningId: null });

    resolveApply(makeMilestoneRows(2));
    await act(async () => {
      await submitPromise;
    });

    expect(setEstimateTaskRows).not.toHaveBeenCalled();
    expect(result.current.milestoneDialogOpen).toBe(true);
  });
});
