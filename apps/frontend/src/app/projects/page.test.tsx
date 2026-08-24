import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/backend";

const { getProjects, router } = vi.hoisted(() => {
  return {
    getProjects: vi.fn(),
    router: { push: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    getMe: vi.fn().mockResolvedValue({}),
    getProjects,
    restoreSession: vi.fn(),
  };
});

vi.mock("@/lib/session", () => ({
  clearSession: vi.fn(),
  getSession: vi.fn(() => ({ accessToken: "test-token" })),
  setSession: vi.fn(),
}));

import ProjectsPage from "./page";

const project = (overrides: Partial<Project>): Project =>
  ({
    id: 1,
    name: "Projet test",
    status: "en_cours",
    code: "TEST-1",
    short_description: null,
    source_version: 2016,
    save_version_out: 16,
    schedule_from_start: true,
    start_date: null,
    finish_date: null,
    currency_code: null,
    planning_reference_id: null,
    displayed_planning_id: null,
    reference_estimate_id: null,
    ...overrides,
  }) as Project;

describe("ProjectsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getProjects.mockResolvedValue([project({})]);
  });

  afterEach(() => {
    cleanup();
  });

  it("loads active projects by default and includes archived projects on demand", async () => {
    getProjects.mockImplementation((_tokens, _refresh, _limit, _offset, includeArchived) =>
      Promise.resolve(
        includeArchived
          ? [project({}), project({ id: 2, name: "Projet terminé", status: "termine" })]
          : [project({})],
      ),
    );

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledWith(expect.anything(), expect.anything(), 50, 0, false));
    expect(screen.queryByText("Projet terminé")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Inclure les projets/ }));
    await waitFor(() => expect(getProjects).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), 50, 0, true));
    await waitFor(() => expect(screen.getByText("Projet terminé")).toBeInTheDocument());
  });

  it("renders accessible status labels and keeps archived projects read-only", async () => {
    getProjects.mockImplementation((_tokens, _refresh, _limit, _offset, includeArchived) =>
      Promise.resolve(
        includeArchived
          ? [project({}), project({ id: 2, name: "Projet perdu", status: "perdu" })]
          : [project({})],
      ),
    );

    render(<ProjectsPage />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Inclure les projets/ }));

    await waitFor(() => expect(screen.getByText("Lecture seule")).toBeInTheDocument());
    expect(screen.getByText("En cours")).toBeInTheDocument();
    expect(screen.getByText("Perdu")).toBeInTheDocument();
    expect(screen.getByLabelText("Statut : Perdu")).toHaveAttribute("title", "Perdu");
    expect(screen.getByRole("checkbox", { name: "Sélectionner Projet perdu" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Supprimer la sélection" })).toBeDisabled();
  });

  it("ignores a stale response after changing the archived filter", async () => {
    let resolveActive!: (projects: Project[]) => void;
    let resolveArchived!: (projects: Project[]) => void;
    getProjects.mockImplementation((_tokens, _refresh, _limit, _offset, includeArchived) =>
      new Promise((resolve) => {
        if (includeArchived) {
          resolveArchived = resolve;
        } else {
          resolveActive = resolve;
        }
      }),
    );

    render(<ProjectsPage />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Inclure les projets/ }));
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(2));
    resolveArchived([project({ id: 2, name: "Projet archivé", status: "termine" })]);
    await waitFor(() => expect(screen.getByText("Projet archivé")).toBeInTheDocument());

    resolveActive([project({ id: 3, name: "Réponse obsolète" })]);
    await waitFor(() => expect(screen.queryByText("Réponse obsolète")).not.toBeInTheDocument());
    expect(screen.getByText("Projet archivé")).toBeInTheDocument();
  });
});