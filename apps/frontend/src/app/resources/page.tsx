"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiError,
  AuthUserAdmin,
  CostCategory,
  CostRate,
  CostType,
  InflationRate,
  ResourceNode,
  ResourceRole,
  RoleCapacity,
  SessionExpiredError,
  createCostCategory,
  createCostRate,
  createCostType,
  createResourceNode,
  createResourceRole,
  createRoleCapacity,
  createUser,
  deleteUser,
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
  updateCostCategory,
  updateCostType,
  updateResourceNode,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

type Notice = { kind: "error" | "success"; message: string } | null;
type SettingsTab = "resources" | "costs" | "users";

const costTypeKindLabels = {
  labor: "Main d'œuvre",
  supply: "Fourniture",
  other: "Autres",
} as const;

type OrganizationRow = ResourceNode & { depth: number; hasChildren: boolean };

function flattenOrganization(nodes: ResourceNode[], collapsedIds: Set<number>): OrganizationRow[] {
  const childrenByParent = new Map<number | null, ResourceNode[]>();
  for (const node of nodes) {
    const parentId = node.parent_id ?? null;
    const siblings = childrenByParent.get(parentId) ?? [];
    siblings.push(node);
    childrenByParent.set(parentId, siblings);
  }
  for (const siblings of childrenByParent.values()) {
    siblings.sort((left, right) => left.code.localeCompare(right.code));
  }

  const rows: OrganizationRow[] = [];
  function visit(parentId: number | null, depth: number) {
    for (const node of childrenByParent.get(parentId) ?? []) {
      const hasChildren = (childrenByParent.get(node.id)?.length ?? 0) > 0;
      rows.push({ ...node, depth, hasChildren });
      if (hasChildren && !collapsedIds.has(node.id)) visit(node.id, depth + 1);
    }
  }
  visit(null, 0);
  return rows;
}

