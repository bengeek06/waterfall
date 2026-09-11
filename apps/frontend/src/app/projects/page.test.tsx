import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, SessionExpiredError, type Project } from "@/lib/backend";

const { getProjects, createProject, deleteProject, getProjectSetupWarnings, router, clearSession } = vi.hoisted(() => {
  return {
    getProjects: vi.fn(),
    createProject: vi.fn(),
    deleteProject: vi.fn(),
    getProjectSetupWarnings: vi.fn(),
    router: { push: vi.fn() },
    clearSession: vi.fn(),
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
    createProject,
    deleteProject,
    getProjectSetupWarnings,
    restoreSession: vi.fn(),
  };
});

vi.mock("@/lib/session", () => ({
  clearSession,
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

const page = (items: Project[], total = items.length) => ({ items, total });

describe("ProjectsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getProjects.mockResolvedValue(page([project({})]));
    getProjectSetupWarnings.mockResolvedValue({ warnings: [] });
  });

  afterEach(() => {
    cleanup();
  });

  it("loads active projects by default and includes archived projects on demand", async () => {
    getProjects.mockImplementation((_tokens, _refresh, includeArchived) =>
      Promise.resolve(
        page(
          includeArchived
            ? [project({}), project({ id: 2, name: "Projet terminé", status: "termine" })]
            : [project({})],
        ),
      ),
    );

    render(<ProjectsPage />);
    await waitFor(() =>
      expect(getProjects).toHaveBeenCalledWith(expect.anything(), expect.anything(), false, {
        limit: 20,
        offset: 0,
        sort: null,
        q: undefined,
      }),
    );
    expect(screen.queryByText("Projet terminé")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Inclure les projets/ }));
    await waitFor(() =>
      expect(getProjects).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), true, {
        limit: 20,
        offset: 0,
        sort: null,
        q: undefined,
      }),
    );
    await waitFor(() => expect(screen.getByText("Projet terminé")).toBeInTheDocument());
  });

  it("renders accessible status labels and keeps archived projects read-only", async () => {
    getProjects.mockImplementation((_tokens, _refresh, includeArchived) =>
      Promise.resolve(
        page(
          includeArchived
            ? [project({}), project({ id: 2, name: "Projet perdu", status: "perdu" })]
            : [project({})],
        ),
      ),
    );

    render(<ProjectsPage />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Inclure les projets/ }));

    await waitFor(() => expect(screen.getByText("Lecture seule")).toBeInTheDocument());
    expect(screen.getByText("En cours")).toBeInTheDocument();
    expect(screen.getByText("Perdu")).toBeInTheDocument();
    expect(screen.getByText("Perdu").querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("checkbox", { name: "Sélectionner Projet perdu" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Supprimer la sélection" })).toBeDisabled();
  });

  it("ignores a stale response after changing the archived filter", async () => {
    let resolveActive!: (result: { items: Project[]; total: number }) => void;
    let resolveArchived!: (result: { items: Project[]; total: number }) => void;
    getProjects.mockImplementation((_tokens, _refresh, includeArchived) =>
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
    resolveArchived(page([project({ id: 2, name: "Projet archivé", status: "termine" })]));
    await waitFor(() => expect(screen.getByText("Projet archivé")).toBeInTheDocument());

    resolveActive(page([project({ id: 3, name: "Réponse obsolète" })]));
    await waitFor(() => expect(screen.queryByText("Réponse obsolète")).not.toBeInTheDocument());
    expect(screen.getByText("Projet archivé")).toBeInTheDocument();
  });

  it("requests the server column name when a sortable header is clicked, and resets pagination/selection", async () => {
    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));
    expect(screen.getByRole("checkbox", { name: "Sélectionner Projet test" })).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Nom" }));

    await waitFor(() =>
      expect(getProjects).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), false, {
        limit: 20,
        offset: 0,
        sort: "name",
        q: undefined,
      }),
    );
    // Selection is scoped to the previous page's rows and must not survive a
    // sort change silently pointing "Supprimer la sélection" at stale ids.
    expect(screen.queryByRole("button", { name: "Supprimer la sélection" })).toBeDisabled();
  });

  it("delegates search to the server and resets pagination", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<ProjectsPage />);
      await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

      fireEvent.change(screen.getByLabelText("Rechercher un projet"), { target: { value: "pilote" } });
      await vi.advanceTimersByTimeAsync(300);

      await waitFor(() =>
        expect(getProjects).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), false, {
          limit: 20,
          offset: 0,
          sort: null,
          q: "pilote",
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("navigates to the project page when a row is clicked", async () => {
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("Projet test")).toBeInTheDocument());

    fireEvent.click(screen.getByText("En cours"));

    expect(router.push).toHaveBeenCalledExactlyOnceWith("/projects/1");
  });

  it("creates a project and reloads the current page", async () => {
    createProject.mockResolvedValue(project({ id: 2, name: "Nouveau projet" }));
    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));
    fireEvent.change(screen.getByLabelText("Nom du projet"), { target: { value: "Nouveau projet" } });
    fireEvent.change(screen.getByLabelText("Code projet"), { target: { value: "NP-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));

    await waitFor(() => expect(createProject).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(2));
  });

  // #109: a complete global setup (no default calendar/working-day, cost category,
  // or resource role missing) must not surface any warning in the create dialog.
  it("shows no setup warning when the global setup is complete", async () => {
    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));

    await waitFor(() => expect(getProjectSetupWarnings).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/Paramétrage global incomplet/)).not.toBeInTheDocument();
  });

  // #109: the create dialog can be closed and reopened (or "Créer projet" double-clicked,
  // since it isn't disabled while setup warnings are loading) faster than a
  // `getProjectSetupWarnings` request resolves, firing a second call while the first is
  // still in flight. A late-arriving first response must not silently overwrite the
  // second, more recent (and already-displayed) result.
  it("ignores a stale getProjectSetupWarnings response when the dialog is reopened before it resolves", async () => {
    const deferred: Array<{ resolve: (result: { warnings: unknown[] }) => void }> = [];
    getProjectSetupWarnings.mockImplementation(
      () =>
        new Promise((resolve) => {
          deferred.push({ resolve });
        }),
    );

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));
    fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));
    await waitFor(() => expect(getProjectSetupWarnings).toHaveBeenCalledTimes(2));

    // The second (most recent) request resolves first, with the correct current state.
    deferred[1].resolve({ warnings: [{ code: "no_default_calendar", message: "no default calendar" }] });
    await waitFor(() =>
      expect(screen.getByText(/calendrier par défaut actif n'est défini/)).toBeInTheDocument(),
    );

    // The first (stale) request resolves late, with a different warning -- it must not
    // clobber the already-displayed, more recent result. `waitFor` here also flushes any
    // pending state update from the stale response's resolution before asserting on it.
    deferred[0].resolve({ warnings: [{ code: "no_active_cost_category", message: "no active cost category" }] });
    await waitFor(() =>
      expect(screen.getByText(/calendrier par défaut actif n'est défini/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Aucune catégorie de coût active/)).not.toBeInTheDocument();
  });

  // #109: each missing prerequisite must be reported with its own precise, French
  // message naming the /resources tab where it can be fixed -- never the backend's raw
  // English diagnostic `message` string.
  it.each([
    ["no_default_calendar", /calendrier par défaut actif n'est défini/],
    ["default_calendar_has_no_working_day", /n'a aucun jour travaillé/],
    ["no_active_cost_category", /Aucune catégorie de coût active/],
    ["no_active_resource_role", /Aucun rôle actif n'est défini/],
  ] as const)("shows the French message for the %s setup warning", async (code, expectedMessage) => {
    getProjectSetupWarnings.mockResolvedValue({ warnings: [{ code, message: "english diagnostic, never shown" }] });

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));

    await waitFor(() => expect(screen.getByText(expectedMessage)).toBeInTheDocument());
    expect(screen.queryByText("english diagnostic, never shown")).not.toBeInTheDocument();
  });

  // An unknown code (e.g. added server-side before this mapping is updated) must fall
  // back to a generic message instead of crashing or rendering nothing.
  it("falls back to a generic message for an unrecognized setup warning code", async () => {
    getProjectSetupWarnings.mockResolvedValue({
      warnings: [{ code: "some_future_code", message: "future diagnostic" }],
    });

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));

    await waitFor(() =>
      expect(screen.getByText(/Le paramétrage global comporte un point à vérifier/)).toBeInTheDocument(),
    );
  });

  it("lists every missing prerequisite when several setup warnings are combined", async () => {
    getProjectSetupWarnings.mockResolvedValue({
      warnings: [
        { code: "no_default_calendar", message: "no default calendar" },
        { code: "no_active_resource_role", message: "no active role" },
      ],
    });

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));

    await waitFor(() =>
      expect(screen.getByText(/calendrier par défaut actif n'est défini/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Aucun rôle actif n'est défini/)).toBeInTheDocument();
  });

  // The setup warnings are advisory only -- creation must still succeed while one is
  // displayed, and the "Créer" button must never become disabled because of it.
  it("still allows creating a project while a setup warning is displayed", async () => {
    getProjectSetupWarnings.mockResolvedValue({
      warnings: [{ code: "no_active_cost_category", message: "no active cost category" }],
    });
    createProject.mockResolvedValue(project({ id: 2, name: "Nouveau projet" }));

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));
    await waitFor(() => expect(screen.getByText(/Aucune catégorie de coût active/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Créer" })).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Nom du projet"), { target: { value: "Nouveau projet" } });
    fireEvent.change(screen.getByLabelText("Code projet"), { target: { value: "NP-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));

    await waitFor(() => expect(createProject).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(2));
  });

  // #109: loading the setup warnings is subject to the same session-expiry handling
  // as every other load on this page -- a stale/expired session must clear it and
  // redirect to login rather than leaving the dialog stuck or showing a raw error.
  it("clears the session and redirects to login when loading setup warnings reports session expiry", async () => {
    getProjectSetupWarnings.mockRejectedValue(new SessionExpiredError());

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));

    await waitFor(() => expect(clearSession).toHaveBeenCalled());
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login"));
  });

  // Regression test for #227: the main list-load effect guards its catch block with
  // `isCurrentGeneration()` (a stale/superseded request must not overwrite fresher
  // state). Before #227, that guard ran *before* the session-expiry check, so a
  // request that became stale (e.g. the user toggled a filter before it resolved)
  // and failed precisely because the session expired would return early and never
  // reach `clearSession`/redirect -- the session would then never get invalidated
  // if the user stopped interacting. The session check must run first, regardless
  // of staleness.
  it("still logs out when a now-stale initial-load request fails with a post-refresh 401, even though a fresher load has already won", async () => {
    let rejectStale!: (cause: unknown) => void;
    let callCount = 0;
    getProjects.mockImplementation(() => {
      callCount += 1;
      if (callCount === 1) {
        // The initial load (includeArchived: false), held pending until rejected
        // explicitly below, once the toggle's own fresher request has resolved.
        return new Promise((_resolve, reject) => {
          rejectStale = reject;
        });
      }
      // The fresher request, triggered by toggling "Inclure les projets..." while
      // call 1 is still in flight.
      return Promise.resolve(page([project({ id: 2, name: "Projet archivé", status: "termine" })]));
    });

    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    // Toggling the filter changes `includeArchived`, an effect dependency: this
    // starts a fresher generation before call 1 has resolved.
    fireEvent.click(screen.getByRole("checkbox", { name: /Inclure les projets/ }));
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText("Projet archivé")).toBeInTheDocument());

    // The now-stale call 1 fails after the fresher call already won -- it must
    // still force a logout instead of being silently discarded.
    rejectStale(new ApiError(401, "Unauthorized"));
    await waitFor(() => expect(clearSession).toHaveBeenCalled());
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login"));
  });

  // Regression test for #195: a mutation handler must clear the session and
  // redirect to login on session expiry, the same way `reloadProjectsPage`
  // already does, instead of surfacing a generic error message.
  it("clears the session and redirects to login, instead of showing a generic error, when project creation reports session expiry", async () => {
    createProject.mockRejectedValue(new SessionExpiredError());
    render(<ProjectsPage />);
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Créer projet" }));
    fireEvent.change(screen.getByLabelText("Nom du projet"), { target: { value: "Nouveau projet" } });
    fireEvent.change(screen.getByLabelText("Code projet"), { target: { value: "NP-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));

    await waitFor(() => expect(clearSession).toHaveBeenCalled());
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Impossible de créer le projet.")).not.toBeInTheDocument();
  });

  it("deletes the selected projects and reloads the current page", async () => {
    deleteProject.mockResolvedValue(undefined);
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("Projet test")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(deleteProject).toHaveBeenCalledExactlyOnceWith(1, expect.anything(), expect.anything()));
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(2));
  });

  // Regression test for #195: same as project creation above, but for the
  // delete-selection mutation handler.
  it("clears the session and redirects to login, instead of showing a generic error, when deleting selected projects reports session expiry", async () => {
    deleteProject.mockRejectedValue(new SessionExpiredError());
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("Projet test")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(clearSession).toHaveBeenCalled());
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Impossible de supprimer les projets.")).not.toBeInTheDocument();
    // The session is already invalidated at this point -- `reloadProjectsPage()`
    // (normally called unconditionally in `onDeleteSelected`'s `finally`) must be
    // skipped, not fired as a doomed extra request/refresh attempt. Only the
    // initial page load's call should ever have happened.
    expect(getProjects).toHaveBeenCalledTimes(1);
  });

  it("reloads the current page even when a delete fails partway through the selection", async () => {
    getProjects.mockResolvedValue(page([project({ id: 1 }), project({ id: 2, name: "Autre projet" })]));
    deleteProject.mockImplementation((projectId: number) =>
      projectId === 2 ? Promise.reject(new Error("boom")) : Promise.resolve(undefined),
    );

    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("Autre projet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Autre projet" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));

    // The first id in the batch is deleted successfully server-side before the
    // second one rejects -- the table/selection must not keep referencing either
    // as if the whole batch had simply failed.
    await waitFor(() => expect(deleteProject).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Supprimer la sélection" })).toBeDisabled();
  });

  it(
    "keeps a user-triggered sort's result even though a mutation's reload (using live, " +
      "not stale, sort state) resolves later",
    async () => {
      const deferredGetProjects: Array<{ resolve: (r: { items: Project[]; total: number }) => void }> = [];
      getProjects.mockImplementation(
        () =>
          new Promise((resolve) => {
            deferredGetProjects.push({ resolve });
          }),
      );
      let resolveDelete!: () => void;
      deleteProject.mockImplementation(
        () =>
          new Promise<void>((resolve) => {
            resolveDelete = resolve;
          }),
      );

      render(<ProjectsPage />);
      await waitFor(() => expect(deferredGetProjects).toHaveLength(1));
      deferredGetProjects[0].resolve(page([project({ id: 1 }), project({ id: 2, name: "Autre projet" })]));
      await waitFor(() => expect(screen.getByText("Autre projet")).toBeInTheDocument());

      // Start a deletion; `deleteProject` stays pending ("in flight").
      fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));
      fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
      fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
      await waitFor(() => expect(deleteProject).toHaveBeenCalledTimes(1));

      // While the deletion is still in flight, the user sorts by name -- an
      // independent, user-triggered getProjects call.
      fireEvent.click(screen.getByRole("button", { name: "Nom" }));
      await waitFor(() => expect(deferredGetProjects).toHaveLength(2));

      // The sort's own fetch resolves first.
      deferredGetProjects[1].resolve(page([project({ id: 3, name: "Résultat trié" })]));
      await waitFor(() => expect(screen.getByText("Résultat trié")).toBeInTheDocument());

      // The deletion finally resolves, triggering its own reload -- a third
      // getProjects call. It must read the *live* sort ("name"), not the "null"
      // sort in effect when the deletion started, or its eventually-arriving
      // response would silently clobber the user's more recent sort change with
      // stale, pre-sort data.
      resolveDelete();
      await waitFor(() => expect(deferredGetProjects).toHaveLength(3));
      expect(getProjects).toHaveBeenNthCalledWith(3, expect.anything(), expect.anything(), false, {
        limit: 20,
        offset: 0,
        sort: "name",
        q: undefined,
      });

      deferredGetProjects[2].resolve(page([project({ id: 3, name: "Résultat trié" })]));
      await waitFor(() => expect(getProjects).toHaveBeenCalledTimes(3));
      expect(screen.getByText("Résultat trié")).toBeInTheDocument();
    },
  );

  it("mentions the current-page scope of the selection once more than one page exists", async () => {
    getProjects.mockResolvedValue(page([project({ id: 1 }), project({ id: 2, name: "Autre projet" })], 40));
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("Projet test")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));

    expect(screen.getByText("1 sélectionné(s) sur cette page")).toBeInTheDocument();
  });

  it("does not add a page-scope qualifier to the selection count when everything fits on one page", async () => {
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("Projet test")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));

    expect(screen.getByText("1 sélectionné(s)")).toBeInTheDocument();
  });
});
