import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  SessionExpiredError,
  type Calendar,
  type CostCategory,
  type CostType,
  type ResourceNode,
  type ResourceRole,
} from "@/lib/backend";
import { defaultWeekdays } from "@/components/calendars-table";

const mocks = vi.hoisted(() => ({
  getResourceNodes: vi.fn(),
  getResourceRoles: vi.fn(),
  getCalendars: vi.fn(),
  getCostTypes: vi.fn(),
  getCostCategories: vi.fn(),
  getCostRates: vi.fn(),
  getInflationRates: vi.fn(),
  getRoleCapacities: vi.fn(),
  getUsers: vi.fn(),
  createCalendar: vi.fn(),
  updateCalendar: vi.fn(),
  deleteCalendar: vi.fn(),
  updateResourceRole: vi.fn(),
  createCostType: vi.fn(),
  createResourceRole: vi.fn(),
  deleteResourceNode: vi.fn(),
  createRoleCapacity: vi.fn(),
  updateRoleCapacity: vi.fn(),
  createCostCategory: vi.fn(),
  router: { push: vi.fn() },
}));

vi.mock("next/navigation", () => ({
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
    getResourceNodes: mocks.getResourceNodes,
    getResourceRoles: mocks.getResourceRoles,
    getCalendars: mocks.getCalendars,
    getCostTypes: mocks.getCostTypes,
    getCostCategories: mocks.getCostCategories,
    getCostRates: mocks.getCostRates,
    getInflationRates: mocks.getInflationRates,
    getRoleCapacities: mocks.getRoleCapacities,
    getUsers: mocks.getUsers,
    createCalendar: mocks.createCalendar,
    updateCalendar: mocks.updateCalendar,
    deleteCalendar: mocks.deleteCalendar,
    updateResourceRole: mocks.updateResourceRole,
    createCostType: mocks.createCostType,
    createResourceRole: mocks.createResourceRole,
    deleteResourceNode: mocks.deleteResourceNode,
    createRoleCapacity: mocks.createRoleCapacity,
    updateRoleCapacity: mocks.updateRoleCapacity,
    createCostCategory: mocks.createCostCategory,
  };
});

import ResourcesPage from "./page";

const activeCalendar: Calendar = {
  id: 1,
  code: "STANDARD",
  name: "Calendrier standard",
  weeks_per_year: 47,
  is_active: true,
  is_default: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  weekdays: [],
};

const inactiveCalendar: Calendar = {
  id: 2,
  code: "REDUIT",
  name: "Calendrier réduit",
  weeks_per_year: 40,
  is_active: false,
  is_default: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  weekdays: [],
};

const nodeFixture: ResourceNode = {
  id: 1,
  code: "IT",
  name: "Informatique",
  parent_id: null,
} as never;

const roleFixture: ResourceRole = {
  id: 10,
  name: "Développeur",
  node_id: 1,
  cost_category_id: 1,
  calendar_id: null,
  is_active: true,
} as never;

async function renderResourcesTab(calendars: Calendar[], roles: ResourceRole[] = [], nodes: ResourceNode[] = []) {
  mocks.getResourceNodes.mockResolvedValue(nodes);
  mocks.getResourceRoles.mockResolvedValue({ items: roles, total: roles.length });
  mocks.getCalendars.mockResolvedValue(calendars);
  mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostRates.mockResolvedValue([]);
  mocks.getInflationRates.mockResolvedValue([]);
  mocks.getRoleCapacities.mockResolvedValue([]);
  mocks.getUsers.mockResolvedValue([]);

  render(<ResourcesPage />);

  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
  await waitFor(() => expect(screen.getByText(calendars[0].code)).toBeInTheDocument());
}

describe("ResourcesPage calendar toggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("deletes an active calendar via the guarded DELETE endpoint instead of PATCH", async () => {
    mocks.deleteCalendar.mockResolvedValue(undefined);
    await renderResourcesTab([activeCalendar]);

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() => expect(mocks.deleteCalendar).toHaveBeenCalledWith(1, expect.anything(), expect.anything()));
    expect(mocks.updateCalendar).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Réactiver" })).toBeInTheDocument());
  });

  it("reactivates an inactive calendar via PATCH is_active:true instead of DELETE", async () => {
    mocks.updateCalendar.mockResolvedValue({ ...inactiveCalendar, is_active: true });
    await renderResourcesTab([inactiveCalendar]);

    fireEvent.click(screen.getByRole("button", { name: "Réactiver" }));

    await waitFor(() =>
      expect(mocks.updateCalendar).toHaveBeenCalledWith(2, { is_active: true }, expect.anything(), expect.anything()),
    );
    expect(mocks.deleteCalendar).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument());
  });

  it("surfaces the 409 guard error and leaves the calendar active when deletion is blocked", async () => {
    mocks.deleteCalendar.mockRejectedValue(new ApiError(409, "Calendrier assigné à un rôle actif."));
    await renderResourcesTab([activeCalendar]);

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() => expect(screen.getByText("Calendrier assigné à un rôle actif.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Réactiver" })).not.toBeInTheDocument();
  });
});

describe("ResourcesPage calendar mutations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("creates a calendar via the add form, appends it to the list, and resets the form", async () => {
    const createdCalendar: Calendar = {
      id: 3,
      code: "NEW",
      name: "Nouveau calendrier",
      weeks_per_year: 45,
      is_active: true,
      is_default: false,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      weekdays: [],
    };
    mocks.createCalendar.mockResolvedValue(createdCalendar);
    await renderResourcesTab([activeCalendar]);

    const codeInput = screen.getByLabelText("Code du nouveau calendrier");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau calendrier"), { target: { value: "Nouveau calendrier" } });
    fireEvent.change(screen.getByLabelText("Semaines par an du nouveau calendrier"), { target: { value: "45" } });

    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() =>
      expect(mocks.createCalendar).toHaveBeenCalledWith(
        { code: "NEW", name: "Nouveau calendrier", weeks_per_year: 45, weekdays: defaultWeekdays() },
        expect.anything(),
        expect.anything(),
      ),
    );

    await waitFor(() => expect(screen.getByText("NEW")).toBeInTheDocument());
    expect(screen.getByLabelText("Code du nouveau calendrier")).toHaveValue("");
    expect(screen.getByLabelText("Nom du nouveau calendrier")).toHaveValue("");
    expect(screen.getByLabelText("Semaines par an du nouveau calendrier")).toHaveValue(47);
  });

  it("saves edits to an existing calendar, replaces it in the list, and exits edit mode", async () => {
    const updatedCalendar: Calendar = { ...activeCalendar, code: "STD2", name: "Calendrier standard v2" };
    mocks.updateCalendar.mockResolvedValue(updatedCalendar);
    await renderResourcesTab([activeCalendar]);

    fireEvent.click(screen.getByRole("button", { name: "Modifier" }));
    fireEvent.change(screen.getByLabelText("Code de STANDARD"), { target: { value: "STD2" } });
    fireEvent.change(screen.getByLabelText("Nom de STANDARD"), { target: { value: "Calendrier standard v2" } });

    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() =>
      expect(mocks.updateCalendar).toHaveBeenCalledWith(
        1,
        { code: "STD2", name: "Calendrier standard v2", weeks_per_year: 47, weekdays: [] },
        expect.anything(),
        expect.anything(),
      ),
    );

    await waitFor(() => expect(screen.getByText("STD2")).toBeInTheDocument());
    expect(screen.queryByText("STANDARD")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument();
  });

  it("assigns a calendar to a role and reflects the update in the select", async () => {
    const otherCalendar: Calendar = {
      id: 3,
      code: "OTHER",
      name: "Autre calendrier",
      weeks_per_year: 44,
      is_active: true,
      is_default: false,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      weekdays: [],
    };
    const updatedRole: ResourceRole = { ...roleFixture, calendar_id: otherCalendar.id } as never;
    mocks.updateResourceRole.mockResolvedValue(updatedRole);
    await renderResourcesTab([activeCalendar, otherCalendar], [roleFixture], [nodeFixture]);

    const select = screen.getByLabelText(`Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`);
    fireEvent.change(select, { target: { value: String(otherCalendar.id) } });

    const roleRow = select.closest("tr");
    if (!roleRow) throw new Error("role row not found");
    fireEvent.click(within(roleRow).getByRole("button", { name: "Enregistrer" }));

    await waitFor(() =>
      expect(mocks.updateResourceRole).toHaveBeenCalledWith(
        roleFixture.id,
        { calendar_id: otherCalendar.id },
        expect.anything(),
        expect.anything(),
      ),
    );

    await waitFor(() => expect(select).toHaveValue(String(otherCalendar.id)));
  });

  it("promotes a calendar as default and locally demotes the previous default without a reload", async () => {
    const previousDefault: Calendar = { ...activeCalendar, id: 1, code: "STANDARD", is_default: true };
    const candidate: Calendar = {
      id: 3,
      code: "OTHER",
      name: "Autre calendrier",
      weeks_per_year: 44,
      is_active: true,
      is_default: false,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
      weekdays: [],
    };
    const promoted: Calendar = { ...candidate, is_default: true };
    mocks.updateCalendar.mockResolvedValue(promoted);
    await renderResourcesTab([previousDefault, candidate]);

    const otherRow = screen.getByText("OTHER").closest("tr");
    if (!otherRow) throw new Error("row not found");
    fireEvent.click(within(otherRow).getByRole("button", { name: "Définir par défaut" }));

    await waitFor(() =>
      expect(mocks.updateCalendar).toHaveBeenCalledWith(3, { is_default: true }, expect.anything(), expect.anything()),
    );

    await waitFor(() => expect(screen.getAllByText("Par défaut")).toHaveLength(1));
    const standardRow = screen.getByText("STANDARD").closest("tr");
    if (!standardRow) throw new Error("row not found");
    expect(within(standardRow).queryByText("Par défaut")).not.toBeInTheDocument();
    expect(within(otherRow).getByText("Par défaut")).toBeInTheDocument();
  });
});

