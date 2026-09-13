import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type ImportDiff,
  type Planning,
  type PlanningDetail,
  type Project,
  type Revision,
  type RevisionAggregates,
  type RevisionList,
  type RevisionNode,
  type RevisionTree,
} from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  listProjectEstimates: vi.fn(),
  listPlannings: vi.fn(),
  getPlanning: vi.fn(),
  exportProjectXml: vi.fn(),
  getEstimateAggregates: vi.fn(),
  getProjectCostCodes: vi.fn(),
  getCostCategories: vi.fn(),
  getCostTypes: vi.fn(),
  getResourceNodes: vi.fn(),
  getResourceRoles: vi.fn(),
  getCostRates: vi.fn(),
  getRevisionAggregates: vi.fn(),
  exportRevisionExcel: vi.fn(),
  createRevisionCostLine: vi.fn(),
  updateRevisionCostFacet: vi.fn(),
  createImportBatch: vi.fn(),
  uploadImportSourceXml: vi.fn(),
  runImportBatch: vi.fn(),
  getImportBatchStatus: vi.fn(),
  getImportBatchDiff: vi.fn(),
  listRevisions: vi.fn(),
  getRevisionNodes: vi.fn(),
  moveRevisionNodes: vi.fn(),
  createRevisionTask: vi.fn(),
  deleteRevisionNodes: vi.fn(),
  updateRevisionPlanFacet: vi.fn(),
  replaceRevisionPredecessors: vi.fn(),
  copyRevision: vi.fn(),
  validateRevision: vi.fn(),
  savePlanningStructureDraft: vi.fn(),
  getPlanningStructureDraft: vi.fn(),
  createPlanningStructure: vi.fn(),
  reopenPlanningStructure: vi.fn(),
  skipPlanningStructure: vi.fn(),
  router: { push: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "1" }),
  useRouter: () => mocks.router,
}));

vi.mock("@/lib/session", () => ({
  clearSession: vi.fn(),
  getSession: vi.fn(() => ({ accessToken: "test-token" })),
  setSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    getProject: mocks.getProject,
    listProjectEstimates: mocks.listProjectEstimates,
    listPlannings: mocks.listPlannings,
    getPlanning: mocks.getPlanning,
    exportProjectXml: mocks.exportProjectXml,
    getEstimateAggregates: mocks.getEstimateAggregates,
    getProjectCostCodes: mocks.getProjectCostCodes,
    getCostCategories: mocks.getCostCategories,
    getCostTypes: mocks.getCostTypes,
    getResourceNodes: mocks.getResourceNodes,
    getResourceRoles: mocks.getResourceRoles,
    getCostRates: mocks.getCostRates,
    getRevisionAggregates: mocks.getRevisionAggregates,
    exportRevisionExcel: mocks.exportRevisionExcel,
    createRevisionCostLine: mocks.createRevisionCostLine,
    updateRevisionCostFacet: mocks.updateRevisionCostFacet,
    createImportBatch: mocks.createImportBatch,
    uploadImportSourceXml: mocks.uploadImportSourceXml,
    runImportBatch: mocks.runImportBatch,
    getImportBatchStatus: mocks.getImportBatchStatus,
    getImportBatchDiff: mocks.getImportBatchDiff,
    listRevisions: mocks.listRevisions,
    getRevisionNodes: mocks.getRevisionNodes,
    moveRevisionNodes: mocks.moveRevisionNodes,
    createRevisionTask: mocks.createRevisionTask,
    deleteRevisionNodes: mocks.deleteRevisionNodes,
    updateRevisionPlanFacet: mocks.updateRevisionPlanFacet,
    replaceRevisionPredecessors: mocks.replaceRevisionPredecessors,
    copyRevision: mocks.copyRevision,
    validateRevision: mocks.validateRevision,
    savePlanningStructureDraft: mocks.savePlanningStructureDraft,
    getPlanningStructureDraft: mocks.getPlanningStructureDraft,
    createPlanningStructure: mocks.createPlanningStructure,
    reopenPlanningStructure: mocks.reopenPlanningStructure,
    skipPlanningStructure: mocks.skipPlanningStructure,
  };
});

import ProjectDetailsPage from "./page";

const project = (overrides: Partial<Project> = {}): Project => ({
  id: 1,
  name: "Projet test",
  status: "cree",
  code: null,
  short_description: null,
  source_version: 2016,
  save_version_out: 16,
  schedule_from_start: true,
  start_date: null,
  finish_date: null,
  currency_code: "EUR",
  planning_reference_id: null,
  displayed_planning_id: null,
  reference_estimate_id: null,
  minutes_per_day: 480,
  minutes_per_week: 2400,
  days_per_month: 20,
  ...overrides,
});

const planning = (overrides: Partial<Planning> = {}): Planning => ({
  id: 2,
  project_id: 1,
  version_number: 1,
  status: "draft",
  revision: 0,
  note: null,
  created_at: "2026-08-21T00:00:00Z",
  validated_at: null,
  ...overrides,
});

const detail = (version: Planning): PlanningDetail => ({
  ...version,
  tasks: [
    {
      id: 10,
      project_id: 1,
      uid: 10,
      row_number: 0,
      structure_key: "post/lot/deliverable",
      structure_kind: "livrable",
      parent_uid: null,
      position: 1,
      name: `Tâche ${version.version_number}`,
      outline_number: "1.1.1",
      outline_level: 3,
      start_at: null,
      finish_at: null,
      percent_complete: 0,
      is_summary: false,
      is_milestone: false,
      is_manual: true,
      description: null,
      predecessor_links: [],
    },
  ],
  links: [],
});

// E14-10 (#336): the revision fixtures the Planning tab now reads.
function revisionSummary(overrides: Partial<Revision> = {}): Revision {
  return {
    revision_id: 7,
    project_id: 1,
    version_number: 1,
    kind: "initial",
    status: "draft",
    lock_version: 0,
    note: null,
    created_at: "2026-09-01T00:00:00Z",
    validated_at: null,
    ...overrides,
  };
}

function emptyRevisionList(): RevisionList {
  return { items: [], reference_revision_id: null, displayed_revision_id: null };
}

function revisionList(items: Revision[], overrides: Partial<RevisionList> = {}): RevisionList {
  return { items, reference_revision_id: null, displayed_revision_id: null, ...overrides };
}

function taskNode(
  nodeId: number,
  options: { name?: string; parentId?: number | null; position?: number; level?: number; rowNumber?: number } = {},
): RevisionNode {
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "task",
    parent_id: options.parentId ?? null,
    position: options.position ?? 1,
    row_number: options.rowNumber ?? nodeId,
    level: options.level ?? 1,
    external_uid: null,
    description: null,
    planning: {
      name: options.name ?? `Tâche ${nodeId}`,
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
}

// E14-11 (#337): a cost node of that same tree -- a cost line is a node, not a parallel list.
function costNode(
  nodeId: number,
  options: { label?: string; parentId?: number | null; position?: number; level?: number; rowNumber?: number } = {},
): RevisionNode {
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "cost",
    parent_id: options.parentId ?? null,
    position: options.position ?? 1,
    row_number: options.rowNumber ?? nodeId,
    level: options.level ?? 1,
    external_uid: null,
    description: null,
    planning: null,
    cost: {
      nature: "non_labor",
      label: options.label ?? `Ligne ${nodeId}`,
      quantity: "2.00",
      role_id: null,
      hours: null,
      cost_type_id: 1,
      cost_category_id: 4,
      unit_cost: "50.00",
      supply_status: null,
      planned_date: null,
      cost_code_id: null,
      comment: null,
      bearing_task_node_id: options.parentId ?? null,
      bearing_task_name: null,
    },
    predecessors: [],
  };
}

function revisionAggregates(overrides: Partial<RevisionAggregates> = {}): RevisionAggregates {
  return {
    revision_id: 7,
    total_labor_cost: "0.00",
    total_purchase_cost: "100.00",
    total_unburdened_cost: "100.00",
    by_category: {},
    by_cost_code: {},
    unpriceable_facets: [],
    missing_cost_rates: [],
    missing_inflation_years: [],
    ...overrides,
  };
}

function revisionTree(overrides: Partial<RevisionTree> = {}): RevisionTree {
  return {
    revision_id: 7,
    project_id: 1,
    version_number: 1,
    kind: "initial",
    status: "draft",
    lock_version: 0,
    note: null,
    nodes: [taskNode(1, { name: "Étude" })],
    ...overrides,
  };
}

