import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  SessionExpiredError,
  type AuthUserAdmin,
  type Calendar,
  type CostCategory,
  type CostType,
  type ResourceNode,
  type ResourceRole,
  type RoleCapacity,
} from "@/lib/backend";
import { defaultWeekdays } from "@/components/calendars-table";

const mocks = vi.hoisted(() => ({
  // Given a persistent default resolved value here (not just `vi.fn()`), since
  // `vi.clearAllMocks()` (used throughout this file) clears call history but not
  // mock implementations -- every describe block's initial page load calls this
  // once, and most don't care about its result, so a single sensible default
  // (an id no test's user fixtures use) avoids needing to mock it everywhere.
  getMe: vi.fn().mockResolvedValue({ id: 999, email: "admin@example.com", is_active: true }),
  getResourceNodes: vi.fn(),
  getResourceRoles: vi.fn(),
  getCalendars: vi.fn(),
  getCostTypes: vi.fn(),
  getCostCategories: vi.fn(),
  getCostRates: vi.fn(),
  getInflationRates: vi.fn(),
  getRoleCapacities: vi.fn(),
  getUsers: vi.fn(),
  createUser: vi.fn(),
  deleteUser: vi.fn(),
  setUserStatus: vi.fn(),
  setUserRole: vi.fn(),
  createCalendar: vi.fn(),
  updateCalendar: vi.fn(),
  deleteCalendar: vi.fn(),
  updateResourceRole: vi.fn(),
  createCostType: vi.fn(),
  createCostRate: vi.fn(),
  updateCostRate: vi.fn(),
  createResourceRole: vi.fn(),
  deleteResourceNode: vi.fn(),
  createRoleCapacity: vi.fn(),
  updateRoleCapacity: vi.fn(),
  createCostCategory: vi.fn(),
  createResourceNode: vi.fn(),
  clearSession: vi.fn(),
  router: { push: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => mocks.router,
}));

vi.mock("@/lib/session", () => ({
  clearSession: mocks.clearSession,
  getSession: vi.fn(() => ({ accessToken: "test-token" })),
  setSession: vi.fn(),
}));

vi.mock("@/lib/backend", async () => {
  const actual = await vi.importActual<typeof import("@/lib/backend")>("@/lib/backend");
  return {
    ...actual,
    getMe: mocks.getMe,
    getResourceNodes: mocks.getResourceNodes,
    getResourceRoles: mocks.getResourceRoles,
    getCalendars: mocks.getCalendars,
    getCostTypes: mocks.getCostTypes,
    getCostCategories: mocks.getCostCategories,
    getCostRates: mocks.getCostRates,
    getInflationRates: mocks.getInflationRates,
    getRoleCapacities: mocks.getRoleCapacities,
    getUsers: mocks.getUsers,
    createUser: mocks.createUser,
    deleteUser: mocks.deleteUser,
    setUserStatus: mocks.setUserStatus,
    setUserRole: mocks.setUserRole,
    createCalendar: mocks.createCalendar,
    updateCalendar: mocks.updateCalendar,
    deleteCalendar: mocks.deleteCalendar,
    updateResourceRole: mocks.updateResourceRole,
    createCostType: mocks.createCostType,
    createCostRate: mocks.createCostRate,
    updateCostRate: mocks.updateCostRate,
    createResourceRole: mocks.createResourceRole,
    deleteResourceNode: mocks.deleteResourceNode,
    createRoleCapacity: mocks.createRoleCapacity,
    updateRoleCapacity: mocks.updateRoleCapacity,
    createCostCategory: mocks.createCostCategory,
    createResourceNode: mocks.createResourceNode,
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

// `getResourceRoles` always resolves to `{items, total}`, whether or not
// `listParams` is passed -- see `ListPage`/`buildListQuery` in backend.ts. Most
// tests in this file don't care about pagination and just want the same roles to
// show up for every call, hence this shared helper instead of a bare
// `mockResolvedValue`.
function mockGetResourceRoles(roles: ResourceRole[]) {
  mocks.getResourceRoles.mockResolvedValue({ items: roles, total: roles.length });
}

async function renderResourcesTab(calendars: Calendar[], roles: ResourceRole[] = [], nodes: ResourceNode[] = []) {
  mocks.getResourceNodes.mockResolvedValue(nodes);
  mockGetResourceRoles(roles);
  mocks.getCalendars.mockResolvedValue({ items: calendars, total: calendars.length });
  mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostRates.mockResolvedValue([]);
  mocks.getInflationRates.mockResolvedValue([]);
  mocks.getRoleCapacities.mockResolvedValue([]);
  mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

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

  it("keeps the row's displayed state on the just-applied toggle when the post-toggle reload silently fails", async () => {
    // Regression test for the optimistic patch to `calendarsPage.items` in
    // `toggleCalendarActive`: the mutation itself (`deleteCalendar`) succeeds, but the
    // `reloadCalendarsPage()` call that follows fails with a non-auth error, which
    // `reloadCalendarsPage` swallows silently (see its own comment in page.tsx) rather
    // than surfacing it. Without the optimistic patch, the table's displayed row would
    // be stuck showing the pre-toggle state forever, with no error to explain why.
    mocks.deleteCalendar.mockResolvedValue(undefined);
    await renderResourcesTab([activeCalendar]);
    // Only the reload triggered by the toggle (the next call) must fail -- the initial
    // page load above already resolved successfully via `renderResourcesTab`.
    mocks.getCalendars.mockRejectedValueOnce(new ApiError(500, "Erreur serveur interne."));

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() => expect(mocks.deleteCalendar).toHaveBeenCalledWith(1, expect.anything(), expect.anything()));
    // The row must flip to "Réactiver" from the optimistic patch alone, since the
    // failed reload could not have supplied this value.
    await waitFor(() => expect(screen.getByRole("button", { name: "Réactiver" })).toBeInTheDocument());
    // The action is still reported as successful to the user -- the reload failure is
    // deliberately silent -- and no error notice is shown.
    expect(await screen.findByText("Calendrier désactivé.")).toBeInTheDocument();
    expect(screen.queryByText("Erreur serveur interne.")).not.toBeInTheDocument();
  });

  it("surfaces the 409 guard error and leaves the calendar active when deletion is blocked", async () => {
    mocks.deleteCalendar.mockRejectedValue(new ApiError(409, "Calendrier assigné à un rôle actif."));
    await renderResourcesTab([activeCalendar]);

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));

    await waitFor(() => expect(screen.getByText("Calendrier assigné à un rôle actif.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Réactiver" })).not.toBeInTheDocument();
  });

  // Regression test for #195: `submitAction` (used by every mutation on this page,
  // including `addNode`) must handle `SessionExpiredError` the same way the page's
  // own reload functions already do (see `reloadCalendarsPage`), instead of falling
  // through to the generic "Opération impossible" message.
  it("clears the session and redirects to login, instead of showing a generic error, when a submitAction mutation reports session expiry", async () => {
    mocks.createResourceNode.mockRejectedValue(new SessionExpiredError());
    await renderResourcesTab([activeCalendar]);

    const codeInput = screen.getByLabelText("Code du nouveau nœud");
    fireEvent.change(codeInput, { target: { value: "IT" } });
    fireEvent.change(screen.getByLabelText("Nom du nouveau nœud"), { target: { value: "Informatique" } });
    const addRow = codeInput.closest("tr");
    if (!addRow) throw new Error("add row not found");
    fireEvent.click(within(addRow).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Opération impossible")).not.toBeInTheDocument();
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

    // The role-calendars table's own paginated fetch (see E8-06) resolves separately
    // from the reference lists driving the rest of the "Ressources" tab, so the
    // select isn't guaranteed to exist yet just because that tab is showing --
    // `findByLabelText` waits for it instead of asserting synchronously.
    const roleCalendarSelectLabel = `Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`;
    const select = await screen.findByLabelText(roleCalendarSelectLabel);
    fireEvent.change(select, { target: { value: String(otherCalendar.id) } });

    // The select keeps the same DOM identity across the draft-change re-render
    // (`columns` is memoized -- see `role-calendars-table.tsx`'s `RoleCalendarSelect`/
    // `columns` comments), so the original reference stays valid -- no need to
    // re-query it. CapacityTable renders an "Enregistrer" button per role too, so the
    // button lookup must stay scoped to this row.
    await waitFor(() => expect(select).toHaveValue(String(otherCalendar.id)));
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

    await waitFor(() => expect(screen.getByLabelText(roleCalendarSelectLabel)).toHaveValue(String(otherCalendar.id)));
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

  // Regression test for issue #138: every one of this page's data-loading
  // effects used to depend on `session` itself, whose *identity* changes on
  // every token rotation (see `onSessionRefresh` in page.tsx) -- not just on
  // a real login/logout transition. A token refresh firing while a mutation's
  // own request was still in flight therefore re-ran the calendars table's
  // own paginated-view effect too, starting a concurrent GET whose response
  // could land right after the mutation's optimistic patch and silently
  // overwrite it with pre-mutation data.
  it("does not let a concurrent token refresh during setDefaultCalendar's mutation overwrite the optimistic update it applies", async () => {
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

    // Captures the shared `onSessionRefresh` callback (the same stable
    // reference passed to every effect and mutation on this page) via
    // `getResourceRoles`, called once at mount -- same pattern used by the
    // users-table tests below. Rendered by hand here, rather than via the
    // `renderResourcesTab` helper, since that helper unconditionally
    // overwrites `getResourceRoles` with its own non-capturing mock.
    let onSessionRefresh: ((next: { accessToken: string }) => void) | null = null;
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, refresh: (next: { accessToken: string }) => void) => {
        onSessionRefresh ??= refresh;
        return Promise.resolve({ items: [], total: 0 });
      },
    );
    mocks.getCalendars.mockResolvedValue({ items: [previousDefault, candidate], total: 2 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(screen.getByText("OTHER")).toBeInTheDocument());
    if (!onSessionRefresh) throw new Error("onSessionRefresh was never captured");

    let resolveUpdate!: (calendar: Calendar) => void;
    mocks.updateCalendar.mockReturnValue(
      new Promise<Calendar>((resolve) => {
        resolveUpdate = resolve;
      }),
    );
    // Once `updateCalendar` resolves, `setDefaultCalendar` reloads the table's
    // own paginated page -- simulated here the same way as the sibling
    // "promotes a calendar as default..." test above.
    mocks.getCalendars.mockResolvedValue({ items: [{ ...previousDefault, is_default: false }, promoted], total: 2 });

    const otherRow = screen.getByText("OTHER").closest("tr");
    if (!otherRow) throw new Error("row not found");
    fireEvent.click(within(otherRow).getByRole("button", { name: "Définir par défaut" }));
    await waitFor(() => expect(mocks.updateCalendar).toHaveBeenCalledTimes(1));

    // A token rotation fires now, with `updateCalendar`'s own request still
    // pending. Before the #138 fix, this alone re-ran the calendars table's
    // paginated-view effect (it depended on `session`'s identity, not just its
    // presence) and started a concurrent GET.
    const getCalendarsCallsBeforeRefresh = mocks.getCalendars.mock.calls.length;
    act(() => onSessionRefresh!({ accessToken: "refreshed-token" }));
    expect(mocks.getCalendars.mock.calls.length).toBe(getCalendarsCallsBeforeRefresh);

    // `updateCalendar` now resolves: `setDefaultCalendar` applies its
    // optimistic patch, then triggers its own (legitimate) reload.
    resolveUpdate(promoted);

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
    mocks.getCalendars.mockResolvedValue({ items: [activeCalendar], total: 1 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

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
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

    render(<ResourcesPage />);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    expect(screen.getByText("Chargement impossible")).toBeInTheDocument();
    expect(
      screen.queryByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).not.toBeInTheDocument();
  });

  // Regression test for issue #138: this effect used to depend on `session`
  // itself, whose *identity* changes on every token rotation (see
  // `onSessionRefresh` in page.tsx) -- not just on a real login/logout
  // transition. A token refresh firing mid-request during the initial load
  // therefore re-ran this same effect for a second, full reload, which could
  // race an in-flight optimistic mutation elsewhere on the page and overwrite
  // its freshly-applied state. It no longer does: a token rotation alone must
  // not start a second reload of the initial data at all.
  it("does not start a second reload of the initial data when a session refresh fires mid-flight during the initial load", async () => {
    let onSessionRefresh: ((next: { accessToken: string }) => void) | null = null;
    let resolveNodes!: (nodes: ResourceNode[]) => void;
    const nodesPromise = new Promise<ResourceNode[]>((resolve) => {
      resolveNodes = resolve;
    });
    mocks.getResourceNodes.mockImplementation(() => nodesPromise);
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, refresh: (next: { accessToken: string }) => void) => {
        // Fires mid-flight, before the initial load's own `Promise.all` has
        // settled -- mirroring `authFetch` calling `onSessionRefresh` before a
        // retried request settles.
        onSessionRefresh ??= refresh;
        refresh({ accessToken: "refreshed-token" });
        return Promise.resolve({ items: [], total: 0 });
      },
    );
    mocks.getCalendars.mockResolvedValue({ items: [activeCalendar], total: 1 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

    render(<ResourcesPage />);

    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());
    if (!onSessionRefresh) throw new Error("onSessionRefresh was never captured");
    // The mid-flight session refresh above must not have started a second
    // initial load.
    expect(mocks.getResourceNodes).toHaveBeenCalledTimes(1);

    resolveNodes([]);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    // The warning still reflects the *one* successful load's data -- no
    // second, failing reload ever ran to flip it off.
    expect(
      screen.getByText("Aucun calendrier par défaut n'est défini. Désignez un calendrier par défaut dans l'onglet Ressources."),
    ).toBeInTheDocument();
    expect(mocks.getResourceNodes).toHaveBeenCalledTimes(1);
  });
});

describe("ResourcesPage reload race", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  // Regression test for issue #138: before the fix, a session refresh firing
  // mid-flight during the initial load re-ran that same effect (it depended on
  // `session`'s identity, not just its presence), starting a second, "more
  // recently triggered" reload -- exercised below as generation guard
  // (`loadGenerationRef`) coverage. It no longer does: a token rotation alone
  // must not start a redundant reload, so the single in-flight load's own
  // data is what ends up rendered once it resolves, whatever order its
  // `Promise.all` calls settle in.
  it("does not start a redundant reload when a session refresh fires mid-flight during the initial load, and renders the single in-flight load's own data", async () => {
    const genOneNode: ResourceNode = { id: 1, code: "GEN1", name: "Génération 1", parent_id: null } as never;

    let resolveNodes!: (nodes: ResourceNode[]) => void;
    const nodesPromise = new Promise<ResourceNode[]>((resolve) => {
      resolveNodes = resolve;
    });
    mocks.getResourceNodes.mockImplementation(() => nodesPromise);

    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, onSessionRefresh: (next: { accessToken: string }) => void) => {
        // Fires mid-flight, before the initial load's own `Promise.all` has
        // settled -- mirroring `authFetch` calling `onSessionRefresh` before a
        // retried request settles.
        onSessionRefresh({ accessToken: "refreshed-token" });
        return Promise.resolve({ items: [], total: 0 });
      },
    );

    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

    render(<ResourcesPage />);

    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalled());
    // The mid-flight session refresh above must not have started a second,
    // redundant call.
    expect(mocks.getResourceNodes).toHaveBeenCalledTimes(1);

    resolveNodes([genOneNode]);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(screen.getByText("GEN1")).toBeInTheDocument());

    // Still only ever called once, even after the single in-flight load settles.
    expect(mocks.getResourceNodes).toHaveBeenCalledTimes(1);
  });

  // Regression test for #227: the main grouped-load effect's catch guards on
  // `isCurrentGeneration()` (see `loadGenerationRef`'s comment in page.tsx -- kept
  // as defense in depth against, e.g., React StrictMode's double-invoke of this
  // effect, exercised directly here). Per issue #227, that guard must run *after*
  // the session-expiry check: a now-superseded generation's request that fails
  // precisely because the session expired must still force a logout, or the
  // session would never get invalidated once the user stops interacting.
  // StrictMode double-invokes the effect on mount, starting two overlapping
  // generations of the "loaded" branch; `getMe` is made to hang on the first
  // (soon-to-be-stale) call and resolve immediately on the second, so generation
  // 2 commits its data well before generation 1's own request is rejected below.
  it("still logs out when a StrictMode-superseded generation of the initial load fails with a post-refresh 401", async () => {
    let rejectFirstGetMe!: (cause: unknown) => void;
    let getMeCallCount = 0;
    mocks.getMe.mockImplementation(() => {
      getMeCallCount += 1;
      if (getMeCallCount === 1) {
        return new Promise((_resolve, reject) => {
          rejectFirstGetMe = reject;
        });
      }
      return Promise.resolve({ id: 999, email: "admin@example.com", is_active: true });
    });
    mocks.getResourceNodes.mockResolvedValue([]);
    mockGetResourceRoles([]);
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

    render(
      <StrictMode>
        <ResourcesPage />
      </StrictMode>,
    );

    // Generation 2 (the second, fresher double-invoked run) resolves and commits
    // successfully -- the loading indicator clears.
    await waitFor(() => expect(mocks.getMe).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    // The now-stale generation 1 fails afterward -- it must still force a
    // logout instead of being silently discarded.
    rejectFirstGetMe(new ApiError(401, "Unauthorized"));
    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.router.push).toHaveBeenCalledWith("/login");
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
    mocks.getResourceRoles.mockResolvedValue({ items: [roleFixture], total: 1 });
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
    // Scoped to the calendars card (not a bare role/name query): every other
    // paginated table on this same tab (roles, capacities, cost categories) has its
    // own "Suivant" button too.
    const card = (await screen.findByRole("heading", { name: "Calendriers de travail" })).closest(
      "[data-slot='card']",
    ) as HTMLElement;
    const suivant = within(card).getByRole("button", { name: "Suivant" });
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

describe("ResourcesPage valuation panel (E8-04)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [costTypeFixture({})], total: 1 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  function valuationCard() {
    return screen.getByRole("heading", { name: "Valorisation" }).closest("[data-slot='card']") as HTMLElement;
  }

  it("bulk-saves a rate entered on a page other than the one visible when Enregistrer is clicked, exercising the full labor-category set rather than just the visible page", async () => {
    // 21 labor categories: 20 fit on the ValuationPanel's first page (limit 20),
    // leaving exactly one -- "A21" -- on page 2. This is the concrete gap named by
    // the local review: `getLaborCategories`/`getValuationCategoryPage` and the
    // page-level bulk-save wiring were previously exercised only by
    // `valuation-panel.test.tsx`'s hand-constructed props, never by a real
    // multi-page scenario driven through `ResourcesPage` itself.
    const categories = Array.from({ length: 21 }, (_, index) => ({
      id: index + 1,
      accounting_code: `A${String(index + 1).padStart(2, "0")}`,
      category_code: null,
      name: `Catégorie ${index + 1}`,
      cost_type_id: 1,
      is_active: true,
    })) as never[];
    mocks.getCostCategories.mockResolvedValue({ items: categories, total: categories.length });
    mocks.createCostRate.mockResolvedValue({
      id: 100,
      cost_category_id: 21,
      year: new Date().getFullYear(),
      hourly_rate: "42.00",
      currency_code: "EUR",
    });

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    const card = valuationCard();
    expect(within(card).getByText("A01")).toBeInTheDocument();
    expect(within(card).queryByText("A21")).not.toBeInTheDocument();

    // Navigate to page 2, where category A21 lives, and enter a rate for it.
    fireEvent.click(within(card).getByRole("button", { name: "Suivant" }));
    await waitFor(() => expect(within(card).getByText("A21")).toBeInTheDocument());
    const year = new Date().getFullYear();
    fireEvent.change(within(card).getByLabelText(`A21 ${year}`), { target: { value: "42.00" } });

    // Navigate back to page 1 -- A21's row (and its draft) is no longer rendered --
    // then save from there.
    fireEvent.click(within(card).getByRole("button", { name: "Précédent" }));
    await waitFor(() => expect(within(card).getByText("A01")).toBeInTheDocument());
    expect(within(card).queryByText("A21")).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Enregistrer" }));

    await waitFor(() =>
      expect(mocks.createCostRate).toHaveBeenCalledWith(
        { cost_category_id: 21, year, hourly_rate: "42.00", currency_code: "EUR" },
        expect.anything(),
        expect.anything(),
      ),
    );
    // Only the one category with an actual draft value should have triggered a
    // save -- the other 20 labor categories were left blank.
    expect(mocks.createCostRate).toHaveBeenCalledTimes(1);
    expect(mocks.updateCostRate).not.toHaveBeenCalled();
  });

  it("only shows labor categories in the grid and filters them by accounting code/category code/name when searching", async () => {
    // A deliberate mix of labor ("MO") and non-labor ("FN") cost types/categories:
    // `getValuationCategoryPage`'s labor filter (`getLaborCategories`) must exclude
    // "A01-FN" from the grid entirely, in every render and every search result --
    // not merely absent from the *default*, unfiltered view.
    mocks.getCostTypes.mockResolvedValue({
      items: [costTypeFixture({ id: 1, code: "MO", kind: "labor" }), costTypeFixture({ id: 2, code: "FN", name: "Fourniture", kind: "supply" })],
      total: 2,
    });
    mocks.getCostCategories.mockResolvedValue({
      items: [
        { id: 1, accounting_code: "B02-MO", category_code: null, name: "Beta", cost_type_id: 1, is_active: true },
        { id: 2, accounting_code: "A01-FN", category_code: null, name: "Alpha", cost_type_id: 2, is_active: true },
        { id: 3, accounting_code: "C03-MO", category_code: null, name: "Charlie", cost_type_id: 1, is_active: true },
      ] as never[],
      total: 3,
    });

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    const card = valuationCard();
    expect(within(card).getByText("B02-MO")).toBeInTheDocument();
    expect(within(card).getByText("C03-MO")).toBeInTheDocument();
    expect(within(card).queryByText("A01-FN")).not.toBeInTheDocument();

    fireEvent.change(within(card).getByLabelText("Rechercher une catégorie"), { target: { value: "C03" } });

    await waitFor(() => expect(within(card).queryByText("B02-MO")).not.toBeInTheDocument());
    expect(within(card).getByText("C03-MO")).toBeInTheDocument();
    expect(within(card).queryByText("A01-FN")).not.toBeInTheDocument();
  });

  it("sorts the grid ascending then descending by accounting code when the Code comptable header is clicked", async () => {
    mocks.getCostCategories.mockResolvedValue({
      items: [
        { id: 1, accounting_code: "C-003", category_code: null, name: "Charlie", cost_type_id: 1, is_active: true },
        { id: 2, accounting_code: "A-001", category_code: null, name: "Alpha", cost_type_id: 1, is_active: true },
        { id: 3, accounting_code: "B-002", category_code: null, name: "Bravo", cost_type_id: 1, is_active: true },
      ] as never[],
      total: 3,
    });

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    const card = valuationCard();
    await waitFor(() => expect(within(card).getByText("A-001")).toBeInTheDocument());

    function accountingCodeOrder() {
      return within(card)
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("cell")[0].textContent);
    }

    fireEvent.click(within(card).getByRole("button", { name: "Code comptable" }));
    await waitFor(() => expect(accountingCodeOrder()).toEqual(["A-001", "B-002", "C-003"]));

    fireEvent.click(within(card).getByRole("button", { name: "Code comptable" }));
    await waitFor(() => expect(accountingCodeOrder()).toEqual(["C-003", "B-002", "A-001"]));
  });
});