describe("ResourcesPage default calendar warning", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a warning when no active calendar is flagged as default", async () => {
    await renderResourcesTab([activeCalendar]);

    expect(
      screen.getByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).toBeInTheDocument();
  });

  it("shows the warning on initial render, before switching to the Ressources tab", async () => {
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue([activeCalendar]);
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);

    render(<ResourcesPage />);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    // Stays on the default tab (not "Ressources") to prove the warning is not
    // scoped to a tab-specific conditional render.
    expect(screen.getByRole("tab", { name: "Ressources" })).toHaveAttribute("aria-selected", "false");
    expect(
      screen.getByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).toBeInTheDocument();
  });

  it("does not show the warning once an active calendar is flagged as default", async () => {
    const defaultCalendar: Calendar = { ...activeCalendar, is_default: true };
    await renderResourcesTab([defaultCalendar]);

    expect(
      screen.queryByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).not.toBeInTheDocument();
  });

  it("does not show the warning when the initial load fails, and surfaces the load error instead", async () => {
    mocks.getResourceNodes.mockRejectedValue(new ApiError(500, "Chargement impossible"));
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue([]);
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);

    render(<ResourcesPage />);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    expect(screen.getByText("Chargement impossible")).toBeInTheDocument();
    expect(
      screen.queryByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).not.toBeInTheDocument();
  });

  it("does not show the warning when a later reload (triggered by a session refresh) fails after an initial successful load", async () => {
    let nodeCallCount = 0;
    mocks.getResourceNodes.mockImplementation((_tokens: unknown, onSessionRefresh: (next: { accessToken: string }) => void) => {
      nodeCallCount += 1;
      if (nodeCallCount === 1) {
        // Simulate a token refresh happening mid-request during the first, successful load,
        // which re-triggers the load effect (session changes) for a second, failing load.
        return Promise.resolve([]).then((result) => {
          onSessionRefresh({ accessToken: "refreshed-token" });
          return result;
        });
      }
      return Promise.reject(new ApiError(500, "Rechargement impossible"));
    });
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue([activeCalendar]);
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);

    render(<ResourcesPage />);

    await waitFor(() => expect(mocks.getResourceNodes).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText("Rechargement impossible")).toBeInTheDocument());

    expect(
      screen.queryByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).not.toBeInTheDocument();
  });
});

describe("ResourcesPage reload race", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps the most recently triggered reload's data even when an older, obsolete reload resolves later", async () => {
    const genOneNode: ResourceNode = { id: 1, code: "GEN1", name: "Génération 1", parent_id: null } as never;
    const genTwoNode: ResourceNode = { id: 2, code: "GEN2", name: "Génération 2", parent_id: null } as never;

    let resolveFirstNodes!: (nodes: ResourceNode[]) => void;
    const firstNodesPromise = new Promise<ResourceNode[]>((resolve) => {
      resolveFirstNodes = resolve;
    });

    let nodeCallCount = 0;
    mocks.getResourceNodes.mockImplementation(() => {
      nodeCallCount += 1;
      // First call: the initial (mount) reload. Stays pending until the test
      // explicitly releases it below, once the second reload has committed --
      // simulating an older reload that resolves after a newer one.
      if (nodeCallCount === 1) return firstNodesPromise;
      // Second call: the reload triggered by the mid-flight session refresh
      // below. Resolves immediately, well before the first call is released.
      return Promise.resolve([genTwoNode]);
    });

    let rolesCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, onSessionRefresh: (next: { accessToken: string }) => void) => {
        rolesCallCount += 1;
        if (rolesCallCount === 1) {
          // Fires mid-flight during the first reload's still-pending Promise.all,
          // mirroring `authFetch` calling `onSessionRefresh` before a retried
          // request settles. This starts a second, more recently triggered reload.
          onSessionRefresh({ accessToken: "refreshed-token" });
        }
        return Promise.resolve({ items: [], total: 0 });
      },
    );

    mocks.getCalendars.mockResolvedValue([]);
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);

    render(<ResourcesPage />);

    // The second (more recently triggered) reload completes first: its own
    // getResourceNodes call resolves immediately.
    await waitFor(() => expect(nodeCallCount).toBe(2));
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(screen.getByText("GEN2")).toBeInTheDocument());

    // Now release the first (obsolete) reload's stale data, after the second
    // reload has already committed its own.
    resolveFirstNodes([genOneNode]);

    // The obsolete first reload must not overwrite the more recently triggered
    // second reload's committed state.
    await waitFor(() => expect(screen.queryByText("GEN1")).not.toBeInTheDocument());
    expect(screen.getByText("GEN2")).toBeInTheDocument();
  });
});

