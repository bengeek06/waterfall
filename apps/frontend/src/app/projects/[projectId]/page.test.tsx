import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Planning, PlanningDetail, Project } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  listProjectEstimates: vi.fn(),
  listPlannings: vi.fn(),
  getPlanning: vi.fn(),
  createImportBatch: vi.fn(),
  uploadImportSourceXml: vi.fn(),
  runImportBatch: vi.fn(),
  getImportBatchStatus: vi.fn(),
  getImportBatchDiff: vi.fn(),
  setDisplayedPlanning: vi.fn(),
  setPlanningReference: vi.fn(),
  savePlanningStructureDraft: vi.fn(),
  createPlanningStructure: vi.fn(),
  reopenPlanningStructure: vi.fn(),
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
    createImportBatch: mocks.createImportBatch,
    uploadImportSourceXml: mocks.uploadImportSourceXml,
    runImportBatch: mocks.runImportBatch,
    getImportBatchStatus: mocks.getImportBatchStatus,
    getImportBatchDiff: mocks.getImportBatchDiff,
    setDisplayedPlanning: mocks.setDisplayedPlanning,
    setPlanningReference: mocks.setPlanningReference,
    savePlanningStructureDraft: mocks.savePlanningStructureDraft,
    createPlanningStructure: mocks.createPlanningStructure,
    reopenPlanningStructure: mocks.reopenPlanningStructure,
    getCostCategories: vi.fn().mockResolvedValue([]),
    getCostTypes: vi.fn().mockResolvedValue([]),
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
  ...overrides,
});

