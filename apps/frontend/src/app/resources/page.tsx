"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
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
  const [roles, setRoles] = useState<ResourceRole[]>([]);
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [costTypes, setCostTypes] = useState<CostType[]>([]);
  const [categories, setCategories] = useState<CostCategory[]>([]);
  const [rates, setRates] = useState<CostRate[]>([]);
  const [capacities, setCapacities] = useState<RoleCapacity[]>([]);
  const [capacityDrafts, setCapacityDrafts] = useState<Record<number, { personCount: string; availableHours: string }>>({});
  const [roleCalendarDrafts, setRoleCalendarDrafts] = useState<Record<number, string>>({});
  const [users, setUsers] = useState<AuthUserAdmin[]>([]);
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
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
  const [roleCode, setRoleCode] = useState("");
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

  useEffect(() => {
    async function load() {
      if (!session) {
        try {
          const restoredSession = await restoreSession();
          setSession(restoredSession);
          setSessionState(restoredSession);
        } catch {
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
          getResourceRoles(session, onSessionRefresh),
          getCalendars(session, onSessionRefresh, true),
          getCostTypes(session, onSessionRefresh, true),
          getCostCategories(session, onSessionRefresh, true),
          getCostRates(session, onSessionRefresh),
          getInflationRates(session, onSessionRefresh),
          getRoleCapacities(session, onSessionRefresh),
          getUsers(session, onSessionRefresh),
        ]);
        setNodes(nodeData);
        setSelectedNodeId((previous) => previous ?? nodeData[0]?.id ?? null);
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
      } catch (cause) {
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
        setBusy(false);
      }
    }

    void load();
  }, [onSessionRefresh, router, session]);

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
      setSelectedNodeId((previous) => previous === node.id ? null : previous);
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
    }, category.is_active ? "Catégorie désactivée." : "Catégorie réactivée.");
  }

  async function addRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createResourceRole(
        {
          code: roleCode,
          name: roleName,
          node_id: Number(roleNodeId),
          cost_category_id: Number(roleCategoryId),
        },
        session,
        onSessionRefresh,
      );
      setRoles((prev) => [...prev, created].sort((left, right) => left.code.localeCompare(right.code)));
      setRoleCode("");
      setRoleName("");
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
  const calendarIdsInUseByActiveRoles = new Set(
    roles.filter((role) => role.is_active && role.calendar_id != null).map((role) => role.calendar_id as number),
  );
  const organizationRows = useMemo(() => flattenOrganization(nodes, collapsedNodeIds), [nodes, collapsedNodeIds]);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedRoles = selectedNodeId === null ? [] : roles.filter((role) => role.node_id === selectedNodeId);

  function selectNode(nodeId: number) {
    setSelectedNodeId(nodeId);
    setRoleNodeId(String(nodeId));
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

          <RolesPanel selectedNode={selectedNode} selectedRoles={selectedRoles} nodes={nodes} categories={categories} costTypes={costTypes} roleCode={roleCode} roleName={roleName} roleNodeId={roleNodeId} roleCategoryId={roleCategoryId} actionBusy={actionBusy} categoryNames={categoryNameById} onSubmit={addRole} onCodeChange={setRoleCode} onNameChange={setRoleName} onNodeChange={(value) => { setRoleNodeId(value); setSelectedNodeId(Number(value)); }} onCategoryChange={setRoleCategoryId} />

          </div>
          <CapacityTable roles={roles} drafts={capacityDrafts} actionBusy={actionBusy} onDraftChange={(roleId, draft) => setCapacityDrafts((previous) => ({ ...previous, [roleId]: draft }))} onSave={(roleId) => void saveRoleCapacity(roleId)} />
          <RoleCalendarsTable roles={roles} calendars={calendars} drafts={roleCalendarDrafts} actionBusy={actionBusy} onDraftChange={(roleId, calendarId) => setRoleCalendarDrafts((previous) => ({ ...previous, [roleId]: calendarId }))} onSave={(roleId) => void saveRoleCalendar(roleId)} />
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
          />
        </>
      ) : null}

      {!busy && activeTab === "costs" ? (
        <>
          <CostTypesTable items={costTypes} code={costTypeCode} name={costTypeName} kind={costTypeKind} draft={costTypeDraft} editingId={editingCostTypeId} busy={actionBusy} labels={costTypeKindLabels} onSubmit={addCostType} onCodeChange={setCostTypeCode} onNameChange={setCostTypeName} onKindChange={setCostTypeKind} onStartEdit={startEditCostType} onDraftChange={setCostTypeDraft} onSave={(item) => void saveCostType(item)} onCancel={() => setEditingCostTypeId(null)} onToggle={(item) => void toggleCostTypeActive(item)} />

          <CostCategoriesTable items={categories} types={costTypes} typeId={categoryCostTypeId} accountingCode={categoryCode} categoryCode={accountingCode} name={categoryName} draft={categoryDraft} editingId={editingCategoryId} busy={actionBusy} onSubmit={addCategory} onTypeChange={setCategoryCostTypeId} onAccountingCodeChange={setCategoryCode} onCategoryCodeChange={setAccountingCode} onNameChange={setCategoryName} onStartEdit={startEditCategory} onDraftChange={(field, value) => setCategoryDraft((previous) => ({ ...previous, [field]: value }))} onSave={(item) => void saveCategory(item)} onCancel={() => setEditingCategoryId(null)} onToggle={(item) => void toggleCategoryActive(item)} />

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