const costTypeFixture = (overrides: Partial<CostType> = {}): CostType =>
  ({
    id: 1,
    code: "MO",
    name: "Main d'œuvre",
    kind: "labor",
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as CostType;

describe("ResourcesPage cost types table (E8-02)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue([]);
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("requests the table's own paginated page independently from the unpaginated reference list other panels rely on, without either leaking into the other", async () => {
    // Genuinely different item sets for the two call shapes -- if the paginated
    // slice ever got wired into the reference-data consumers (or vice versa), this
    // test would catch it by which codes show up where, not just by which params
    // getCostTypes was called with.
    const fullList = [
      costTypeFixture({ id: 1, code: "MO", name: "Main d'œuvre" }),
      costTypeFixture({ id: 2, code: "FN", name: "Fourniture" }),
      costTypeFixture({ id: 3, code: "TR", name: "Transport" }),
      costTypeFixture({ id: 4, code: "SS", name: "Sous-traitance" }),
      costTypeFixture({ id: 5, code: "AU", name: "Autre" }),
    ];
    const paginatedSlice = [costTypeFixture({ id: 6, code: "PAGE1", name: "Page item" })];
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: fullList, total: fullList.length }
            : { items: paginatedSlice, total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.getCostTypes).toHaveBeenCalledTimes(2));

    const calls = mocks.getCostTypes.mock.calls as [unknown, unknown, unknown, unknown][];
    // The full reference list (feeds RolesPanel/CostCategoriesTable/ValuationPanel) is
    // requested with no pagination params at all -- absence of `limit` must return
    // everything, per EPIC E7/E8.
    expect(calls.some(([, , , listParams]) => listParams === undefined)).toBe(true);
    // The table's own view is requested separately, with an explicit page size.
    expect(
      calls.some(
        ([, , , listParams]) =>
          typeof listParams === "object" &&
          listParams !== null &&
          (listParams as { limit?: number }).limit === 20 &&
          (listParams as { offset?: number }).offset === 0,
      ),
    ).toBe(true);

    // The cost-categories create-row's type dropdown (fed by the full, unpaginated
    // list) must offer every reference type, not just the cost-types table's page.
    const typeSelect = screen.getByLabelText("Type de la nouvelle catégorie");
    for (const type of fullList) {
      expect(within(typeSelect).getByRole("option", { name: `${type.code} - ${type.name}` })).toBeInTheDocument();
    }
    expect(within(typeSelect).queryByRole("option", { name: /PAGE1/ })).not.toBeInTheDocument();

    // The cost-types table itself shows only its own paginated slice, not the full list.
    expect(screen.getByText("PAGE1")).toBeInTheDocument();
    expect(screen.queryByText("MO")).not.toBeInTheDocument();
  });

  it("paginates: clicking Suivant refetches the table with the next offset, leaving the reference-list call untouched", async () => {
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [costTypeFixture({})], total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    // Scoped to the cost-types table's own <form>: the cost-categories table below it
    // (E8-03) renders an identically-labeled "Suivant" button of its own.
    const costTypesTable = (await screen.findByLabelText("Rechercher un type de coût")).closest("form") as HTMLElement;
    const suivant = within(costTypesTable).getByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());

    fireEvent.click(suivant);

    await waitFor(() =>
      expect(mocks.getCostTypes).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });

  it("searches: typing in the cost-types search box debounces then refetches with q, resetting to offset 0", async () => {
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [costTypeFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    const searchInput = await screen.findByLabelText("Rechercher un type de coût");

    fireEvent.change(searchInput, { target: { value: "main" } });

    await waitFor(() =>
      expect(mocks.getCostTypes).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ q: "main", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Code column header refetches with sort=code", async () => {
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [costTypeFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await screen.findByRole("columnheader", { name: "Code" });

    fireEvent.click(screen.getByRole("button", { name: "Code" }));

    await waitFor(() =>
      expect(mocks.getCostTypes).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ sort: "code" }),
      ),
    );
  });

  it("refetches the table's page after creating a cost type, on top of the existing local list update", async () => {
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [], total: 0 },
        ),
    );
    mocks.createCostType.mockResolvedValue(costTypeFixture({ id: 3, code: "NEW", name: "Nouveau" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.getCostTypes).toHaveBeenCalledTimes(2));

    const codeInput = screen.getByLabelText("Code du nouveau type");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau type"), { target: { value: "Nouveau" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCostType).toHaveBeenCalledTimes(1));
    // The initial load made 2 calls (reference list + table page); creating a cost
    // type must trigger a 3rd, to refresh the table's own paginated view.
    await waitFor(() => expect(mocks.getCostTypes).toHaveBeenCalledTimes(3));
  });

  it("redirects to login when the cost-types table's own paginated fetch reports session expiry", async () => {
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        listParams === undefined
          ? Promise.resolve({ items: [], total: 0 })
          : Promise.reject(new SessionExpiredError()),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("does not mask a successful mutation as failed when the follow-up table refresh fails", async () => {
    let costTypesCallCount = 0;
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        costTypesCallCount += 1;
        // First paginated call: the initial load, succeeds. Second paginated call:
        // the reload triggered by the mutation below, fails transiently.
        if (costTypesCallCount === 1) return Promise.resolve({ items: [], total: 0 });
        return Promise.reject(new ApiError(500, "Actualisation impossible"));
      },
    );
    mocks.createCostType.mockResolvedValue(costTypeFixture({ id: 3, code: "NEW", name: "Nouveau" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.getCostTypes).toHaveBeenCalledTimes(2));

    const codeInput = screen.getByLabelText("Code du nouveau type");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau type"), { target: { value: "Nouveau" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCostType).toHaveBeenCalledTimes(1));
    // The mutation itself succeeded and must be reported as such, even though the
    // follow-up table-page refresh it triggers fails.
    await waitFor(() => expect(screen.getByText("Type de coût créé.")).toBeInTheDocument());
    expect(screen.queryByText("Actualisation impossible")).not.toBeInTheDocument();
  });

  it("does not leave the table's loading indicator stuck when a mutation's reload races an in-flight pagination fetch", async () => {
    // The initial paginated fetch is left pending on purpose (released at the end of
    // the test), simulating a mutation firing while a pagination/sort/search fetch
    // is still in flight. The mutation's own reload uses a fresh generation number
    // and resolves immediately; without its own loading-state handling, the stale
    // fetch's eventual resolution would be the only thing ever touching
    // `costTypesLoading`, and it's guarded out by the generation check -- leaving
    // the loading indicator stuck forever.
    let resolveStalePage!: (page: { items: CostType[]; total: number }) => void;
    const stalePagePromise = new Promise<{ items: CostType[]; total: number }>((resolve) => {
      resolveStalePage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getCostTypes.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        if (paginatedCallCount === 1) return stalePagePromise;
        return Promise.resolve({
          items: [costTypeFixture({ id: 3, code: "NEW", name: "Nouveau" })],
          total: 1,
        });
      },
    );
    mocks.createCostType.mockResolvedValue(costTypeFixture({ id: 3, code: "NEW", name: "Nouveau" }));

    render(<ResourcesPage />);
    // Signaled by call count rather than the generic `status` role: the cost-types
    // table's own loading skeleton is also a `role="status"`, and stays mounted
    // throughout this test by design, so it can't be used as a page-ready signal.
    await waitFor(() => expect(mocks.getCostTypes).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("status", { name: "Chargement des données" })).toBeInTheDocument());

    const codeInput = screen.getByLabelText("Code du nouveau type");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau type"), { target: { value: "Nouveau" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCostType).toHaveBeenCalledTimes(1));
    // The mutation's own reload (2nd paginated call) resolves immediately and must
    // clear the loading state on its own -- it must not wait for the stale 1st call.
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );

    // Releasing the stale initial fetch afterwards must not resurrect the loading
    // state or overwrite the fresher data already committed.
    resolveStalePage({ items: [], total: 0 });
    await waitFor(() => expect(screen.getByText("NEW")).toBeInTheDocument());
    expect(screen.queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument();
  });
});

const nodeA: ResourceNode = { id: 1, code: "NODEA", name: "Nœud A", parent_id: null } as never;
const nodeB: ResourceNode = { id: 2, code: "NODEB", name: "Nœud B", parent_id: null } as never;

const roleFixture2 = (overrides: Partial<ResourceRole> = {}): ResourceRole =>
  ({
    id: 10,
    name: "Développeur",
    node_id: nodeA.id,
    cost_category_id: 1,
    calendar_id: null,
    is_active: true,
    ...overrides,
  }) as ResourceRole;

async function openRessourcesTab() {
  render(<ResourcesPage />);
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
}

// RolesPanel shares its search placeholder ("Rechercher un rôle") with
// CapacityTable, both mounted on the same "Ressources" tab -- every query in
// this describe block that could otherwise match either table is scoped to
// RolesPanel's own <Card>. Its heading is dynamic ("Rôles" or "Rôles de
// <node name>" once a node is selected), hence the prefix match.
function rolesPanelCard(): HTMLElement {
  const heading = screen.getByRole("heading", { name: /^Rôles/ });
  const card = heading.closest('[data-slot="card"]');
  if (!card) throw new Error("roles panel card not found");
  return card as HTMLElement;
}

