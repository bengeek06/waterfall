import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  SessionExpiredError,
  type Calendar,
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
  mocks.getResourceRoles.mockResolvedValue(roles);
  mocks.getCalendars.mockResolvedValue({ items: calendars, total: calendars.length });
  mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostCategories.mockResolvedValue([]);
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
    // The toggle handler mutates `calendars` (the full reference list) optimistically,
    // then reloads the table's own paginated view (`reloadCalendarsPage`) -- which, in
    // production, would reflect the just-applied deactivation. Simulated here by
    // updating what the next `getCalendars` call resolves to.
    mocks.getCalendars.mockResolvedValue({ items: [{ ...activeCalendar, is_active: false }], total: 1 });

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() => expect(mocks.deleteCalendar).toHaveBeenCalledWith(1, expect.anything(), expect.anything()));
    expect(mocks.updateCalendar).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Réactiver" })).toBeInTheDocument());
  });

  it("reactivates an inactive calendar via PATCH is_active:true instead of DELETE", async () => {
    mocks.updateCalendar.mockResolvedValue({ ...inactiveCalendar, is_active: true });
    await renderResourcesTab([inactiveCalendar]);
    // See the comment in the deactivate test above: the table's own paginated view is
    // only refreshed by the reload the toggle handler triggers, not by the optimistic
    // update to the full reference list.
    mocks.getCalendars.mockResolvedValue({ items: [{ ...inactiveCalendar, is_active: true }], total: 1 });

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
    // The create handler appends the new calendar to `calendars` (the full reference
    // list) optimistically, then reloads the table's own paginated view: simulated
    // here by updating what the next `getCalendars` call resolves to.
    mocks.getCalendars.mockResolvedValue({ items: [activeCalendar, createdCalendar], total: 2 });

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
    // The save handler replaces the calendar in `calendars` (the full reference list)
    // optimistically, then reloads the table's own paginated view: simulated here by
    // updating what the next `getCalendars` call resolves to.
    mocks.getCalendars.mockResolvedValue({ items: [updatedCalendar], total: 1 });

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

  it("promotes a calendar as default and reflects the previous default's demotion once the table's page reloads", async () => {
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
    // The set-default handler demotes the previous default in `calendars` (the full
    // reference list) optimistically, then reloads the table's own paginated view:
    // simulated here by updating what the next `getCalendars` call resolves to.
    mocks.getCalendars.mockResolvedValue({ items: [{ ...previousDefault, is_default: false }, promoted], total: 2 });

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
    mocks.getResourceRoles.mockResolvedValue([]);
    mocks.getCalendars.mockResolvedValue({ items: [activeCalendar], total: 1 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue([]);
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
    mocks.getResourceRoles.mockResolvedValue([]);
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue([]);
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
    mocks.getResourceRoles.mockResolvedValue([]);
    mocks.getCalendars.mockResolvedValue({ items: [activeCalendar], total: 1 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue([]);
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
        return Promise.resolve([]);
      },
    );

    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue([]);
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

const calendarFixture = (overrides: Partial<Calendar> = {}): Calendar =>
  ({
    id: 1,
    code: "STANDARD",
    name: "Calendrier standard",
    weeks_per_year: 47,
    is_active: true,
    is_default: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    weekdays: [],
    ...overrides,
  }) as Calendar;

describe("ResourcesPage calendars table (E8-07)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([nodeFixture]);
    mocks.getResourceRoles.mockResolvedValue([roleFixture]);
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue([]);
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
    // getCalendars was called with.
    const fullList = [
      calendarFixture({ id: 1, code: "STANDARD", name: "Calendrier standard" }),
      calendarFixture({ id: 2, code: "REDUIT", name: "Calendrier réduit" }),
    ];
    const paginatedSlice = [calendarFixture({ id: 6, code: "PAGE1", name: "Page item" })];
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: fullList, total: fullList.length }
            : { items: paginatedSlice, total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(mocks.getCalendars).toHaveBeenCalledTimes(2));

    const calls = mocks.getCalendars.mock.calls as [unknown, unknown, unknown, unknown][];
    // The full reference list (feeds RoleCalendarsTable's assignment dropdown and the
    // missing-default-calendar banner) is requested with no pagination params at all
    // -- absence of `limit` must return everything, per EPIC E7/E8.
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

    // The role-calendar assignment dropdown (fed by the full, unpaginated list) must
    // offer every reference calendar, not just the calendars table's page.
    const calendarSelect = screen.getByLabelText(
      `Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`,
    );
    for (const calendar of fullList) {
      expect(within(calendarSelect).getByRole("option", { name: `${calendar.code} - ${calendar.name}` })).toBeInTheDocument();
    }
    expect(within(calendarSelect).queryByRole("option", { name: /PAGE1/ })).not.toBeInTheDocument();

    // The calendars table itself shows only its own paginated slice, not the full list.
    expect(screen.getByText("PAGE1")).toBeInTheDocument();
    expect(screen.queryByText("STANDARD")).not.toBeInTheDocument();
  });

  it("paginates: clicking Suivant refetches the table with the next offset, leaving the reference-list call untouched", async () => {
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [calendarFixture({})], total: 25 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    const suivant = await screen.findByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());

    fireEvent.click(suivant);

    await waitFor(() =>
      expect(mocks.getCalendars).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });

  it("searches: typing in the calendars search box debounces then refetches with q, resetting to offset 0", async () => {
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [calendarFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    const searchInput = await screen.findByLabelText("Rechercher un calendrier");

    fireEvent.change(searchInput, { target: { value: "standard" } });

    await waitFor(() =>
      expect(mocks.getCalendars).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ q: "standard", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Code column header refetches with sort=code", async () => {
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [calendarFixture({})], total: 1 },
        ),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // Scoped to a button (not a bare columnheader): the "Organisation" table on this
    // same tab has its own, non-sortable "Code" column header, which would otherwise
    // match too.
    const sortButton = await screen.findByRole("button", { name: "Code" });

    fireEvent.click(sortButton);

    await waitFor(() =>
      expect(mocks.getCalendars).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        true,
        expect.objectContaining({ sort: "code" }),
      ),
    );
  });

  it("refetches the table's page after creating a calendar, on top of the existing local list update", async () => {
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        Promise.resolve(
          listParams === undefined
            ? { items: [], total: 0 }
            : { items: [], total: 0 },
        ),
    );
    mocks.createCalendar.mockResolvedValue(calendarFixture({ id: 3, code: "NEW", name: "Nouveau" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(mocks.getCalendars).toHaveBeenCalledTimes(2));

    const codeInput = screen.getByLabelText("Code du nouveau calendrier");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau calendrier"), { target: { value: "Nouveau" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCalendar).toHaveBeenCalledTimes(1));
    // The initial load made 2 calls (reference list + table page); creating a
    // calendar must trigger a 3rd, to refresh the table's own paginated view.
    await waitFor(() => expect(mocks.getCalendars).toHaveBeenCalledTimes(3));
  });

  it("redirects to login when the calendars table's own paginated fetch reports session expiry", async () => {
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) =>
        listParams === undefined
          ? Promise.resolve({ items: [], total: 0 })
          : Promise.reject(new SessionExpiredError()),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("does not mask a successful mutation as failed when the follow-up table refresh fails", async () => {
    let calendarsCallCount = 0;
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        calendarsCallCount += 1;
        // First paginated call: the initial load, succeeds. Second paginated call:
        // the reload triggered by the mutation below, fails transiently.
        if (calendarsCallCount === 1) return Promise.resolve({ items: [], total: 0 });
        return Promise.reject(new ApiError(500, "Actualisation impossible"));
      },
    );
    mocks.createCalendar.mockResolvedValue(calendarFixture({ id: 3, code: "NEW", name: "Nouveau" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(mocks.getCalendars).toHaveBeenCalledTimes(2));

    const codeInput = screen.getByLabelText("Code du nouveau calendrier");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau calendrier"), { target: { value: "Nouveau" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCalendar).toHaveBeenCalledTimes(1));
    // The mutation itself succeeded and must be reported as such, even though the
    // follow-up table-page refresh it triggers fails.
    await waitFor(() => expect(screen.getByText("Calendrier créé.")).toBeInTheDocument());
    expect(screen.queryByText("Actualisation impossible")).not.toBeInTheDocument();
  });

  it("does not leave the table's loading indicator stuck when a mutation's reload races an in-flight pagination fetch", async () => {
    // The initial paginated fetch is left pending on purpose (released at the end of
    // the test), simulating a mutation firing while a pagination/sort/search fetch is
    // still in flight. The mutation's own reload uses a fresh generation number and
    // resolves immediately; without its own loading-state handling, the stale fetch's
    // eventual resolution would be the only thing ever touching `calendarsLoading`,
    // and it's guarded out by the generation check -- leaving the loading indicator
    // stuck forever.
    let resolveStalePage!: (page: { items: Calendar[]; total: number }) => void;
    const stalePagePromise = new Promise<{ items: Calendar[]; total: number }>((resolve) => {
      resolveStalePage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getCalendars.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _includeInactive: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        if (paginatedCallCount === 1) return stalePagePromise;
        return Promise.resolve({
          items: [calendarFixture({ id: 3, code: "NEW", name: "Nouveau" })],
          total: 1,
        });
      },
    );
    mocks.createCalendar.mockResolvedValue(calendarFixture({ id: 3, code: "NEW", name: "Nouveau" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // Signaled by call count rather than the generic `status` role: the calendars
    // table's own loading skeleton is also a `role="status"`, and stays mounted
    // throughout this test by design, so it can't be used as a page-ready signal.
    await waitFor(() => expect(mocks.getCalendars).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("status", { name: "Chargement des données" })).toBeInTheDocument());

    const codeInput = screen.getByLabelText("Code du nouveau calendrier");
    fireEvent.change(codeInput, { target: { value: "NEW" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau calendrier"), { target: { value: "Nouveau" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createCalendar).toHaveBeenCalledTimes(1));
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
    mocks.getResourceRoles.mockResolvedValue([]);
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue([]);
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
    const suivant = await screen.findByRole("button", { name: "Suivant" });
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