describe("ResourcesPage cost types table (E8-02)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });
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
    // Scoped to the cost-types table's own card: the cost-categories table (E8-03)
    // and the ValuationPanel grid (E8-04) each render their own, independently
    // labeled "Suivant" button on the same tab.
    const costTypesCard = (await screen.findByRole("heading", { name: "Types de coût" })).closest(
      "[data-slot='card']",
    ) as HTMLElement;
    const suivant = within(costTypesCard).getByRole("button", { name: "Suivant" });
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

async function renderRoleCalendarsTab() {
  mocks.getResourceNodes.mockResolvedValue([nodeFixture]);
  mocks.getCalendars.mockResolvedValue({ items: [activeCalendar], total: 1 });
  mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
  mocks.getCostRates.mockResolvedValue([]);
  mocks.getInflationRates.mockResolvedValue([]);
  mocks.getRoleCapacities.mockResolvedValue([]);
  mocks.getUsers.mockResolvedValue({ items: [], total: 0 });

  render(<ResourcesPage />);
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
}

// RolesPanel and CapacityTable are mounted on the same "Ressources" tab and share
// this table's "Rôle"/"Suivant"/"Rechercher un rôle" labels, so every ambiguous
// query in this describe block is scoped to this table's own <Card> via its
// unique heading.
function roleCalendarsCard(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Calendriers des rôles" });
  const card = heading.closest('[data-slot="card"]');
  if (!card) throw new Error("role calendars card not found");
  return card as HTMLElement;
}

describe("ResourcesPage role calendars table (E8-06)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("requests the table's own paginated page independently from the unpaginated reference list other panels rely on, without either leaking into the other", async () => {
    // Genuinely different role sets for the two call shapes, so this test catches a
    // wiring mistake by which roles show up where, not just by which params
    // getResourceRoles was called with.
    const fullList = [roleFixture];
    const pagedRole: ResourceRole = { ...roleFixture, id: 99, name: "Page role" } as never;
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        if (listParams === undefined) return Promise.resolve({ items: fullList, total: fullList.length });
        // RolesPanel's own node-scoped call (the sole node auto-selects on mount)
        // and CapacityTable's own unpaginated-reference-adjacent call must not be
        // confused with this table's own paginated page.
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [pagedRole], total: 25 });
      },
    );

    await renderRoleCalendarsTab();
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

    const calls = mocks.getResourceRoles.mock.calls as [unknown, unknown, unknown, unknown, unknown][];
    expect(calls.some(([, , , , listParams]) => listParams === undefined)).toBe(true);
    expect(
      calls.some(
        ([, , , , listParams]) =>
          typeof listParams === "object" &&
          listParams !== null &&
          (listParams as { limit?: number }).limit === 20 &&
          (listParams as { offset?: number }).offset === 0,
      ),
    ).toBe(true);

    // The role-calendars table itself shows only its own paginated slice, not the
    // full reference list -- checked via each role's calendar-select label rather
    // than plain text, since CapacityTable renders the exact same
    // "name — node (#id)" label format from the full reference list and would
    // otherwise make an ordinary text query ambiguous.
    await waitFor(() =>
      expect(
        screen.getByLabelText(`Calendrier de ${pagedRole.name} — ${nodeFixture.code} (#${pagedRole.id})`),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByLabelText(`Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`),
    ).not.toBeInTheDocument();
  });

  it("paginates: clicking Suivant refetches the table with the next offset", async () => {
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [roleFixture], total: 25 });
      },
    );

    await renderRoleCalendarsTab();
    const roleCalendarsSuivant = await within(roleCalendarsCard()).findByRole("button", { name: "Suivant" });
    await waitFor(() => expect(roleCalendarsSuivant).toBeEnabled());

    fireEvent.click(roleCalendarsSuivant);

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        undefined,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });

  it("searches: typing in the role-calendars search box debounces then refetches with q, resetting to offset 0", async () => {
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [roleFixture], total: 1 });
      },
    );

    await renderRoleCalendarsTab();
    const searchInput = await within(roleCalendarsCard()).findByLabelText("Rechercher un rôle");

    fireEvent.change(searchInput, { target: { value: "dev" } });

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        undefined,
        expect.objectContaining({ q: "dev", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Rôle column header refetches with sort=name", async () => {
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [roleFixture], total: 1 });
      },
    );

    await renderRoleCalendarsTab();
    // CapacityTable renders an identically-labeled sortable "Rôle" column header
    // of its own, so this query must stay scoped to this table's own <Card>.
    const roleHeaderButton = await within(roleCalendarsCard()).findByRole("button", { name: "Rôle" });

    fireEvent.click(roleHeaderButton);

    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        undefined,
        expect.objectContaining({ sort: "name" }),
      ),
    );
  });

  it("refetches the role-calendars page after saving a role's calendar, on top of the existing local roles update", async () => {
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, includeDescendants: unknown) => {
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [roleFixture], total: 1 });
      },
    );
    mocks.updateResourceRole.mockResolvedValue({ ...roleFixture, calendar_id: activeCalendar.id } as never);

    await renderRoleCalendarsTab();
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

    const roleCalendarSelectLabel = `Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`;
    const select = await screen.findByLabelText(roleCalendarSelectLabel);
    fireEvent.change(select, { target: { value: String(activeCalendar.id) } });

    // The select keeps the same DOM identity across the draft-change re-render
    // (see `role-calendars-table.tsx`'s `RoleCalendarSelect`/`columns` comments),
    // so the original reference stays valid -- no need to re-query it.
    // CapacityTable renders an "Enregistrer" button per role too, so the button
    // lookup must stay scoped to this row rather than the page as a whole.
    await waitFor(() => expect(select).toHaveValue(String(activeCalendar.id)));
    fireEvent.click(within(select.closest("tr")!).getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(mocks.updateResourceRole).toHaveBeenCalledTimes(1));
    // The initial load made 4 calls (reference list + this table's own page +
    // CapacityTable's/RolesPanel's own, sharing the same mock); saving a role's
    // calendar must trigger a 5th, to refresh this table's own paginated view.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(5));
  });

  it("redirects to login when the role-calendars table's own paginated fetch reports session expiry", async () => {
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        return Promise.reject(new SessionExpiredError());
      },
    );

    await renderRoleCalendarsTab();

    await waitFor(() => expect(mocks.router.push).toHaveBeenCalledWith("/login"));
  });

  it("does not leave the role-calendars table's loading indicator stuck when a newer pagination fetch resolves before an older, obsolete one", async () => {
    // Unlike the cost-types table (which has an always-visible pinned create row to
    // drive a race from), every interactive element in this table lives inside the
    // same loading-gated body as its data -- so the generation guard is exercised
    // here directly through two overlapping pagination fetches instead of through a
    // mutation's own reload, but it's the same "stale finally must not stomp a
    // fresher generation's loading flag" bug class as `reloadCostTypesPage`'s.
    let resolveFirstPage!: (page: { items: ResourceRole[]; total: number }) => void;
    const firstPagePromise = new Promise<{ items: ResourceRole[]; total: number }>((resolve) => {
      resolveFirstPage = resolve;
    });
    let paginatedCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        if (listParams === undefined) return Promise.resolve({ items: [roleFixture], total: 1 });
        // CapacityTable's and RolesPanel's own calls share this mock but must not
        // be counted as this table's own paginated fetch below.
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        paginatedCallCount += 1;
        // First paginated call: the initial mount fetch. Kept pending on purpose,
        // simulating an older reload that resolves after a newer one triggered
        // below.
        if (paginatedCallCount === 1) return firstPagePromise;
        return Promise.resolve({ items: [roleFixture], total: 1 });
      },
    );

    await renderRoleCalendarsTab();
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));
    await waitFor(() =>
      expect(within(roleCalendarsCard()).getByRole("status", { name: "Chargement des données" })).toBeInTheDocument(),
    );

    // Triggers a second, more recent pagination fetch while the first is still
    // in-flight -- resolves immediately, well before the first is released below.
    const searchInput = await within(roleCalendarsCard()).findByLabelText("Rechercher un rôle");
    fireEvent.change(searchInput, { target: { value: "dev" } });

    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(5));
    // The newer fetch resolving must clear the loading state on its own -- it must
    // not wait for the stale first call.
    await waitFor(() =>
      expect(within(roleCalendarsCard()).queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument(),
    );

    // Releasing the stale initial fetch afterwards must not resurrect the loading
    // state or overwrite the fresher data already committed.
    resolveFirstPage({ items: [], total: 0 });
    await waitFor(() =>
      expect(
        screen.getByLabelText(`Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("status", { name: "Chargement des données" })).not.toBeInTheDocument();
  });

  it("freezes role-calendars pagination while a role's calendar save is in flight (E8-192), then applies the current offset -- not a stale one -- once it's re-enabled", async () => {
    // The pagination effect and `reloadRoleCalendarsPage` share one mock
    // implementation, so responses are distinguished by which offset they were
    // actually called with rather than by call order. `currentCalendarId` lets
    // the mock reflect the save's effect on a reload, the way a real backend
    // would -- needed to observe the freeze (E8-192, `hasUnsavedDraft` in
    // `role-calendars-table.tsx`) actually lift once the draft matches what
    // comes back from the reload it triggers.
    let currentCalendarId: number | null = roleFixture.calendar_id ?? null;
    const pageAtOffset20: ResourceRole[] = [{ ...roleFixture, id: 77, name: "Page 2 role" } as never];
    mocks.getResourceRoles.mockImplementation(
      (
        _tokens: unknown,
        _refresh: unknown,
        nodeId: unknown,
        includeDescendants: unknown,
        listParams: unknown,
      ) => {
        const roleAtOffset0 = { ...roleFixture, calendar_id: currentCalendarId };
        if (listParams === undefined) return Promise.resolve({ items: [roleAtOffset0], total: 1 });
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        const offset = (listParams as { offset?: number }).offset ?? 0;
        return Promise.resolve({
          items: offset === 0 ? [roleAtOffset0] : pageAtOffset20,
          total: 25,
        });
      },
    );
    let resolveUpdate!: (role: ResourceRole) => void;
    mocks.updateResourceRole.mockReturnValue(
      new Promise<ResourceRole>((resolve) => {
        resolveUpdate = resolve;
      }),
    );

    await renderRoleCalendarsTab();
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

    const roleCalendarSelectLabel = `Calendrier de ${roleFixture.name} — ${nodeFixture.code} (#${roleFixture.id})`;
    const select = await screen.findByLabelText(roleCalendarSelectLabel);
    fireEvent.change(select, { target: { value: String(activeCalendar.id) } });
    fireEvent.click(within(select.closest("tr")!).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(mocks.updateResourceRole).toHaveBeenCalledTimes(1));

    // While the save is in flight, the role's draft (the newly picked calendar)
    // still differs from what the currently-visible page shows as saved (the
    // reload the save triggers hasn't landed yet) -- E8-192's freeze applies,
    // so pagination is blocked, unlike before that feature existed (this test
    // used to paginate away here and rely on `roleCalendarsOffsetRef` to avoid
    // applying that stale offset once the save resolved). A disabled "Suivant"
    // button ignores a click in the browser, and jsdom mirrors that.
    const roleCalendarsSuivant = within(roleCalendarsCard()).getByRole("button", { name: "Suivant" });
    expect(roleCalendarsSuivant).toBeDisabled();
    fireEvent.click(roleCalendarsSuivant);
    expect(screen.getByLabelText(roleCalendarSelectLabel)).toBeInTheDocument();

    // Resolving the save updates what a reload reports as saved; the reload
    // itself uses `roleCalendarsOffsetRef`'s *current* offset (still 0, since
    // pagination was frozen throughout -- the very race that ref exists to
    // guard against can no longer occur through the UI now that E8-192 blocks
    // navigation until the draft and the reload agree).
    currentCalendarId = activeCalendar.id;
    resolveUpdate({ ...roleFixture, calendar_id: activeCalendar.id } as never);
    await waitFor(() => expect(roleCalendarsSuivant).toBeEnabled());
    expect(mocks.getResourceRoles).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      undefined,
      undefined,
      expect.objectContaining({ offset: 0 }),
    );

    // Now that the freeze has lifted, pagination proceeds normally.
    fireEvent.click(roleCalendarsSuivant);
    await waitFor(() =>
      expect(mocks.getResourceRoles).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        undefined,
        undefined,
        expect.objectContaining({ offset: 20 }),
      ),
    );
    expect(
      screen.getByLabelText(`Calendrier de Page 2 role — ${nodeFixture.code} (#77)`),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(roleCalendarSelectLabel)).not.toBeInTheDocument();
  });

  it("refetches the role-calendars page after creating a role via the roles panel, on top of the existing local roles update", async () => {
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
    const newRole: ResourceRole = { ...roleFixture, id: 55, name: "Nouveau rôle" } as never;
    mocks.getResourceNodes.mockResolvedValue([nodeFixture]);
    mocks.getCalendars.mockResolvedValue({ items: [activeCalendar], total: 1 });
    mocks.getCostTypes.mockResolvedValue({ items: [laborCostType], total: 1 });
    mocks.getCostCategories.mockResolvedValue({ items: [category], total: 1 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });
    let roleCalendarsCallCount = 0;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId !== undefined || includeDescendants === false) return Promise.resolve({ items: [], total: 0 });
        roleCalendarsCallCount += 1;
        // First (initial-mount) call: empty. Second (post-creation reload) call:
        // the newly created role now shows up.
        return Promise.resolve(roleCalendarsCallCount === 1 ? { items: [], total: 0 } : { items: [newRole], total: 1 });
      },
    );
    mocks.createResourceRole.mockResolvedValue(newRole);

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: newRole.name } });
    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: String(nodeFixture.id) } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "5" } });
    const rolesForm = nameInput.closest("form");
    if (!rolesForm) throw new Error("roles form not found");
    fireEvent.click(within(rolesForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // Without `addRole` also calling `reloadRoleCalendarsPage`, this table would
    // keep showing its stale (empty) page indefinitely, even though the role was
    // successfully created.
    await waitFor(() =>
      expect(
        within(roleCalendarsCard()).getByLabelText(`Calendrier de ${newRole.name} — ${nodeFixture.code} (#${newRole.id})`),
      ).toBeInTheDocument(),
    );
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
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
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
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });
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
        // CapacityTable's/RoleCalendarsTable's own (unscoped) paginated calls --
        // not under test here, given the same reference item so their rendering
        // can't be mistaken for the panel's own node-scoped slice below.
        if (nodeId === undefined) return Promise.resolve({ items: fullList, total: fullList.length });
        return Promise.resolve({ items: paginatedSlice, total: 25 });
      },
    );

    await openRessourcesTab();
    // 4, not 2: the reference list, the panel's own node-scoped page, and
    // CapacityTable's/RoleCalendarsTable's own (unscoped) paginated pages --
    // also mounted on the same "Ressources" tab and also calling
    // `getResourceRoles`.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

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
    // Scoped to RolesPanel's own card: CalendarsTable, on the same tab, also has its
    // own sortable "Nom" column (rendered as a button too), so an unscoped query
    // would be ambiguous.
    const sortButton = await within(rolesPanelCard()).findByRole("button", { name: "Nom" });

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
    // 4, not 2: the reference list, the panel's own page, and
    // CapacityTable's/RoleCalendarsTable's own paginated pages -- also mounted
    // on the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Nœud"), { target: { value: String(nodeA.id) } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "200" } });
    const roleForm = nameInput.closest("form");
    if (!roleForm) throw new Error("role create form not found");
    fireEvent.click(within(roleForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The initial load made 4 calls; creating a role triggers its own panel
    // reload plus CapacityTable's and RoleCalendarsTable's reloads (addRole
    // calls all three), for 7 total.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(7));
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
    // 4, not 2: the reference list, the panel's own page, and
    // CapacityTable's/RoleCalendarsTable's own paginated pages -- also mounted
    // on the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));
    // Scoped to RolesPanel's own card: CapacityTable/RoleCalendarsTable show the
    // same role="status" skeleton while their own (harmless, already-resolved)
    // fetches are briefly in flight.
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
    // 4, not 2: the reference list, the panel's own page, and
    // CapacityTable's/RoleCalendarsTable's own paginated pages -- also mounted
    // on the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));
    // Scoped to RolesPanel's own card: CapacityTable/RoleCalendarsTable show the
    // same role="status" skeleton while their own (harmless, already-resolved)
    // fetches are briefly in flight.
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
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });
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
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: fullList, total: fullList.length });
        // RolesPanel's own node-scoped call and RoleCalendarsTable's own
        // unscoped call -- not under test here, kept out of this table's
        // rendering so they can't collide with the assertions below.
        if (nodeId !== undefined || includeDescendants === undefined) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: paginatedSlice, total: 25 });
      },
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // 4, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's/RoleCalendarsTable's own paginated pages -- also mounted on
    // the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

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
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        if (nodeId !== undefined || includeDescendants === undefined) return Promise.resolve({ items: [], total: 0 });
        return Promise.resolve({ items: [resourceRoleFixture({})], total: 25 });
      },
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    const capacitySuivant = await within(capacityCard()).findByRole("button", { name: "Suivant" });
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
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.createResourceRole.mockResolvedValue(resourceRoleFixture({ id: 9, name: "Nouveau rôle" }));

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    // 4, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's/RoleCalendarsTable's own paginated pages -- also mounted on
    // the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

    const nameInput = screen.getByLabelText("Nom");
    fireEvent.change(nameInput, { target: { value: "Nouveau rôle" } });
    fireEvent.change(screen.getByLabelText("Code comptable"), { target: { value: "5" } });
    const rolesForm = nameInput.closest("form");
    if (!rolesForm) throw new Error("roles form not found");
    fireEvent.click(within(rolesForm).getByRole("button", { name: "Ajouter" }));

    await waitFor(() => expect(mocks.createResourceRole).toHaveBeenCalledTimes(1));
    // The initial load made 4 calls; creating a role triggers RolesPanel's own
    // reload plus the capacity table's and RoleCalendarsTable's reloads (addRole
    // calls all three), for 7 total.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(7));
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

  it("freezes the capacity table's pagination while a visible role's capacity draft differs from its saved value, then re-enables it once saved (E8-192)", async () => {
    const role = resourceRoleFixture({ id: 42, name: "Avec capacité" });
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, _refresh: unknown, _nodeId: unknown, _includeDescendants: unknown, listParams: unknown) =>
        Promise.resolve(listParams === undefined ? { items: [role], total: 1 } : { items: [role], total: 25 }),
    );
    mocks.getRoleCapacities.mockResolvedValue([
      { id: 10, role_id: 42, person_count: "2.00", available_hours: "1600.00" } as never,
    ]);
    let resolveUpdate!: (capacity: RoleCapacity) => void;
    mocks.updateRoleCapacity.mockReturnValue(
      new Promise<RoleCapacity>((resolve) => {
        resolveUpdate = resolve;
      }),
    );

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));
    await waitFor(() => expect(within(capacityCard()).getByText("Avec capacité — IT (#42)")).toBeInTheDocument());

    const suivant = within(capacityCard()).getByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());

    // Typing a value that differs from the saved capacity (fed here through
    // `savedByRoleId`, wired up in `resources/page.tsx` from `capacities`)
    // freezes pagination -- exercises the real wiring, not just the
    // presentational component in isolation (see `capacity-table.test.tsx`).
    const personCountInput = within(capacityCard()).getByLabelText("Nombre de personnes pour Avec capacité — IT (#42)");
    fireEvent.change(personCountInput, { target: { value: "3.00" } });
    expect(suivant).toBeDisabled();

    fireEvent.click(within(capacityCard()).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(mocks.updateRoleCapacity).toHaveBeenCalledTimes(1));
    // Still frozen: the save is in flight, so `capacities`/`savedByRoleId`
    // hasn't been updated to reflect it yet.
    expect(suivant).toBeDisabled();

    resolveUpdate({ id: 10, role_id: 42, person_count: "3.00", available_hours: "1600.00" } as never);
    await waitFor(() => expect(suivant).toBeEnabled());
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
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        // RolesPanel's own node-scoped call and RoleCalendarsTable's own
        // unscoped call -- not under test here, kept out of the
        // capacity-table-specific counter below.
        if (nodeId !== undefined || includeDescendants === undefined) return Promise.resolve({ items: [], total: 0 });
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
    // 4, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's/RoleCalendarsTable's own paginated pages -- also mounted on
    // the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));

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
      (_tokens: unknown, _refresh: unknown, nodeId: unknown, includeDescendants: unknown, listParams: unknown) => {
        if (listParams === undefined) return Promise.resolve({ items: [], total: 0 });
        // RolesPanel's own node-scoped call and RoleCalendarsTable's own
        // unscoped call -- not under test here, kept out of the
        // capacity-table-specific counter below.
        if (nodeId !== undefined || includeDescendants === undefined) return Promise.resolve({ items: [], total: 0 });
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
    // 4, not 2: the reference list, the capacity table's own page, and
    // RolesPanel's/RoleCalendarsTable's own paginated pages -- also mounted on
    // the same "Ressources" tab.
    await waitFor(() => expect(mocks.getResourceRoles).toHaveBeenCalledTimes(4));
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
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    // Deliberately "supply", not "labor": ValuationPanel (also mounted on the "costs"
    // tab) filters the full `categories` reference list down to labor-linked
    // categories only. Keeping the fixture cost type non-labor means the full-list
    // fixtures below never leak into ValuationPanel's own rendering, which would
    // otherwise collide with this describe block's own text/role assertions.
    mocks.getCostTypes.mockResolvedValue({ items: [costTypeFixture({ kind: "supply" })], total: 1 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });
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
    // Both the cost-categories table's own "Code comptable" header and
    // ValuationPanel's (also mounted on the "costs" tab, both now DataTable-backed
    // sortable columns as of E8-04) render a <Button> with this name, so this must
    // be scoped to the cost-categories table's own <form> -- same scoping used by
    // the "paginates" test above for its "Suivant" button.
    const categoriesTable = (await screen.findByLabelText("Rechercher une catégorie de coût")).closest(
      "form",
    ) as HTMLElement;
    const sortButton = within(categoriesTable).getByRole("button", { name: "Code comptable" });

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

const userFixture = (overrides: Partial<AuthUserAdmin> = {}): AuthUserAdmin =>
  ({
    id: 1,
    email: "alice@example.com",
    is_active: true,
    is_admin: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as AuthUserAdmin;

describe("ResourcesPage users table (E8-09)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getResourceNodes.mockResolvedValue([]);
    mocks.getResourceRoles.mockResolvedValue({ items: [], total: 0 });
    mocks.getCalendars.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostTypes.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostCategories.mockResolvedValue({ items: [], total: 0 });
    mocks.getCostRates.mockResolvedValue([]);
    mocks.getInflationRates.mockResolvedValue([]);
    mocks.getRoleCapacities.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  async function openUsersTab() {
    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Utilisateurs" }));
  }

  it("requests the users tab's own paginated page with an explicit page size", async () => {
    mocks.getUsers.mockResolvedValue({ items: [userFixture({})], total: 1 });
    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());
    expect(mocks.getUsers).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      expect.objectContaining({ limit: 20, offset: 0 }),
    );
  });

  it("paginates: clicking Suivant refetches the users table with the next offset", async () => {
    mocks.getUsers.mockResolvedValue({ items: [userFixture({})], total: 25 });
    await openUsersTab();
    const suivant = await screen.findByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());

    fireEvent.click(suivant);

    await waitFor(() =>
      expect(mocks.getUsers).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });

  it("searches: typing in the users search box debounces then refetches with q, resetting to offset 0", async () => {
    mocks.getUsers.mockResolvedValue({ items: [userFixture({})], total: 1 });
    await openUsersTab();
    const searchInput = await screen.findByLabelText("Rechercher un utilisateur");

    fireEvent.change(searchInput, { target: { value: "alice" } });

    await waitFor(() =>
      expect(mocks.getUsers).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        expect.objectContaining({ q: "alice", offset: 0 }),
      ),
    );
  });

  it("sorts: clicking the Email column header refetches with sort=email", async () => {
    mocks.getUsers.mockResolvedValue({ items: [userFixture({})], total: 1 });
    await openUsersTab();
    await screen.findByRole("columnheader", { name: "Email" });

    fireEvent.click(screen.getByRole("button", { name: "Email" }));

    await waitFor(() =>
      expect(mocks.getUsers).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        expect.objectContaining({ sort: "email" }),
      ),
    );
  });

  it("keeps the create-user button accessible regardless of which users page is displayed", async () => {
    mocks.getUsers.mockResolvedValue({ items: [userFixture({})], total: 25 });
    await openUsersTab();
    const suivant = await screen.findByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());

    fireEvent.click(suivant);

    await waitFor(() => expect(mocks.getUsers).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Ajouter un utilisateur" })).toBeInTheDocument();
  });

  it("preserves the existing error display when the users list is unreachable", async () => {
    mocks.getUsers.mockRejectedValue(new ApiError(500, "Liste des utilisateurs indisponible."));
    await openUsersTab();

    await waitFor(() => expect(screen.getByText("Liste des utilisateurs indisponible.")).toBeInTheDocument());
  });

  it("freezes pagination and search while a destructive confirmation is open for a user", async () => {
    mocks.getUsers.mockResolvedValue({ items: [userFixture({})], total: 25 });
    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    await screen.findByRole("alertdialog");

    // The background content is marked `aria-hidden` (assistive tech only) and
    // sits under the alert dialog's full-viewport backdrop, which blocks pointer
    // input but does not make the DOM `inert` -- `{ hidden: true }` is needed
    // here purely to still be able to query past `aria-hidden` for the
    // assertion below. `isEditing`'s own `disabled` attribute (applied
    // synchronously in the same render that opens the dialog, before the
    // backdrop/aria-hidden marking even paints) is the guard this assertion
    // actually verifies, not a redundant defense-in-depth layer on top of
    // something already inert.
    expect(screen.getByLabelText("Rechercher un utilisateur")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant", hidden: true })).toBeDisabled();
  });

  // Regression tests for issue #138. Before the fix, a session-token refresh
  // was the one thing on this page that could trigger a background refetch of
  // the users list without any user interaction (every control that could
  // otherwise do so -- search, sort, pagination, and even "Ajouter un
  // utilisateur" behind the modal overlay -- is unreachable for as long as a
  // confirmation dialog is open, per the "freezes pagination and search..."
  // test above). Since `session`'s identity (a token rotation) no longer
  // re-runs this effect -- only a genuine presence transition does, see
  // `hasSession` in page.tsx -- there is now no trigger left at all that
  // could refetch this list while a confirmation dialog is open: the dialog's
  // captured target user and the underlying table can no longer drift apart
  // during that window.
  it("does not refetch the users list, and still targets the originally selected user's status update, when a session refresh fires while the confirmation is open", async () => {
    const userA = userFixture({ id: 1, email: "alice@example.com", is_active: true });
    const userB = userFixture({ id: 2, email: "bob@example.com", is_active: true });

    let onSessionRefresh: ((next: { accessToken: string }) => void) | null = null;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, refresh: (next: { accessToken: string }) => void) => {
        onSessionRefresh ??= refresh;
        return Promise.resolve({ items: [], total: 0 });
      },
    );
    mocks.getUsers.mockResolvedValue({ items: [userA, userB], total: 2 });
    mocks.setUserStatus.mockResolvedValue({ ...userA, is_active: false });

    render(<ResourcesPage />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("tab", { name: "Utilisateurs" }));
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());

    // Open the confirmation for Alice specifically.
    const aliceRow = screen.getByText("alice@example.com").closest("tr");
    if (!aliceRow) throw new Error("row not found");
    fireEvent.click(within(aliceRow).getByRole("button", { name: "Désactiver" }));
    const alertDialog = await screen.findByRole("alertdialog");
    expect(within(alertDialog).getByText(/alice@example.com sera désactivé/)).toBeInTheDocument();

    // Fire the session refresh now, with the dialog already open.
    const getUsersCallsBeforeRefresh = mocks.getUsers.mock.calls.length;
    if (!onSessionRefresh) throw new Error("onSessionRefresh was never captured");
    act(() => onSessionRefresh!({ accessToken: "refreshed-token" }));

    // No refetch happens: the list, and Alice's row in it, are untouched.
    expect(mocks.getUsers.mock.calls.length).toBe(getUsersCallsBeforeRefresh);
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Désactiver" }));

    await waitFor(() =>
      expect(mocks.setUserStatus).toHaveBeenCalledExactlyOnceWith(1, false, expect.anything(), expect.anything()),
    );
  });

  it("does not refetch the users list, and still targets the originally selected user's deletion, when a session refresh fires while the confirmation is open", async () => {
    const userA = userFixture({ id: 1, email: "alice@example.com" });
    const userB = userFixture({ id: 2, email: "bob@example.com" });

    let onSessionRefresh: ((next: { accessToken: string }) => void) | null = null;
    mocks.getResourceRoles.mockImplementation(
      (_tokens: unknown, refresh: (next: { accessToken: string }) => void) => {
        onSessionRefresh ??= refresh;
        return Promise.resolve({ items: [], total: 0 });
      },
    );
    mocks.getUsers.mockResolvedValue({ items: [userA, userB], total: 2 });
    mocks.deleteUser.mockResolvedValue(undefined);

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("bob@example.com")).toBeInTheDocument());

    // Open the deletion confirmation for Bob, the second row.
    const bobRow = screen.getByText("bob@example.com").closest("tr");
    if (!bobRow) throw new Error("row not found");
    fireEvent.click(within(bobRow).getByRole("button", { name: "Supprimer" }));
    const alertDialog = await screen.findByRole("alertdialog");
    expect(within(alertDialog).getByText(/bob@example.com/)).toBeInTheDocument();

    // Fire the session refresh now, with the dialog already open.
    const getUsersCallsBeforeRefresh = mocks.getUsers.mock.calls.length;
    if (!onSessionRefresh) throw new Error("onSessionRefresh was never captured");
    act(() => onSessionRefresh!({ accessToken: "refreshed-token" }));

    // No refetch happens: the list is untouched.
    expect(mocks.getUsers.mock.calls.length).toBe(getUsersCallsBeforeRefresh);
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();

    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(mocks.deleteUser).toHaveBeenCalledExactlyOnceWith(2, expect.anything(), expect.anything()));
  });

  it("surfaces feedback when a user action succeeds but the follow-up list refresh fails, instead of leaving the page silently stale", async () => {
    // Unlike cost types (where `costTypes` is patched locally and other panels
    // keep working off it even if the table's own paginated reload fails), users
    // has no such local copy: `usersPage` is the only source of truth, and none
    // of the mutation handlers show their own success notice. Silently
    // swallowing a reload failure here would leave the user with *no* feedback
    // at all -- the deletion succeeded server-side, but the row would just
    // never disappear, indistinguishable from the deletion having silently
    // failed.
    const userA = userFixture({ id: 1, email: "alice@example.com" });
    mocks.getUsers.mockResolvedValueOnce({ items: [userA], total: 1 });
    mocks.getUsers.mockRejectedValueOnce(new ApiError(500, "Actualisation impossible"));
    mocks.deleteUser.mockResolvedValue(undefined);

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(mocks.deleteUser).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.getByText("L'action a réussi, mais l'actualisation de la liste a échoué. Rechargez la page pour la voir à jour."),
      ).toBeInTheDocument(),
    );
  });

  it("does not apply a stale offset/sort/search to the reload triggered by a user status update, if the admin navigated away while the update was in flight", async () => {
    // Unlike the destructive-confirmation window (guarded by `isActionPending`,
    // which freezes pagination/search while the alert dialog is open),
    // `confirmPendingUserAction` clears `pendingUserAction` synchronously on
    // confirm -- the dialog closes, and the table becomes interactive again,
    // well before `setUserStatus`'s own request (and the `reloadUsersPage` it
    // triggers) resolve. Responses are distinguished by which offset they were
    // actually requested with, not by call order.
    const userA = userFixture({ id: 1, email: "alice@example.com", is_active: true });
    const pageAtOffset20 = [userFixture({ id: 2, email: "page2@example.com" })];
    mocks.getUsers.mockImplementation((_tokens: unknown, _refresh: unknown, listParams: unknown) => {
      const offset = (listParams as { offset?: number } | undefined)?.offset ?? 0;
      return Promise.resolve({ items: offset === 0 ? [userA] : pageAtOffset20, total: 25 });
    });
    let resolveStatus!: (user: AuthUserAdmin) => void;
    mocks.setUserStatus.mockReturnValue(
      new Promise<AuthUserAdmin>((resolve) => {
        resolveStatus = resolve;
      }),
    );

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Désactiver" }));
    await waitFor(() => expect(mocks.setUserStatus).toHaveBeenCalledTimes(1));

    // Paginate to offset 20 while the status update is still in flight -- the
    // confirmation dialog is already gone by this point, so nothing here blocks
    // this navigation.
    const suivant = await screen.findByRole("button", { name: "Suivant" });
    await waitFor(() => expect(suivant).toBeEnabled());
    fireEvent.click(suivant);
    await waitFor(() => expect(screen.getByText("page2@example.com")).toBeInTheDocument());

    // Resolving the status update now must not refetch/display offset 0's stale
    // page: the reload it triggers must target the *current* offset (20) -- the
    // one the admin navigated to -- not the offset that was current when
    // "Désactiver" was confirmed.
    resolveStatus({ ...userA, is_active: false });
    await waitFor(() =>
      expect(mocks.getUsers).toHaveBeenLastCalledWith(
        expect.anything(),
        expect.anything(),
        expect.objectContaining({ offset: 20 }),
      ),
    );
    expect(screen.getByText("page2@example.com")).toBeInTheDocument();
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument();
  });

  it("still logs out on a stale reload's session expiry, even once a newer generation has already reloaded successfully", async () => {
    // Simulates: `deleteExistingUser` triggers `reloadUsersPage` (generation N),
    // then -- before that request resolves -- the admin changes the sort
    // (the confirmation dialog has already closed by then, so sorting is
    // reachable again; unlike pagination, the sort header isn't disabled while
    // a fetch is in flight -- see `DataTable`), starting the paginated-view
    // effect's own fresher request (generation N+1). The stale generation-N
    // request can still fail afterward (e.g. session expired mid-flight).
    // Per issue #227, that failure must still force a logout -- an obsolete
    // request failing precisely because the session expired must never be
    // silently discarded just because a fresher generation already won, or the
    // session would never get invalidated if the user stops interacting. It
    // must not, however, overwrite the fresh data with a generic error banner
    // (the early `return` after `clearSession`/`router.push` skips that).
    // (A session-token refresh can no longer be the trigger for a background
    // reload here -- see issue #138 -- so a sort change is used instead, which
    // remains a valid trigger once the dialog has closed.)
    const userA = userFixture({ id: 1, email: "alice@example.com" });
    const freshUser = userFixture({ id: 3, email: "fresh@example.com" });
    let rejectStale!: (cause: unknown) => void;
    let getUsersCallCount = 0;
    mocks.getUsers.mockImplementation(() => {
      getUsersCallCount += 1;
      if (getUsersCallCount === 1) return Promise.resolve({ items: [userA], total: 1 });
      if (getUsersCallCount === 2) {
        // The reload triggered below by `deleteExistingUser` (generation N),
        // held pending until rejected explicitly once generation N+1 has
        // already resolved.
        return new Promise((_resolve, reject) => {
          rejectStale = reject;
        });
      }
      // The fresher request (generation N+1), triggered by the sort change
      // below while call 2 is still in flight.
      return Promise.resolve({ items: [freshUser], total: 1 });
    });
    mocks.deleteUser.mockResolvedValue(undefined);

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(mocks.getUsers).toHaveBeenCalledTimes(2));

    // Changes the sort now -- the confirmation dialog has already closed,
    // well before the delete's own reload (call 2, still pending) has
    // settled.
    fireEvent.click(screen.getByRole("button", { name: "Email" }));
    await waitFor(() => expect(mocks.getUsers).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getByText("fresh@example.com")).toBeInTheDocument());

    // The stale generation-N request now fails, well after generation N+1
    // already committed fresh data -- it must still force a logout, but it
    // must not overwrite the already-displayed fresh data with a generic
    // "reload failed" error banner.
    rejectStale(new SessionExpiredError());
    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.router.push).toHaveBeenCalledWith("/login");
    expect(screen.getByText("fresh@example.com")).toBeInTheDocument();
    expect(
      screen.queryByText("L'action a réussi, mais l'actualisation de la liste a échoué. Rechargez la page pour la voir à jour."),
    ).not.toBeInTheDocument();
  });

  it("clears a previous list-refresh error once a later reload succeeds", async () => {
    // `usersError` is the pre-existing error slot for "the mutation succeeded but
    // the follow-up list refresh failed" (see the "surfaces feedback..." test
    // above). A stale error banner from an earlier failed reload must not
    // survive a later reload that succeeds -- otherwise the admin keeps seeing
    // a stale warning even though the table now shows valid, current data.
    const userA = userFixture({ id: 1, email: "alice@example.com" });
    const userB = userFixture({ id: 2, email: "bob@example.com" });
    mocks.getUsers.mockResolvedValueOnce({ items: [userA], total: 1 });
    mocks.getUsers.mockRejectedValueOnce(new ApiError(500, "Actualisation impossible"));
    mocks.getUsers.mockResolvedValueOnce({ items: [userB], total: 1 });
    mocks.deleteUser.mockResolvedValue(undefined);

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());

    // First delete: the mutation succeeds but its own reload fails, surfacing
    // the "reload failed" banner.
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    let alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));
    await waitFor(() =>
      expect(
        screen.getByText("L'action a réussi, mais l'actualisation de la liste a échoué. Rechargez la page pour la voir à jour."),
      ).toBeInTheDocument(),
    );

    // Second delete: this time the reload succeeds -- the stale banner from the
    // first attempt must be cleared, not left dangling over fresh data.
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(screen.getByText("bob@example.com")).toBeInTheDocument());
    expect(
      screen.queryByText("L'action a réussi, mais l'actualisation de la liste a échoué. Rechargez la page pour la voir à jour."),
    ).not.toBeInTheDocument();
  });

  it("clamps to the last valid page and refetches when a delete leaves the current offset past the end of the list", async () => {
    // Admin is on page 2 (offset 20, limit 20) and deletes the only remaining
    // user there -- the new total (20) is no longer greater than that offset,
    // so re-fetching at the stale offset 20 would return an empty page even
    // though 20 users still exist on page 1. The reload must detect this and
    // clamp back to the last valid page instead of rendering "Aucune donnée".
    const page1Items = Array.from({ length: 20 }, (_, index) =>
      userFixture({ id: index + 1, email: `user${index + 1}@example.com` }),
    );
    const lastUserOnPage2 = userFixture({ id: 21, email: "last@example.com" });
    let totalUsers = 21;
    mocks.getUsers.mockImplementation((_tokens: unknown, _refresh: unknown, listParams: unknown) => {
      const offset = (listParams as { offset?: number } | undefined)?.offset ?? 0;
      if (offset === 0) return Promise.resolve({ items: page1Items, total: totalUsers });
      return Promise.resolve({ items: totalUsers > 20 ? [lastUserOnPage2] : [], total: totalUsers });
    });
    mocks.deleteUser.mockImplementation(() => {
      totalUsers = 20;
      return Promise.resolve(undefined);
    });

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("user1@example.com")).toBeInTheDocument());

    const suivant = await screen.findByRole("button", { name: "Suivant" });
    fireEvent.click(suivant);
    await waitFor(() => expect(screen.getByText("last@example.com")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));

    // The reload at the stale offset 20 comes back empty; the page must then
    // clamp back to offset 0 and refetch, rather than showing "Aucune donnée"
    // while 20 users still exist on page 1.
    await waitFor(() =>
      expect(mocks.getUsers).toHaveBeenLastCalledWith(
        expect.anything(),
        expect.anything(),
        expect.objectContaining({ offset: 0 }),
      ),
    );
    await waitFor(() => expect(screen.getByText("user1@example.com")).toBeInTheDocument());
    expect(screen.queryByText("Aucune donnée.")).not.toBeInTheDocument();
    expect(screen.queryByText("last@example.com")).not.toBeInTheDocument();
  });

  it("disables deleting, deactivating, or demoting your own account, matching the backend's own rejection rules", async () => {
    // The backend hard-rejects all three for your own account (auth.py: "Cannot
    // deactivate self"/"Cannot remove own admin role"/"Cannot delete self", each
    // a 400) -- without disabling them here, clicking would surface a raw,
    // untranslated English error string into this otherwise fully French page.
    mocks.getMe.mockResolvedValueOnce({ id: 1, email: "me@example.com", is_active: true });
    const self = userFixture({ id: 1, email: "me@example.com", is_active: true, is_admin: true });
    const other = userFixture({ id: 2, email: "bob@example.com", is_active: true, is_admin: false });
    mocks.getUsers.mockResolvedValue({ items: [self, other], total: 2 });

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("me@example.com")).toBeInTheDocument());

    const selfRow = screen.getByText("me@example.com").closest("tr");
    if (!selfRow) throw new Error("row not found");
    expect(within(selfRow).getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(within(selfRow).getByRole("button", { name: "Retirer admin" })).toBeDisabled();
    expect(within(selfRow).getByRole("button", { name: "Supprimer" })).toBeDisabled();

    // Not self: none of the three should be disabled by this rule.
    const otherRow = screen.getByText("bob@example.com").closest("tr");
    if (!otherRow) throw new Error("row not found");
    expect(within(otherRow).getByRole("button", { name: "Désactiver" })).toBeEnabled();
    expect(within(otherRow).getByRole("button", { name: "Promouvoir admin" })).toBeEnabled();
    expect(within(otherRow).getByRole("button", { name: "Supprimer" })).toBeEnabled();
  });

  // Regression tests for #216: a refresh can succeed yet the retried request still
  // come back 401 (account disabled/deleted between the two calls, server-side
  // race) -- authFetch then rejects with a plain ApiError, not a
  // SessionExpiredError. Every user-management mutation handler on this page must
  // still detect that as a session expiry (clearSession + redirect), not surface
  // it as a generic business error.
  it("clears the session and redirects to login when creating a user reports a post-refresh 401, not a generic error", async () => {
    mocks.getUsers.mockResolvedValue({ items: [], total: 0 });
    mocks.createUser.mockRejectedValue(new ApiError(401, "Unauthorized"));

    await openUsersTab();
    fireEvent.click(screen.getByRole("button", { name: "Ajouter un utilisateur" }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Mot de passe"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));

    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.router.push).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("Impossible de créer l'utilisateur")).not.toBeInTheDocument();
  });

  it("clears the session and redirects to login when deleting a user reports a post-refresh 401, not a generic error", async () => {
    const userA = userFixture({ id: 1, email: "alice@example.com" });
    mocks.getUsers.mockResolvedValue({ items: [userA], total: 1 });
    mocks.deleteUser.mockRejectedValue(new ApiError(401, "Unauthorized"));

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Supprimer" }));

    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.router.push).toHaveBeenCalledWith("/login");
  });

  it("clears the session and redirects to login when toggling a user's status reports a post-refresh 401, not a generic error", async () => {
    const userA = userFixture({ id: 1, email: "alice@example.com", is_active: true });
    mocks.getUsers.mockResolvedValue({ items: [userA], total: 1 });
    mocks.setUserStatus.mockRejectedValue(new ApiError(401, "Unauthorized"));

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Désactiver" }));

    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.router.push).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("Impossible de modifier le statut")).not.toBeInTheDocument();
  });

  it("clears the session and redirects to login when toggling a user's admin role reports a post-refresh 401, not a generic error", async () => {
    const userA = userFixture({ id: 1, email: "alice@example.com", is_admin: false });
    mocks.getUsers.mockResolvedValue({ items: [userA], total: 1 });
    mocks.setUserRole.mockRejectedValue(new ApiError(401, "Unauthorized"));

    await openUsersTab();
    await waitFor(() => expect(screen.getByText("alice@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Promouvoir admin" }));
    const alertDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(alertDialog).getByRole("button", { name: "Promouvoir administrateur" }));

    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.router.push).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("Impossible de modifier le role")).not.toBeInTheDocument();
  });
});