describe("ResourcesPage roles panel (E8-08)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([nodeA, nodeB]);
    mocks.getCalendars.mockResolvedValue([]);
    mocks.getCostTypes.mockResolvedValue({
      items: [{ id: 100, code: "MO", name: "Main d'œuvre", kind: "labor", is_active: true } as CostType],
      total: 1,
    });
    mocks.getCostCategories.mockResolvedValue({
      items: [
        { id: 200, cost_type_id: 100, accounting_code: "MO-DEV", category_code: null, name: "Développement", is_active: true } as never,
      ],
      total: 1,
    });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("requests the panel's own paginated, node-scoped page independently from the unpaginated reference list CapacityTable/RoleCalendarsTable rely on", async () => {
    // Genuinely different item sets for the two call shapes, like the equivalent
    // cost-types test: if the paginated slice ever got wired into the reference-data
    // consumers (or vice versa), this test catches it by which roles show up where.
    const fullList = [roleFixture2({ id: 10, name: "Développeur", node_id: nodeA.id })];
    const paginatedSlice = [roleFixture2({ id: 99, name: "RôlePage", node_id: nodeA.id })];
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: fullList, total: fullList.length });
        // CapacityTable's own paginated call (nodeId undefined) -- not under
        // test here, kept empty so its rendering can't collide with the
        // panel-specific assertions below.
        if (nodeId === undefined) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: paginatedSlice, total: 25 });
      },
    );

    await openRessourcesTab();
    // 3, not 2: the reference list, the panel's own node-scoped page, and
    // CapacityTable's own (unscoped) paginated page -- also mounted on the same
    // "Ressources" tab and also calling `getResourceRoles`.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));

    const calls = mocks.getResourceRoles.mock.calls as [unknown, unknown, unknown, unknown, unknown][];
    // The full reference list (feeds CapacityTable/RoleCalendarsTable) is requested
    // with no node filter and no pagination params at all.
    expect(calls.some(([, , nodeId, , listParams]) => nodeId === undefined && listParams === undefined)).toBe(true);
    // The panel's own view is requested separately, scoped to the selected node
    // (defaulted to the first loaded node) with an explicit page size.
    expect(
      calls.some(
        ([, , nodeId, , listParams]) =>
          nodeId === nodeA.id &&
          typeof listParams === "object" &&
          listParams !== null &&
          (listParams as { limit?: number }).limit === 20 &&
          (listParams as { offset?: number }).offset === 0,
      ),
    ).toBe(true);

    // CapacityTable (fed by the full, unpaginated list) shows the reference role...
    // Shows up in both CapacityTable and RoleCalendarsTable, which both render
    // every role from the full, unpaginated reference list.
    expect(screen.getAllByText(`Développeur — ${nodeA.code} (#10)`).length).toBeGreaterThan(0);
    // ...while RolesPanel shows only its own paginated slice, not the full list.
    expect(screen.getByText("RôlePage (#99)")).toBeInTheDocument();
    expect(screen.queryByText("Développeur (#10)")).not.toBeInTheDocument();
    expect(screen.queryByText(`RôlePage — ${nodeA.code} (#99)`)).not.toBeInTheDocument();
  });

  it("selecting a different node in the organization tree resets pagination to offset 0 and re-scopes the request to the new node", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [roleFixture2({})], total: 25 },
        ),
    );

    await openRessourcesTab();
    // Scoped to RolesPanel's own card: CapacityTable, on the same tab, has its
    // own "Suivant" button too.
    const suivant = await within(rolesPanelCard()).findByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());
    fireEvent.click(suivant);

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        nodeA.id,
        false,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );

    const nodeBRow = screen.getByText(nodeB.code).closest("tr");
    if (!nodeBRow) throw new Error("node row not found");
    fireEvent.click(nodeBRow);

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        nodeB.id,
        false,
        expect.objectContaining({ limit: 20, offset: 0 }),
      ),
    );
  });

  it("scopes search to the selected node: typing sends q alongside node_id, resetting to offset 0", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [roleFixture2({})], total: 1 },
        ),
    );

    await openRessourcesTab();
    // Scoped to RolesPanel's own card: CapacityTable, on the same tab, uses
    // the exact same search placeholder ("Rechercher un rôle").
    const searchInput = await within(rolesPanelCard()).findByLabelText("Rechercher un rôle");

    fireEvent.change(searchInput, { target: { value: "dev" } });

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        nodeA.id,
        false,
        expect.objectContaining({ q: "dev", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Nom column header refetches with sort=name, still scoped to the selected node", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [roleFixture2({})], total: 1 },
        ),
    );

    await openRessourcesTab();
    // Only RolesPanel's "Nom" column is sortable (rendered as a button inside the
    // header); OrganizationTree's and CalendarsTable's own "Nom" columns are plain
    // text, so this is unambiguous even though several "Nom" column headers exist
    // on the page at once.
    const sortButton = await screen.findByRole("button", { name: "Nom" });

    fireEvent.click(sortButton);

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        nodeA.id,
        false,
        expect.objectContaining({ sort: "name" }),
      ),
    );
  });

  it("refetches the panel's page after creating a role, on top of the existing local roles list update", async () => {
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.createResourceRole.mockResolvedValue(roleFixture2({ id: 42, name: "Nouveau rôle" }));

    await openRessourcesTab();
    // 3, not 2: the reference list, the panel's own page, and CapacityTable's
    // own paginated page -- also mounted on the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: String(nodeA.id) } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "200" } });
    const roleForm = nameInput.closest("form");
    if (!roleForm) throw new Error("role create form not found");
    fireEvent.click(within(roleForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The initial load made 3 calls; creating a role triggers both its own
    // panel reload and CapacityTable's reload (addRole calls both), for 5 total.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(5));
  });

  it("redirects to login when the roles panel's own paginated fetch reports session expiry", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        listParams === undefined
          ? Promise.resolve({ items: [], total: 0 })
          : Promise.reject(new SessionExpiredError()),
    );

    await openRessourcesTab();

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("does not leave the panel's loading indicator stuck when a mutation's reload races an in-flight pagination fetch", async () => {
    let resolveStalePage!: (page: { items: ResourceRole[]; total: number }) => void;
    const stalePagePromise = new Promise<{ items: ResourceRole[]; total: number }>((resolve) => {
      resolveStalePage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        // CapacityTable's own paginated call (nodeId undefined) -- not under
        // test here, kept out of the panel-specific counter below.
        if (nodeId === undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        if (paginatedCallCount === 1) return stalePagePromise;
        return Promise.resolve({ items: [roleFixture2({ id: 42, name: "Nouveau rôle" })], total: 1 });
      },
    );
    mocks.createResourceRole.mockResolvedValue(roleFixture2({ id: 42, name: "Nouveau rôle" }));

    await openRessourcesTab();
    // 3, not 2: the reference list, the panel's own page, and CapacityTable's
    // own paginated page -- also mounted on the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));
    // Scoped to RolesPanel's own card: CapacityTable shows the same
    // role="status" skeleton while its own (harmless, already-resolved) fetch
    // is briefly in flight.
    await waitFor(() =>
      expect(within(rolesPanelCard()).getByRole("status", { name: "Chargement des données" })).toBeInTheDocument(),
    );

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: String(nodeA.id) } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "200" } });
    const roleForm = nameInput.closest("form");
    if (!roleForm) throw new Error("role create form not found");
    fireEvent.click(within(roleForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The mutation's own reload (2nd panel-scoped paginated call) resolves
    // immediately and must clear the loading state on its own -- it must not
    // wait for the stale 1st call.
    await waitFor(() =>
      expect(within(rolesPanelCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );

    resolveStalePage({ items: [], total: 0 });
    await waitFor(() => expect(screen.getByText("Nouveau rôle (#42)")).toBeInTheDocument());
    expect(within(rolesPanelCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument();
  });

  it("does not leave the panel's loading indicator stuck when the selected node is deleted while its own paginated fetch is still in flight", async () => {
    let resolvePendingPage!: (page: { items: ResourceRole[]; total: number }) => void;
    const pendingPagePromise = new Promise<{ items: ResourceRole[]; total: number }>((resolve) => {
      resolvePendingPage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        // CapacityTable's own paginated call (nodeId undefined) -- not under
        // test here, kept out of the panel-specific counter below.
        if (nodeId === undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        // First paginated call (for nodeA, on initial load) is left pending on
        // purpose, to simulate the node being deleted while it's still in flight.
        if (paginatedCallCount === 1) return pendingPagePromise;
        return Promise.resolve({ items: [], total: 0 });
      },
    );
    mocks.deleteResourceNode.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);

    await openRessourcesTab();
    // 3, not 2: the reference list, the panel's own page, and CapacityTable's
    // own paginated page -- also mounted on the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));
    // Scoped to RolesPanel's own card: CapacityTable shows the same
    // role="status" skeleton while its own (harmless, already-resolved) fetch
    // is briefly in flight.
    await waitFor(() =>
      expect(within(rolesPanelCard()).getByRole("status", { name: "Chargement des données" })).toBeInTheDocument(),
    );

    const nodeARow = screen.getByText(nodeA.code).closest("tr");
    if (!nodeARow) throw new Error("node row not found");
    fireEvent.click(within(nodeARow).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(mocks.deleteResourceNode).toHaveBeenCalledWith(nodeA.id, expect.anything(), expect.anything()));
    // Deleting the selected node clears `selectedNodeId`, which takes the panel
    // effect's early-return branch on its next run -- that branch must clear the
    // loading indicator itself, since the still-pending first fetch's own
    // generation is now stale and its `finally` block is guarded out.
    await waitFor(() =>
      expect(within(rolesPanelCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Sélectionnez un nœud pour voir ses rôles.")).toBeInTheDocument();

    // Releasing the stale fetch afterwards must not resurrect the loading state.
    resolvePendingPage({ items: [], total: 0 });
    await waitFor(() =>
      expect(within(rolesPanelCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );

    confirmSpy.mockRestore();
  });

  it("does not overwrite the panel with a stale node's data when the selection changes while a role creation's reload is still pending", async () => {
    const nodeARole = roleFixture2({ id: 10, name: "RôleA", node_id: nodeA.id });
    const nodeBRole = roleFixture2({ id: 20, name: "RôleB", node_id: nodeB.id });
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId === nodeA.id) return Promise.resolve({ items: [nodeARole], total: 1 });
        if (nodeId === nodeB.id) return Promise.resolve({ items: [nodeBRole], total: 1 });
        return Promise.resolve({ items: [], total: 0 });
      },
    );
    let resolveCreate!: (role: ResourceRole) => void;
    mocks.createResourceRole.mockReturnValue(
      new Promise<ResourceRole>((resolve) => {
        resolveCreate = resolve;
      }),
    );

    await openRessourcesTab();
    await waitFor(() => expect(screen.getByText("RôleA (#10)")).toBeInTheDocument());

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: String(nodeA.id) } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "200" } });
    const roleForm = nameInput.closest("form");
    if (!roleForm) throw new Error("role create form not found");
    fireEvent.click(within(roleForm).getByRole("button", { name: "Ajouter" }));
    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));

    // Switch to node B in the org tree while node A's role creation is still
    // pending (org-tree row selection isn't disabled by `actionBusy`).
    const nodeBRow = screen.getByText(nodeB.code).closest("tr");
    if (!nodeBRow) throw new Error("node row not found");
    fireEvent.click(nodeBRow);
    await waitFor(() => expect(screen.getByText("RôleB (#20)")).toBeInTheDocument());

    // Resolving the creation now must not re-fetch/apply node A's page: the
    // reload it triggers must target the *currently* selected node (B), not the
    // node that was selected when the create form was submitted (A). Captures
    // the call count first and inspects the *next* call specifically: node B's
    // own selection already issued a `nodeB.id` call before `resolveCreate`
    // below, so a plain `toHaveBeenCalledWith` here could be satisfied by that
    // earlier call alone, without actually proving the creation's own reload
    // (not just the prior node-switch) targets B.
    const callCountBeforeResolve = mocks.getResourceRoles.mock.calls.length;
    resolveCreate(roleFixture2({ id: 30, name: "Nouveau rôle", node_id: nodeA.id }));
    // `addRole` reloads both the panel's own page and CapacityTable's (a call
    // with `nodeId === undefined`), in that order but not necessarily settling
    // in that order -- so the reload under test isn't reliably the *last* new
    // call, only *a* new call scoped to node B.
    await waitFor(() =>
      expect(
        mocks.getResourceRoles.mock.calls
          .slice(callCountBeforeResolve)
          .some((call) => call[2] === nodeB.id && call[4] && (call[4] as { offset?: number }).offset === 0),
      ).toBe(true),
    );
    expect(screen.getByText("RôleB (#20)")).toBeInTheDocument();
    expect(screen.queryByText("RôleA (#10)")).not.toBeInTheDocument();
  });

  it("does not apply a stale offset to the reload triggered by creating a role, if the user paginated away while the creation was in flight", async () => {
    const pageAtOffset0 = { items: [roleFixture2({ id: 1, name: "Page 1 role", node_id: nodeA.id })], total: 25 };
    const pageAtOffset20 = { items: [roleFixture2({ id: 2, name: "Page 2 role", node_id: nodeA.id })], total: 25 };
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId === undefined) return Promise.resolve({ items: [], total: 0 });
        const offset = (listParams as { offset?: number }).offset ?? 0;
        return Promise.resolve(offset === 0 ? pageAtOffset0 : pageAtOffset20);
      },
    );
    let resolveCreate!: (role: ResourceRole) => void;
    mocks.createResourceRole.mockReturnValue(
      new Promise<ResourceRole>((resolve) => {
        resolveCreate = resolve;
      }),
    );

    await openRessourcesTab();
    await waitFor(() => expect(screen.getByText("Page 1 role (#1)")).toBeInTheDocument());

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: String(nodeA.id) } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "200" } });
    const roleForm = nameInput.closest("form");
    if (!roleForm) throw new Error("role create form not found");
    fireEvent.click(within(roleForm).getByRole("button", { name: "Ajouter" }));
    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));

    // Paginate to offset 20 while the role creation is still in flight.
    const suivant = await within(rolesPanelCard()).findByRole("button", { name: "Suivant" });
    fireEvent.click(suivant);
    await waitFor(() => expect(screen.getByText("Page 2 role (#2)")).toBeInTheDocument());

    // Resolving the creation now must not refetch/display offset 0's stale page:
    // the reload it triggers must target the *current* offset (20), not the
    // offset that was current when "Ajouter" was clicked.
    resolveCreate(roleFixture2({ id: 9, name: "Nouveau rôle", node_id: nodeA.id }));
    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        nodeA.id,
        false,
        expect.objectContaining({ offset: 20 }),
      ),
    );
    expect(screen.getByText("Page 2 role (#2)")).toBeInTheDocument();
    expect(screen.queryByText("Page 1 role (#1)")).not.toBeInTheDocument();
  });

  it("treats selecting the placeholder option in the create form's node dropdown as no selection, not as node id 0 (which would fetch every node's roles unscoped)", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [roleFixture2({ node_id: nodeId as number })], total: 1 });
      },
    );

    await openRessourcesTab();
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      nodeA.id,
      false,
      expect.anything(),
    ));

    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: "" } });

    // Must take the "no selection" branch (no paginated fetch at all for the
    // placeholder), never a call with `nodeId` coerced to `0` -- `Number("")`
    // is `0`, and `getResourceRoles` only adds a `node_id` filter for truthy
    // values, so a literal `0` would silently fetch every node's roles unscoped.
    await waitFor(() => expect(screen.getByText("Sélectionnez un nœud pour voir ses rôles.")).toBeInTheDocument());
    expect(mocks.getResourceRoles).not.toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      0,
      expect.anything(),
      expect.anything(),
    );
  });

  it("does not go on showing the previous node's roles under the newly selected node's heading when that node's own fetch fails", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId === nodeA.id) return Promise.resolve({ items: [roleFixture2({ id: 10, name: "RôleA", node_id: nodeA.id })], total: 1 });
        return Promise.reject(new ApiError(500, "Chargement impossible"));
      },
    );

    await openRessourcesTab();
    await waitFor(() => expect(screen.getByText("RôleA (#10)")).toBeInTheDocument());

    const nodeBRow = screen.getByText(nodeB.code).closest("tr");
    if (!nodeBRow) throw new Error("node row not found");
    fireEvent.click(nodeBRow);

    // Node B's own fetch fails -- the panel must not go on displaying node A's
    // roles (now scoped to the wrong node) once the loading skeleton clears.
    await waitFor(() => expect(screen.getByText("Chargement impossible")).toBeInTheDocument());
    expect(screen.queryByText("RôleA (#10)")).not.toBeInTheDocument();
  });

  it("shows the node-selection prompt, not the generic no-results message, when the selected node is cleared while a search is still active", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined || nodeId === undefined
            ? { items: [], total: 0 }
            : { items: [roleFixture2({ node_id: nodeId as number })], total: 1 },
        ),
    );
    mocks.deleteResourceNode.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);

    await openRessourcesTab();
    const searchInput = await within(rolesPanelCard()).findByLabelText("Rechercher un rôle");
    fireEvent.change(searchInput, { target: { value: "dev" } });
    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        nodeA.id,
        false,
        expect.objectContaining({ q: "dev" }),
      ),
    );

    // Delete the selected node (search query left untouched) -- `DataTable`
    // prefers `noResultsState` over `emptyState` whenever a search is active,
    // so without a node-aware `noResultsState` this would silently show the
    // generic "no results" message instead of the "select a node" prompt.
    const nodeARow = screen.getByText(nodeA.code).closest("tr");
    if (!nodeARow) throw new Error("node row not found");
    fireEvent.click(within(nodeARow).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(mocks.deleteResourceNode).toHaveBeenCalledWith(nodeA.id, expect.anything(), expect.anything()));

    await waitFor(() => expect(screen.getByText("Sélectionnez un nœud pour voir ses rôles.")).toBeInTheDocument());
    expect(screen.queryByText("Aucun résultat pour cette recherche.")).not.toBeInTheDocument();

    confirmSpy.mockRestore();
  });
});