export default function ResourcesPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [activeTab, setActiveTab] = useState<SettingsTab>("costs");
  const [nodes, setNodes] = useState<ResourceNode[]>([]);
  const [roles, setRoles] = useState<ResourceRole[]>([]);
  const [costTypes, setCostTypes] = useState<CostType[]>([]);
  const [categories, setCategories] = useState<CostCategory[]>([]);
  const [rates, setRates] = useState<CostRate[]>([]);
  const [inflation, setInflation] = useState<InflationRate[]>([]);
  const [capacities, setCapacities] = useState<RoleCapacity[]>([]);
  const [users, setUsers] = useState<AuthUserAdmin[]>([]);
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [usersError, setUsersError] = useState<string | null>(null);

  const [nodeCode, setNodeCode] = useState("");
  const [nodeName, setNodeName] = useState("");
  const [nodeParentId, setNodeParentId] = useState("");
  const [editingNodeId, setEditingNodeId] = useState<number | null>(null);
  const [nodeDraft, setNodeDraft] = useState({ name: "", parentId: "" });
  const [categoryCode, setCategoryCode] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [categoryCostTypeId, setCategoryCostTypeId] = useState("");
  const [accountingCode, setAccountingCode] = useState("");
  const [calendarCode, setCalendarCode] = useState("");
  const [costTypeCode, setCostTypeCode] = useState("");
  const [costTypeName, setCostTypeName] = useState("");
  const [costTypeKind, setCostTypeKind] = useState<CostType["kind"]>("other");
  const [roleCode, setRoleCode] = useState("");
  const [roleName, setRoleName] = useState("");
  const [roleNodeId, setRoleNodeId] = useState("");
  const [roleCategoryId, setRoleCategoryId] = useState("");
  const [rateCategoryId, setRateCategoryId] = useState("");
  const [rateYear, setRateYear] = useState(String(new Date().getFullYear()));
  const [rateValue, setRateValue] = useState("");
  const [rateCurrency, setRateCurrency] = useState("EUR");
  const [inflationYear, setInflationYear] = useState(String(new Date().getFullYear()));
  const [inflationValue, setInflationValue] = useState("1");
  const [capacityRoleId, setCapacityRoleId] = useState("");
  const [capacityStart, setCapacityStart] = useState("");
  const [capacityEnd, setCapacityEnd] = useState("");
  const [personCount, setPersonCount] = useState("");
  const [availableHours, setAvailableHours] = useState("");
  const [createUserMode, setCreateUserMode] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [editingCostTypeId, setEditingCostTypeId] = useState<number | null>(null);
  const [costTypeDraft, setCostTypeDraft] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [collapsedNodeIds, setCollapsedNodeIds] = useState<Set<number>>(new Set());
  const [categoryDraft, setCategoryDraft] = useState({
    name: "",
    accountingCode: "",
    calendarCode: "",
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
          costTypeData,
          categoryData,
          rateData,
          inflationData,
          capacityData,
          usersData,
        ] = await Promise.all([
          getResourceNodes(session, onSessionRefresh),
          getResourceRoles(session, onSessionRefresh),
          getCostTypes(session, onSessionRefresh, true),
          getCostCategories(session, onSessionRefresh, true),
          getCostRates(session, onSessionRefresh),
          getInflationRates(session, onSessionRefresh),
          getRoleCapacities(session, onSessionRefresh),
          getUsers(session, onSessionRefresh),
        ]);
        setNodes(nodeData);
        setRoles(roleData);
        setCostTypes(costTypeData);
        setCategories(categoryData);
        setRates(rateData);
        setInflation(inflationData);
        setCapacities(capacityData);
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
    setNodeDraft({ name: node.name, parentId: node.parent_id ? String(node.parent_id) : "" });
  }

  async function saveNode(node: ResourceNode) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateResourceNode(
        node.id,
        { name: nodeDraft.name, parent_id: nodeDraft.parentId ? Number(nodeDraft.parentId) : null },
        session,
        onSessionRefresh,
      );
      setNodes((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
      setEditingNodeId(null);
    }, "Nœud modifié.");
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createCostCategory(
        {
          cost_type_id: Number(categoryCostTypeId),
          code: categoryCode,
          accounting_code: accountingCode || null,
          name: categoryName,
          calendar_code: calendarCode || null,
        },
        session,
        onSessionRefresh,
      );
      setCategories((prev) => [...prev, created].sort((left, right) => left.code.localeCompare(right.code)));
      setCategoryCode("");
      setCategoryName("");
      setAccountingCode("");
      setCalendarCode("");
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
    setCategoryDraft({
      name: category.name,
      accountingCode: category.accounting_code ?? "",
      calendarCode: category.calendar_code ?? "",
    });
  }

  async function saveCategory(category: CostCategory) {
    if (!session) return;
    await submitAction(async () => {
      const updated = await updateCostCategory(
        category.id,
        {
          name: categoryDraft.name,
          accounting_code: categoryDraft.accountingCode || null,
          calendar_code: categoryDraft.calendarCode || null,
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

  async function addRate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createCostRate(
        {
          cost_category_id: Number(rateCategoryId),
          year: Number(rateYear),
          hourly_rate: rateValue,
          currency_code: rateCurrency,
        },
        session,
        onSessionRefresh,
      );
      setRates((prev) => [...prev, created].sort((left, right) => left.year - right.year));
      setRateValue("");
    }, "Taux horaire enregistré.");
  }

  async function saveInflation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const updated = await setInflationRate(
        Number(inflationYear),
        inflationValue,
        session,
        onSessionRefresh,
      );
      setInflation((prev) => {
        const rest = prev.filter((item) => item.year !== updated.year);
        return [...rest, updated].sort((left, right) => left.year - right.year);
      });
    }, "Coefficient d'inflation enregistré.");
  }

  async function addCapacity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createRoleCapacity(
        {
          role_id: Number(capacityRoleId),
          period_start: capacityStart,
          period_end: capacityEnd,
          person_count: personCount,
          available_hours: availableHours,
        },
        session,
        onSessionRefresh,
      );
      setCapacities((prev) => [...prev, created]);
    }, "Capacité enregistrée.");
  }

  async function toggleUserStatus(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    const nextStatus = !user.is_active;
    const action = nextStatus ? "activer" : "désactiver";
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} le compte ${user.email} ?`)) {
      return;
    }
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

  async function toggleUserAdmin(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    const nextAdmin = !user.is_admin;
    const action = nextAdmin ? "promouvoir administrateur" : "retirer les droits administrateur";
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} pour ${user.email} ?`)) {
      return;
    }
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

  async function removeUser(user: AuthUserAdmin) {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!window.confirm(`Supprimer définitivement ${user.email} ?`)) {
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

  const nodeNameById = new Map(nodes.map((node) => [node.id, node.name]));
  const costTypeNameById = new Map(costTypes.map((costType) => [costType.id, costType.name]));
  const categoryNameById = new Map(categories.map((category) => [category.id, category.name]));
  const organizationRows = useMemo(
    () => flattenOrganization(nodes, collapsedNodeIds),
    [nodes, collapsedNodeIds],
  );

  function toggleNodeCollapsed(nodeId: number) {
    setCollapsedNodeIds((previous) => {
      const next = new Set(previous);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }
  const roleNameById = new Map(roles.map((role) => [role.id, role.name]));

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">Paramètres</h1>
            <p className="subtitle">Référentiel entreprise réservé aux administrateurs.</p>
          </div>
        </div>
      </section>

      <nav className="project-tabs" aria-label="Sections des paramètres">
        {(
          [
            ["costs", "Coûts"],
            ["resources", "Ressources"],
            ["users", "Utilisateurs"],
          ] as const
        ).map(([tab, label]) => (
          <button
            key={tab}
            className={`project-tab ${activeTab === tab ? "project-tab-active" : ""}`}
            type="button"
            aria-selected={activeTab === tab}
            role="tab"
            onClick={() => setActiveTab(tab)}
          >
            {label}
          </button>
        ))}
      </nav>

      {notice ? (
        <p className={notice.kind === "error" ? "error" : "success"} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.message}
        </p>
      ) : null}
      {busy ? (
        <section className="panel">
          <p className="muted" role="status">Chargement...</p>
        </section>
      ) : null}

      {!busy && activeTab === "resources" ? (
        <>
          <section className="panel panel-stack">
            <h2>Organisation</h2>
            <form onSubmit={addNode}>
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th scope="col">Code</th><th scope="col">Nom</th><th scope="col">Actions</th></tr></thead>
                  <tbody>
                    <tr>
                      <td><input id="node-code" aria-label="Code du nouveau nœud" value={nodeCode} onChange={(event) => setNodeCode(event.target.value)} required /></td>
                      <td><input id="node-name" aria-label="Nom du nouveau nœud" value={nodeName} onChange={(event) => setNodeName(event.target.value)} required /></td>
                      <td><div className="row"><select id="node-parent" aria-label="Parent du nouveau nœud" value={nodeParentId} onChange={(event) => setNodeParentId(event.target.value)}><option value="">Racine</option>{organizationRows.map((node) => <option key={node.id} value={node.id}>{"  ".repeat(node.depth)}{node.code} - {node.name}</option>)}</select><button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button></div></td>
                    </tr>
                    {organizationRows.map((node) => {
                      const editing = editingNodeId === node.id;
                      return (
                        <tr key={node.id}>
                          <td>
                            <div className="row" style={{ gap: "0.35rem", paddingLeft: `${node.depth * 1.25}rem` }}>
                              {node.hasChildren ? <button className="btn btn-icon" type="button" aria-label={collapsedNodeIds.has(node.id) ? `Déplier ${node.name}` : `Replier ${node.name}`} onClick={() => toggleNodeCollapsed(node.id)}>{collapsedNodeIds.has(node.id) ? "▸" : "▾"}</button> : <span style={{ width: "2rem" }} />}
                              <strong>{node.code}</strong>
                            </div>
                          </td>
                          <td>
                            {editing ? <input aria-label={`Nom de ${node.code}`} value={nodeDraft.name} onChange={(event) => setNodeDraft((previous) => ({ ...previous, name: event.target.value }))} /> : <span>{node.name}</span>}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {editing ? (
                              <div className="row" style={{ justifyContent: "flex-end" }}>
                                <select aria-label={`Parent de ${node.code}`} value={nodeDraft.parentId} onChange={(event) => setNodeDraft((previous) => ({ ...previous, parentId: event.target.value }))}>
                                  <option value="">Racine</option>
                                  {organizationRows.filter((candidate) => candidate.id !== node.id).map((candidate) => <option key={candidate.id} value={candidate.id}>{"  ".repeat(candidate.depth)}{candidate.code} - {candidate.name}</option>)}
                                </select>
                                <button className="btn btn-primary" type="button" disabled={actionBusy} onClick={() => void saveNode(node)}>Enregistrer</button>
                                <button className="btn" type="button" onClick={() => setEditingNodeId(null)}>Annuler</button>
                              </div>
                            ) : <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" type="button" onClick={() => startEditNode(node)}>Modifier</button></div>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </form>
          </section>

          <section className="grid-3">

          <div className="panel">
            <h2>Rôles</h2>
            <form onSubmit={addRole}>
              <div className="field"><label htmlFor="role-code">Code</label><input id="role-code" value={roleCode} onChange={(event) => setRoleCode(event.target.value)} required /></div>
              <div className="field"><label htmlFor="role-name">Nom</label><input id="role-name" value={roleName} onChange={(event) => setRoleName(event.target.value)} required /></div>
              <div className="field"><label htmlFor="role-node">Nœud</label><select id="role-node" value={roleNodeId} onChange={(event) => setRoleNodeId(event.target.value)} required><option value="">Sélectionner</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
              <div className="field"><label htmlFor="role-category">Catégorie</label><select id="role-category" value={roleCategoryId} onChange={(event) => setRoleCategoryId(event.target.value)} required><option value="">Sélectionner</option>{categories.filter((category) => category.is_active).map((category) => <option key={category.id} value={category.id}>{category.code} - {category.name}</option>)}</select></div>
              <button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button>
            </form>
            <ul className="resource-list">{roles.map((role) => <li key={role.id}><strong>{role.code}</strong> {role.name}<span>{nodeNameById.get(role.node_id) ?? "?"} / {categoryNameById.get(role.cost_category_id) ?? "?"}</span></li>)}</ul>
          </div>

          <div className="panel"><h2>Capacités</h2><form onSubmit={addCapacity}><div className="field"><label htmlFor="capacity-role">Rôle</label><select id="capacity-role" value={capacityRoleId} onChange={(event) => setCapacityRoleId(event.target.value)} required><option value="">Sélectionner</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.code} - {role.name}</option>)}</select></div><div className="field"><label htmlFor="capacity-start">Début</label><input id="capacity-start" type="date" value={capacityStart} onChange={(event) => setCapacityStart(event.target.value)} required /></div><div className="field"><label htmlFor="capacity-end">Fin</label><input id="capacity-end" type="date" value={capacityEnd} onChange={(event) => setCapacityEnd(event.target.value)} required /></div><div className="field"><label htmlFor="person-count">Nombre de personnes</label><input id="person-count" type="number" min="0" step="0.01" value={personCount} onChange={(event) => setPersonCount(event.target.value)} required /></div><div className="field"><label htmlFor="available-hours">Heures disponibles</label><input id="available-hours" type="number" min="0" step="0.01" value={availableHours} onChange={(event) => setAvailableHours(event.target.value)} required /></div><button className="btn btn-primary" disabled={actionBusy} type="submit">Enregistrer</button></form></div>
          <div className="panel"><h2>Capacités enregistrées</h2><ul className="resource-list">{capacities.map((capacity) => <li key={capacity.id}><strong>{roleNameById.get(capacity.role_id) ?? "?"}</strong><span>{capacity.period_start} {"->"} {capacity.period_end}</span><span>{capacity.person_count} personnes / {capacity.available_hours} h</span></li>)}</ul></div>
          </section>
        </>
      ) : null}

      {!busy && activeTab === "costs" ? (
        <>
          <section className="panel panel-stack">
            <h2>Types de coût</h2>
            <form onSubmit={addCostType}>
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th scope="col">Code</th><th scope="col">Nom</th><th scope="col">Comportement</th><th scope="col">Actions</th></tr></thead>
                  <tbody>
                    <tr>
                      <td><input id="cost-type-code" aria-label="Code du nouveau type" value={costTypeCode} onChange={(event) => setCostTypeCode(event.target.value)} required /></td>
                      <td><input id="cost-type-name" aria-label="Nom du nouveau type" value={costTypeName} onChange={(event) => setCostTypeName(event.target.value)} required /></td>
                      <td><select aria-label="Comportement du nouveau type" value={costTypeKind} onChange={(event) => setCostTypeKind(event.target.value as CostType["kind"])}><option value="labor">{costTypeKindLabels.labor}</option><option value="supply">{costTypeKindLabels.supply}</option><option value="other">{costTypeKindLabels.other}</option></select></td>
                      <td><button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button></td>
                    </tr>
                    {costTypes.map((costType) => {
                      const editing = editingCostTypeId === costType.id;
                      return (
                        <tr key={costType.id} style={{ opacity: costType.is_active ? 1 : 0.55 }}>
                          <td><strong>{costType.code}</strong></td>
                          <td>{editing ? <input aria-label={`Nom de ${costType.code}`} value={costTypeDraft} onChange={(event) => setCostTypeDraft(event.target.value)} /> : costType.name}</td>
                          <td>{costTypeKindLabels[costType.kind]}</td>
                          <td>
                            <div className="row">
                              {costType.is_active && (editing ? (
                                <>
                                  <button className="btn btn-primary" type="button" disabled={actionBusy} onClick={() => void saveCostType(costType)}>Enregistrer</button>
                                  <button className="btn" type="button" onClick={() => setEditingCostTypeId(null)}>Annuler</button>
                                </>
                              ) : <button className="btn" type="button" onClick={() => startEditCostType(costType)}>Modifier</button>)}
                              <button className="btn" type="button" disabled={actionBusy} onClick={() => void toggleCostTypeActive(costType)}>{costType.is_active ? "Désactiver" : "Réactiver"}</button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </form>
          </section>

          <section className="grid-3">

            <div className="panel">
              <h2>Catégories de coût</h2>
              <form onSubmit={addCategory}>
                <div className="field"><label htmlFor="category-type">Type</label><select id="category-type" value={categoryCostTypeId} onChange={(event) => setCategoryCostTypeId(event.target.value)} required><option value="">Sélectionner</option>{costTypes.filter((costType) => costType.is_active).map((costType) => <option key={costType.id} value={costType.id}>{costType.code} - {costType.name}</option>)}</select></div>
                <div className="field"><label htmlFor="category-code">Code</label><input id="category-code" value={categoryCode} onChange={(event) => setCategoryCode(event.target.value)} required /></div>
                <div className="field"><label htmlFor="accounting-code">Code comptable</label><input id="accounting-code" value={accountingCode} onChange={(event) => setAccountingCode(event.target.value)} /></div>
                <div className="field"><label htmlFor="category-name">Nom</label><input id="category-name" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} required /></div>
                <div className="field"><label htmlFor="calendar-code">Calendrier</label><input id="calendar-code" value={calendarCode} onChange={(event) => setCalendarCode(event.target.value)} /></div>
                <button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button>
              </form>
              <ul className="resource-list">
                {categories.map((category) => {
                  const editing = editingCategoryId === category.id;
                  return (
                    <li key={category.id} style={{ opacity: category.is_active ? 1 : 0.55 }}>
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <div>
                          <strong>{category.code}</strong>{" "}
                          {editing ? (
                            <input
                              value={categoryDraft.name}
                              onChange={(event) => setCategoryDraft((prev) => ({ ...prev, name: event.target.value }))}
                              style={{ display: "inline-block", width: "auto" }}
                            />
                          ) : (
                            category.name
                          )}
                          {category.is_active ? null : <span className="tag" style={{ marginLeft: "0.4rem" }}>Inactive</span>}
                          <span>{costTypeNameById.get(category.cost_type_id) ?? "?"} / {editing ? (
                            <input
                              value={categoryDraft.accountingCode}
                              placeholder="Code comptable"
                              onChange={(event) => setCategoryDraft((prev) => ({ ...prev, accountingCode: event.target.value }))}
                              style={{ display: "inline-block", width: "auto" }}
                            />
                          ) : (category.accounting_code ?? "Sans code comptable")}</span>
                          <span>{editing ? (
                            <input
                              value={categoryDraft.calendarCode}
                              placeholder="Calendrier"
                              onChange={(event) => setCategoryDraft((prev) => ({ ...prev, calendarCode: event.target.value }))}
                              style={{ display: "inline-block", width: "auto" }}
                            />
                          ) : (category.calendar_code ?? "Sans calendrier")}</span>
                        </div>
                        <div className="row">
                          {editing ? (
                            <>
                              <button className="btn btn-primary" type="button" disabled={actionBusy} onClick={() => void saveCategory(category)}>Sauver</button>
                              <button className="btn" type="button" onClick={() => setEditingCategoryId(null)}>Annuler</button>
                            </>
                          ) : (
                            <button className="btn" type="button" onClick={() => startEditCategory(category)}>Modifier</button>
                          )}
                          <button className="btn" type="button" disabled={actionBusy} onClick={() => void toggleCategoryActive(category)}>
                            {category.is_active ? "Désactiver" : "Réactiver"}
                          </button>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>

            <div className="panel"><h2>Inflation</h2><form onSubmit={saveInflation}><div className="field"><label htmlFor="inflation-year">Année</label><input id="inflation-year" type="number" min="2000" value={inflationYear} onChange={(event) => setInflationYear(event.target.value)} required /></div><div className="field"><label htmlFor="inflation-value">Coefficient</label><input id="inflation-value" type="number" min="0.0001" step="0.0001" value={inflationValue} onChange={(event) => setInflationValue(event.target.value)} required /></div><button className="btn btn-primary" disabled={actionBusy} type="submit">Enregistrer</button></form><ul className="resource-list">{inflation.map((item) => <li key={item.id}><strong>{item.year}</strong><span>{item.coefficient}</span></li>)}</ul></div>
          </section>

          <section className="panel panel-stack">
            <h2>Taux horaires</h2>
            <form className="grid-3" onSubmit={addRate}>
              <div className="field"><label htmlFor="rate-category">Catégorie</label><select id="rate-category" value={rateCategoryId} onChange={(event) => setRateCategoryId(event.target.value)} required><option value="">Sélectionner</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.code}</option>)}</select></div>
              <div className="field"><label htmlFor="rate-year">Année</label><input id="rate-year" type="number" min="2000" value={rateYear} onChange={(event) => setRateYear(event.target.value)} required /></div>
              <div className="field"><label htmlFor="rate-value">Taux horaire</label><input id="rate-value" type="number" min="0" step="0.0001" value={rateValue} onChange={(event) => setRateValue(event.target.value)} required /></div>
              <div className="field"><label htmlFor="rate-currency">Devise</label><input id="rate-currency" maxLength={3} value={rateCurrency} onChange={(event) => setRateCurrency(event.target.value)} required /></div>
              <div className="row"><button className="btn btn-primary" disabled={actionBusy} type="submit">Enregistrer le taux</button></div>
            </form>
            <div className="table-scroll"><table className="table"><thead><tr><th scope="col">Année</th><th scope="col">Catégorie</th><th scope="col">Taux</th><th scope="col">Devise</th></tr></thead><tbody>{rates.map((rate) => <tr key={rate.id}><td>{rate.year}</td><td>{categoryNameById.get(rate.cost_category_id) ?? "?"}</td><td>{rate.hourly_rate}</td><td>{rate.currency_code}</td></tr>)}</tbody></table></div>
          </section>
        </>
      ) : null}

      {!busy && activeTab === "users" ? (
        <>
          <section className="panel">
            <div className="row" style={{ marginTop: "0" }}>
              <button className="btn btn-primary" type="button" onClick={() => setCreateUserMode(true)}>
                Ajouter un utilisateur
              </button>
            </div>
            {createUserMode ? (
              <form onSubmit={addUser} style={{ marginTop: "1rem" }}>
                <div className="grid-3">
                  <div className="field">
                    <label htmlFor="new-user-email">Email</label>
                    <input
                      id="new-user-email"
                      type="email"
                      value={newEmail}
                      onChange={(event) => setNewEmail(event.target.value)}
                      autoComplete="off"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="new-user-password">Mot de passe</label>
                    <input
                      id="new-user-password"
                      type="password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      minLength={8}
                      autoComplete="new-password"
                      required
                    />
                  </div>
                </div>
                <div className="row">
                  <button className="btn btn-primary" type="submit" disabled={actionBusy}>
                    {actionBusy ? "Création..." : "Créer"}
                  </button>
                  <button className="btn" type="button" onClick={() => setCreateUserMode(false)}>
                    Annuler
                  </button>
                </div>
              </form>
            ) : null}
          </section>

          <section className="panel">
            {usersError ? <p className="error" role="alert">{usersError}</p> : null}
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">ID</th>
                    <th scope="col">Email</th>
                    <th scope="col">Statut</th>
                    <th scope="col">Role</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td>{user.id}</td>
                      <td>{user.email}</td>
                      <td>{user.is_active ? "Actif" : "Inactif"}</td>
                      <td>{user.is_admin ? "Admin" : "Standard"}</td>
                      <td>
                        <div className="row">
                          <button className="btn" onClick={() => void toggleUserStatus(user)} type="button" disabled={actionBusy}>
                            {user.is_active ? "Désactiver" : "Activer"}
                          </button>
                          <button className="btn" onClick={() => void toggleUserAdmin(user)} type="button" disabled={actionBusy}>
                            {user.is_admin ? "Retirer admin" : "Promouvoir admin"}
                          </button>
                          <button
                            className="btn btn-danger"
                            onClick={() => void removeUser(user)}
                            type="button"
                            disabled={actionBusy}
                          >
                            Supprimer
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </>
  );
}