const planning = (overrides: Partial<Planning> = {}): Planning => ({
  id: 2,
  project_id: 1,
  version_number: 1,
  status: "draft",
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
      id_display: 10,
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

describe("ProjectDetailsPage planning lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getProject.mockReset();
    mocks.listProjectEstimates.mockReset();
    mocks.listPlannings.mockReset();
    mocks.getPlanning.mockReset();
    mocks.createImportBatch.mockReset();
    mocks.uploadImportSourceXml.mockReset();
    mocks.runImportBatch.mockReset();
    mocks.getImportBatchStatus.mockReset();
    mocks.getImportBatchDiff.mockReset();
    mocks.setDisplayedPlanning.mockReset();
    mocks.setPlanningReference.mockReset();
    mocks.savePlanningStructureDraft.mockReset();
    mocks.createPlanningStructure.mockReset();
    mocks.reopenPlanningStructure.mockReset();
    mocks.listProjectEstimates.mockResolvedValue([]);
    mocks.listPlannings.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });
    mocks.savePlanningStructureDraft.mockResolvedValue({ planning_id: 2, structure: { posts: [] } });
    mocks.reopenPlanningStructure.mockResolvedValue(project({ status: "initialise", displayed_planning_id: 3 }));
    mocks.createImportBatch.mockResolvedValue({ id: 42 });
    mocks.uploadImportSourceXml.mockResolvedValue({ id: 42 });
    mocks.runImportBatch.mockResolvedValue({ batchId: 42 });
    mocks.getImportBatchStatus.mockResolvedValue({ status: "success" });
    mocks.getImportBatchDiff.mockResolvedValue({ batchId: 42, identicalSource: false, items: [] });
    mocks.setPlanningReference.mockResolvedValue(project({ status: "initialise" }));
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
  });

  afterEach(() => cleanup());

  it("shows only the hierarchical structure form for a new project", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);

    render(<ProjectDetailsPage />);

    expect(await screen.findByRole("heading", { name: "Structure initiale" })).toBeInTheDocument();
    expect(screen.queryByText("Aucune tâche.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enregistrer la structure" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Générer le squelette" })).toBeInTheDocument();
  });

  it("saves the structure draft without closing the form or generating a planning", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Structure initiale" });
    fireEvent.change(screen.getByLabelText("Nom poste 1"), { target: { value: "Poste" } });
    fireEvent.change(screen.getByLabelText("Nom lot 1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrables 1"), { target: { value: "Livrable" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer la structure" }));

    await waitFor(() => expect(mocks.savePlanningStructureDraft).toHaveBeenCalledTimes(1));
    expect(mocks.savePlanningStructureDraft).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ posts: expect.any(Array) }),
      expect.anything(),
      expect.anything(),
    );
    expect(mocks.createPlanningStructure).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Structure initiale" })).toBeInTheDocument();
  });

  it("uses the generation action and closes the structure form", async () => {
    mocks.getProject.mockResolvedValue(project());
    mocks.listPlannings.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Structure initiale" });
    fireEvent.change(screen.getByLabelText("Nom poste 1"), { target: { value: "Poste" } });
    fireEvent.change(screen.getByLabelText("Nom lot 1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrables 1"), { target: { value: "Livrable" } });
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
      expect(screen.queryByRole("heading", { name: "Structure initiale" })).not.toBeInTheDocument(),
    );
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

  it("hydrates the structure form from a saved draft", async () => {
    const draft = planning({
      id: 3,
      status: "draft",
      note: `planning-structure-draft:${JSON.stringify({
        posts: [{
          key: "post-1",
          name: "Poste sauvegardé",
          lots: [{ key: "lot-1", name: "Lot sauvegardé", deliverables: [{ key: "deliverable-1", name: "Livrable sauvegardé" }] }],
        }],
      })}`,
    });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(detail(draft));

    render(<ProjectDetailsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Rouvrir la structure" }));

    expect(await screen.findByDisplayValue("Poste sauvegardé")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Lot sauvegardé")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Livrable sauvegardé")).toBeInTheDocument();
  });

  it("does not allow reopening a draft in a read-only project", async () => {
    const draft = planning({ id: 3, status: "draft" });
    mocks.getProject.mockResolvedValue(project({ status: "perdu", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(detail(draft));

    render(<ProjectDetailsPage />);

    expect(await screen.findByText("Tâche 1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rouvrir la structure" })).not.toBeInTheDocument();
  });

  it("loads and persists the selected planning without showing the previous detail", async () => {
    const first = planning({ id: 1, version_number: 1 });
    const second = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: 2 }));
    mocks.listPlannings.mockResolvedValue([first, second]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      detail(planningId === 1 ? first : second),
    );

    render(<ProjectDetailsPage />);

    expect(await screen.findByText("Tâche 2")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Version affichée" }), {
      target: { value: "1" },
    });

    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Tâche 1")).toBeInTheDocument());
    expect(mocks.setDisplayedPlanning).toHaveBeenCalledWith(
      1,
      1,
      expect.anything(),
      expect.anything(),
    );
  });

  it("restores the previous planning when displaying another planning fails", async () => {
    const first = planning({ id: 1, version_number: 1 });
    const second = planning({ id: 2, version_number: 2 });
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: 2 }));
    mocks.listPlannings.mockResolvedValue([first, second]);
    mocks.getPlanning.mockResolvedValue(detail(second));
    mocks.setDisplayedPlanning.mockRejectedValueOnce(new Error("display failed"));

    render(<ProjectDetailsPage />);

    const selector = await screen.findByRole("combobox", { name: "Version affichée" });
    fireEvent.change(selector, { target: { value: "1" } });

    await waitFor(() => expect(selector).toHaveValue("2"));
    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
  });

  it("allows historical planning navigation in a read-only project without mutation", async () => {
    const current = planning({ id: 2, version_number: 2, status: "validated" });
    const historical = planning({ id: 1, version_number: 1, status: "superseded" });
    mocks.getProject.mockResolvedValue(
      project({ status: "perdu", displayed_planning_id: current.id, planning_reference_id: current.id }),
    );
    mocks.listPlannings.mockResolvedValue([historical, current]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      detail(planningId === historical.id ? historical : current),
    );

    render(<ProjectDetailsPage />);

    const selector = await screen.findByRole("combobox", { name: "Version affichée" });
    expect(selector).not.toBeDisabled();
    fireEvent.change(selector, { target: { value: String(historical.id) } });

    await waitFor(() => expect(screen.getByText("Tâche 1")).toBeInTheDocument());
    expect(mocks.setDisplayedPlanning).not.toHaveBeenCalled();
  });

  it("refreshes planning metadata after changing the reference", async () => {
    const previous = planning({ id: 1, version_number: 1, status: "validated" });
    const next = planning({ id: 2, version_number: 2, status: "validated" });
    mocks.getProject
      .mockResolvedValueOnce(project({ status: "initialise", displayed_planning_id: next.id }))
      .mockResolvedValueOnce(project({
        status: "initialise",
        displayed_planning_id: next.id,
        planning_reference_id: next.id,
      }));
    mocks.listPlannings
      .mockResolvedValueOnce([previous, next])
      .mockResolvedValueOnce([{ ...previous, status: "superseded" }, next]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      detail(planningId === previous.id ? previous : next),
    );
    mocks.setPlanningReference.mockResolvedValue(
      project({ status: "initialise", displayed_planning_id: previous.id, planning_reference_id: next.id }),
    );

    render(<ProjectDetailsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Définir comme référence" }));

    await waitFor(() => expect(mocks.listPlannings).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Version 2 - validated")).toBeInTheDocument();
  });

  it("keeps archived projects read-only", async () => {
    const archived = planning({ status: "validated" });
    mocks.getProject.mockResolvedValue(
      project({ status: "perdu", planning_reference_id: archived.id, displayed_planning_id: archived.id }),
    );
    mocks.listPlannings.mockResolvedValue([archived]);
    mocks.getPlanning.mockResolvedValue(detail(archived));

    render(<ProjectDetailsPage />);

    expect(await screen.findByText("Tâche 1")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByLabelText("Importer un planning MS Project (.xml)")).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Modifier" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Valider le planning" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rouvrir la structure" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Version affichée" })).not.toBeDisabled();
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
});