const resourceRoleFixture = (overrides: Partial<ResourceRole> = {}): ResourceRole =>
  ({
    id: 1,
    name: "Développeur",
    node_id: 1,
    cost_category_id: 1,
    calendar_id: null,
    is_active: true,
    ...overrides,
  }) as ResourceRole;

// The capacity table shares its exact role-label format ("name — nodeCode
// (#id)") with RoleCalendarsTable (both fed by the same unpaginated `roles`
// reference list) and its "Enregistrer" per-row button text with RoleCalendarsTable
// too -- both render below it on the same "Ressources" tab. Every query in this
// describe block is scoped to the capacity table's own <Card> to avoid ambiguous
// matches against that sibling table.
function capacityCard(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Capacités" });
  const card = heading.closest('[data-slot="card"]');
  if (!card) throw new Error("capacity card not found");
  return card as HTMLElement;
}

describe("ResourcesPage capacity table (E8-05)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([nodeFixture]);
    mocks.getCalendars.mockResolvedValue([]);
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("requests the capacity table's own paginated page (via GET /resources/roles) independently from the unpaginated reference list other panels rely on, without either leaking into the other", async () => {
    // Genuinely different item sets for the two call shapes -- if the paginated
    // slice ever got wired into the reference-data consumers (or vice versa), this
    // test would catch it by which roles show up where, not just by which params
    // getResourceRoles was called with.
    const fullList = [
      resourceRoleFixture({ id: 1, name: "Développeur" }),
      resourceRoleFixture({ id: 2, name: "Chef de projet" }),
    ];
    const paginatedSlice = [resourceRoleFixture({ id: 6, name: "PAGE1 role" })];
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: fullList, total: fullList.length }
            : { items: paginatedSlice, total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // 3, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's own (node-scoped) paginated page -- also mounted on the
    // same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));

    const calls = mocks.getResourceRoles.mock.calls as [unknown, unknown, unknown, unknown, unknown][];
    // The full reference list (feeds RolesPanel/RoleCalendarsTable/capacity drafts) is
    // requested with no pagination params at all -- absence of `limit` must return
    // everything, per EPIC E7/E8.
    expect(calls.some(([, , , , listParams]) => listParams === undefined)).toBe(true);
    // The capacity table's own view is requested separately, with an explicit page size.
    expect(
      calls.some(
        ([, , , , listParams]) =>
          typeof listParams === "object" &&
          listParams !== null &&
          (listParams as { limit?: number }).limit === 20 &&
          (listParams as { offset?: number }).offset === 0,
      ),
    ).toBe(true);

    // The capacity table itself shows only its own paginated slice, not the full list.
    await waitFor(() => expect(within(capacityCard()).getByText("PAGE1 role — IT (#6)")).toBeInTheDocument());
    expect(within(capacityCard()).queryByText("Développeur — IT (#1)")).not.toBeInTheDocument();
  });

  it("paginates: clicking Suivant refetches the capacity table with the next offset, leaving the reference-list call untouched", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [resourceRoleFixture({})], total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    const suivantButtons = await screen.findAllByRole("button", { name: "Suivant" });
    const capacitySuivant = suivantButtons[suivantButtons.length - 1];
    await waitFor(() => expect(capacitySuivant).toBeEnabled());

    fireEvent.click(capacitySuivant);

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        false,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });

  it("searches: typing in the capacity table's search box debounces then refetches with q, resetting to offset 0", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [resourceRoleFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // Scoped to the capacity table's own card: RolesPanel, on the same tab,
    // uses the exact same search placeholder ("Rechercher un rôle").
    const searchInput = await within(capacityCard()).findByLabelText("Rechercher un rôle");

    fireEvent.change(searchInput, { target: { value: "dev" } });

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        false,
        expect.objectContaining({ q: "dev", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Rôle column header refetches with sort=name", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [resourceRoleFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(within(capacityCard()).getByRole("columnheader", { name: "Rôle" })).toBeInTheDocument());

    fireEvent.click(within(capacityCard()).getByRole("button", { name: "Rôle" }));

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        false,
        expect.objectContaining({ sort: "name" }),
      ),
    );
  });

  it("refetches the capacity table's page after creating a role, on top of the existing local list update", async () => {
    const laborCostType = {
      id: 1,
      code: "MO",
      name: "Main d'œuvre",
      kind: "labor",
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    } as CostType;
    const category = {
      id: 5,
      accounting_code: "C1",
      category_code: null,
      name: "Catégorie 1",
      cost_type_id: 1,
      is_active: true,
    } as never;
    mocks.getCostTypes.mockResolvedValue({ items: [laborCostType], total: 1 });
    mocks.getCostCategories.mockResolvedValue({ items: [category], total: 1 });
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [], total: 0 },
        ),
    );
    mocks.createResourceRole.mockResolvedValue(resourceRoleFixture({ id: 9, name: "Nouveau rôle" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // 3, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's own paginated page -- also mounted on the same "Ressources"
    // tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "5" } });
    const rolesForm = nameInput.closest("form");
    if (!rolesForm) throw new Error("roles form not found");
    fireEvent.click(within(rolesForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The initial load made 3 calls; creating a role triggers both RolesPanel's
    // own reload and the capacity table's reload (addRole calls both), for 5 total.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(5));
  });

  it("redirects to login when the capacity table's own paginated fetch reports session expiry", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        listParams === undefined
          ? Promise.resolve({ items: [], total: 0 })
          : Promise.reject(new SessionExpiredError()),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("saves a capacity inline for a role that has none yet (creates rather than updates), even though the role list is now server-paginated", async () => {
    const role = resourceRoleFixture({ id: 42, name: "Sans capacité" });
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [role], total: 1 }
            : { items: [role], total: 1 },
        ),
    );
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.createRoleCapacity.mockResolvedValue({
      id: 100,
      role_id: 42,
      person_count: "2.00",
      available_hours: "1600.00",
    });

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(within(capacityCard()).getByText("Sans capacité — IT (#42)")).toBeInTheDocument());

    const personCountInput = within(capacityCard()).getByLabelText("Nombre de personnes pour Sans capacité — IT (#42)");
    fireEvent.change(personCountInput, { target: { value: "2.00" } });
    fireEvent.click(within(capacityCard()).getByRole("button", { name: "Enregistrer" }));

    await waitFor(() =>
      expect(mocks.createRoleCapacity).toHaveBeenCalledWith(
        { role_id: 42, person_count: "2.00", available_hours: "0.00" },
        expect.anything(),
        expect.anything(),
      ),
    );
    expect(mocks.updateRoleCapacity).not.toHaveBeenCalled();
  });

  it("does not mask a successful role creation as failed when the follow-up capacity-table refresh fails", async () => {
    const laborCostType = {
      id: 1,
      code: "MO",
      name: "Main d'œuvre",
      kind: "labor",
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    } as CostType;
    const category = {
      id: 5,
      accounting_code: "C1",
      category_code: null,
      name: "Catégorie 1",
      cost_type_id: 1,
      is_active: true,
    } as never;
    mocks.getCostTypes.mockResolvedValue({ items: [laborCostType], total: 1 });
    mocks.getCostCategories.mockResolvedValue({ items: [category], total: 1 });
    let paginatedCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        // RolesPanel's own paginated call (nodeId defined) -- not under test
        // here, kept out of the capacity-table-specific counter below.
        if (nodeId !== undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        // First paginated call: the initial load, succeeds. Second paginated call: the
        // reload triggered by the role creation below, fails transiently.
        if (paginatedCallCount === 1) return Promise.resolve({ items: [], total: 0 });
        return Promise.reject(new ApiError(500, "Actualisation impossible"));
      },
    );
    mocks.createResourceRole.mockResolvedValue(resourceRoleFixture({ id: 9, name: "Nouveau rôle" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // 3, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's own paginated page -- also mounted on the same "Ressources"
    // tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "5" } });
    const rolesForm = nameInput.closest("form");
    if (!rolesForm) throw new Error("roles form not found");
    fireEvent.click(within(rolesForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The role creation itself succeeded and must be reported as such, even though
    // the follow-up capacity-table refresh it triggers fails.
    await waitFor(() => expect(screen.getByText("Rôle créé.")).toBeInTheDocument());
    expect(screen.queryByText("Actualisation impossible")).not.toBeInTheDocument();
  });

  it("does not leave the capacity table's loading indicator stuck when a role creation's reload races an in-flight pagination fetch", async () => {
    const laborCostType = {
      id: 1,
      code: "MO",
      name: "Main d'œuvre",
      kind: "labor",
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    } as CostType;
    const category = {
      id: 5,
      accounting_code: "C1",
      category_code: null,
      name: "Catégorie 1",
      cost_type_id: 1,
      is_active: true,
    } as never;
    mocks.getCostTypes.mockResolvedValue({ items: [laborCostType], total: 1 });
    mocks.getCostCategories.mockResolvedValue({ items: [category], total: 1 });
    let resolveStalePage!: (page: { items: ResourceRole[]; total: number }) => void;
    const stalePagePromise = new Promise<{ items: ResourceRole[]; total: number }>((resolve) => {
      resolveStalePage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        // RolesPanel's own paginated call (nodeId defined) -- not under test
        // here, kept out of the capacity-table-specific counter below.
        if (nodeId !== undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        if (paginatedCallCount === 1) return stalePagePromise;
        return Promise.resolve({
          items: [resourceRoleFixture({ id: 9, name: "Nouveau rôle" })],
          total: 1,
        });
      },
    );
    mocks.createResourceRole.mockResolvedValue(resourceRoleFixture({ id: 9, name: "Nouveau rôle" }));

    render(<ResourcesPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // Signaled by call count rather than the generic `status` role: the capacity
    // table's own loading skeleton is also a `role="status"`, and stays mounted
    // throughout this test by design, so it can't be used as a page-ready signal.
    // 3, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's own paginated page -- also mounted on the same "Ressources"
    // tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(within(capacityCard()).getByRole("status", { name: "Chargement des données" })).toBeInTheDocument(),
    );

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "5" } });
    const rolesForm = nameInput.closest("form");
    if (!rolesForm) throw new Error("roles form not found");
    fireEvent.click(within(rolesForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The role creation's own reload (2nd paginated call) resolves immediately and
    // must clear the loading state on its own -- it must not wait for the stale call.
    await waitFor(() =>
      expect(within(capacityCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );

    // Releasing the stale initial fetch afterwards must not resurrect the loading
    // state or overwrite the fresher data already committed.
    resolveStalePage({ items: [], total: 0 });
    await waitFor(() => expect(within(capacityCard()).getByText("Nouveau rôle — IT (#9)")).toBeInTheDocument());
    expect(within(capacityCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument();
  });

  it("does not apply a stale offset to the reload triggered by creating a role, if the user paginated away while the creation was in flight", async () => {
    const laborCostType = {
      id: 1,
      code: "MO",
      name: "Main d'œuvre",
      kind: "labor",
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    } as CostType;
    const category = {
      id: 5,
      accounting_code: "C1",
      category_code: null,
      name: "Catégorie 1",
      cost_type_id: 1,
      is_active: true,
    } as never;
    mocks.getCostTypes.mockResolvedValue({ items: [laborCostType], total: 1 });
    mocks.getCostCategories.mockResolvedValue({ items: [category], total: 1 });
    const pageAtOffset0 = { items: [resourceRoleFixture({ id: 1, name: "Page 1 role" })], total: 25 };
    const pageAtOffset20 = { items: [resourceRoleFixture({ id: 2, name: "Page 2 role" })], total: 25 };
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        const offset = (listParams as { offset?: number }).offset ?? 0;
        return Promise.resolve(offset === 0 ? pageAtOffset0 : pageAtOffset20);
      },
    );
    let resolveCreate!: (role: ResourceRole) => void;
    mocks.createResourceRole.mockReturnValue(
      new Promise<ResourceRole>((resolve) => {
        resolveCreate = resolve;
      }),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(within(capacityCard()).getByText("Page 1 role — IT (#1)")).toBeInTheDocument());

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "5" } });
    const rolesForm = nameInput.closest("form");
    if (!rolesForm) throw new Error("roles form not found");
    fireEvent.click(within(rolesForm).getByRole("button", { name: "Ajouter" }));
    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));

    // Paginate to offset 20 while the role creation is still in flight.
    const suivant = within(capacityCard()).getByRole("button", { name: "Suivant" });
    fireEvent.click(suivant);
    await waitFor(() => expect(within(capacityCard()).getByText("Page 2 role — IT (#2)")).toBeInTheDocument());

    // Resolving the creation now must not refetch/display offset 0's stale page:
    // the reload it triggers must target the *current* offset (20), not the
    // offset that was current when "Ajouter" was clicked.
    resolveCreate(resourceRoleFixture({ id: 9, name: "Nouveau rôle" }));
    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        false,
        expect.objectContaining({ offset: 20 }),
      ),
    );
    expect(within(capacityCard()).getByText("Page 2 role — IT (#2)")).toBeInTheDocument();
    expect(within(capacityCard()).queryByText("Page 1 role — IT (#1)")).not.toBeInTheDocument();
  });
});

