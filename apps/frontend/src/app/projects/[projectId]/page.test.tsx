import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Planning, PlanningDetail, Project } from "@/lib/backend";

const mocks = vi.hoisted(() => ({
  getProject: vi.fn(),
  listProjectEstimates: vi.fn(),
  listPlannings: vi.fn(),
  getPlanning: vi.fn(),
  setDisplayedPlanning: vi.fn(),
  createPlanningStructure: vi.fn(),
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
    setDisplayedPlanning: mocks.setDisplayedPlanning,
    createPlanningStructure: mocks.createPlanningStructure,
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
    mocks.listProjectEstimates.mockResolvedValue([]);
    mocks.createPlanningStructure.mockResolvedValue({ tasks: [] });
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

    expect(screen.queryByText("Tâche 2")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Tâche 1")).toBeInTheDocument());
    expect(mocks.setDisplayedPlanning).toHaveBeenCalledWith(
      1,
      1,
      expect.anything(),
      expect.anything(),
    );
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
    expect(screen.queryByLabelText("Importer un planning MS Project (.xml)")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Modifier" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Valider le planning" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rouvrir la structure" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Version affichée" })).toBeDisabled();
  });
});
