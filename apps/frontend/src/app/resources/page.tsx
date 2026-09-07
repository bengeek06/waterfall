"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Card, CardContent } from "@/components/ui/card";
import {
  ApiError,
  AuthUserAdmin,
  Calendar,
  CostCategory,
  CostRate,
  CostType,
  ResourceNode,
  ResourceRole,
  RoleCapacity,
  SessionExpiredError,
  createCalendar,
  createCostCategory,
  createCostRate,
  createCostType,
  createResourceNode,
  createResourceRole,
  deleteCalendar,
  deleteResourceNode,
  createRoleCapacity,
  createUser,
  deleteUser,
  getCalendars,
  getCostCategories,
  getCostRates,
  getCostTypes,
  getInflationRates,
  getResourceNodes,
  getResourceRoles,
  getRoleCapacities,
  getUsers,
  restoreSession,
  setInflationRate,
  setUserRole,
  setUserStatus,
  updateCalendar,
  updateCostCategory,
  updateCostRate,
  updateCostType,
  updateRoleCapacity,
  updateResourceNode,
  updateResourceRole,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";
import { SettingsTabs, type SettingsTab } from "@/components/settings-tabs";
import { UsersTab } from "@/components/users-tab";
import { OrganizationTree, type OrganizationRow } from "@/components/organization-tree";
import { RolesPanel } from "@/components/roles-panel";
import { CapacityTable } from "@/components/capacity-table";
import { CostTypesTable } from "@/components/cost-types-table";
import { CostCategoriesTable } from "@/components/cost-categories-table";
import { ValuationPanel } from "@/components/valuation-panel";
import { CalendarsTable, defaultWeekdays, type WeekdayDraft } from "@/components/calendars-table";
import { RoleCalendarsTable } from "@/components/role-calendars-table";

type Notice = { kind: "error" | "success"; message: string } | null;
type PendingUserAction = { kind: "status" | "admin" | "delete"; user: AuthUserAdmin } | null;
const costTypeKindLabels = {
  labor: "Main d'œuvre",
  supply: "Fourniture",
  other: "Autres",
} as const;

function flattenOrganization(nodes: ResourceNode[], collapsedIds: Set<number>): OrganizationRow[] {
  const childrenByParent = new Map<number | null, ResourceNode[]>();
  for (const node of nodes) { const parentId = node.parent_id ?? null; const siblings = childrenByParent.get(parentId) ?? []; siblings.push(node); childrenByParent.set(parentId, siblings); }
  for (const siblings of childrenByParent.values()) siblings.sort((left, right) => left.code.localeCompare(right.code));
  const rows: OrganizationRow[] = [];
  function visit(parentId: number | null, depth: number) { for (const node of childrenByParent.get(parentId) ?? []) { const hasChildren = (childrenByParent.get(node.id)?.length ?? 0) > 0; rows.push({ ...node, depth, hasChildren }); if (hasChildren && !collapsedIds.has(node.id)) visit(node.id, depth + 1); } }
  visit(null, 0);
  return rows;
}

export default function ResourcesPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [activeTab, setActiveTab] = useState<SettingsTab>("costs");
  const [nodes, setNodes] = useState<ResourceNode[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  // Mirrors `selectedNodeId` synchronously (updated at every write site below,
  // not via a `useEffect`) so an async continuation resumed after selection has
  // since changed (e.g. `reloadRolesPanelPage`, called from `addRole` after
  // `await createResourceRole`) can read the *live* selection instead of the
  // value closed over when it started -- otherwise a role created for node A
  // while the user has since switched to node B would fetch and display A's
  // page under B's heading.
  const selectedNodeIdRef = useRef<number | null>(null);
  // `roles` (full, unfiltered across every node) feeds CapacityTable and
  // RoleCalendarsTable, which both need the complete reference list (they display
  // every role, labelled with its own node code, not just the currently selected
  // node's roles). Per the same EPIC E7/E8 guarantee as `costTypes` below, this must
  // stay a plain unpaginated fetch. RolesPanel's own view -- scoped to the selected
  // node, with server search/sort/pagination -- is a second, independent fetch
  // (`rolesPanelPage` below), not a client-side slice of `roles`.
  const [roles, setRoles] = useState<ResourceRole[]>([]);
  const [rolesPanelPage, setRolesPanelPage] = useState<{ items: ResourceRole[]; total: number }>({
    items: [],
    total: 0,
  });
  const [rolesPanelLoading, setRolesPanelLoading] = useState(false);
  const [rolesPanelOffset, setRolesPanelOffset] = useState(0);
  const [rolesPanelLimit] = useState(20);
  const [rolesPanelSort, setRolesPanelSort] = useState<string | null>(null);
  const [rolesPanelQuery, setRolesPanelQuery] = useState("");
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  // `costTypes` (full, unfiltered) feeds other panels that need the complete list as
  // reference data (RolesPanel, CostCategoriesTable's type dropdown, ValuationPanel) --
  // per EPIC E7/E8, that guarantee ("absent limit, tout est renvoye") must not be
  // broken by pagination. The cost-types table's own paginated view is therefore a
  // second, independent fetch (`costTypesPage` below), not a client-side slice of
  // `costTypes` -- slicing it locally would silently violate the "recherche et tri
  // delegues au serveur" requirement even though today's dataset happens to be small
  // enough that it would look correct.
  const [costTypes, setCostTypes] = useState<CostType[]>([]);
  const [costTypesPage, setCostTypesPage] = useState<{ items: CostType[]; total: number }>({
    items: [],
    total: 0,
  });
  const [costTypesLoading, setCostTypesLoading] = useState(false);
  const [costTypesOffset, setCostTypesOffset] = useState(0);
  const [costTypesLimit] = useState(20);
  const [costTypesSort, setCostTypesSort] = useState<string | null>(null);
  const [costTypesQuery, setCostTypesQuery] = useState("");
  // The role-calendars table's own paginated/sortable/searchable-by-name view --
  // independent of the full `roles` list above (still needed unpaginated by
  // RolesPanel/CapacityTable/`calendarIdsInUseByActiveRoles`), mirroring the
  // `costTypes` vs `costTypesPage` split for the same reason: slicing `roles`
  // client-side would silently violate "recherche et tri delegues au serveur".
  const [roleCalendarsPage, setRoleCalendarsPage] = useState<{ items: ResourceRole[]; total: number }>({
    items: [],
    total: 0,
  });
  const [roleCalendarsLoading, setRoleCalendarsLoading] = useState(false);
  const [roleCalendarsOffset, setRoleCalendarsOffset] = useState(0);
  const [roleCalendarsLimit] = useState(20);
  const [roleCalendarsSort, setRoleCalendarsSort] = useState<string | null>(null);
  const [roleCalendarsQuery, setRoleCalendarsQuery] = useState("");
  // `categories` (full, unfiltered) feeds other panels that need the complete list as
  // reference data (RolesPanel, ValuationPanel, the categoryNameById lookup) -- same
  // reasoning as `costTypes` above. CostCategoriesTable's own paginated view is a
  // second, independent fetch (`categoriesPage` below).
  const [categories, setCategories] = useState<CostCategory[]>([]);
  const [categoriesPage, setCategoriesPage] = useState<{ items: CostCategory[]; total: number }>({
    items: [],
    total: 0,
  });
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [categoriesOffset, setCategoriesOffset] = useState(0);
  const [categoriesLimit] = useState(20);
  const [categoriesSort, setCategoriesSort] = useState<string | null>(null);
  const [categoriesQuery, setCategoriesQuery] = useState("");
  const [rates, setRates] = useState<CostRate[]>([]);
  // `roles` (full, unfiltered) feeds RolesPanel, RoleCalendarsTable, and the
  // capacity/calendar drafts keyed by role id -- per EPIC E7/E8, that "absent limit,
  // tout est renvoye" guarantee must not be broken by pagination. The capacity
  // table's own view is therefore a second, independent fetch (`rolesPage` below),
  // mirroring the `costTypes`/`costTypesPage` split above -- not a client-side slice
  // of `roles`, which would silently violate the "recherche et tri delegues au
  // serveur" requirement.
  const [rolesPage, setRolesPage] = useState<{ items: ResourceRole[]; total: number }>({
    items: [],
    total: 0,
  });
  const [rolesPageLoading, setRolesPageLoading] = useState(false);
  const [rolesOffset, setRolesOffset] = useState(0);
  const [rolesLimit] = useState(20);
  const [rolesSort, setRolesSort] = useState<string | null>(null);
  const [rolesQuery, setRolesQuery] = useState("");
  const [capacities, setCapacities] = useState<RoleCapacity[]>([]);
  const [capacityDrafts, setCapacityDrafts] = useState<Record<number, { personCount: string; availableHours: string }>>({});
  const [roleCalendarDrafts, setRoleCalendarDrafts] = useState<Record<number, string>>({});
  const [users, setUsers] = useState<AuthUserAdmin[]>([]);
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [loadSucceeded, setLoadSucceeded] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [pendingUserAction, setPendingUserAction] = useState<PendingUserAction>(null);

  const [nodeCode, setNodeCode] = useState("");
  const [nodeName, setNodeName] = useState("");
  const [nodeParentId, setNodeParentId] = useState("");
  const [editingNodeId, setEditingNodeId] = useState<number | null>(null);
  const [nodeDraft, setNodeDraft] = useState({ code: "", name: "", parentId: "" });
  const [categoryCode, setCategoryCode] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [categoryCostTypeId, setCategoryCostTypeId] = useState("");
  const [accountingCode, setAccountingCode] = useState("");
  const [costTypeCode, setCostTypeCode] = useState("");
  const [costTypeName, setCostTypeName] = useState("");
  const [costTypeKind, setCostTypeKind] = useState<CostType["kind"]>("other");
  const [roleName, setRoleName] = useState("");
  const [roleNodeId, setRoleNodeId] = useState("");
  const [roleCategoryId, setRoleCategoryId] = useState("");
  const [calendarCode, setCalendarCode] = useState("");
  const [calendarName, setCalendarName] = useState("");
  const [calendarWeeksPerYear, setCalendarWeeksPerYear] = useState("47");
  const [calendarWeekdays, setCalendarWeekdays] = useState<WeekdayDraft[]>(() => defaultWeekdays());
  const [editingCalendarId, setEditingCalendarId] = useState<number | null>(null);
  const [calendarDraft, setCalendarDraft] = useState<{ code: string; name: string; weeksPerYear: string; weekdays: WeekdayDraft[] }>({
    code: "",
    name: "",
    weeksPerYear: "47",
    weekdays: defaultWeekdays(),
  });
  const [inflationYear] = useState(String(new Date().getFullYear()));
  const [inflationValue, setInflationValue] = useState("");
  const [displayCurrency, setDisplayCurrency] = useState("EUR");
  const [rateDrafts, setRateDrafts] = useState<Record<string, string>>({});
  const [createUserMode, setCreateUserMode] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [editingCostTypeId, setEditingCostTypeId] = useState<number | null>(null);
  const [costTypeDraft, setCostTypeDraft] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [collapsedNodeIds, setCollapsedNodeIds] = useState<Set<number>>(new Set());
  const [categoryDraft, setCategoryDraft] = useState({
    code: "",
    name: "",
    accountingCode: "",
  });

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  // Guards against out-of-order reloads: a token refresh (see `onSessionRefresh`
  // above) changes `session`, which re-runs this effect. If an older reload is
  // still in flight when a newer one starts (or finishes) and later resolves,
  // its now-stale results must not overwrite state a more recent reload (or a
  // local optimistic update racing against it) has already committed.
  const loadGenerationRef = useRef(0);

  useEffect(() => {
    const generation = ++loadGenerationRef.current;
    const isCurrentGeneration = () => loadGenerationRef.current === generation;

    async function load() {
      if (!session) {
        try {
          const restoredSession = await restoreSession();
          if (!isCurrentGeneration()) return;
          setSession(restoredSession);
          setSessionState(restoredSession);
        } catch {
          if (!isCurrentGeneration()) return;
          clearSession();
          router.push("/login");
        }
        return;
      }
      setBusy(true);
      try {
        const [
          nodeData,
          roleData,
          calendarData,
          costTypeData,
          categoryData,
          rateData,
          inflationData,
          capacityData,
          usersData,
        ] = await Promise.all([
          getResourceNodes(session, onSessionRefresh),
          getResourceRoles(session, onSessionRefresh).then((page) => page.items),
          getCalendars(session, onSessionRefresh, true),
          getCostTypes(session, onSessionRefresh, true).then((page) => page.items),
          getCostCategories(session, onSessionRefresh, true).then((page) => page.items),
          getCostRates(session, onSessionRefresh),
          getInflationRates(session, onSessionRefresh),
          getRoleCapacities(session, onSessionRefresh),
          getUsers(session, onSessionRefresh),
        ]);
        if (!isCurrentGeneration()) return;
        setNodes(nodeData);
        setSelectedNodeId((previous) => {
          const next = previous ?? nodeData[0]?.id ?? null;
          selectedNodeIdRef.current = next;
          return next;
        });
        setRoleNodeId((previous) => previous || (nodeData[0] ? String(nodeData[0].id) : ""));
        setRoles(roleData);
        setCalendars(calendarData);
        setRoleCalendarDrafts(Object.fromEntries(roleData.map((role) => [role.id, role.calendar_id ? String(role.calendar_id) : ""])));
        setCostTypes(costTypeData);
        setCategories(categoryData);
        setRates(rateData);
        const currentInflation = inflationData.find((item) => item.year === new Date().getFullYear());
        setInflationValue(currentInflation ? ((Number(currentInflation.coefficient) - 1) * 100).toFixed(2) : "");
        setRateDrafts(Object.fromEntries(rateData.map((rate) => [`${rate.cost_category_id}:${rate.year}`, Number(rate.hourly_rate).toFixed(2)])));
        setCapacities(capacityData);
        setCapacityDrafts(Object.fromEntries(capacityData.map((capacity) => [capacity.role_id, { personCount: String(capacity.person_count), availableHours: String(capacity.available_hours) }])))
        setUsers(usersData);
        setLoadSucceeded(true);
      } catch (cause) {
        if (!isCurrentGeneration()) return;
        setLoadSucceeded(false);
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
          router.push("/login");
          return;
        }
        setNotice({
          kind: "error",
          message: cause instanceof ApiError ? cause.message : "Chargement impossible",
        });
      } finally {
        // A more recent reload may still be in flight: don't flip `busy` back to
        // false on its behalf, or the UI would flash "loaded" with stale data.
        if (isCurrentGeneration()) setBusy(false);
      }
    }

    void load();
  }, [onSessionRefresh, router, session]);

  // The cost-types table's own paginated view: independent of the full `costTypes`
  // list above, refetched whenever pagination, sort, or search change, and again
  // after any create/update/toggle mutation (see `reloadCostTypesPage` below) since
  // those mutate `costTypes` directly but have no way to patch this separate,
  // server-ordered page in place. Guarded by its own generation counter for the same
  // reason as the main load above (a session refresh, rapid paging, or a mutation's
  // reload racing an in-flight fetch must not let a stale response win).
  const costTypesGenerationRef = useRef(0);

  useEffect(() => {
    const generation = ++costTypesGenerationRef.current;
    const isCurrentGeneration = () => costTypesGenerationRef.current === generation;

    async function load() {
      if (!session) return;
      setCostTypesLoading(true);
      try {
        const page = await getCostTypes(session, onSessionRefresh, true, {
          limit: costTypesLimit,
          offset: costTypesOffset,
          sort: costTypesSort,
          q: costTypesQuery || undefined,
        });
        if (!isCurrentGeneration()) return;
        setCostTypesPage(page);
      } catch (cause) {
        if (!isCurrentGeneration()) return;
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
          router.push("/login");
          return;
        }
        setNotice({
          kind: "error",
          message: cause instanceof ApiError ? cause.message : "Chargement des types de coût impossible",
        });
      } finally {
        if (isCurrentGeneration()) setCostTypesLoading(false);
      }
    }

    void load();
  }, [session, onSessionRefresh, router, costTypesLimit, costTypesOffset, costTypesSort, costTypesQuery]);

  // Deliberately swallows its own non-session errors rather than letting them
  // propagate: this is called as the last step of `addCostType`/`saveCostType`/
  // `toggleCostTypeActive`, all wrapped in `submitAction`, which sets its own
  // success notice right after `action()` returns -- a `setNotice` call here would
  // just be overwritten by that success notice a moment later, while *throwing*
  // would make `submitAction` report the whole operation as failed even though the
  // actual mutation (already applied to `costTypes` and the server) succeeded. The
  // table's own view simply stays one refresh behind until the next pagination/
  // sort/search interaction. Session expiry is the one exception: it must still
  // force a logout like every other data source on this page, regardless of where
  // it's detected.
  //
  // Also sets `costTypesLoading` itself (guarded by the shared generation counter,
  // like the effect above): a mutation can race an in-flight pagination/sort/search
  // fetch, bumping `costTypesGenerationRef` and making that fetch's own result
  // (including its `finally`'s `setCostTypesLoading(false)`) obsolete. Without this,
  // `costTypesLoading` could get stuck `true` forever -- set by the now-abandoned
  // effect fetch, never reset by anyone, since this function didn't touch it at all.
  async function reloadCostTypesPage() {
    if (!session) return;
    const generation = ++costTypesGenerationRef.current;
    setCostTypesLoading(true);
    try {
      const page = await getCostTypes(session, onSessionRefresh, true, {
        limit: costTypesLimit,
        offset: costTypesOffset,
        sort: costTypesSort,
        q: costTypesQuery || undefined,
      });
      if (costTypesGenerationRef.current === generation) setCostTypesPage(page);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
    } finally {
      if (costTypesGenerationRef.current === generation) setCostTypesLoading(false);
    }
  }

  // The role-calendars table's own paginated view, independent of the full `roles`
  // list above -- refetched whenever pagination, sort, or search change, and again
  // after `saveRoleCalendar` (see `reloadRoleCalendarsPage` below), since that
  // mutates `roles` directly but has no way to patch this separate, server-ordered
  // page in place. Guarded by its own generation counter, for the same reason as
  // the main load and the cost-types page above.
  const roleCalendarsGenerationRef = useRef(0);
  // Mirrors `roleCalendarsOffset`/`roleCalendarsSort`/`roleCalendarsQuery`
  // synchronously (updated at every write site below, not via a `useEffect`)
  // so `reloadRoleCalendarsPage` -- called from `saveRoleCalendar` after an
  // `await` -- reads the *live* pagination/sort/search state instead of the
  // value closed over when `saveRoleCalendar` started. Otherwise: user saves a
  // role's calendar (PATCH in flight), pages to offset 20 while it's pending,
  // then the PATCH resolves -- the reload it triggers would silently refetch
  // and display stale offset-0 data under the offset-20 label.
  const roleCalendarsOffsetRef = useRef(roleCalendarsOffset);
  const roleCalendarsSortRef = useRef(roleCalendarsSort);
  const roleCalendarsQueryRef = useRef(roleCalendarsQuery);

  useEffect(() => {
    const generation = ++roleCalendarsGenerationRef.current;
    const isCurrentGeneration = () => roleCalendarsGenerationRef.current === generation;

    async function load() {
      if (!session) return;
      setRoleCalendarsLoading(true);
      try {
        const page = await getResourceRoles(session, onSessionRefresh, undefined, undefined, {
          limit: roleCalendarsLimit,
          offset: roleCalendarsOffset,
          sort: roleCalendarsSort,
          q: roleCalendarsQuery || undefined,
        });
        if (!isCurrentGeneration()) return;
        setRoleCalendarsPage(page);
      } catch (cause) {
        if (!isCurrentGeneration()) return;
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
          router.push("/login");
          return;
        }
        setNotice({
          kind: "error",
          message: cause instanceof ApiError ? cause.message : "Chargement des calendriers de rôles impossible",
        });
      } finally {
        if (isCurrentGeneration()) setRoleCalendarsLoading(false);
      }
    }

    void load();
  }, [session, onSessionRefresh, router, roleCalendarsLimit, roleCalendarsOffset, roleCalendarsSort, roleCalendarsQuery]);

  // Deliberately swallows its own non-session errors, like `reloadCostTypesPage`
  // above, for the same reason: called from `saveRoleCalendar`, itself wrapped in
  // `submitAction`, which already reports success/failure of the mutation itself.
  // Also sets `roleCalendarsLoading` itself under the same generation counter, to
  // avoid the same "stuck true forever" bug class documented on
  // `reloadCostTypesPage`: a mutation reload can race an in-flight pagination/sort/
  // search fetch, and only whichever one owns the current generation may touch the
  // loading flag in its `finally`.
  async function reloadRoleCalendarsPage() {
    if (!session) return;
    const generation = ++roleCalendarsGenerationRef.current;
    setRoleCalendarsLoading(true);
    try {
      const page = await getResourceRoles(session, onSessionRefresh, undefined, undefined, {
        limit: roleCalendarsLimit,
        offset: roleCalendarsOffsetRef.current,
        sort: roleCalendarsSortRef.current,
        q: roleCalendarsQueryRef.current || undefined,
      });
      if (roleCalendarsGenerationRef.current === generation) setRoleCalendarsPage(page);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
    } finally {
      if (roleCalendarsGenerationRef.current === generation) setRoleCalendarsLoading(false);
    }
  }

  // RolesPanel's own paginated view: scoped to the selected node (the panel's
  // structural filter, sourced from the organization tree -- never overridden by
  // free-text search) and refetched whenever the selected node, pagination, sort,
  // or search change, plus once more after creating a role (`reloadRolesPanelPage`
  // below), since that mutation only appends to the full `roles` list and has no
  // way to patch this separate, server-ordered/filtered page in place.
  //
  // The backend applies `node_id` as a plain WHERE filter *before* the free-text
  // search (see `list_roles` in resources.py: the node filter narrows the query,
  // then `apply_pagination` searches only within what's left) -- so search here is
  // scoped to the selected node's roles, never the whole organization. That keeps
  // what's searched consistent with what's displayed (no need for a "node" column
  // on results, since every row already belongs to the single node shown in the
  // panel's heading) and matches how this panel has always behaved: a per-node
  // view, not an organization-wide one.
  //
  // No fetch happens while no node is selected (`selectedNodeId === null`):
  // mirrors the previous client-side-filtered behavior, where the list was simply
  // empty until a node was picked.
  const rolesPanelGenerationRef = useRef(0);
  // Mirrors `rolesPanelOffset`/`rolesPanelSort`/`rolesPanelQuery` synchronously
  // (updated at every write site below, not via a `useEffect`) so
  // `reloadRolesPanelPage` -- called from `addRole` after an `await` -- reads
  // the *live* pagination/sort/search state instead of the value closed over
  // when `addRole` started. Otherwise: the table remains interactive while
  // `createResourceRole` is pending, so a user can page/sort/search before it
  // resolves -- the reload it triggers would then silently commit rows fetched
  // with the stale parameters under the new controls. Same bug class and fix
  // as `reloadRolesPage`/`reloadRoleCalendarsPage`.
  const rolesPanelOffsetRef = useRef(rolesPanelOffset);
  const rolesPanelSortRef = useRef(rolesPanelSort);
  const rolesPanelQueryRef = useRef(rolesPanelQuery);

  useEffect(() => {
    const generation = ++rolesPanelGenerationRef.current;
    // The generation counter alone only orders requests -- it doesn't verify a
    // resolved request still matches what's currently selected. The refs are
    // updated synchronously in the handlers (selectNode/pagination/sort/search),
    // strictly before React re-renders and re-runs this effect: a request
    // started for one set of parameters can therefore still resolve, generation
    // unchanged, in the window after the user has already moved on (e.g.
    // clicked a different node) but before this effect gets to run again for
    // that change. Comparing every captured parameter against the live refs
    // closes that window, the same way `reloadRolesPanelPage` already does for
    // `nodeId`.
    const capturedNodeId = selectedNodeId;
    const capturedOffset = rolesPanelOffset;
    const capturedSort = rolesPanelSort;
    const capturedQuery = rolesPanelQuery;
    const isStillCurrent = () =>
      rolesPanelGenerationRef.current === generation &&
      selectedNodeIdRef.current === capturedNodeId &&
      rolesPanelOffsetRef.current === capturedOffset &&
      rolesPanelSortRef.current === capturedSort &&
      rolesPanelQueryRef.current === capturedQuery;

    async function load() {
      if (!session || selectedNodeId === null) {
        setRolesPanelPage({ items: [], total: 0 });
        // Also clears any loading state a still-in-flight, now-obsolete fetch left
        // behind (e.g. the selected node was deleted, or the session was cleared,
        // while a request for it was pending): that fetch's own generation is now
        // stale, so its `finally` block is guarded out and will never fire this
        // itself, which would otherwise leave the indicator stuck forever.
        setRolesPanelLoading(false);
        return;
      }
      setRolesPanelLoading(true);
      // Cleared unconditionally, not just on the no-selection branch above: if
      // this request fails (e.g. right after switching to a different node),
      // the table must not go on showing the *previous* node's rows under the
      // newly selected node's heading once the loading skeleton disappears.
      setRolesPanelPage({ items: [], total: 0 });
      try {
        const page = await getResourceRoles(session, onSessionRefresh, selectedNodeId, false, {
          limit: rolesPanelLimit,
          offset: rolesPanelOffset,
          sort: rolesPanelSort,
          q: rolesPanelQuery || undefined,
        });
        if (!isStillCurrent()) return;
        setRolesPanelPage(page);
      } catch (cause) {
        if (!isStillCurrent()) return;
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
          router.push("/login");
          return;
        }
        setNotice({
          kind: "error",
          message: cause instanceof ApiError ? cause.message : "Chargement des rôles impossible",
        });
      } finally {
        if (isStillCurrent()) setRolesPanelLoading(false);
      }
    }

    void load();
  }, [session, onSessionRefresh, router, selectedNodeId, rolesPanelLimit, rolesPanelOffset, rolesPanelSort, rolesPanelQuery]);

  // Mirrors `reloadCostTypesPage`: deliberately swallows its own non-session
  // errors (see that function's comment for the full rationale) and sets
  // `rolesPanelLoading` itself, guarded by the shared generation counter, so a
  // mutation's reload racing an in-flight pagination/sort/search fetch can't leave
  // the loading indicator stuck forever.
  async function reloadRolesPanelPage() {
    // Reads the live selection via the ref, not the `selectedNodeId` closed over
    // when this function's caller was invoked -- see `selectedNodeIdRef`'s
    // comment above. The ref is re-checked again below after the request
    // resolves, since the selection can also change while this request is
    // itself in flight.
    const nodeId = selectedNodeIdRef.current;
    if (!session || nodeId === null) return;
    const generation = ++rolesPanelGenerationRef.current;
    setRolesPanelLoading(true);
    try {
      const page = await getResourceRoles(session, onSessionRefresh, nodeId, false, {
        limit: rolesPanelLimit,
        offset: rolesPanelOffsetRef.current,
        sort: rolesPanelSortRef.current,
        q: rolesPanelQueryRef.current || undefined,
      });
      if (rolesPanelGenerationRef.current === generation && selectedNodeIdRef.current === nodeId) {
        setRolesPanelPage(page);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
    } finally {
      if (rolesPanelGenerationRef.current === generation) setRolesPanelLoading(false);
    }
  }

  // The capacity table's own paginated view: independent of the full `roles` list
  // above, refetched whenever pagination, sort, or search change. Unlike the
  // cost-types table, no mutation here (`saveRoleCapacity` below) needs to trigger a
  // reload of this page -- a capacity save never changes a role's own name/node_id,
  // only `capacities` (fetched separately, in full, since a `RoleCapacity` row only
  // exists once created for a role and the full set stays small). Guarded by its own
  // generation counter for the same reason as the main load above.
  const rolesPageGenerationRef = useRef(0);
  // Mirrors `rolesOffset`/`rolesSort`/`rolesQuery` synchronously (updated at
  // every write site below, not via a `useEffect`) so `reloadRolesPage` --
  // called from `saveRoleCapacity` after an `await` -- reads the *live*
  // pagination/sort/search state instead of the value closed over when
  // `saveRoleCapacity` started. Otherwise: user saves a capacity (PATCH/POST in
  // flight), pages to a later offset while it's pending, then the save
  // resolves -- the reload it triggers would silently refetch and display
  // stale data under the new offset's label. Same bug class and fix as #124
  // (role-calendars-table)'s `reloadRoleCalendarsPage`.
  const rolesOffsetRef = useRef(rolesOffset);
  const rolesSortRef = useRef(rolesSort);
  const rolesQueryRef = useRef(rolesQuery);

  useEffect(() => {
    const generation = ++rolesPageGenerationRef.current;
    const isCurrentGeneration = () => rolesPageGenerationRef.current === generation;

    async function load() {
      if (!session) return;
      setRolesPageLoading(true);
      try {
        const page = await getResourceRoles(session, onSessionRefresh, undefined, false, {
          limit: rolesLimit,
          offset: rolesOffset,
          sort: rolesSort,
          q: rolesQuery || undefined,
        });
        if (!isCurrentGeneration()) return;
        setRolesPage(page);
      } catch (cause) {
        if (!isCurrentGeneration()) return;
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
          router.push("/login");
          return;
        }
        setNotice({
          kind: "error",
          message: cause instanceof ApiError ? cause.message : "Chargement des rôles impossible",
        });
      } finally {
        if (isCurrentGeneration()) setRolesPageLoading(false);
      }
    }

    void load();
  }, [session, onSessionRefresh, router, rolesLimit, rolesOffset, rolesSort, rolesQuery]);

  // Called as the last step of `addRole` (wrapped in `submitAction`, which sets its
  // own success notice right after `action()` returns): swallows its own non-session
  // errors for the same reason as `reloadCostTypesPage` above -- the mutation itself
  // (already applied to `roles` and the server) must not be reported as failed just
  // because this follow-up refresh of the table's own page failed. Also sets
  // `rolesPageLoading` itself, guarded by the shared generation counter, to avoid the
  // same stuck-loading bug class fixed on the cost-types table (a mutation's reload
  // racing an in-flight pagination/sort/search fetch must still clear the loading
  // flag when it, not the now-obsolete fetch, is the one that settles).
  async function reloadRolesPage() {
    if (!session) return;
    const generation = ++rolesPageGenerationRef.current;
    setRolesPageLoading(true);
    try {
      const page = await getResourceRoles(session, onSessionRefresh, undefined, false, {
        limit: rolesLimit,
        offset: rolesOffsetRef.current,
        sort: rolesSortRef.current,
        q: rolesQueryRef.current || undefined,
      });
      if (rolesPageGenerationRef.current === generation) setRolesPage(page);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
    } finally {
      if (rolesPageGenerationRef.current === generation) setRolesPageLoading(false);
    }
  }

  // The cost-categories table's own paginated view: same rationale as `costTypesPage`
  // above -- independent of the full `categories` list, refetched on pagination/sort/
  // search changes and again after any create/update/toggle mutation (see
  // `reloadCategoriesPage` below).
  const categoriesGenerationRef = useRef(0);

  useEffect(() => {
    const generation = ++categoriesGenerationRef.current;
    const isCurrentGeneration = () => categoriesGenerationRef.current === generation;

    async function load() {
      if (!session) return;
      setCategoriesLoading(true);
      try {
        const page = await getCostCategories(session, onSessionRefresh, true, {
          limit: categoriesLimit,
          offset: categoriesOffset,
          sort: categoriesSort,
          q: categoriesQuery || undefined,
        });
        if (!isCurrentGeneration()) return;
        setCategoriesPage(page);
      } catch (cause) {
        if (!isCurrentGeneration()) return;
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError && cause.status === 401) {
          clearSession();
          router.push("/login");
          return;
        }
        setNotice({
          kind: "error",
          message: cause instanceof ApiError ? cause.message : "Chargement des catégories de coût impossible",
        });
      } finally {
        if (isCurrentGeneration()) setCategoriesLoading(false);
      }
    }

    void load();
  }, [session, onSessionRefresh, router, categoriesLimit, categoriesOffset, categoriesSort, categoriesQuery]);

  // Deliberately swallows its own non-session errors rather than letting them
  // propagate: this is called as the last step of `addCategory`/`saveCategory`/
  // `toggleCategoryActive`, all wrapped in `submitAction`, which sets its own success
  // notice right after `action()` returns -- see `reloadCostTypesPage` above for the
  // full reasoning (a `setNotice` call here would just be overwritten, while throwing
  // would make `submitAction` report the whole operation as failed even though the
  // mutation itself succeeded). Session expiry is the one exception: it must still
  // force a logout.
  //
  // Also sets `categoriesLoading` itself (guarded by the shared generation counter,
  // like the effect above) so a mutation racing an in-flight pagination/sort/search
  // fetch can't leave `categoriesLoading` stuck `true` forever.
  async function reloadCategoriesPage() {
    if (!session) return;
    const generation = ++categoriesGenerationRef.current;
    setCategoriesLoading(true);
    try {
      const page = await getCostCategories(session, onSessionRefresh, true, {
        limit: categoriesLimit,
        offset: categoriesOffset,
        sort: categoriesSort,
        q: categoriesQuery || undefined,
      });
      if (categoriesGenerationRef.current === generation) setCategoriesPage(page);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
    } finally {
      if (categoriesGenerationRef.current === generation) setCategoriesLoading(false);
    }
  }

  async function submitAction(action: () => Promise<void>, success: string) {
    setActionBusy(true);
    setNotice(null);
    try {
      await action();
      setNotice({ kind: "success", message: success });
    } catch (cause) {
      setNotice({
        kind: "error",
        message: cause instanceof ApiError ? cause.message : "Opération impossible",
      });
    } finally {
      setActionBusy(false);
    }
  }

  async function addNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createResourceNode(
        { code: nodeCode, name: nodeName, parent_id: nodeParentId ? Number(nodeParentId) : null },
        session,
        onSessionRefresh,
      );
      setNodes((prev) => [...prev, created].sort((left, right) => left.code.localeCompare(right.code)));
      setNodeCode("");
      setNodeName("");
      setNodeParentId("");
    }, "Nœud créé.");
  }

  function startEditNode(node: ResourceNode) {
    setEditingNodeId(node.id);
    setNodeDraft({ code: node.code, name: node.name, parentId: node.parent_id ? String(node.parent_id) : "" });
  }

  async function saveNode(node: ResourceNode) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateResourceNode(
        node.id,
        { code: nodeDraft.code, name: nodeDraft.name, parent_id: nodeDraft.parentId ? Number(nodeDraft.parentId) : null },
        session,
        onSessionRefresh,
      );
      setNodes((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
      setEditingNodeId(null);
    }, "Nœud modifié.");
  }

  async function removeNode(node: ResourceNode) {
    if (!session || !globalThis.confirm(`Supprimer le nœud ${node.name} ?`)) return;
    await submitAction(async () => {
      await deleteResourceNode(node.id, session, onSessionRefresh);
      setNodes((previous) => previous.filter((item) => item.id !== node.id));
      // Reads the live selection via the ref (see `selectedNodeIdRef`'s comment
      // above), not the value closed over when `removeNode` started -- otherwise
      // deleting node A while the user has since switched to node B would
      // incorrectly reset B's own pagination back to page 1.
      if (selectedNodeIdRef.current === node.id) {
        selectedNodeIdRef.current = null;
        setSelectedNodeId(null);
        rolesPanelOffsetRef.current = 0;
        setRolesPanelOffset(0);
      }
    }, "Nœud supprimé.");
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createCostCategory(
        {
          cost_type_id: Number(categoryCostTypeId),
          accounting_code: categoryCode,
          category_code: accountingCode || null,
          name: categoryName,
        },
        session,
        onSessionRefresh,
      );
      setCategories((prev) => [...prev, created].sort((left, right) => left.accounting_code.localeCompare(right.accounting_code)));
      setCategoryCode("");
      setCategoryName("");
      setAccountingCode("");
      await reloadCategoriesPage();
    }, "Catégorie créée.");
  }

  async function addCostType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createCostType(
        { code: costTypeCode, name: costTypeName, kind: costTypeKind },
        session,
        onSessionRefresh,
      );
      setCostTypes((prev) => [...prev, created].sort((left, right) => left.code.localeCompare(right.code)));
      setCostTypeCode("");
      setCostTypeName("");
      setCostTypeKind("other");
      await reloadCostTypesPage();
    }, "Type de coût créé.");
  }

  function startEditCostType(costType: CostType) {
    setEditingCostTypeId(costType.id);
    setCostTypeDraft(costType.name);
  }

  async function saveCostType(costType: CostType) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCostType(
        costType.id,
        { name: costTypeDraft },
        session,
        onSessionRefresh,
      );
      setCostTypes((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setEditingCostTypeId(null);
      await reloadCostTypesPage();
    }, "Type de coût modifié.");
  }

  async function toggleCostTypeActive(costType: CostType) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCostType(
        costType.id,
        { is_active: !costType.is_active },
        session,
        onSessionRefresh,
      );
      setCostTypes((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      await reloadCostTypesPage();
    }, costType.is_active ? "Type de coût désactivé." : "Type de coût réactivé.");
  }

  function startEditCategory(category: CostCategory) {
    setEditingCategoryId(category.id);
    setCategoryDraft({ code: category.accounting_code, name: category.name ?? "", accountingCode: category.category_code ?? "" });
  }

  async function saveCategory(category: CostCategory) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCostCategory(
        category.id,
        {
          accounting_code: categoryDraft.code,
          name: categoryDraft.name,
          category_code: categoryDraft.accountingCode || null,
        },
        session,
        onSessionRefresh,
      );
      setCategories((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setEditingCategoryId(null);
      await reloadCategoriesPage();
    }, "Catégorie modifiée.");
  }

  async function toggleCategoryActive(category: CostCategory) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCostCategory(
        category.id,
        { is_active: !category.is_active },
        session,
        onSessionRefresh,
      );
      setCategories((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      await reloadCategoriesPage();
    }, category.is_active ? "Catégorie désactivée." : "Catégorie réactivée.");
  }

  async function addRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createResourceRole(
        {
          name: roleName,
          node_id: Number(roleNodeId),
          cost_category_id: Number(roleCategoryId),
        },
        session,
        onSessionRefresh,
      );
      setRoles((prev) => [...prev, created].sort((left, right) => left.name.localeCompare(right.name)));
      setRoleName("");
      await reloadRolesPanelPage();
      await reloadRolesPage();
      await reloadRoleCalendarsPage();
    }, "Rôle créé.");
  }

  async function addCalendar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createCalendar(
        {
          code: calendarCode,
          name: calendarName,
          weeks_per_year: Number(calendarWeeksPerYear),
          weekdays: calendarWeekdays,
        },
        session,
        onSessionRefresh,
      );
      setCalendars((prev) => [...prev, created].sort((left, right) => left.code.localeCompare(right.code)));
      setCalendarCode("");
      setCalendarName("");
      setCalendarWeeksPerYear("47");
      setCalendarWeekdays(defaultWeekdays());
    }, "Calendrier créé.");
  }

  function startEditCalendar(calendar: Calendar) {
    setEditingCalendarId(calendar.id);
    setCalendarDraft({
      code: calendar.code,
      name: calendar.name,
      weeksPerYear: String(calendar.weeks_per_year),
      weekdays: (calendar.weekdays ?? []).map((weekday) => ({ day_type: weekday.day_type, hours_per_day: String(weekday.hours_per_day) })),
    });
  }

  async function saveCalendar(calendar: Calendar) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCalendar(
        calendar.id,
        {
          code: calendarDraft.code,
          name: calendarDraft.name,
          weeks_per_year: Number(calendarDraft.weeksPerYear),
          weekdays: calendarDraft.weekdays,
        },
        session,
        onSessionRefresh,
      );
      setCalendars((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setEditingCalendarId(null);
    }, "Calendrier modifié.");
  }

  async function toggleCalendarActive(calendar: Calendar) {
    if (!session) return;
    await submitAction(async () => {
      if (calendar.is_active) {
        await deleteCalendar(calendar.id, session, onSessionRefresh);
        setCalendars((prev) => prev.map((item) => (item.id === calendar.id ? { ...item, is_active: false } : item)));
      } else {
        const updated = await updateCalendar(calendar.id, { is_active: true }, session, onSessionRefresh);
        setCalendars((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      }
    }, calendar.is_active ? "Calendrier désactivé." : "Calendrier réactivé.");
  }

  async function setDefaultCalendar(calendar: Calendar) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCalendar(calendar.id, { is_default: true }, session, onSessionRefresh);
      setCalendars((prev) => prev.map((item) => {
        if (item.id === updated.id) return updated;
        return item.is_default ? { ...item, is_default: false } : item;
      }));
    }, "Calendrier par défaut mis à jour.");
  }

  async function saveRoleCalendar(roleId: number) {
    if (!session) return;
    const draft = roleCalendarDrafts[roleId] ?? "";
    await submitAction(async () => {
      const updated = await updateResourceRole(
        roleId,
        { calendar_id: draft ? Number(draft) : null },
        session,
        onSessionRefresh,
      );
      setRoles((previous) => previous.map((role) => (role.id === updated.id ? updated : role)));
      await reloadRoleCalendarsPage();
    }, "Calendrier du rôle enregistré.");
  }

  async function saveAllValuation() {
    if (!session) return;
    await submitAction(async () => {
      if (inflationValue.trim()) {
        const percentage = Number(inflationValue);
        await setInflationRate(Number(inflationYear), String(1 + percentage / 100), session, onSessionRefresh);
      }
      const years = [-4, -3, -2, -1, 0].map((offset) => new Date().getFullYear() + offset);
      const laborCategories = categories.filter((category) => costTypes.find((type) => type.id === category.cost_type_id)?.kind === "labor");
      for (const category of laborCategories) {
        for (const year of years) {
          const value = rateDrafts[`${category.id}:${year}`]?.trim() ?? "";
          if (!value) continue;
          const existing = rates.find((rate) => rate.cost_category_id === category.id && rate.year === year);
          const saved = existing
            ? await updateCostRate(existing.id, { hourly_rate: value }, session, onSessionRefresh)
            : await createCostRate({ cost_category_id: category.id, year, hourly_rate: value, currency_code: displayCurrency }, session, onSessionRefresh);
          setRates((previous) => existing ? previous.map((rate) => rate.id === saved.id ? saved : rate) : [...previous, saved]);
        }
      }
    }, "Taux horaires enregistrés.");
  }

  async function saveRoleCapacity(roleId: number) {
    if (!session) return;
    const draft = capacityDrafts[roleId] ?? { personCount: "0.00", availableHours: "0.00" };
    await submitAction(async () => {
      const existing = capacities.find((capacity) => capacity.role_id === roleId);
      const saved = existing
        ? await updateRoleCapacity(existing.id, { person_count: draft.personCount, available_hours: draft.availableHours }, session, onSessionRefresh)
        : await createRoleCapacity({ role_id: roleId, person_count: draft.personCount, available_hours: draft.availableHours }, session, onSessionRefresh);
      setCapacities((previous) => existing ? previous.map((capacity) => capacity.id === saved.id ? saved : capacity) : [...previous, saved]);
    }, "Capacité enregistrée.");
  }

  async function updateUserStatus(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    const nextStatus = !user.is_active;
    setActionBusy(true);
    try {
      const updated = await setUserStatus(user.id, nextStatus, session, onSessionRefresh);
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setUsersError(cause instanceof ApiError ? cause.message : "Impossible de modifier le statut");
    } finally {
      setActionBusy(false);
    }
  }

  async function updateUserAdmin(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    const nextAdmin = !user.is_admin;
    setActionBusy(true);
    try {
      const updated = await setUserRole(user.id, nextAdmin, session, onSessionRefresh);
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setUsersError(cause instanceof ApiError ? cause.message : "Impossible de modifier le role");
    } finally {
      setActionBusy(false);
    }
  }

  async function addUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      router.push("/login");
      return;
    }

    setUsersError(null);
    setActionBusy(true);
    try {
      const created = await createUser(newEmail, newPassword, session, onSessionRefresh);
      setUsers((prev) => [...prev, created].sort((left, right) => left.id - right.id));
      setNewEmail("");
      setNewPassword("");
      setCreateUserMode(false);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setUsersError(cause instanceof ApiError ? cause.message : "Impossible de créer l'utilisateur");
    } finally {
      setActionBusy(false);
    }
  }

  async function deleteExistingUser(user: AuthUserAdmin) {
    if (!session) {
      router.push("/login");
      return;
    }
    setUsersError(null);
    setActionBusy(true);
    try {
      await deleteUser(user.id, session, onSessionRefresh);
      setUsers((prev) => prev.filter((item) => item.id !== user.id));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setUsersError(cause instanceof ApiError ? cause.message : "Impossible de supprimer l'utilisateur");
    } finally {
      setActionBusy(false);
    }
  }

  const categoryNameById = new Map(categories.map((category) => [category.id, category.name]));
  const nodeCodeById = new Map(nodes.map((node) => [node.id, node.code]));
  const calendarIdsInUseByActiveRoles = new Set(
    roles.filter((role) => role.is_active && role.calendar_id != null).map((role) => role.calendar_id as number),
  );
  const organizationRows = useMemo(() => flattenOrganization(nodes, collapsedNodeIds), [nodes, collapsedNodeIds]);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;

  function selectNode(nodeId: number) {
    selectedNodeIdRef.current = nodeId;
    setSelectedNodeId(nodeId);
    setRoleNodeId(String(nodeId));
    rolesPanelOffsetRef.current = 0;
    setRolesPanelOffset(0);
  }

  function toggleNodeCollapsed(nodeId: number) {
    setCollapsedNodeIds((previous) => {
      const next = new Set(previous);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }

  function getPendingUserActionCopy(action: Exclude<PendingUserAction, null>) {
    if (action.kind === "delete") {
      return {
        title: "Supprimer cet utilisateur ?",
        description: `${action.user.email} sera supprimé définitivement. Cette action est irréversible.`,
        confirmLabel: "Supprimer",
        destructive: true,
      };
    }

    if (action.kind === "status") {
      const verb = action.user.is_active ? "désactiver" : "activer";
      return {
        title: `${verb[0].toUpperCase()}${verb.slice(1)} cet utilisateur ?`,
        description: `Le compte ${action.user.email} sera ${verb}.`,
        confirmLabel: verb[0].toUpperCase() + verb.slice(1),
        destructive: action.user.is_active,
      };
    }

    const verb = action.user.is_admin ? "retirer les droits administrateur" : "promouvoir administrateur";
    return {
      title: `${verb[0].toUpperCase()}${verb.slice(1)} ?`,
      description: `Les droits de ${action.user.email} seront mis à jour.`,
      confirmLabel: verb[0].toUpperCase() + verb.slice(1),
      destructive: action.user.is_admin,
    };
  }

  function confirmPendingUserAction() {
    const action = pendingUserAction;
    setPendingUserAction(null);
    if (!action) {
      return;
    }
    if (action.kind === "status") {
      void updateUserStatus(action.user);
    } else if (action.kind === "admin") {
      void updateUserAdmin(action.user);
    } else {
      void deleteExistingUser(action.user);
    }
  }

  return (
    <>
      <Card>
        <CardContent>
        <div className="flex flex-wrap justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Paramètres</h1>
            <p className="mt-1 text-sm text-muted-foreground">Référentiel entreprise réservé aux administrateurs.</p>
          </div>
        </div>
        </CardContent>
      </Card>

      <div className="mt-4">
        <SettingsTabs activeTab={activeTab} onChange={setActiveTab} />
      </div>

      {notice ? (
        <Alert variant={notice.kind === "error" ? "destructive" : "default"}><AlertDescription>{notice.message}</AlertDescription></Alert>
      ) : null}
      {loadSucceeded && !busy && !calendars.some((calendar) => calendar.is_active && calendar.is_default) ? (
        <Alert variant="default"><AlertDescription>Aucun calendrier par défaut n&apos;est défini. Désignez un calendrier par défaut dans l&apos;onglet Ressources.</AlertDescription></Alert>
      ) : null}
      {busy ? (
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground" role="status">Chargement...</p></CardContent></Card>
      ) : null}

      {!busy && activeTab === "resources" ? (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
          <OrganizationTree
            rows={organizationRows}
            selectedNodeId={selectedNodeId}
            collapsedNodeIds={collapsedNodeIds}
            editingNodeId={editingNodeId}
            nodeCode={nodeCode}
            nodeName={nodeName}
            nodeParentId={nodeParentId}
            nodeDraft={nodeDraft}
            actionBusy={actionBusy}
            onAdd={addNode}
            onSelect={selectNode}
            onToggleCollapsed={toggleNodeCollapsed}
            onStartEdit={startEditNode}
            onDraftChange={(field, value) => setNodeDraft((previous) => ({ ...previous, [field]: value }))}
            onSave={(node) => void saveNode(node)}
            onCancel={() => setEditingNodeId(null)}
            onRemove={(node) => void removeNode(node)}
            onNodeChange={(field, value) => { if (field === "code") setNodeCode(value); if (field === "name") setNodeName(value); if (field === "parent") setNodeParentId(value); }}
          />

          <RolesPanel selectedNode={selectedNode} items={rolesPanelPage.items} pagination={{ total: rolesPanelPage.total, limit: rolesPanelLimit, offset: rolesPanelOffset }} onPaginationChange={(next) => { rolesPanelOffsetRef.current = next.offset; setRolesPanelOffset(next.offset); }} sort={rolesPanelSort} onSortChange={(next) => { rolesPanelSortRef.current = next; setRolesPanelSort(next); }} search={rolesPanelQuery} onSearchChange={(next) => { rolesPanelQueryRef.current = next; setRolesPanelQuery(next); rolesPanelOffsetRef.current = 0; setRolesPanelOffset(0); }} isLoading={rolesPanelLoading} nodes={nodes} categories={categories} costTypes={costTypes} roleName={roleName} roleNodeId={roleNodeId} roleCategoryId={roleCategoryId} actionBusy={actionBusy} categoryNames={categoryNameById} onSubmit={addRole} onNameChange={setRoleName} onNodeChange={(value) => { setRoleNodeId(value); const nextNodeId = value === "" ? null : Number(value); selectedNodeIdRef.current = nextNodeId; setSelectedNodeId(nextNodeId); rolesPanelOffsetRef.current = 0; setRolesPanelOffset(0); }} onCategoryChange={setRoleCategoryId} />

          </div>
          <CapacityTable items={rolesPage.items} pagination={{ total: rolesPage.total, limit: rolesLimit, offset: rolesOffset }} onPaginationChange={(next) => { rolesOffsetRef.current = next.offset; setRolesOffset(next.offset); }} sort={rolesSort} onSortChange={(next) => { rolesSortRef.current = next; setRolesSort(next); }} search={rolesQuery} onSearchChange={(next) => { rolesQueryRef.current = next; setRolesQuery(next); rolesOffsetRef.current = 0; setRolesOffset(0); }} isLoading={rolesPageLoading} drafts={capacityDrafts} actionBusy={actionBusy} nodeCodeById={nodeCodeById} onDraftChange={(roleId, draft) => setCapacityDrafts((previous) => ({ ...previous, [roleId]: draft }))} onSave={(roleId) => void saveRoleCapacity(roleId)} />
          <RoleCalendarsTable roles={roleCalendarsPage.items} calendars={calendars} pagination={{ total: roleCalendarsPage.total, limit: roleCalendarsLimit, offset: roleCalendarsOffset }} onPaginationChange={(next) => { roleCalendarsOffsetRef.current = next.offset; setRoleCalendarsOffset(next.offset); }} sort={roleCalendarsSort} onSortChange={(next) => { roleCalendarsSortRef.current = next; setRoleCalendarsSort(next); }} search={roleCalendarsQuery} onSearchChange={(next) => { roleCalendarsQueryRef.current = next; setRoleCalendarsQuery(next); roleCalendarsOffsetRef.current = 0; setRoleCalendarsOffset(0); }} isLoading={roleCalendarsLoading} drafts={roleCalendarDrafts} actionBusy={actionBusy} nodeCodeById={nodeCodeById} onDraftChange={(roleId, calendarId) => setRoleCalendarDrafts((previous) => ({ ...previous, [roleId]: calendarId }))} onSave={(roleId) => void saveRoleCalendar(roleId)} />
          <CalendarsTable
            items={calendars}
            code={calendarCode}
            name={calendarName}
            weeksPerYear={calendarWeeksPerYear}
            weekdays={calendarWeekdays}
            draft={calendarDraft}
            editingId={editingCalendarId}
            busy={actionBusy}
            calendarIdsInUseByActiveRoles={calendarIdsInUseByActiveRoles}
            onSubmit={addCalendar}
            onCodeChange={setCalendarCode}
            onNameChange={setCalendarName}
            onWeeksPerYearChange={setCalendarWeeksPerYear}
            onWeekdayChange={(dayType, value) => setCalendarWeekdays((previous) => previous.map((weekday) => (weekday.day_type === dayType ? { ...weekday, hours_per_day: value } : weekday)))}
            onStartEdit={startEditCalendar}
            onDraftChange={(field, value) => setCalendarDraft((previous) => ({ ...previous, [field]: value }))}
            onDraftWeekdayChange={(dayType, value) => setCalendarDraft((previous) => ({ ...previous, weekdays: previous.weekdays.map((weekday) => (weekday.day_type === dayType ? { ...weekday, hours_per_day: value } : weekday)) }))}
            onSave={(item) => void saveCalendar(item)}
            onCancel={() => setEditingCalendarId(null)}
            onToggle={(item) => void toggleCalendarActive(item)}
            onSetDefault={(item) => void setDefaultCalendar(item)}
          />
        </>
      ) : null}

      {!busy && activeTab === "costs" ? (
        <>
          <CostTypesTable items={costTypesPage.items} pagination={{ total: costTypesPage.total, limit: costTypesLimit, offset: costTypesOffset }} onPaginationChange={(next) => setCostTypesOffset(next.offset)} sort={costTypesSort} onSortChange={setCostTypesSort} search={costTypesQuery} onSearchChange={(next) => { setCostTypesQuery(next); setCostTypesOffset(0); }} isLoading={costTypesLoading} code={costTypeCode} name={costTypeName} kind={costTypeKind} draft={costTypeDraft} editingId={editingCostTypeId} busy={actionBusy} labels={costTypeKindLabels} onSubmit={addCostType} onCodeChange={setCostTypeCode} onNameChange={setCostTypeName} onKindChange={setCostTypeKind} onStartEdit={startEditCostType} onDraftChange={setCostTypeDraft} onSave={(item) => void saveCostType(item)} onCancel={() => setEditingCostTypeId(null)} onToggle={(item) => void toggleCostTypeActive(item)} />

          <CostCategoriesTable items={categoriesPage.items} types={costTypes} pagination={{ total: categoriesPage.total, limit: categoriesLimit, offset: categoriesOffset }} onPaginationChange={(next) => setCategoriesOffset(next.offset)} sort={categoriesSort} onSortChange={setCategoriesSort} search={categoriesQuery} onSearchChange={(next) => { setCategoriesQuery(next); setCategoriesOffset(0); }} isLoading={categoriesLoading} typeId={categoryCostTypeId} accountingCode={categoryCode} categoryCode={accountingCode} name={categoryName} draft={categoryDraft} editingId={editingCategoryId} busy={actionBusy} onSubmit={addCategory} onTypeChange={setCategoryCostTypeId} onAccountingCodeChange={setCategoryCode} onCategoryCodeChange={setAccountingCode} onNameChange={setCategoryName} onStartEdit={startEditCategory} onDraftChange={(field, value) => setCategoryDraft((previous) => ({ ...previous, [field]: value }))} onSave={(item) => void saveCategory(item)} onCancel={() => setEditingCategoryId(null)} onToggle={(item) => void toggleCategoryActive(item)} />

          <ValuationPanel categories={categories} costTypes={costTypes} inflationYear={inflationYear} inflationValue={inflationValue} currency={displayCurrency} drafts={rateDrafts} busy={actionBusy} onCurrencyChange={setDisplayCurrency} onInflationChange={setInflationValue} onRateChange={(key, value) => setRateDrafts((previous) => ({ ...previous, [key]: value }))} onSave={() => void saveAllValuation()} />
        </>
      ) : null}

      {!busy && activeTab === "users" ? <UsersTab users={users} usersError={usersError} createUserMode={createUserMode} newEmail={newEmail} newPassword={newPassword} actionBusy={actionBusy} onCreateUser={addUser} onSetCreateUserMode={setCreateUserMode} onEmailChange={setNewEmail} onPasswordChange={setNewPassword} onToggleStatus={(user) => setPendingUserAction({ kind: "status", user })} onToggleAdmin={(user) => setPendingUserAction({ kind: "admin", user })} onRemove={(user) => setPendingUserAction({ kind: "delete", user })} /> : null}

      {pendingUserAction ? (() => {
        const copy = getPendingUserActionCopy(pendingUserAction);
        return <AlertDialog open onOpenChange={(open) => !open && setPendingUserAction(null)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{copy.title}</AlertDialogTitle><AlertDialogDescription>{copy.description}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Annuler</AlertDialogCancel><AlertDialogAction variant={copy.destructive ? "destructive" : "default"} onClick={confirmPendingUserAction}>{copy.confirmLabel}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>;
      })() : null}
    </>
  );
}