const categoryFixture = (overrides: Partial<CostCategory> = {}): CostCategory =>
  ({
    id: 1,
    cost_type_id: 1,
    accounting_code: "601",
    category_code: "MAT",
    name: "Matériel",
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as CostCategory;

describe("ResourcesPage cost categories table (E8-03)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue([]);
    // Deliberately "supply", not "labor": ValuationPanel (also mounted on the "costs"
    // tab) filters the full `categories` reference list down to labor-linked
    // categories only. Keeping the fixture cost type non-labor means the full-list
    // fixtures below never leak into ValuationPanel's own rendering, which would
    // otherwise collide with this describe block's own text/role assertions.
    mocks.getCostTypes.mockResolvedValue({ items: [costTypeFixture({ kind: "supply" })], total: 1 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("requests the table's own paginated page independently from the unpaginated reference list other panels rely on, without either leaking into the other", async () => {
    const fullList = [
      categoryFixture({ id: 1, accounting_code: "601", name: "Matériel" }),
      categoryFixture({ id: 2, accounting_code: "602", name: "Sous-traitance" }),
    ];
    const paginatedSlice = [categoryFixture({ id: 6, accounting_code: "PAGE1", name: "Page item" })];
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: fullList, total: fullList.length }
            : { items: paginatedSlice, total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.getCostCategories).toHaveBeenCalledTimes(2));

    const calls = mocks.getCostCategories.mock.calls as [unknown, unknown, unknown, unknown][];
    // The full reference list (feeds RolesPanel/ValuationPanel/categoryNameById) is
    // requested with no pagination params at all -- absence of `limit` must return
    // everything, per EPIC E7/E8.
    expect(calls.some(([, , , listParams]) => listParams === undefined)).toBe(true);
    // The table's own view is requested separately, with an explicit page size.
    expect(
      calls.some(
        ([, , , listParams]) =>
          typeof listParams === "object" &&
          listParams !== null &&
          (listParams as { limit?: number }).limit === 20 &&
          (listParams as { offset?: number }).offset === 0,
      ),
    ).toBe(true);

    // The cost-categories table itself shows only its own paginated slice, not the full list.
    expect(screen.getByText("PAGE1")).toBeInTheDocument();
    expect(screen.queryByText("601")).not.toBeInTheDocument();
  });

  it("paginates: clicking Suivant refetches the table with the next offset, leaving the reference-list call untouched", async () => {
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [categoryFixture({})], total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    // Scoped to the cost-categories table's own <form>: the cost-types table above it
    // renders an identically-labeled "Suivant" button of its own.
    const categoriesTable = (await screen.findByLabelText("Rechercher une catégorie de coût")).closest(
      "form",
    ) as HTMLElement;
    const suivant = within(categoriesTable).getByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());

    fireEvent.click(suivant);

    await waitFor(() =>
      expect(mocks.getCostCategories).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });

  it("searches: typing in the cost-categories search box debounces then refetches with q, resetting to offset 0", async () => {
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [categoryFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    const searchInput = await screen.findByLabelText("Rechercher une catégorie de coût");

    fireEvent.change(searchInput, { target: { value: "mat" } });

    await waitFor(() =>
      expect(mocks.getCostCategories).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ q: "mat", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Code comptable column header refetches with sort=accounting_code", async () => {
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [categoryFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    // Only the cost-categories table's own "Code comptable" header renders as a
    // sortable <Button>; ValuationPanel's own static "Code comptable" column header
    // (also mounted on the "costs" tab) is a plain, non-interactive <TableHead>, so
    // this stays unambiguous without needing to scope it further.
    const sortButton = await screen.findByRole("button", { name: "Code comptable" });

    fireEvent.click(sortButton);

    await waitFor(() =>
      expect(mocks.getCostCategories).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ sort: "accounting_code" }),
      ),
    );
  });

  it("refetches the table's page after creating a category, on top of the existing local list update", async () => {
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined ? { items: [], total: 0 } : { items: [], total: 0 },
        ),
    );
    mocks.createCostCategory.mockResolvedValue(
      categoryFixture({ id: 3, accounting_code: "NEW", name: "Nouveau" }),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.getCostCategories).toHaveBeenCalledTimes(2));

    const typeSelect = screen.getByLabelText("Type de la nouvelle catégorie");
    fireEvent.change(typeSelect, { target: { value: "1" } });
    const accountingCodeInput = screen.getByLabelText("Code comptable de la nouvelle catégorie");
    fireEvent.change(accountingCodeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom de la nouvelle catégorie"), { target: { value: "Nouveau" } });
    const addRow = accountingCodeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCostCategory).toHaveBeenCalledTimes(1));
    // The initial load made 2 calls (reference list + table page); creating a category
    // must trigger a 3rd, to refresh the table's own paginated view.
    await waitFor(() => expect(mocks.getCostCategories).toHaveBeenCalledTimes(3));
  });

  it("redirects to login when the cost-categories table's own paginated fetch reports session expiry", async () => {
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        listParams === undefined
          ? Promise.resolve({ items: [], total: 0 })
          : Promise.reject(new SessionExpiredError()),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("does not mask a successful mutation as failed when the follow-up table refresh fails", async () => {
    let categoriesCallCount = 0;
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        categoriesCallCount += 1;
        // First paginated call: the initial load, succeeds. Second paginated call:
        // the reload triggered by the mutation below, fails transiently.
        if (categoriesCallCount === 1) return Promise.resolve({ items: [], total: 0 });
        return Promise.reject(new ApiError(500, "Actualisation impossible"));
      },
    );
    mocks.createCostCategory.mockResolvedValue(
      categoryFixture({ id: 3, accounting_code: "NEW", name: "Nouveau" }),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.getCostCategories).toHaveBeenCalledTimes(2));

    const typeSelect = screen.getByLabelText("Type de la nouvelle catégorie");
    fireEvent.change(typeSelect, { target: { value: "1" } });
    const accountingCodeInput = screen.getByLabelText("Code comptable de la nouvelle catégorie");
    fireEvent.change(accountingCodeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom de la nouvelle catégorie"), { target: { value: "Nouveau" } });
    const addRow = accountingCodeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCostCategory).toHaveBeenCalledTimes(1));
    // The mutation itself succeeded and must be reported as such, even though the
    // follow-up table-page refresh it triggers fails.
    await waitFor(() => expect(screen.getByText("Catégorie créée.")).toBeInTheDocument());
    expect(screen.queryByText("Actualisation impossible")).not.toBeInTheDocument();
  });

  it("does not leave the table's loading indicator stuck when a mutation's reload races an in-flight pagination fetch", async () => {
    let resolveStalePage!: (page: { items: CostCategory[]; total: number }) => void;
    const stalePagePromise = new Promise<{ items: CostCategory[]; total: number }>((resolve) => {
      resolveStalePage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getCostCategories.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        if (paginatedCallCount === 1) return stalePagePromise;
        return Promise.resolve({
          items: [categoryFixture({ id: 3, accounting_code: "NEW", name: "Nouveau" })],
          total: 1,
        });
      },
    );
    mocks.createCostCategory.mockResolvedValue(
      categoryFixture({ id: 3, accounting_code: "NEW", name: "Nouveau" }),
    );

    render(<ResourcesPage />);
    // Signaled by call count rather than the generic `status` role: the
    // cost-categories table's own loading skeleton is also a `role="status"`, and
    // stays mounted throughout this test by design, so it can't be used as a
    // page-ready signal.
    await waitFor(() => expect(mocks.getCostCategories).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByRole("status", { name: "Chargement des données" }).length).toBeGreaterThan(0));

    const typeSelect = screen.getByLabelText("Type de la nouvelle catégorie");
    fireEvent.change(typeSelect, { target: { value: "1" } });
    const accountingCodeInput = screen.getByLabelText("Code comptable de la nouvelle catégorie");
    fireEvent.change(accountingCodeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom de la nouvelle catégorie"), { target: { value: "Nouveau" } });
    const addRow = accountingCodeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCostCategory).toHaveBeenCalledTimes(1));
    // The mutation's own reload (2nd paginated call) resolves immediately and must
    // clear the loading state on its own -- it must not wait for the stale 1st call.
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );

    // Releasing the stale initial fetch afterwards must not resurrect the loading
    // state or overwrite the fresher data already committed.
    resolveStalePage({ items: [], total: 0 });
    await waitFor(() => expect(screen.getByText("NEW")).toBeInTheDocument());
    expect(screen.queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument();
  });
});