describe("ProjectDetailsPage planning lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getProject.mockReset();
    mocks.listProjectEstimates.mockReset();
    mocks.listPlannings.mockReset();
    mocks.getPlanning.mockReset();
    mocks.exportProjectXml.mockReset();
    mocks.getEstimateAggregates.mockReset();
    mocks.getProjectCostCodes.mockReset();
    mocks.getCostCategories.mockReset();
    mocks.getCostTypes.mockReset();
    mocks.getResourceNodes.mockReset();
    mocks.getResourceRoles.mockReset();
    mocks.getCostRates.mockReset();
    mocks.getRevisionAggregates.mockReset();
    mocks.exportRevisionExcel.mockReset();
    mocks.createRevisionCostLine.mockReset();
    mocks.updateRevisionCostFacet.mockReset();
    mocks.createImportBatch.mockReset();
    mocks.uploadImportSourceXml.mockReset();
    mocks.runImportBatch.mockReset();
    mocks.getImportBatchStatus.mockReset();
    mocks.getImportBatchDiff.mockReset();
    mocks.listRevisions.mockReset();
    mocks.getRevisionNodes.mockReset();
    mocks.moveRevisionNodes.mockReset();
    mocks.createRevisionTask.mockReset();
    mocks.deleteRevisionNodes.mockReset();
    mocks.updateRevisionPlanFacet.mockReset();
    mocks.replaceRevisionPredecessors.mockReset();
    mocks.copyRevision.mockReset();
    mocks.validateRevision.mockReset();
    mocks.savePlanningStructureDraft.mockReset();
    mocks.getPlanningStructureDraft.mockReset();
    mocks.createPlanningStructure.mockReset();
    mocks.reopenPlanningStructure.mockReset();
    mocks.skipPlanningStructure.mockReset();
    mocks.listProjectEstimates.mockResolvedValue([]);
    mocks.listPlannings.mockResolvedValue([]);
    mocks.getProjectCostCodes.mockResolvedValue([]);
    // One non-MO category and its cost type: the least a devis needs to be able to add a line.
    mocks.getCostCategories.mockResolvedValue({
      items: [{ id: 4, cost_type_id: 2, accounting_code: "604", category_code: null, name: "Fournitures", is_active: true, created_at: "", updated_at: "" }],
      total: 1,
    });
    mocks.getCostTypes.mockResolvedValue({
      items: [{ id: 2, code: "FOU", name: "Fournitures", kind: "supply", is_active: true, created_at: "", updated_at: "" }],
      total: 1,
    });
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getRevisionAggregates.mockResolvedValue(revisionAggregates());
    mocks.createRevisionCostLine.mockResolvedValue({ revision_id: 7, lock_version: 1, node_id: 99, work_item_id: 99 });
    mocks.updateRevisionCostFacet.mockResolvedValue({ revision_id: 7, lock_version: 1 });
    mocks.listRevisions.mockResolvedValue(emptyRevisionList());
    mocks.getRevisionNodes.mockImplementation(async (_projectId: number, revisionId: number) =>
      revisionTree({ revision_id: revisionId }),
    );
    mocks.moveRevisionNodes.mockResolvedValue({ revision_id: 7, lock_version: 1 });
    mocks.createRevisionTask.mockResolvedValue({ revision_id: 7, lock_version: 1, node_id: 99, work_item_id: 99 });
    mocks.deleteRevisionNodes.mockResolvedValue({ revision_id: 7, lock_version: 1, removed_node_ids: [], cost_losses: [] });
    mocks.updateRevisionPlanFacet.mockResolvedValue({ revision_id: 7, lock_version: 1 });
    mocks.replaceRevisionPredecessors.mockResolvedValue({ revision_id: 7, lock_version: 1 });
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });
    mocks.savePlanningStructureDraft.mockResolvedValue({ planning_id: 2, structure: { posts: [] } });
    mocks.getPlanningStructureDraft.mockResolvedValue(null);
    mocks.reopenPlanningStructure.mockResolvedValue(project({ status: "initialise", displayed_planning_id: 3 }));
    mocks.skipPlanningStructure.mockResolvedValue(project({ status: "initialise", displayed_planning_id: 3 }));
    mocks.createImportBatch.mockResolvedValue({ id: 42 });
    mocks.uploadImportSourceXml.mockResolvedValue({ id: 42 });
    mocks.runImportBatch.mockResolvedValue({ batchId: 42, revisionId: 7, revisionCreated: false });
    mocks.getImportBatchStatus.mockResolvedValue({ status: "success" });
    mocks.getImportBatchDiff.mockResolvedValue({ batchId: 42, identicalSource: false, items: [], costLosses: [] });
  });

  afterEach(() => cleanup());

  it("shows only the hierarchical structure form for a new project", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);

    render(<ProjectDetailsPage />);

    expect(await screen.findByRole("heading", { name: "Lotissement du projet" })).toBeInTheDocument();
    expect(screen.queryByText("Aucune tâche.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Générer le squelette" })).toBeInTheDocument();
  });

  it("shows a blocking non technical error when initial planning metadata fails", async () => {
    mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
    mocks.listPlannings.mockRejectedValue(
      new ApiError(500, "sqlalchemy.exc.ProgrammingError: SELECT wf_planning.revision"),
    );

    render(<ProjectDetailsPage />);

    expect(await screen.findByText("Projet indisponible")).toBeInTheDocument();
    expect(screen.getByText(/Réessaie dans quelques instants/)).toBeInTheDocument();
    expect(screen.queryByText(/sqlalchemy/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/base est migrée/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/remise à jour/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Planning affiché")).not.toBeInTheDocument();
    expect(mocks.getPlanning).not.toHaveBeenCalled();
  });

  // Regression test for #227: the initial load effect's catch guards on `cancelled`
  // (set by the effect's cleanup, e.g. when the user navigates away before the
  // request resolves) *before* checking for session expiry. Per issue #227, a
  // request that became obsolete and failed precisely because the session expired
  // must still force a logout -- otherwise the session would never get invalidated
  // once the user has moved on. Unmounting before the pending request settles is
  // the way this effect's `cancelled` flag becomes true (see the `useEffect`
  // cleanup in page.tsx), simulating "the user navigated elsewhere".
  it("still logs out when the initial load's now-cancelled request fails with a post-refresh 401", async () => {
    let rejectLoad!: (cause: unknown) => void;
    mocks.getProject.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectLoad = reject;
        }),
    );
    mocks.listProjectEstimates.mockResolvedValue([]);
    mocks.listPlannings.mockResolvedValue([]);
    mocks.listRevisions.mockResolvedValue(emptyRevisionList());
    mocks.getRevisionNodes.mockImplementation(async (_projectId: number, revisionId: number) =>
      revisionTree({ revision_id: revisionId }),
    );
    mocks.moveRevisionNodes.mockResolvedValue({ revision_id: 7, lock_version: 1 });
    mocks.createRevisionTask.mockResolvedValue({ revision_id: 7, lock_version: 1, node_id: 99, work_item_id: 99 });
    mocks.deleteRevisionNodes.mockResolvedValue({ revision_id: 7, lock_version: 1, removed_node_ids: [], cost_losses: [] });
    mocks.updateRevisionPlanFacet.mockResolvedValue({ revision_id: 7, lock_version: 1 });
    mocks.replaceRevisionPredecessors.mockResolvedValue({ revision_id: 7, lock_version: 1 });

    const { unmount } = render(<ProjectDetailsPage />);
    await waitFor(() => expect(mocks.getProject).toHaveBeenCalledTimes(1));

    // Simulates the user navigating away before the request resolves: the
    // effect's cleanup runs, setting `cancelled = true`.
    unmount();

    rejectLoad(new ApiError(401, "Unauthorized"));
    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  // Regression test for #230: exportPlanningXml only checked SessionExpiredError, missing the
  // ApiError(401) authFetch throws when a token refresh succeeds but the replayed request still
  // 401s (same bug family as #216).
  it("logs out when exporting the planning fails with a post-refresh 401", async () => {
    mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
    mocks.listPlannings.mockResolvedValue([]);
    mocks.exportProjectXml.mockRejectedValue(new ApiError(401, "Unauthorized"));

    render(<ProjectDetailsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Export XML" }));

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
    // The fallback branch (`setError(cause instanceof ApiError ? cause.message : ...)`) would
    // render the raw backend message, not the generic French string, for an ApiError -- assert
    // against the string that could actually leak, not one this branch could never produce.
    expect(screen.queryByText("Unauthorized")).not.toBeInTheDocument();
  });

  // Regression test for the Haute finding on #230's own review: every catch block of this file
  // must treat a post-refresh 401 as a session expiry. E14-11 (#337) replaced the Devis tab's own
  // reads by the revision's: this is the same guard, on the read that took their place.
  it("logs out when loading the revision's totals fails with a post-refresh 401", async () => {
    mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
    mocks.listPlannings.mockResolvedValue([]);
    mocks.listRevisions.mockResolvedValue(revisionList([revisionSummary()]));
    mocks.getRevisionAggregates.mockRejectedValue(new ApiError(401, "Unauthorized"));

    render(<ProjectDetailsPage />);
    // The totals are only read while the Devis tab is the one on screen, so the guard is only
    // reachable from there -- this click is what actually crosses it.
    fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));

    await waitFor(() => expect(mocks.getRevisionAggregates).toHaveBeenCalled());
    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("logs out when loading the estimate aggregates fails with a post-refresh 401", async () => {
    mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
    mocks.listPlannings.mockResolvedValue([]);
    mocks.listProjectEstimates.mockResolvedValue([
      {
        id: 1,
        project_id: 1,
        planning_id: null,
        version_number: 1,
        kind: "initial",
        status: "draft",
        currency_code: "EUR",
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mocks.getEstimateAggregates.mockRejectedValue(new ApiError(401, "Unauthorized"));

    render(<ProjectDetailsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Analytique" }));

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Impossible de charger les agrégats.")).not.toBeInTheDocument();
  });

  it("saves the structure draft without closing the form or generating a planning", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    fireEvent.change(screen.getByLabelText("Nom poste 1"), { target: { value: "Poste" } });
    fireEvent.change(screen.getByLabelText("Nom lot 1.1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrable 1.1.1"), { target: { value: "Livrable" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(mocks.savePlanningStructureDraft).toHaveBeenCalledTimes(1));
    expect(mocks.savePlanningStructureDraft).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ posts: expect.any(Array) }),
      expect.anything(),
      expect.anything(),
    );
    expect(mocks.createPlanningStructure).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Lotissement du projet" })).toBeInTheDocument();
  });

  it("uses the generation action and closes the structure form", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    fireEvent.change(screen.getByLabelText("Nom poste 1"), { target: { value: "Poste" } });
    fireEvent.change(screen.getByLabelText("Nom lot 1.1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrable 1.1.1"), { target: { value: "Livrable" } });
    fireEvent.click(screen.getByRole("button", { name: "Générer le squelette" }));

    await waitFor(() => expect(mocks.createPlanningStructure).toHaveBeenCalledTimes(1));
    expect(mocks.createPlanningStructure).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ posts: expect.any(Array) }),
      expect.anything(),
      expect.anything(),
    );
    expect(mocks.savePlanningStructureDraft).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Lotissement du projet" })).not.toBeInTheDocument(),
    );
  });

  it("only shows a progress label on the structure action actually running", async () => {
    // Regression: the three structure actions share a single busy flag to stay mutually
    // exclusive, but each button must only claim to be busy when it is the one actually running
    // -- not all three at once.
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    let resolveGenerate!: (value: { tasks: never[] }) => void;
    mocks.createPlanningStructure.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGenerate = resolve;
        }),
    );

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    fireEvent.change(screen.getByLabelText("Nom poste 1"), { target: { value: "Poste" } });
    fireEvent.change(screen.getByLabelText("Nom lot 1.1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrable 1.1.1"), { target: { value: "Livrable" } });
    fireEvent.click(screen.getByRole("button", { name: "Générer le squelette" }));

    await waitFor(() => expect(mocks.createPlanningStructure).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Génération..." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Passer cette étape" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Passer cette étape" })).toBeDisabled();

    resolveGenerate({ tasks: [] });
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Lotissement du projet" })).not.toBeInTheDocument(),
    );
  });

  it("allows skipping the structure step even with empty post/lot/deliverable fields", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    mocks.skipPlanningStructure.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: 3 }),
    );
    mocks.getPlanning.mockResolvedValue(detail(planning({ id: 3, status: "draft" })));

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    fireEvent.click(screen.getByRole("button", { name: "Passer cette étape" }));

    await waitFor(() => expect(mocks.skipPlanningStructure).toHaveBeenCalledTimes(1));
    expect(mocks.skipPlanningStructure).toHaveBeenCalledWith(1, expect.anything(), expect.anything());
    expect(mocks.createPlanningStructure).not.toHaveBeenCalled();
    expect(mocks.savePlanningStructureDraft).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Lotissement du projet" })).not.toBeInTheDocument(),
    );
  });

  it("reveals the MS Project import once the structure step has been skipped", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    mocks.skipPlanningStructure.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: 3 }),
    );
    mocks.getPlanning.mockResolvedValue(detail(planning({ id: 3, status: "draft" })));

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    fireEvent.click(screen.getByRole("button", { name: "Passer cette étape" }));

    expect(await screen.findByLabelText("Importer un planning MS Project (.xml)")).toBeInTheDocument();
  });

  it("closes the structure screen and reports a distinct error when the post-skip refresh fails", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValueOnce([]).mockRejectedValueOnce(new Error("network"));
    mocks.skipPlanningStructure.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: 3 }),
    );

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    fireEvent.click(screen.getByRole("button", { name: "Passer cette étape" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Lotissement du projet" })).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByText("Passage effectué, mais impossible de recharger le planning. Recharge la page."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Impossible de passer cette étape.")).not.toBeInTheDocument();
  });

  it("hides the skip button after reopening a structure that has already left status cree", async () => {
    const draftAfterSkip = planning({ id: 3, status: "draft" });
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValueOnce([]).mockResolvedValue([draftAfterSkip]);
    mocks.skipPlanningStructure.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: 3 }),
    );
    mocks.reopenPlanningStructure.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: 3 }),
    );
    mocks.getPlanning.mockResolvedValue(detail(draftAfterSkip));

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    expect(screen.getByRole("button", { name: "Passer cette étape" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Passer cette étape" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Lotissement du projet" })).not.toBeInTheDocument(),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Rouvrir la structure" }));

    expect(await screen.findByRole("heading", { name: "Lotissement du projet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Passer cette étape" })).not.toBeInTheDocument();
  });

  it("hides the skip button for a cree project that already has a displayed/reference planning", async () => {
    mocks.getProject.mockResolvedValue(
      project({ status: "cree", displayed_planning_id: 3, planning_reference_id: 3 }),
    );
    mocks.listPlannings.mockResolvedValue([planning({ id: 3, status: "draft" })]);
    mocks.getPlanning.mockResolvedValue(detail(planning({ id: 3, status: "draft" })));

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Lotissement du projet" });
    expect(screen.queryByRole("button", { name: "Passer cette étape" })).not.toBeInTheDocument();
  });


  it("allows reopening an existing draft without a planning reference", async () => {
    const draft = planning({ id: 3, status: "draft" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(detail(draft));

    render(<ProjectDetailsPage />);

    expect(await screen.findByRole("button", { name: "Rouvrir la structure" })).toBeInTheDocument();
  });

  it("allows reopening from a validated planning reference without a draft", async () => {
    const reference = planning({ id: 4, status: "validated" });
    mocks.getProject.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: reference.id, planning_reference_id: reference.id }),
    );
    mocks.listPlannings.mockResolvedValue([reference]);
    mocks.getPlanning.mockResolvedValue(detail(reference));

    render(<ProjectDetailsPage />);

    expect(await screen.findByRole("button", { name: "Rouvrir la structure" })).toBeInTheDocument();
  });

  it("allows reopening a validated planning that was never set as reference", async () => {
    const validated = planning({ id: 4, status: "validated" });
    mocks.getProject.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: validated.id, planning_reference_id: null }),
    );
    mocks.listPlannings.mockResolvedValue([validated]);
    mocks.getPlanning.mockResolvedValue(detail(validated));

    render(<ProjectDetailsPage />);

    expect(await screen.findByRole("button", { name: "Rouvrir la structure" })).toBeInTheDocument();
  });

  it("hydrates the structure form from a saved draft", async () => {
    const draft = planning({ id: 3, status: "draft" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(detail(draft));
    mocks.getPlanningStructureDraft.mockResolvedValue({
      planning_id: draft.id,
      structure: {
        posts: [{
          key: "post-1",
          name: "Poste sauvegardé",
          lots: [{ key: "lot-1", name: "Lot sauvegardé", deliverables: [{ key: "deliverable-1", name: "Livrable sauvegardé" }] }],
        }],
      },
    });

    render(<ProjectDetailsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Rouvrir la structure" }));

    expect(await screen.findByDisplayValue("Poste sauvegardé")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Lot sauvegardé")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Livrable sauvegardé")).toBeInTheDocument();
  });


  it("previews an import and refreshes the selected planning after confirmation", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject
      .mockResolvedValueOnce(project({ status: "initialise", displayed_planning_id: current.id }))
      .mockResolvedValueOnce(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings
      .mockResolvedValueOnce([current])
      .mockResolvedValueOnce([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const file = new File(["<Project />"], "planning.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

    await waitFor(() => expect(mocks.getImportBatchDiff).toHaveBeenCalledWith(
      42,
      expect.anything(),
      expect.anything(),
    ));
    expect(mocks.getImportBatchStatus).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Remplacement à confirmer" })).toBeInTheDocument();
    expect(mocks.runImportBatch).toHaveBeenCalledWith(42, expect.anything(), expect.anything(), true, false);

    fireEvent.click(screen.getByRole("button", { name: "Confirmer le remplacement" }));
    await waitFor(() => expect(mocks.runImportBatch).toHaveBeenLastCalledWith(
      42,
      expect.anything(),
      expect.anything(),
      false,
      true,
    ));
    await waitFor(() => expect(mocks.listPlannings).toHaveBeenCalledTimes(2));
    expect(mocks.getPlanning).toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();
  });

  // Regression coverage for the round-2 Copilot review on #132: `importReview.batchId` refers to
  // whatever file was uploaded when the preview was last requested. Selecting a new candidate file
  // afterwards -- even a valid one -- must invalidate that stale preview immediately, otherwise
  // "Confirmer le remplacement" would still submit the previous (file A) batch while the UI shows
  // file B as selected.
  it("invalidates a pending import preview when a new file is selected before confirming", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileA] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

    await waitFor(() => expect(mocks.getImportBatchDiff).toHaveBeenCalledWith(
      42,
      expect.anything(),
      expect.anything(),
    ));
    expect(screen.getByRole("heading", { name: "Remplacement à confirmer" })).toBeInTheDocument();

    const fileB = new File(["<Project />"], "b.xml", { type: "application/xml" });
    fireEvent.change(screen.getByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileB] },
    });

    expect(await screen.findByText("Fichier sélectionné : b.xml")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();
  });

  it("invalidates a pending import preview even when the newly selected file is rejected", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileA] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

    await waitFor(() => expect(mocks.getImportBatchDiff).toHaveBeenCalledWith(
      42,
      expect.anything(),
      expect.anything(),
    ));
    expect(screen.getByRole("heading", { name: "Remplacement à confirmer" })).toBeInTheDocument();

    const wrongTypeFile = new File(["not xml"], "b.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const dropZone = screen.getByRole("group", { name: "Zone de dépôt du fichier de planning à importer" });
    fireEvent.drop(dropZone, { dataTransfer: { files: [wrongTypeFile] } });

    expect(await screen.findByText("Seuls les fichiers .xml sont acceptés.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();
  });

  // Regression coverage for the round-3 review on #132: invalidating `importReview` when the
  // candidate file changes (see the two tests above) only covers the case where the change
  // happens *after* a preview request has already settled. If the user swaps the candidate file
  // WHILE the preview request for the previous file is still in flight, the request must not be
  // allowed to resurrect a review banner for a file that is no longer selected once it resolves.
  it("drops a stale preview result if the candidate file changed while the request was in flight", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    let resolveDiff!: (value: ImportDiff) => void;
    mocks.getImportBatchDiff.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveDiff = resolve;
        }),
    );

    render(<ProjectDetailsPage />);
    const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileA] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

    await waitFor(() => expect(mocks.getImportBatchDiff).toHaveBeenCalledTimes(1));

    const fileB = new File(["<Project />"], "b.xml", { type: "application/xml" });
    fireEvent.change(screen.getByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileB] },
    });
    expect(await screen.findByText("Fichier sélectionné : b.xml")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();

    resolveDiff({ batchId: 42, identicalSource: false, items: [], costLosses: [] });
    // Wait for the (now-stale) preview request to actually settle -- the busy button reverting to
    // its idle label is the observable signal that `preparePlanningImport`'s `finally` block ran --
    // before asserting the stale result was dropped rather than resurrecting the review banner.
    await screen.findByRole("button", { name: "Prévisualiser l'import" });
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();
    expect(screen.getByText("Fichier sélectionné : b.xml")).toBeInTheDocument();
  });

  it("does not show a stale import error if the candidate file changed while the request was in flight", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    let rejectDiff!: (error: Error) => void;
    mocks.getImportBatchDiff.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectDiff = reject;
        }),
    );

    render(<ProjectDetailsPage />);
    const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileA] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

    await waitFor(() => expect(mocks.getImportBatchDiff).toHaveBeenCalledTimes(1));

    const fileB = new File(["<Project />"], "b.xml", { type: "application/xml" });
    fireEvent.change(screen.getByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileB] },
    });
    expect(await screen.findByText("Fichier sélectionné : b.xml")).toBeInTheDocument();

    rejectDiff(new Error("boom"));
    // Wait for the (now-stale) preview request to actually settle -- the busy button reverting to
    // its idle label is the observable signal that `preparePlanningImport`'s `finally` block ran --
    // before asserting no error message was shown for a request tied to a file that is no longer
    // selected.
    await screen.findByRole("button", { name: "Prévisualiser l'import" });
    expect(screen.queryByText("Impossible d'importer le planning.")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();
    expect(screen.getByText("Fichier sélectionné : b.xml")).toBeInTheDocument();
  });

  // Regression test for #230: preparePlanningImport only checked SessionExpiredError, missing
  // the ApiError(401) authFetch throws when a token refresh succeeds but the replayed request
  // still 401s (same bug family as #216).
  it("logs out when previewing the import fails with a post-refresh 401", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));
    mocks.createImportBatch.mockRejectedValue(new ApiError(401, "Unauthorized"));

    render(<ProjectDetailsPage />);
    const file = new File(["<Project />"], "a.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
    // Same reasoning as the export test above: the fallback branch would render the raw
    // ApiError message, never the generic French string, so assert against what could leak.
    expect(screen.queryByText("Unauthorized")).not.toBeInTheDocument();
  });

  it("imports a dropped file the same way as a manually selected file", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject
      .mockResolvedValueOnce(project({ status: "initialise", displayed_planning_id: current.id }))
      .mockResolvedValueOnce(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings
      .mockResolvedValueOnce([current])
      .mockResolvedValueOnce([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const file = new File(["<Project />"], "planning.xml", { type: "application/xml" });
    const dropZone = await screen.findByRole("group", {
      name: "Zone de dépôt du fichier de planning à importer",
    });
    fireEvent.drop(dropZone, { dataTransfer: { files: [file] } });

    const previewButton = screen.getByRole("button", { name: "Prévisualiser l'import" });
    expect(previewButton).not.toBeDisabled();
    fireEvent.click(previewButton);

    await waitFor(() => expect(mocks.getImportBatchDiff).toHaveBeenCalledWith(
      42,
      expect.anything(),
      expect.anything(),
    ));
    expect(screen.getByRole("heading", { name: "Remplacement à confirmer" })).toBeInTheDocument();
  });

  it("refuses a dropped file larger than 25 MiB with the same message as the manual picker", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const oversizedFile = new File(["<Project />"], "planning.xml", { type: "application/xml" });
    Object.defineProperty(oversizedFile, "size", { value: 25 * 1024 * 1024 + 1 });
    const dropZone = await screen.findByRole("group", {
      name: "Zone de dépôt du fichier de planning à importer",
    });
    fireEvent.drop(dropZone, { dataTransfer: { files: [oversizedFile] } });

    expect(await screen.findByText("Le fichier XML ne doit pas dépasser 25 MiB.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prévisualiser l'import" })).toBeDisabled();
    expect(mocks.createImportBatch).not.toHaveBeenCalled();
  });

  it("refuses a dropped file of a different type with an explicit message", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const wrongTypeFile = new File(["not xml"], "planning.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const dropZone = await screen.findByRole("group", {
      name: "Zone de dépôt du fichier de planning à importer",
    });
    fireEvent.drop(dropZone, { dataTransfer: { files: [wrongTypeFile] } });

    expect(await screen.findByText("Seuls les fichiers .xml sont acceptés.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prévisualiser l'import" })).toBeDisabled();
    expect(mocks.createImportBatch).not.toHaveBeenCalled();
  });

  it("refuses dropping multiple files without a silent failure", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const fileOne = new File(["<Project />"], "planning-1.xml", { type: "application/xml" });
    const fileTwo = new File(["<Project />"], "planning-2.xml", { type: "application/xml" });
    const dropZone = await screen.findByRole("group", {
      name: "Zone de dépôt du fichier de planning à importer",
    });
    fireEvent.drop(dropZone, { dataTransfer: { files: [fileOne, fileTwo] } });

    expect(await screen.findByText("Dépose un seul fichier à la fois.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prévisualiser l'import" })).toBeDisabled();
    expect(mocks.createImportBatch).not.toHaveBeenCalled();
  });

  it("refuses an empty drop (e.g. a dropped directory) with an explicit error instead of staying silent", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const dropZone = await screen.findByRole("group", {
      name: "Zone de dépôt du fichier de planning à importer",
    });
    fireEvent.drop(dropZone, { dataTransfer: { files: [] } });

    expect(
      await screen.findByText(
        "Le dépôt ne contient aucun fichier exploitable (dossier non pris en charge ou élément invalide).",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prévisualiser l'import" })).toBeDisabled();
    expect(mocks.createImportBatch).not.toHaveBeenCalled();
  });

  it("replaces a manually selected file with a subsequently dropped one, not the other way around", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
    const fileB = new File(["<Project />"], "b.xml", { type: "application/xml" });

    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileA] },
    });
    expect(await screen.findByText("Fichier sélectionné : a.xml")).toBeInTheDocument();

    const dropZone = screen.getByRole("group", { name: "Zone de dépôt du fichier de planning à importer" });
    fireEvent.drop(dropZone, { dataTransfer: { files: [fileB] } });

    expect(await screen.findByText("Fichier sélectionné : b.xml")).toBeInTheDocument();
    expect(screen.queryByText("Fichier sélectionné : a.xml")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));
    await waitFor(() => expect(mocks.uploadImportSourceXml).toHaveBeenCalledWith(
      42,
      fileB,
      expect.anything(),
      expect.anything(),
    ));
  });

  it("clears the displayed selection when a drop is rejected after a valid manual selection", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: current.id }));
    mocks.listPlannings.mockResolvedValue([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
    const wrongTypeFile = new File(["not xml"], "planning.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });

    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [fileA] },
    });
    expect(await screen.findByText("Fichier sélectionné : a.xml")).toBeInTheDocument();

    const dropZone = screen.getByRole("group", { name: "Zone de dépôt du fichier de planning à importer" });
    fireEvent.drop(dropZone, { dataTransfer: { files: [wrongTypeFile] } });

    expect(await screen.findByText("Seuls les fichiers .xml sont acceptés.")).toBeInTheDocument();
    expect(screen.getByText("Aucun fichier sélectionné.")).toBeInTheDocument();
    expect(screen.queryByText("Fichier sélectionné : a.xml")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prévisualiser l'import" })).toBeDisabled();
  });

  it("keeps the import success visible when a post-import refresh fails", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject
      .mockResolvedValueOnce(project({ status: "initialise", displayed_planning_id: current.id }))
      .mockRejectedValueOnce(new Error("refresh failed"));
    mocks.listPlannings
      .mockResolvedValueOnce([current])
      .mockResolvedValueOnce([current]);
    mocks.getPlanning.mockResolvedValue(detail(current));

    render(<ProjectDetailsPage />);
    const file = new File(["<Project />"], "planning.xml", { type: "application/xml" });
    fireEvent.change(await screen.findByLabelText("Importer un planning MS Project (.xml)"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));
    await screen.findByRole("heading", { name: "Remplacement à confirmer" });

    fireEvent.click(screen.getByRole("button", { name: "Confirmer le remplacement" }));

    await waitFor(() => expect(screen.getByText(/Import réussi, mais le projet/)).toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "Remplacement à confirmer" })).not.toBeInTheDocument();
    expect(mocks.runImportBatch).toHaveBeenCalledTimes(2);
  });


  // E6-06/#67 (Haute + Moyenne review findings): creating a task from the Devis tab must
  // refresh `planningDetail` -- without a page reload -- so the "Tâche parente" selector in a
  // second, consecutive "Ajouter une tâche au planning" can offer the task just created.
  // ------------------------------------------------------------------------------------------
  // E14-11 (#337): the Devis tab and the Planning tab are two views of **one** tree. Nothing
  // below mocks a synchronisation: there is none to mock.
  // ------------------------------------------------------------------------------------------

  describe("the Devis tab, on the same revision as the Planning tab", () => {
    function openDevisTab() {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(revisionList([revisionSummary()]));
    }

    it("shows the very tree the Planning tab shows, cost lines included", async () => {
      openDevisTab();
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({
          nodes: [taskNode(1, { name: "Poste", rowNumber: 1 }), costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Béton" })],
        }),
      );

      render(<ProjectDetailsPage />);
      // The Planning tab renders the task and not the cost line...
      expect(await screen.findByRole("treegrid", { name: "Planning de la révision" })).toBeInTheDocument();
      expect(screen.queryByText("Béton")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Devis" }));

      // ...the Devis grid renders both, out of the same single read.
      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });
      expect(within(grid).getByLabelText("Libellé de Poste")).toBeInTheDocument();
      expect(within(grid).getByLabelText("Libellé de Béton")).toBeInTheDocument();
      expect(mocks.getRevisionNodes).toHaveBeenCalledTimes(1);
    });

    // Criterion 3 of #337: moving a task from the devis grid moves it in the planning table, with
    // no action in between -- because it is the same move on the same tree.
    it("moves a task from the devis grid and the planning table follows, with no synchronisation", async () => {
      openDevisTab();
      mocks.getRevisionNodes
        .mockResolvedValueOnce(
          revisionTree({
            nodes: [
              taskNode(1, { name: "Poste A", position: 1, rowNumber: 1 }),
              taskNode(2, { name: "Poste B", position: 2, rowNumber: 2 }),
            ],
          }),
        )
        .mockResolvedValue(
          revisionTree({
            lock_version: 1,
            nodes: [
              taskNode(2, { name: "Poste B", position: 1, rowNumber: 1 }),
              taskNode(1, { name: "Poste A", position: 2, rowNumber: 2 }),
            ],
          }),
        );

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));

      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });
      fireEvent.click(within(grid).getByLabelText("Libellé de Poste B").closest("tr") as HTMLElement);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      await waitFor(() =>
        expect(mocks.moveRevisionNodes).toHaveBeenCalledWith(
          1,
          7,
          { expected_lock_version: 0, node_ids: [2], mode: "up" },
          expect.anything(),
          expect.anything(),
        ),
      );

      fireEvent.click(screen.getByRole("tab", { name: "Planning" }));
      const planning = await screen.findByRole("treegrid", { name: "Planning de la révision" });
      const rows = within(planning).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Poste B")).toBeInTheDocument();
      expect(within(rows[0]).getByText("1")).toBeInTheDocument();
    });

    // Criterion 2: a cost line's move is not visible *as a row* in the planning table (which only
    // renders tasks) but the tree it renumbers is the same one -- so the planning's own positional
    // identifiers follow, again with nothing to synchronise.
    it("moves a cost line from the devis grid and the planning's numbering follows", async () => {
      openDevisTab();
      mocks.getRevisionNodes
        .mockResolvedValueOnce(
          revisionTree({
            nodes: [
              taskNode(1, { name: "Poste A", position: 1, rowNumber: 1 }),
              costNode(2, { label: "Béton", position: 2, rowNumber: 2 }),
              taskNode(3, { name: "Poste C", position: 3, rowNumber: 3 }),
            ],
          }),
        )
        .mockResolvedValue(
          revisionTree({
            lock_version: 1,
            nodes: [
              taskNode(1, { name: "Poste A", position: 1, rowNumber: 1 }),
              taskNode(3, { name: "Poste C", position: 2, rowNumber: 2 }),
              costNode(2, { label: "Béton", position: 3, rowNumber: 3 }),
            ],
          }),
        );

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));

      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });
      fireEvent.click(within(grid).getByLabelText("Libellé de Béton").closest("tr") as HTMLElement);
      fireEvent.click(screen.getByRole("button", { name: "Descendre" }));

      await waitFor(() =>
        expect(mocks.moveRevisionNodes).toHaveBeenCalledWith(
          1,
          7,
          { expected_lock_version: 0, node_ids: [2], mode: "down" },
          expect.anything(),
          expect.anything(),
        ),
      );

      fireEvent.click(screen.getByRole("tab", { name: "Planning" }));
      const planning = await screen.findByRole("treegrid", { name: "Planning de la révision" });
      const rows = within(planning).getAllByRole("row").slice(1);
      expect(within(rows[1]).getByText("Poste C")).toBeInTheDocument();
      expect(within(rows[1]).getByText("2")).toBeInTheDocument();
    });

    it("adds a task to the planning from the Devis tab, on the revision's own endpoint", async () => {
      openDevisTab();
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({ nodes: [taskNode(1, { name: "Poste", rowNumber: 1 })] }),
      );

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      fireEvent.click(await screen.findByRole("button", { name: "Ajouter une tâche" }));

      const dialog = await screen.findByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText("Nom de la nouvelle tâche"), {
        target: { value: "Terrassement" },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Ajouter" }));

      await waitFor(() =>
        expect(mocks.createRevisionTask).toHaveBeenCalledWith(
          1,
          7,
          { name: "Terrassement", is_milestone: false, parent_id: null, position: null, expected_lock_version: 0 },
          expect.anything(),
          expect.anything(),
        ),
      );
    });

    it("creates a cost line carrying its whole non-MO shape, and re-reads the tree it wrote into", async () => {
      openDevisTab();
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({ nodes: [taskNode(1, { name: "Poste", rowNumber: 1 })] }),
      );

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      await screen.findByRole("treegrid", { name: "Devis de la révision" });
      fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne de coût" }));

      await waitFor(() =>
        expect(mocks.createRevisionCostLine).toHaveBeenCalledWith(
          1,
          7,
          expect.objectContaining({ nature: "non_labor", expected_lock_version: 0, parent_id: null }),
          expect.anything(),
          expect.anything(),
        ),
      );
      // A write answers the counter and not the tree, so the screen re-reads it (row_number, level
      // and the bearing task are all computed on read).
      await waitFor(() => expect(mocks.getRevisionNodes).toHaveBeenCalledTimes(2));
    });

    // Criterion 5 of #337 is only observable if the figure follows the tree: the revision's totals
    // are re-read whenever its lock counter advances, that is after every write.
    it("re-reads the revision's totals after a write, so the figure follows the tree", async () => {
      openDevisTab();
      mocks.getRevisionNodes
        .mockResolvedValueOnce(
          revisionTree({
            nodes: [
              taskNode(1, { name: "Poste", rowNumber: 1 }),
              costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
            ],
          }),
        )
        .mockResolvedValue(
          revisionTree({
            lock_version: 1,
            nodes: [
              taskNode(1, { name: "Poste", rowNumber: 1 }),
              costNode(2, { position: 2, rowNumber: 2, label: "Béton" }),
            ],
          }),
        );
      // Amounts no cell of the grid itself computes, so the assertion can only be reading the
      // published total and not a row's own PRU.
      mocks.getRevisionAggregates
        .mockResolvedValueOnce(revisionAggregates({ total_purchase_cost: "1234.00" }))
        .mockResolvedValue(revisionAggregates({ total_purchase_cost: "2345.00" }));

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });
      await screen.findByText("1 234,00 €");

      // Outdented to the root: it bears no task any more, and is counted all the same.
      fireEvent.click(within(grid).getByLabelText("Libellé de Béton").closest("tr") as HTMLElement);
      fireEvent.click(screen.getByRole("button", { name: "Désindenter" }));

      expect(await screen.findByText("2 345,00 €")).toBeInTheDocument();
    });

    it("keeps the displayed revision's totals while a write's new ones are being read", async () => {
      // The counterpart of the test above, and the reason the clearing is bound to a *change of
      // revision*: blanking the three cards on every `lock_version` bump would be a flicker after
      // every edit, not a correction -- the figures still describe the revision on screen, a cent
      // out of date for the length of one request.
      openDevisTab();
      mocks.getRevisionNodes
        .mockResolvedValueOnce(
          revisionTree({
            nodes: [
              taskNode(1, { name: "Poste", rowNumber: 1 }),
              costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
            ],
          }),
        )
        .mockResolvedValue(
          revisionTree({
            lock_version: 1,
            nodes: [
              taskNode(1, { name: "Poste", rowNumber: 1 }),
              costNode(2, { position: 2, rowNumber: 2, label: "Béton" }),
            ],
          }),
        );
      mocks.getRevisionAggregates
        .mockResolvedValueOnce(revisionAggregates({ total_purchase_cost: "1234.00" }))
        .mockReturnValue(new Promise<RevisionAggregates>(() => undefined));

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });
      await screen.findByText("1 234,00 €");

      fireEvent.click(within(grid).getByLabelText("Libellé de Béton").closest("tr") as HTMLElement);
      fireEvent.click(screen.getByRole("button", { name: "Désindenter" }));

      await waitFor(() => expect(mocks.getRevisionAggregates).toHaveBeenCalledTimes(2));
      expect(screen.getByText("1 234,00 €")).toBeInTheDocument();
    });

    it("exports the displayed revision's devis, and not some other document", async () => {
      openDevisTab();
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({ nodes: [taskNode(1, { name: "Poste", rowNumber: 1 })] }),
      );
      mocks.exportRevisionExcel.mockResolvedValue(new Blob(["x"]));
      const createObjectURL = vi.fn(() => "blob:devis");
      const revokeObjectURL = vi.fn();
      Object.defineProperty(window.URL, "createObjectURL", { value: createObjectURL, configurable: true });
      Object.defineProperty(window.URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      fireEvent.click(await screen.findByRole("button", { name: "Exporter le devis" }));

      await waitFor(() =>
        expect(mocks.exportRevisionExcel).toHaveBeenCalledWith(1, 7, expect.anything(), expect.anything()),
      );
      await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    });

    // E6-03's bulk assignment, carried over to the revision: several writes, one lock counter.
    it("assigns a cost code to a selection, threading the counter from one write to the next", async () => {
      openDevisTab();
      mocks.getProjectCostCodes.mockResolvedValue([{ id: 3, code: "C1", name: "Chantier" }]);
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({
          nodes: [
            costNode(1, { label: "Béton", position: 1, rowNumber: 1 }),
            costNode(2, { label: "Acier", position: 2, rowNumber: 2 }),
          ],
        }),
      );
      mocks.updateRevisionCostFacet
        .mockResolvedValueOnce({ revision_id: 7, lock_version: 1 })
        .mockResolvedValue({ revision_id: 7, lock_version: 2 });

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });

      fireEvent.click(within(grid).getByLabelText("Libellé de Béton").closest("tr") as HTMLElement);
      fireEvent.click(within(grid).getByLabelText("Libellé de Acier").closest("tr") as HTMLElement, {
        ctrlKey: true,
      });
      fireEvent.change(screen.getByLabelText("Code d'imputation"), { target: { value: "3" } });
      fireEvent.click(screen.getByRole("button", { name: "Affecter" }));

      await waitFor(() => expect(mocks.updateRevisionCostFacet).toHaveBeenCalledTimes(2));
      // React state does not update between two awaits, so a loop of independent writes would send
      // `0` twice and 409 on the second line. The second call must carry what the first answered.
      expect(mocks.updateRevisionCostFacet.mock.calls[0][3]).toEqual({
        expected_lock_version: 0,
        cost_code_id: 3,
      });
      expect(mocks.updateRevisionCostFacet.mock.calls[1][3]).toEqual({
        expected_lock_version: 1,
        cost_code_id: 3,
      });
    });

    // The amendment's second point, end to end: there is no `nature` to PATCH, so the switch is a
    // create followed by a delete, both under the same lock and in that order.
    it("switches a cost line to MO by replacing it, threading the lock counter through", async () => {
      openDevisTab();
      mocks.getResourceNodes.mockResolvedValue([
        { id: 1, parent_id: null, code: "DIR", name: "Direction", is_active: true, created_at: "", updated_at: "" },
        { id: 2, parent_id: 1, code: "ETU", name: "Études", is_active: true, created_at: "", updated_at: "" },
      ]);
      mocks.getResourceRoles.mockResolvedValue({
        items: [{ id: 7, node_id: 2, cost_category_id: 40, name: "Ingénieur", calendar_id: null, is_active: true, created_at: "", updated_at: "" }],
        total: 1,
      });
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({
          nodes: [
            taskNode(1, { name: "Poste", rowNumber: 1 }),
            costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
          ],
        }),
      );
      mocks.createRevisionCostLine.mockResolvedValue({ revision_id: 7, lock_version: 5, node_id: 99, work_item_id: 99 });

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      await screen.findByRole("treegrid", { name: "Devis de la révision" });
      await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());

      fireEvent.change(screen.getByLabelText("Type de Béton"), { target: { value: "labor" } });
      fireEvent.change(await screen.findByLabelText("Dpt 1er niveau de Béton"), { target: { value: "1" } });
      fireEvent.change(screen.getByLabelText("Dpt 2eme niveau de Béton"), { target: { value: "2" } });
      fireEvent.change(screen.getByLabelText("Rôle de Béton"), { target: { value: "7" } });

      await waitFor(() =>
        expect(mocks.createRevisionCostLine).toHaveBeenCalledWith(
          1,
          7,
          {
            nature: "labor",
            label: "Béton",
            quantity: 2,
            role_id: 7,
            hours: 0,
            // Nature-agnostic attributes, carried over so the replacement does not silently drop
            // them (empty on this fixture; estimate-grid-tree-table.test.tsx carries real ones).
            cost_code_id: null,
            comment: null,
            description: null,
            planned_date: null,
            // Same parent and same rank, so the row stays where the user left it.
            parent_id: 1,
            position: 1,
            expected_lock_version: 0,
          },
          expect.anything(),
          expect.anything(),
        ),
      );
      // The delete carries the counter the *create* answered, not the one read from the tree: the
      // two are one composite write, and re-reading React state between two awaits would send a
      // counter already spent.
      await waitFor(() =>
        expect(mocks.deleteRevisionNodes).toHaveBeenCalledWith(
          1,
          7,
          { expected_lock_version: 5, node_ids: [2] },
          expect.anything(),
          expect.anything(),
        ),
      );
    });

    // ----------------------------------------------------------------------------------------
    // The failure branches of the composite write, which is the most delicate path of #337: the
    // nominal case above is one request followed by another, and everything below is what
    // happens when the second one does not answer.
    // ----------------------------------------------------------------------------------------

    /** A revision whose only cost line can be switched, with the referential the cascade needs. */
    function switchableCostLine(nodes: RevisionNode[]) {
      openDevisTab();
      mocks.getResourceNodes.mockResolvedValue([
        { id: 1, parent_id: null, code: "DIR", name: "Direction", is_active: true, created_at: "", updated_at: "" },
        { id: 2, parent_id: 1, code: "ETU", name: "Études", is_active: true, created_at: "", updated_at: "" },
      ]);
      mocks.getResourceRoles.mockResolvedValue({
        items: [{ id: 7, node_id: 2, cost_category_id: 40, name: "Ingénieur", calendar_id: null, is_active: true, created_at: "", updated_at: "" }],
        total: 1,
      });
      mocks.getRevisionNodes.mockResolvedValue(revisionTree({ nodes }));
    }

    /** Walks the whole Dpt -> Dpt -> Rôle cascade on `label`, which is what asks for the switch. */
    async function switchToLabor(label: string) {
      fireEvent.change(screen.getByLabelText(`Type de ${label}`), { target: { value: "labor" } });
      fireEvent.change(await screen.findByLabelText(`Dpt 1er niveau de ${label}`), { target: { value: "1" } });
      fireEvent.change(screen.getByLabelText(`Dpt 2eme niveau de ${label}`), { target: { value: "2" } });
      fireEvent.change(screen.getByLabelText(`Rôle de ${label}`), { target: { value: "7" } });
    }

    it("never sends a nature switch for a line carrying sub-lines, and says why", async () => {
      // Two layers, both asserted. The command itself is withheld -- the rule is decided on the
      // row, before any request -- and the hook refuses the write anyway if the change ever
      // reaches it: this test forces exactly that by driving a control the user cannot operate,
      // which is the only thing defence in depth is ever for.
      switchableCostLine([
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
        costNode(3, { parentId: 2, position: 1, level: 3, rowNumber: 3, label: "Coffrage" }),
      ]);

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      await screen.findByRole("treegrid", { name: "Devis de la révision" });
      await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());

      expect(screen.getByLabelText("Type de Béton")).toBeDisabled();
      await switchToLabor("Béton");

      // The hook's message in full, not a prefix: the cell now *shows* its own refusal motif next
      // to the disabled select (a `title` would only have reached a mouse), and the two copies
      // share an opening. Matching loosely would let this assertion pass on the static cell text
      // alone, i.e. without the second layer it exists to observe.
      expect(
        await screen.findByText(
          "Cette ligne porte des sous-lignes : changer sa nature la remplace, ce qui supprimerait son sous-arbre. Déplace ou supprime ses sous-lignes d'abord.",
        ),
      ).toBeInTheDocument();
      // Nothing was created: a replacement would have taken the sub-line with it into the
      // delete's INV-02 cascade.
      expect(mocks.createRevisionCostLine).not.toHaveBeenCalled();
      expect(mocks.deleteRevisionNodes).not.toHaveBeenCalled();
    });

    it("names the half-applied state when the delete fails, offers no replay, and re-reads the tree", async () => {
      // The create landed and the delete did not, so the revision now holds *two* lines and its
      // counter has moved. Three things follow, and all three are the point:
      //   * the message names what happened rather than "impossible de changer la nature";
      //   * no "Réessayer": replaying the pair would create a second replacement;
      //   * the tree is re-read, so the duplicate the message tells the user to delete is on
      //     screen -- and the local lock counter is not left one write behind the server's.
      switchableCostLine([
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
      ]);
      mocks.createRevisionCostLine.mockResolvedValue({ revision_id: 7, lock_version: 5, node_id: 99, work_item_id: 99 });
      mocks.deleteRevisionNodes.mockRejectedValue(new ApiError(502, "Passerelle indisponible"));

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      await screen.findByRole("treegrid", { name: "Devis de la révision" });
      await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());
      expect(mocks.getRevisionNodes).toHaveBeenCalledTimes(1);

      await switchToLabor("Béton");

      expect(
        await screen.findByText(/l'ancienne n'a pas pu être supprimée : recharge la révision/),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
      // The re-read the failure branch owes: without it the grid never shows the duplicate, and
      // every later write leaves with a counter the create has already spent.
      await waitFor(() => expect(mocks.getRevisionNodes).toHaveBeenCalledTimes(2));
    });

    it("shows the reload banner when the delete half comes back on a stale counter", async () => {
      // The re-wrapping the composite write does must not cost the failure its classification: a
      // 409 REVISION_LOCK_CONFLICT stripped of its `detail.code` is no longer recognised as one,
      // and the banner -- the only way to resynchronise this screen -- never appears. The user is
      // then left on an editable grid where every write fails with a generic message and no exit.
      switchableCostLine([
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
      ]);
      mocks.createRevisionCostLine.mockResolvedValue({ revision_id: 7, lock_version: 5, node_id: 99, work_item_id: 99 });
      mocks.deleteRevisionNodes.mockRejectedValue(
        new ApiError(409, "Conflit de version", {
          code: "REVISION_LOCK_CONFLICT",
          revision_id: 7,
          expected_lock_version: 5,
          current_lock_version: 6,
        }),
      );

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      await screen.findByRole("treegrid", { name: "Devis de la révision" });
      await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());

      await switchToLabor("Béton");

      expect(await screen.findByRole("button", { name: "Recharger la révision" })).toBeInTheDocument();
    });

    it("re-reads the tree when a bulk cost-code assignment fails half-way through", async () => {
      // Same half-applied shape as the nature switch, one write later in the sequence: the first
      // line is written, the second is not, and the counter the tree still holds is the one the
      // first line already spent. Without the re-read every later write leaves with it.
      openDevisTab();
      mocks.getProjectCostCodes.mockResolvedValue([{ id: 3, code: "C1", name: "Chantier" }]);
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({
          nodes: [
            costNode(1, { label: "Béton", position: 1, rowNumber: 1 }),
            costNode(2, { label: "Acier", position: 2, rowNumber: 2 }),
          ],
        }),
      );
      mocks.updateRevisionCostFacet
        .mockResolvedValueOnce({ revision_id: 7, lock_version: 1 })
        .mockRejectedValue(new ApiError(502, "Passerelle indisponible"));

      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      const grid = await screen.findByRole("treegrid", { name: "Devis de la révision" });
      expect(mocks.getRevisionNodes).toHaveBeenCalledTimes(1);

      fireEvent.click(within(grid).getByLabelText("Libellé de Béton").closest("tr") as HTMLElement);
      fireEvent.click(within(grid).getByLabelText("Libellé de Acier").closest("tr") as HTMLElement, {
        ctrlKey: true,
      });
      fireEvent.change(screen.getByLabelText("Code d'imputation"), { target: { value: "3" } });
      fireEvent.click(screen.getByRole("button", { name: "Affecter" }));

      expect(await screen.findByText("Passerelle indisponible")).toBeInTheDocument();
      // No replay either: the sequence would restart from a counter its own first write spent.
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
      await waitFor(() => expect(mocks.getRevisionNodes).toHaveBeenCalledTimes(2));
    });

    /** V3 (id 8, the displayed draft) and V2 (id 7), each with its own single cost line. */
    async function renderTwoRevisionsInDevis() {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(
        revisionList(
          [
            revisionSummary({ revision_id: 7, version_number: 2, lock_version: 2 }),
            revisionSummary({ revision_id: 8, version_number: 3, lock_version: 4 }),
          ],
          { displayed_revision_id: 8 },
        ),
      );
      mocks.getResourceNodes.mockResolvedValue([
        { id: 1, parent_id: null, code: "DIR", name: "Direction", is_active: true, created_at: "", updated_at: "" },
        { id: 2, parent_id: 1, code: "ETU", name: "Études", is_active: true, created_at: "", updated_at: "" },
      ]);
      mocks.getResourceRoles.mockResolvedValue({
        items: [{ id: 7, node_id: 2, cost_category_id: 40, name: "Ingénieur", calendar_id: null, is_active: true, created_at: "", updated_at: "" }],
        total: 1,
      });
      mocks.getRevisionNodes.mockImplementation(async (_projectId: number, revisionId: number) =>
        revisionId === 8
          ? revisionTree({
              revision_id: 8,
              version_number: 3,
              lock_version: 4,
              nodes: [costNode(2, { rowNumber: 92, label: "Béton V3" })],
            })
          : revisionTree({
              revision_id: 7,
              version_number: 2,
              lock_version: 2,
              nodes: [costNode(3, { rowNumber: 81, label: "Béton V2" })],
            }),
      );
      render(<ProjectDetailsPage />);
      fireEvent.click(await screen.findByRole("tab", { name: "Devis" }));
      await screen.findByLabelText("Libellé de Béton V3");
      await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());
    }

    /** Starts a nature switch on V3 whose delete half never settles, then displays V2. */
    async function leaveRevisionMidSwitch(): Promise<(cause: unknown) => void> {
      let rejectDelete: (cause: unknown) => void = () => undefined;
      mocks.createRevisionCostLine.mockResolvedValue({ revision_id: 8, lock_version: 5, node_id: 99, work_item_id: 99 });
      mocks.deleteRevisionNodes.mockReturnValue(
        new Promise((_resolve, reject) => {
          rejectDelete = reject;
        }),
      );

      await switchToLabor("Béton V3");
      await waitFor(() => expect(mocks.deleteRevisionNodes).toHaveBeenCalled());

      fireEvent.change(screen.getByRole("combobox", { name: "Révision affichée" }), {
        target: { value: "7" },
      });
      expect(await screen.findByLabelText("Libellé de Béton V2")).toBeInTheDocument();
      return rejectDelete;
    }

    it("says nothing about a nature switch whose delete fails once another revision is displayed", async () => {
      // A 409 deliberately, and not a generic failure: it is the one the re-wrapped error has to
      // keep classifiable, so if the guard let it through it would not merely print a message --
      // it would raise the conflict banner over V2 and turn a perfectly editable revision
      // read-only over a write that never touched it.
      await renderTwoRevisionsInDevis();
      const rejectDelete = await leaveRevisionMidSwitch();

      rejectDelete(
        new ApiError(409, "Conflit de version", {
          code: "REVISION_LOCK_CONFLICT",
          revision_id: 8,
          expected_lock_version: 5,
          current_lock_version: 6,
        }),
      );

      await waitFor(() => expect(screen.getByLabelText("Libellé de Béton V2")).toBeInTheDocument());
      expect(screen.queryByText(/l'ancienne n'a pas pu être supprimée/)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Recharger la révision" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
    });

    it("still logs out when that same late failure is a 401", async () => {
      // The expiry is not a statement about a revision: it must log the user out whatever is on
      // screen -- including through the re-wrapping the composite write does, which is why the
      // status has to survive it.
      await renderTwoRevisionsInDevis();
      const rejectDelete = await leaveRevisionMidSwitch();

      rejectDelete(new ApiError(401, "Session expirée"));

      await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
    });

    it("drops the previous revision's totals as soon as another revision is displayed", async () => {
      // The tree and the totals are two reads: the tree can come back first, and the panel would
      // then be mounted with the figures of the revision the user just left -- a total in euros
      // over somebody else's lines.
      let resolveAggregates: (value: RevisionAggregates) => void = () => undefined;
      mocks.getRevisionAggregates.mockImplementation(async (_projectId: number, revisionId: number) =>
        revisionId === 8
          ? revisionAggregates({ revision_id: 8, total_purchase_cost: "1234.00" })
          : new Promise<RevisionAggregates>((resolve) => {
              resolveAggregates = resolve;
            }),
      );
      await renderTwoRevisionsInDevis();
      expect(await screen.findByText(/1\s*234,00/)).toBeInTheDocument();

      fireEvent.change(screen.getByRole("combobox", { name: "Révision affichée" }), {
        target: { value: "7" },
      });

      expect(await screen.findByLabelText("Libellé de Béton V2")).toBeInTheDocument();
      expect(screen.queryByText(/1\s*234,00/)).not.toBeInTheDocument();

      resolveAggregates(revisionAggregates({ revision_id: 7, total_purchase_cost: "77.00" }));
      expect(await screen.findByText(/77,00/)).toBeInTheDocument();
    });
  });

  // ------------------------------------------------------------------------------------------
  // E14-10 (#336): the Planning tab reads and writes a **revision**.
  // ------------------------------------------------------------------------------------------

  describe("the displayed revision", () => {
    function initialisedProject() {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
    }

    it("displays the tree of the revision the project points at, with its positional identifiers", async () => {
      initialisedProject();
      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 7, version_number: 3 })], { displayed_revision_id: 7 }),
      );
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({
          revision_id: 7,
          version_number: 3,
          nodes: [taskNode(1, { name: "Terrassement", rowNumber: 91 })],
        }),
      );

      render(<ProjectDetailsPage />);

      expect(await screen.findByText("Terrassement")).toBeInTheDocument();
      expect(screen.getByText("91")).toBeInTheDocument();
      expect(mocks.getRevisionNodes).toHaveBeenCalledWith(1, 7, expect.anything(), expect.anything());
      expect(screen.getByRole("combobox", { name: "Révision affichée" })).toHaveValue("7");
    });

    it("falls back to the reference revision when no draft is being worked on", async () => {
      initialisedProject();
      mocks.listRevisions.mockResolvedValue(
        revisionList(
          [
            revisionSummary({ revision_id: 7, version_number: 1, status: "validated" }),
            revisionSummary({ revision_id: 8, version_number: 2, status: "draft" }),
          ],
          { reference_revision_id: 7, displayed_revision_id: null },
        ),
      );

      render(<ProjectDetailsPage />);

      await waitFor(() =>
        expect(mocks.getRevisionNodes).toHaveBeenCalledWith(1, 7, expect.anything(), expect.anything()),
      );
    });

    it("says there is nothing to display, rather than failing, on a project with no revision", async () => {
      initialisedProject();
      mocks.listRevisions.mockResolvedValue(emptyRevisionList());

      render(<ProjectDetailsPage />);

      expect(await screen.findByText(/Aucune révision à afficher/)).toBeInTheDocument();
      expect(mocks.getRevisionNodes).not.toHaveBeenCalled();
    });

    it("does not claim the project has no revision while the list is still being read", async () => {
      // The first render has `revisions = []` simply because nothing has been asked yet. Drawing
      // the empty state from it tells the user to import a planning over a network round-trip
      // that may well be about to answer with three revisions.
      initialisedProject();
      let resolveList: (list: RevisionList) => void = () => undefined;
      mocks.listRevisions.mockReturnValue(
        new Promise<RevisionList>((resolve) => {
          resolveList = resolve;
        }),
      );

      render(<ProjectDetailsPage />);

      expect(await screen.findByText(/Chargement des révisions/)).toBeInTheDocument();
      expect(screen.queryByText(/Aucune révision à afficher/)).not.toBeInTheDocument();
      expect(screen.queryByText("Aucune révision pour ce projet.")).not.toBeInTheDocument();

      resolveList(emptyRevisionList());

      expect(await screen.findByText(/Aucune révision à afficher/)).toBeInTheDocument();
    });

    it("does not invite an import when the revision list failed to load", async () => {
      // A failed read is not an empty project: the way out is to retry, not to import a planning.
      initialisedProject();
      mocks.listRevisions.mockRejectedValue(new ApiError(503, "Service indisponible"));

      render(<ProjectDetailsPage />);

      expect(await screen.findByText("Service indisponible")).toBeInTheDocument();
      expect(screen.getByText(/n'ont pas pu être chargées/)).toBeInTheDocument();
      expect(screen.queryByText(/Aucune révision à afficher/)).not.toBeInTheDocument();
    });

    it("renders a validated revision read-only, with no edit command at all", async () => {
      initialisedProject();
      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 7, status: "validated", validated_at: "2026-09-02T10:00:00Z" })]),
      );
      mocks.getRevisionNodes.mockResolvedValue(revisionTree({ status: "validated" }));

      render(<ProjectDetailsPage />);

      expect(await screen.findByText("Étude")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Ajouter une tâche" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Valider la révision" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Créer un brouillon" })).toBeInTheDocument();
    });
  });

  describe("revision commands", () => {
    async function renderDraftRevision(treeOverrides: Partial<RevisionTree> = {}) {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 7, lock_version: 4 })], { displayed_revision_id: 7 }),
      );
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({
          lock_version: 4,
          nodes: [taskNode(1, { name: "Étude", rowNumber: 91 }), taskNode(2, { name: "Réalisation", position: 2, rowNumber: 92 })],
          ...treeOverrides,
        }),
      );
      render(<ProjectDetailsPage />);
      expect(await screen.findByText("Étude")).toBeInTheDocument();
    }

    it("sends a move as a mode and the selection, quoting the counter the tree was read with", async () => {
      await renderDraftRevision();

      fireEvent.click(screen.getAllByRole("row")[2]); // "Réalisation"
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      await waitFor(() =>
        expect(mocks.moveRevisionNodes).toHaveBeenCalledWith(
          1,
          7,
          { expected_lock_version: 4, node_ids: [2], mode: "up" },
          expect.anything(),
          expect.anything(),
        ),
      );
    });

    it("re-reads the whole tree after a write, since a move changes rows the response never names", async () => {
      // This is what makes a task drag its cost lines along: row_number, level and a cost facet's
      // bearing task are computed on read, so only a re-read shows the new state (EPIC #326).
      await renderDraftRevision();
      const readsBefore = mocks.getRevisionNodes.mock.calls.length;

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      await waitFor(() => expect(mocks.getRevisionNodes.mock.calls.length).toBeGreaterThan(readsBefore));
    });

    it("creates a draft from the displayed revision and switches to it, without writing to the source", async () => {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 7, status: "validated", lock_version: 2 })]),
      );
      mocks.getRevisionNodes.mockResolvedValue(revisionTree({ status: "validated", lock_version: 2 }));
      mocks.copyRevision.mockResolvedValue({
        revision_id: 8,
        lock_version: 0,
        source_revision_id: 7,
        version_number: 2,
        kind: "initial",
      });

      render(<ProjectDetailsPage />);
      expect(await screen.findByText("Étude")).toBeInTheDocument();

      mocks.listRevisions.mockResolvedValue(
        revisionList(
          [
            revisionSummary({ revision_id: 7, status: "validated", lock_version: 2 }),
            revisionSummary({ revision_id: 8, version_number: 2 }),
          ],
          { displayed_revision_id: 8 },
        ),
      );
      mocks.getRevisionNodes.mockResolvedValue(revisionTree({ revision_id: 8, version_number: 2 }));

      fireEvent.click(screen.getByRole("button", { name: "Créer un brouillon" }));

      await waitFor(() =>
        // The **source**'s counter: a source that moved since it was read would produce the copy
        // of a tree the user never saw.
        expect(mocks.copyRevision).toHaveBeenCalledWith(
          1,
          7,
          { expected_lock_version: 2 },
          expect.anything(),
          expect.anything(),
        ),
      );
      // The copy is displayed, and the source was never written to.
      await waitFor(() =>
        expect(mocks.getRevisionNodes).toHaveBeenCalledWith(1, 8, expect.anything(), expect.anything()),
      );
      expect(mocks.updateRevisionPlanFacet).not.toHaveBeenCalled();
      expect(mocks.moveRevisionNodes).not.toHaveBeenCalled();
      expect(await screen.findByText(/Brouillon V2 créé/)).toBeInTheDocument();
    });

    it("turns the table read-only when a write is refused because the revision was validated", async () => {
      // INV-03 under the user's feet: another tab validated it. Keeping an editable table over a
      // revision that refuses every write would only produce a second refusal.
      await renderDraftRevision();
      mocks.moveRevisionNodes.mockRejectedValue(
        new ApiError(409, "Figée", { code: "REVISION_IMMUTABLE" }),
      );
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({ status: "validated", nodes: [taskNode(1, { name: "Étude" })] }),
      );

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      await waitFor(() => expect(screen.queryByRole("button", { name: "Monter" })).not.toBeInTheDocument());
      expect(screen.getByText(/Révision validée ou projet en lecture seule/)).toBeInTheDocument();
    });

    it("shows a reload banner on a stale-counter conflict, and reloads only when asked", async () => {
      await renderDraftRevision();
      mocks.moveRevisionNodes.mockRejectedValue(
        new ApiError(409, "Conflit", {
          code: "REVISION_LOCK_CONFLICT",
          revision_id: 7,
          expected_lock_version: 4,
          current_lock_version: 6,
        }),
      );

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      expect(await screen.findByText("Révision modifiée")).toBeInTheDocument();
      const readsBefore = mocks.getRevisionNodes.mock.calls.length;

      fireEvent.click(screen.getByRole("button", { name: "Recharger la révision" }));

      await waitFor(() => expect(mocks.getRevisionNodes.mock.calls.length).toBeGreaterThan(readsBefore));
      await waitFor(() => expect(screen.queryByText("Révision modifiée")).not.toBeInTheDocument());
    });

    it("names the chiffrage a deletion took away rather than losing it silently", async () => {
      await renderDraftRevision();
      mocks.deleteRevisionNodes.mockResolvedValue({
        revision_id: 7,
        lock_version: 5,
        removed_node_ids: [2],
        cost_losses: [
          {
            node_id: 30,
            work_item_id: 300,
            label: "Étude béton",
            nature: "labor",
            amount: "1200.00",
            bearing_task_name: "Réalisation",
          },
        ],
      });

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
      fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));

      await waitFor(() => expect(mocks.deleteRevisionNodes).toHaveBeenCalled());
      expect(await screen.findByText(/Étude béton/)).toBeInTheDocument();
    });

    it("validates the displayed draft and re-reads it as read-only", async () => {
      await renderDraftRevision();
      mocks.validateRevision.mockResolvedValue({
        revision_id: 7,
        lock_version: 5,
        version_number: 1,
        status: "validated",
        validated_at: "2026-09-03T09:00:00Z",
        frozen_line_count: 3,
        superseded_revision_ids: [],
      });
      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 7, status: "validated", lock_version: 5 })]),
      );
      mocks.getRevisionNodes.mockResolvedValue(revisionTree({ status: "validated", lock_version: 5 }));

      fireEvent.click(screen.getByRole("button", { name: "Valider la révision" }));

      await waitFor(() =>
        expect(mocks.validateRevision).toHaveBeenCalledWith(
          1,
          7,
          { expected_lock_version: 4 },
          expect.anything(),
          expect.anything(),
        ),
      );
      expect(await screen.findByText(/3 ligne\(s\) figée\(s\)/)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument());
    });
  });

  // ----------------------------------------------------------------------------------------
  // A response landing after the user switched revisions, and the failure affordances.
  // ----------------------------------------------------------------------------------------

  describe("a write whose response lands late", () => {
    /** V2 (validated, id 7) and V3 (the displayed draft, id 8), each with its own tree. */
    async function renderTwoRevisions() {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(
        revisionList(
          [
            revisionSummary({ revision_id: 7, version_number: 2, status: "validated", lock_version: 2 }),
            revisionSummary({ revision_id: 8, version_number: 3, lock_version: 4 }),
          ],
          { displayed_revision_id: 8 },
        ),
      );
      mocks.getRevisionNodes.mockImplementation(async (_projectId: number, revisionId: number) =>
        revisionId === 8
          ? revisionTree({
              revision_id: 8,
              version_number: 3,
              lock_version: 4,
              nodes: [
                taskNode(1, { name: "Étude V3", rowNumber: 91 }),
                taskNode(2, { name: "Réalisation V3", position: 2, rowNumber: 92 }),
              ],
            })
          : revisionTree({
              revision_id: 7,
              version_number: 2,
              status: "validated",
              lock_version: 2,
              nodes: [taskNode(1, { name: "Étude V2", rowNumber: 81 })],
            }),
      );
      render(<ProjectDetailsPage />);
      expect(await screen.findByText("Étude V3")).toBeInTheDocument();
    }

    it("drops the failure of a write aimed at the revision the user has just left", async () => {
      // The whole point of the guard: a 502 on V3 must not put an error -- nor, on a 409, a
      // read-only conflict banner -- over V2, which the user is now looking at and which the
      // failed command never touched.
      await renderTwoRevisions();
      let rejectMove: (cause: unknown) => void = () => undefined;
      mocks.moveRevisionNodes.mockReturnValue(
        new Promise((_resolve, reject) => {
          rejectMove = reject;
        }),
      );

      fireEvent.click(screen.getAllByRole("row")[2]); // "Réalisation V3"
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));
      await waitFor(() => expect(mocks.moveRevisionNodes).toHaveBeenCalled());

      fireEvent.change(screen.getByRole("combobox", { name: "Révision affichée" }), {
        target: { value: "7" },
      });
      expect(await screen.findByText("Étude V2")).toBeInTheDocument();

      rejectMove(new ApiError(502, "Passerelle indisponible"));

      await waitFor(() => expect(screen.getByText("Étude V2")).toBeInTheDocument());
      expect(screen.queryByText("Passerelle indisponible")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
      expect(screen.queryByText("Étude V3")).not.toBeInTheDocument();
    });

    it("does not offer to replay a failed write once another revision is displayed", async () => {
      // The retry replays the command with the lock_version of the tree it failed on, so offered
      // over V2 it would write into V3 -- and the re-read that follows, being stale, would be
      // dropped: the write would land with nothing on screen to say so.
      await renderTwoRevisions();
      mocks.moveRevisionNodes.mockRejectedValue(new Error("network down"));

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));
      expect(await screen.findByRole("button", { name: "Réessayer" })).toBeInTheDocument();

      fireEvent.change(screen.getByRole("combobox", { name: "Révision affichée" }), {
        target: { value: "7" },
      });

      expect(await screen.findByText("Étude V2")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
      // The error itself belonged to V3 too, and goes with it. Asserted on the message actually
      // rendered -- a generic failure is reported with the fallback, never with `cause.message`,
      // so looking for "network down" here would be an assertion nothing could ever fail.
      expect(screen.queryByText("Impossible de déplacer la sélection.")).not.toBeInTheDocument();
    });

    it("offers a retry after a generic move failure and re-sends the very same command", async () => {
      await renderTwoRevisions();
      mocks.moveRevisionNodes
        .mockRejectedValueOnce(new Error("network down"))
        .mockResolvedValueOnce({ revision_id: 8, lock_version: 5 });

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      await waitFor(() => expect(mocks.moveRevisionNodes).toHaveBeenCalledTimes(1));
      fireEvent.click(await screen.findByRole("button", { name: "Réessayer" }));

      await waitFor(() => expect(mocks.moveRevisionNodes).toHaveBeenCalledTimes(2));
      // Same counter, deliberately: the retry replays the command against the tree the user acted
      // on, so a revision that moved in the meantime answers a 409 instead of applying it twice.
      expect(mocks.moveRevisionNodes.mock.calls[1][2]).toEqual(mocks.moveRevisionNodes.mock.calls[0][2]);
      expect(mocks.moveRevisionNodes.mock.calls[1][2]).toEqual({
        expected_lock_version: 4,
        node_ids: [2],
        mode: "up",
      });
      await waitFor(() => expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument());
    });

    it("logs out when a revision write fails with a post-refresh 401", async () => {
      // Unconditional, unlike everything above: an expired session is not a statement about a
      // revision, and must log the user out whatever is on screen when the response lands.
      await renderTwoRevisions();
      mocks.moveRevisionNodes.mockRejectedValue(new ApiError(401, "Session expirée"));

      fireEvent.click(screen.getAllByRole("row")[2]);
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));

      await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
      expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
    });

    it("logs out on a 401 that lands after the user has switched revisions", async () => {
      // What makes the expiry check *unconditional* rather than merely first: the test above
      // never leaves V3, so it passes just as well with the check placed behind the "is this
      // still the displayed revision?" guard. Here the guard is crossed, and only a check that
      // runs before it still logs the user out -- otherwise the session is dead in place, with
      // no redirection and every later write failing silently.
      await renderTwoRevisions();
      let rejectMove: (cause: unknown) => void = () => undefined;
      mocks.moveRevisionNodes.mockReturnValue(
        new Promise((_resolve, reject) => {
          rejectMove = reject;
        }),
      );

      fireEvent.click(screen.getAllByRole("row")[2]); // "Réalisation V3"
      fireEvent.click(screen.getByRole("button", { name: "Monter" }));
      await waitFor(() => expect(mocks.moveRevisionNodes).toHaveBeenCalled());

      fireEvent.change(screen.getByRole("combobox", { name: "Révision affichée" }), {
        target: { value: "7" },
      });
      expect(await screen.findByText("Étude V2")).toBeInTheDocument();

      rejectMove(new ApiError(401, "Session expirée"));

      await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
    });
  });

  describe("importing into a revision", () => {
    it("says which revision the file landed in once the import is confirmed", async () => {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(emptyRevisionList());
      mocks.runImportBatch.mockResolvedValue({ batchId: 42, revisionId: 9, revisionCreated: true });

      render(<ProjectDetailsPage />);

      const input = await screen.findByLabelText("Importer un planning MS Project (.xml)");
      fireEvent.change(input, {
        target: { files: [new File(["<Project />"], "planning.xml", { type: "application/xml" })] },
      });
      fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

      expect(await screen.findByRole("heading", { name: "Remplacement à confirmer" })).toBeInTheDocument();

      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 9, version_number: 1 })], { displayed_revision_id: 9 }),
      );
      mocks.getRevisionNodes.mockResolvedValue(revisionTree({ revision_id: 9 }));

      fireEvent.click(screen.getByRole("button", { name: "Confirmer le remplacement" }));

      expect(await screen.findByRole("heading", { name: "Import appliqué" })).toBeInTheDocument();
      expect(screen.getByText(/importé dans la révision V1/)).toBeInTheDocument();
      expect(screen.getByText(/créée pour l'occasion/)).toBeInTheDocument();

      // Picking another file must take the banner down with the preview: left up, it keeps
      // asserting that the file now selected has already been imported into V1.
      fireEvent.change(screen.getByLabelText("Importer un planning MS Project (.xml)"), {
        target: { files: [new File(["<Project />"], "autre.xml", { type: "application/xml" })] },
      });

      expect(await screen.findByText("Fichier sélectionné : autre.xml")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Import appliqué" })).not.toBeInTheDocument();
      await waitFor(() =>
        expect(mocks.getRevisionNodes).toHaveBeenCalledWith(1, 9, expect.anything(), expect.anything()),
      );
    });

    it("applies an import that removes a task without any error, on a project that carries chiffrage", async () => {
      mocks.getProject.mockResolvedValue(project({ status: "initialise" }));
      mocks.listPlannings.mockResolvedValue([]);
      mocks.listRevisions.mockResolvedValue(
        revisionList([revisionSummary({ revision_id: 9 })], { displayed_revision_id: 9 }),
      );
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({ revision_id: 9, nodes: [taskNode(1, { name: "Étude" }), taskNode(2, { name: "Disparue", position: 2 })] }),
      );
      mocks.getImportBatchDiff.mockResolvedValue({
        batchId: 42,
        identicalSource: false,
        items: [
          {
            kind: "removed",
            uid: 2,
            message: "Tâche 2 (Disparue) supprimée",
            fields: [],
            costLosses: [
              {
                nodeId: 30,
                workItemId: 300,
                label: "Étude béton",
                nature: "labor",
                amount: "1200.00",
                bearingTaskName: "Disparue",
              },
            ],
          },
        ],
        costLosses: [
          {
            nodeId: 30,
            workItemId: 300,
            label: "Étude béton",
            nature: "labor",
            amount: "1200.00",
            bearingTaskName: "Disparue",
          },
        ],
      });
      mocks.runImportBatch.mockResolvedValue({ batchId: 42, revisionId: 9, revisionCreated: false });

      render(<ProjectDetailsPage />);

      const input = await screen.findByLabelText("Importer un planning MS Project (.xml)");
      fireEvent.change(input, {
        target: { files: [new File(["<Project />"], "planning.xml", { type: "application/xml" })] },
      });
      fireEvent.click(screen.getByRole("button", { name: "Prévisualiser l'import" }));

      // Règle 3: the deletion is named, with its deduplicated total, before it is confirmed.
      expect(await screen.findByText(/1 ligne\(s\) de chiffrage/)).toBeInTheDocument();
      expect(screen.getByText(/Tâche 2 \(Disparue\) supprimée/)).toBeInTheDocument();

      // After the import the row is simply gone -- no 409, no error banner (#325 is over).
      mocks.getRevisionNodes.mockResolvedValue(
        revisionTree({ revision_id: 9, nodes: [taskNode(1, { name: "Étude" })] }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Confirmer le remplacement" }));

      await waitFor(() => expect(screen.queryByText("Disparue")).not.toBeInTheDocument());
      // No 409, no error banner: a draft allows a deletion, chiffrage or not (#325 is over).
      expect(screen.queryByText(/Impossible/)).not.toBeInTheDocument();
      expect(document.querySelector('[data-slot="alert"].text-destructive')).toBeNull();
    });
  });
});
