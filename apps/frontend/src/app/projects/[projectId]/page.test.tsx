import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Planning, type PlanningDetail, type Project } from "@/lib/backend";

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
  movePlanningTasks: vi.fn(),
  updatePlanningTaskSchedule: vi.fn(),
  replaceTaskPredecessorLinks: vi.fn(),
  createPlanningTask: vi.fn(),
  deletePlanningTasks: vi.fn(),
  savePlanningStructureDraft: vi.fn(),
  getPlanningStructureDraft: vi.fn(),
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
    movePlanningTasks: mocks.movePlanningTasks,
    updatePlanningTaskSchedule: mocks.updatePlanningTaskSchedule,
    replaceTaskPredecessorLinks: mocks.replaceTaskPredecessorLinks,
    createPlanningTask: mocks.createPlanningTask,
    deletePlanningTasks: mocks.deletePlanningTasks,
    savePlanningStructureDraft: mocks.savePlanningStructureDraft,
    getPlanningStructureDraft: mocks.getPlanningStructureDraft,
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
    mocks.movePlanningTasks.mockReset();
    mocks.updatePlanningTaskSchedule.mockReset();
    mocks.replaceTaskPredecessorLinks.mockReset();
    mocks.createPlanningTask.mockReset();
    mocks.deletePlanningTasks.mockReset();
    mocks.savePlanningStructureDraft.mockReset();
    mocks.getPlanningStructureDraft.mockReset();
    mocks.createPlanningStructure.mockReset();
    mocks.reopenPlanningStructure.mockReset();
    mocks.listProjectEstimates.mockResolvedValue([]);
    mocks.listPlannings.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });
    mocks.savePlanningStructureDraft.mockResolvedValue({ planning_id: 2, structure: { posts: [] } });
    mocks.getPlanningStructureDraft.mockResolvedValue(null);
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
    fireEvent.change(screen.getByLabelText("Nom lot 1.1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrable 1.1.1"), { target: { value: "Livrable" } });
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
      expect(screen.queryByRole("heading", { name: "Structure initiale" })).not.toBeInTheDocument(),
    );
  });

  it("renders the refetched planning tasks after generation, including manual ones", async () => {
    const generated = planning({ id: 5, status: "draft" });
    const generatedDetail: PlanningDetail = {
      ...generated,
      tasks: [
        {
          id: 20,
          project_id: 1,
          uid: 20,
          id_display: 20,
          structure_key: "post/lot/deliverable",
          structure_kind: "livrable",
          parent_uid: null,
          position: 1,
          name: "Tâche structurée",
          outline_number: "1.1.1",
          outline_level: 3,
          start_at: null,
          finish_at: null,
          percent_complete: 0,
          is_summary: false,
          is_milestone: false,
          is_manual: false,
          description: null,
          predecessor_links: [],
        },
        {
          id: 21,
          project_id: 1,
          uid: 21,
          id_display: 21,
          structure_key: null,
          structure_kind: null,
          parent_uid: null,
          position: 2,
          name: "Tâche manuelle",
          outline_number: "2",
          outline_level: 1,
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
    };
    mocks.getProject
      .mockResolvedValueOnce(project())
      .mockResolvedValue(project({ status: "initialise", displayed_planning_id: generated.id }));
    mocks.listPlannings.mockResolvedValueOnce([]).mockResolvedValue([generated]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: generatedDetail.tasks });
    mocks.getPlanning.mockResolvedValue(generatedDetail);

    render(<ProjectDetailsPage />);

    await screen.findByRole("heading", { name: "Structure initiale" });
    fireEvent.change(screen.getByLabelText("Nom poste 1"), { target: { value: "Poste" } });
    fireEvent.change(screen.getByLabelText("Nom lot 1.1"), { target: { value: "Lot" } });
    fireEvent.change(screen.getByLabelText("Livrable 1.1.1"), { target: { value: "Livrable" } });
    fireEvent.click(screen.getByRole("button", { name: "Générer le squelette" }));

    await waitFor(() =>
      expect(mocks.getPlanning).toHaveBeenCalledWith(
        1,
        generated.id,
        expect.anything(),
        expect.anything(),
      ),
    );
    expect(await screen.findAllByText("Tâche structurée")).not.toHaveLength(0);
    expect(await screen.findAllByText("Tâche manuelle")).not.toHaveLength(0);
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

  it("sends a move command and replaces the planning detail with the full server response", async () => {
    const draft = planning({ id: 2, status: "draft" });
    const siblingsDetail: PlanningDetail = {
      ...draft,
      tasks: [
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draft).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    const movedDetail: PlanningDetail = {
      ...draft,
      revision: 1,
      tasks: [
        { ...detail(draft).tasks[0], uid: 11, id_display: 11, name: "Second", position: 1, parent_uid: null },
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 2, parent_uid: null },
      ],
      links: [],
    };
    const secondMovedDetail: PlanningDetail = {
      ...draft,
      revision: 2,
      tasks: [
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draft).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(siblingsDetail);
    mocks.movePlanningTasks.mockResolvedValueOnce(movedDetail).mockResolvedValueOnce(secondMovedDetail);

    render(<ProjectDetailsPage />);

    await screen.findByText("Second");
    fireEvent.click(screen.getByText("Second"));
    fireEvent.click(screen.getByRole("button", { name: "Monter" }));

    await waitFor(() =>
      expect(mocks.movePlanningTasks).toHaveBeenCalledWith(
        1,
        draft.id,
        { task_uids: [11], target_parent_uid: null, position: 1, expected_revision: 0 },
        expect.anything(),
        expect.anything(),
      ),
    );
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("Second");
    expect(rows[2]).toHaveTextContent("Premier");

    // The second move must send the revision the first move's response actually
    // returned (1), not the stale revision (0) still held on the plannings list.
    fireEvent.click(screen.getByText("Premier"));
    fireEvent.click(screen.getByRole("button", { name: "Monter" }));

    await waitFor(() =>
      expect(mocks.movePlanningTasks).toHaveBeenCalledWith(
        1,
        draft.id,
        { task_uids: [10], target_parent_uid: null, position: 1, expected_revision: 1 },
        expect.anything(),
        expect.anything(),
      ),
    );
  });

  it("ignores a move response for a planning that is no longer selected", async () => {
    const draftA = planning({ id: 2, status: "draft" });
    const draftB = planning({ id: 6, status: "draft", version_number: 2 });
    const detailA: PlanningDetail = {
      ...draftA,
      tasks: [
        { ...detail(draftA).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draftA).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    const detailB = detail(draftB);
    const staleDetail: PlanningDetail = {
      ...draftA,
      tasks: [{ ...detailA.tasks[0], name: "Réponse obsolète" }],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draftA.id }));
    mocks.listPlannings.mockResolvedValue([draftA, draftB]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      planningId === draftA.id ? detailA : detailB,
    );
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
    let resolveMove!: (value: PlanningDetail) => void;
    mocks.movePlanningTasks.mockImplementation(() => new Promise<PlanningDetail>((resolve) => {
      resolveMove = resolve;
    }));

    render(<ProjectDetailsPage />);

    await screen.findByText("Second");
    fireEvent.click(screen.getByText("Second"));
    fireEvent.click(screen.getByRole("button", { name: "Monter" }));
    await waitFor(() => expect(mocks.movePlanningTasks).toHaveBeenCalledTimes(1));

    fireEvent.change(await screen.findByRole("combobox", { name: "Version affichée" }), {
      target: { value: String(draftB.id) },
    });
    await waitFor(() => expect(screen.getByText("Tâche 2")).toBeInTheDocument());

    resolveMove(staleDetail);
    await waitFor(() => expect(mocks.movePlanningTasks).toHaveResolved());

    expect(screen.queryByText("Réponse obsolète")).not.toBeInTheDocument();
    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
  });

  it("does not show a move error after switching to another planning version", async () => {
    const draftA = planning({ id: 2, status: "draft" });
    const draftB = planning({ id: 6, status: "draft", version_number: 2 });
    const detailA: PlanningDetail = {
      ...draftA,
      tasks: [
        { ...detail(draftA).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draftA).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    const detailB = detail(draftB);
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draftA.id }));
    mocks.listPlannings.mockResolvedValue([draftA, draftB]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      planningId === draftA.id ? detailA : detailB,
    );
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
    let rejectMove!: (error: Error) => void;
    mocks.movePlanningTasks.mockImplementation(() => new Promise<PlanningDetail>((_resolve, reject) => {
      rejectMove = reject;
    }));

    render(<ProjectDetailsPage />);

    await screen.findByText("Second");
    fireEvent.click(screen.getByText("Second"));
    fireEvent.click(screen.getByRole("button", { name: "Monter" }));
    await waitFor(() => expect(mocks.movePlanningTasks).toHaveBeenCalledTimes(1));

    fireEvent.change(await screen.findByRole("combobox", { name: "Version affichée" }), {
      target: { value: String(draftB.id) },
    });
    await waitFor(() => expect(screen.getByText("Tâche 2")).toBeInTheDocument());

    rejectMove(new Error("move failed"));
    await waitFor(() => expect(screen.queryByText("Impossible de déplacer les tâches sélectionnées.")).not.toBeInTheDocument());
    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
  });

  it("sends a schedule update and replaces the planning detail with the full server response", async () => {
    const draft = planning({ id: 2, status: "draft" });
    const initialDetail: PlanningDetail = {
      ...draft,
      tasks: [{ ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Tâche éditable", duration_minutes: 480 }],
      links: [],
    };
    const updatedDetail: PlanningDetail = {
      ...draft,
      tasks: [{ ...initialDetail.tasks[0], name: "Tâche mise à jour", duration_minutes: 600 }],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(initialDetail);
    mocks.updatePlanningTaskSchedule.mockResolvedValue(updatedDetail);

    render(<ProjectDetailsPage />);

    const durationInput = await screen.findByLabelText("Durée de Tâche éditable");
    fireEvent.change(durationInput, { target: { value: "600" } });
    fireEvent.blur(durationInput);

    await waitFor(() =>
      expect(mocks.updatePlanningTaskSchedule).toHaveBeenCalledWith(
        1,
        draft.id,
        10,
        expect.objectContaining({ duration_minutes: 600 }),
        expect.anything(),
        expect.anything(),
      ),
    );
    expect(await screen.findByText("Tâche mise à jour")).toBeInTheDocument();
  });

  it("sends a predecessor links replace and replaces the planning detail with the full server response", async () => {
    const draft = planning({ id: 2, status: "draft" });
    const siblingsDetail: PlanningDetail = {
      ...draft,
      tasks: [
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draft).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    const updatedDetail: PlanningDetail = {
      ...draft,
      tasks: [
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        {
          ...detail(draft).tasks[0],
          uid: 11,
          id_display: 11,
          name: "Second",
          position: 2,
          parent_uid: null,
          predecessor_links: [{ predecessor_uid: 10, link_type: 1, lag_tenth_minute: 0, lag_format: 7 }],
        },
      ],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(siblingsDetail);
    mocks.replaceTaskPredecessorLinks.mockResolvedValue(updatedDetail);

    render(<ProjectDetailsPage />);

    await screen.findByText("Second");
    fireEvent.click(screen.getByRole("button", { name: "Éditer les prédécesseurs de Second" }));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne" }));
    fireEvent.change(screen.getByLabelText("Tâche prédécesseure"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() =>
      expect(mocks.replaceTaskPredecessorLinks).toHaveBeenCalledWith(
        1,
        draft.id,
        11,
        {
          links: [{ predecessor_uid: 10, link_type: 1, lag_tenth_minute: 0, lag_format: 7 }],
          expected_revision: 0,
        },
        expect.anything(),
        expect.anything(),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("10 (FS)")).toBeInTheDocument();
  });

  it("ignores a schedule update response for a planning that is no longer selected", async () => {
    const draftA = planning({ id: 2, status: "draft" });
    const draftB = planning({ id: 6, status: "draft", version_number: 2 });
    const detailA: PlanningDetail = {
      ...draftA,
      tasks: [{ ...detail(draftA).tasks[0], uid: 10, id_display: 10, name: "Tâche éditable", duration_minutes: 480 }],
      links: [],
    };
    const detailB = detail(draftB);
    const staleDetail: PlanningDetail = {
      ...draftA,
      tasks: [{ ...detailA.tasks[0], name: "Réponse obsolète" }],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draftA.id }));
    mocks.listPlannings.mockResolvedValue([draftA, draftB]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      planningId === draftA.id ? detailA : detailB,
    );
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
    let resolveScheduleUpdate!: (value: PlanningDetail) => void;
    mocks.updatePlanningTaskSchedule.mockImplementation(
      () => new Promise<PlanningDetail>((resolve) => {
        resolveScheduleUpdate = resolve;
      }),
    );

    render(<ProjectDetailsPage />);

    const durationInput = await screen.findByLabelText("Durée de Tâche éditable");
    fireEvent.change(durationInput, { target: { value: "600" } });
    fireEvent.blur(durationInput);
    await waitFor(() => expect(mocks.updatePlanningTaskSchedule).toHaveBeenCalledTimes(1));

    fireEvent.change(await screen.findByRole("combobox", { name: "Version affichée" }), {
      target: { value: String(draftB.id) },
    });
    await waitFor(() => expect(screen.getByText("Tâche 2")).toBeInTheDocument());

    resolveScheduleUpdate(staleDetail);
    await waitFor(() => expect(mocks.updatePlanningTaskSchedule).toHaveResolved());

    expect(screen.queryByText("Réponse obsolète")).not.toBeInTheDocument();
    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
  });

  it("reports a project-read-only conflict distinctly from a cycle conflict", async () => {
    const draft = planning({ id: 2, status: "draft" });
    const siblingsDetail: PlanningDetail = {
      ...draft,
      tasks: [
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draft).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(siblingsDetail);
    mocks.replaceTaskPredecessorLinks.mockRejectedValue(
      new ApiError(409, "Project is read-only in its current status"),
    );

    render(<ProjectDetailsPage />);

    await screen.findByText("Second");
    fireEvent.click(screen.getByRole("button", { name: "Éditer les prédécesseurs de Second" }));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne" }));
    fireEvent.change(screen.getByLabelText("Tâche prédécesseure"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    // Rendered both by the page-level error banner and by the dialog's own inline error
    // (editTaskPredecessorLinksSelection sets both from the same message).
    await waitFor(() =>
      expect(
        screen.getAllByText("Le projet est passé en lecture seule et ne peut plus être modifié."),
      ).not.toHaveLength(0),
    );
    expect(screen.queryByText("Cette combinaison de prédécesseurs créerait un cycle dans le planning.")).not.toBeInTheDocument();
  });

  it("ignores a predecessor links response for a planning that is no longer selected", async () => {
    const draftA = planning({ id: 2, status: "draft" });
    const draftB = planning({ id: 6, status: "draft", version_number: 2 });
    const detailA: PlanningDetail = {
      ...draftA,
      tasks: [
        { ...detail(draftA).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null },
        { ...detail(draftA).tasks[0], uid: 11, id_display: 11, name: "Second", position: 2, parent_uid: null },
      ],
      links: [],
    };
    const detailB = detail(draftB);
    const staleDetail: PlanningDetail = {
      ...draftA,
      tasks: [{ ...detailA.tasks[0], name: "Réponse obsolète" }],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draftA.id }));
    mocks.listPlannings.mockResolvedValue([draftA, draftB]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      planningId === draftA.id ? detailA : detailB,
    );
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
    let resolveLinks!: (value: PlanningDetail) => void;
    mocks.replaceTaskPredecessorLinks.mockImplementation(() => new Promise<PlanningDetail>((resolve) => {
      resolveLinks = resolve;
    }));

    render(<ProjectDetailsPage />);

    await screen.findByText("Second");
    fireEvent.click(screen.getByRole("button", { name: "Éditer les prédécesseurs de Second" }));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne" }));
    fireEvent.change(screen.getByLabelText("Tâche prédécesseure"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(mocks.replaceTaskPredecessorLinks).toHaveBeenCalledTimes(1));

    // The predecessor links dialog is a modal (unlike the move toolbar), so the version selector
    // is marked aria-hidden while it stays open pending the in-flight request; `hidden: true`
    // reaches through that to exercise the same stale-response guard the move test covers.
    fireEvent.change(await screen.findByRole("combobox", { name: "Version affichée", hidden: true }), {
      target: { value: String(draftB.id) },
    });
    await waitFor(() => expect(screen.getByText("Tâche 2")).toBeInTheDocument());

    resolveLinks(staleDetail);
    await waitFor(() => expect(mocks.replaceTaskPredecessorLinks).toHaveResolved());

    expect(screen.queryByText("Réponse obsolète")).not.toBeInTheDocument();
    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
  });

  it("sends a create-task request and replaces the planning detail with the full server response", async () => {
    const draft = planning({ id: 2, status: "draft" });
    const initialDetail: PlanningDetail = {
      ...draft,
      tasks: [{ ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "Tâche existante" }],
      links: [],
    };
    const updatedDetail: PlanningDetail = {
      ...draft,
      tasks: [
        ...initialDetail.tasks,
        { ...initialDetail.tasks[0], uid: 11, id_display: 11, name: "Nouvelle tâche", position: 2 },
      ],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(initialDetail);
    mocks.createPlanningTask.mockResolvedValue(updatedDetail);

    render(<ProjectDetailsPage />);

    await screen.findByText("Tâche existante");
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une tâche" }));
    fireEvent.change(screen.getByLabelText("Nom de la nouvelle tâche"), { target: { value: "Nouvelle tâche" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));

    await waitFor(() =>
      expect(mocks.createPlanningTask).toHaveBeenCalledWith(
        1,
        draft.id,
        {
          name: "Nouvelle tâche",
          is_milestone: false,
          target_parent_uid: undefined,
          insert_after_uid: undefined,
          expected_revision: 0,
        },
        expect.anything(),
        expect.anything(),
      ),
    );
    expect(await screen.findByText("Nouvelle tâche")).toBeInTheDocument();
  });

  it("sends a delete-tasks request and replaces the planning detail with the full server response", async () => {
    const draft = planning({ id: 2, status: "draft" });
    const initialDetail: PlanningDetail = {
      ...draft,
      tasks: [
        { ...detail(draft).tasks[0], uid: 10, id_display: 10, name: "À conserver", position: 1 },
        { ...detail(draft).tasks[0], uid: 11, id_display: 11, name: "À supprimer", position: 2 },
      ],
      links: [],
    };
    const updatedDetail: PlanningDetail = {
      ...draft,
      tasks: [initialDetail.tasks[0]],
      links: [],
    };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draft.id }));
    mocks.listPlannings.mockResolvedValue([draft]);
    mocks.getPlanning.mockResolvedValue(initialDetail);
    mocks.deletePlanningTasks.mockResolvedValue(updatedDetail);

    render(<ProjectDetailsPage />);

    await screen.findByText("À supprimer");
    fireEvent.click(screen.getByText("À supprimer"));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));

    await waitFor(() =>
      expect(mocks.deletePlanningTasks).toHaveBeenCalledWith(
        1,
        draft.id,
        { task_uids: [11], confirm_cascade: false, expected_revision: 0 },
        expect.anything(),
        expect.anything(),
      ),
    );
    await waitFor(() => expect(screen.queryByText("À supprimer")).not.toBeInTheDocument());
    expect(screen.getByText("À conserver")).toBeInTheDocument();
  });

  it("ignores a delete-tasks response for a planning that is no longer selected", async () => {
    const draftA = planning({ id: 2, status: "draft" });
    const draftB = planning({ id: 6, status: "draft", version_number: 2 });
    const detailA: PlanningDetail = {
      ...draftA,
      tasks: [{ ...detail(draftA).tasks[0], uid: 10, id_display: 10, name: "Premier", position: 1, parent_uid: null }],
      links: [],
    };
    const detailB = detail(draftB);
    const staleDetail: PlanningDetail = { ...draftA, tasks: [], links: [] };
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draftA.id }));
    mocks.listPlannings.mockResolvedValue([draftA, draftB]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      planningId === draftA.id ? detailA : detailB,
    );
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
    let resolveDelete!: (value: PlanningDetail) => void;
    mocks.deletePlanningTasks.mockImplementation(() => new Promise<PlanningDetail>((resolve) => {
      resolveDelete = resolve;
    }));

    render(<ProjectDetailsPage />);

    await screen.findByText("Premier");
    fireEvent.click(screen.getByText("Premier"));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
    await waitFor(() => expect(mocks.deletePlanningTasks).toHaveBeenCalledTimes(1));

    fireEvent.change(await screen.findByRole("combobox", { name: "Version affichée" }), {
      target: { value: String(draftB.id) },
    });
    await waitFor(() => expect(screen.getByText("Tâche 2")).toBeInTheDocument());

    resolveDelete(staleDetail);
    await waitFor(() => expect(mocks.deletePlanningTasks).toHaveResolved());

    // The stale response (an empty task list for A) must never be applied on top of B's tasks.
    expect(screen.getByText("Tâche 2")).toBeInTheDocument();
  });

  it("never sends a cascade delete confirmation to a planning version that is no longer displayed", async () => {
    // Reproduces the race from the E3-05 review: requestDeleteSelection's probe (confirm_cascade
    // false) is answered with CASCADE_CONFIRMATION_REQUIRED while planning A is displayed, opening
    // PlanningTreeTable's own cascade AlertDialog; the user then switches the displayed planning
    // to B before ever confirming it. Task uids are reused across a planning's versions, so
    // blindly confirming here could delete the wrong version's tasks (see
    // waterfall.services.planning_structure) -- deletePlanningTasks must never be called a second
    // time (confirm_cascade: true) against B with A's task uids.
    const draftA = planning({ id: 2, status: "draft" });
    const draftB = planning({ id: 6, status: "draft", version_number: 2 });
    const detailA: PlanningDetail = {
      ...draftA,
      tasks: [
        { ...detail(draftA).tasks[0], uid: 10, id_display: 10, name: "Poste", position: 1, parent_uid: null, is_summary: true },
        { ...detail(draftA).tasks[0], uid: 11, id_display: 11, name: "Lot", position: 1, parent_uid: 10 },
      ],
      links: [],
    };
    const detailB = detail(draftB);
    mocks.getProject.mockResolvedValue(project({ status: "initialise", displayed_planning_id: draftA.id }));
    mocks.listPlannings.mockResolvedValue([draftA, draftB]);
    mocks.getPlanning.mockImplementation(async (_projectId, planningId) =>
      planningId === draftA.id ? detailA : detailB,
    );
    mocks.setDisplayedPlanning.mockImplementation(async (_projectId, planningId) =>
      project({ status: "initialise", displayed_planning_id: planningId }),
    );
    mocks.deletePlanningTasks.mockImplementation(async (_projectId, _planningId, payload) => {
      if (!payload.confirm_cascade) {
        throw new ApiError(409, "Cette tâche a des tâches enfants et nécessite une confirmation.", {
          code: "CASCADE_CONFIRMATION_REQUIRED",
          descendant_uids: [11],
        });
      }
      throw new Error("deletePlanningTasks must never be retried with confirm_cascade after a version switch");
    });

    render(<ProjectDetailsPage />);

    await screen.findByText("Poste");
    fireEvent.click(screen.getByText("Poste"));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));

    await screen.findByRole("alertdialog");
    expect(mocks.deletePlanningTasks).toHaveBeenCalledTimes(1);

    // The cascade AlertDialog is modal, so the version selector is marked aria-hidden while it
    // stays open; `hidden: true` reaches through that (see the analogous predecessor-links test
    // above for the same pattern).
    fireEvent.change(await screen.findByRole("combobox", { name: "Version affichée", hidden: true }), {
      target: { value: String(draftB.id) },
    });
    await waitFor(() => expect(screen.getByText("Tâche 2")).toBeInTheDocument());

    // Switching the displayed planning must close (or otherwise invalidate) the stale cascade
    // dialog rather than leave it confirmable against the wrong version.
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(mocks.deletePlanningTasks).toHaveBeenCalledTimes(1);
    expect(mocks.deletePlanningTasks).not.toHaveBeenCalledWith(
      1,
      draftB.id,
      expect.objectContaining({ confirm_cascade: true }),
      expect.anything(),
      expect.anything(),
    );
  });
});
