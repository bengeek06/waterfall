"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiError,
  AuthUserAdmin,
  CostCategory,
  CostRate,
  CostType,
  ResourceNode,
  ResourceRole,
  RoleCapacity,
  SessionExpiredError,
  createCostCategory,
  createCostRate,
  createCostType,
  createResourceNode,
  createResourceRole,
  deleteResourceNode,
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
  updateCostRate,
  updateCostType,
  updateRoleCapacity,
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
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [roles, setRoles] = useState<ResourceRole[]>([]);
  const [costTypes, setCostTypes] = useState<CostType[]>([]);
  const [categories, setCategories] = useState<CostCategory[]>([]);
  const [rates, setRates] = useState<CostRate[]>([]);
  const [capacities, setCapacities] = useState<RoleCapacity[]>([]);
  const [capacityDrafts, setCapacityDrafts] = useState<Record<number, { personCount: string; availableHours: string }>>({});
  const [users, setUsers] = useState<AuthUserAdmin[]>([]);
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [usersError, setUsersError] = useState<string | null>(null);

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
        setSelectedNodeId((previous) => previous ?? nodeData[0]?.id ?? null);
        setRoleNodeId((previous) => previous || (nodeData[0] ? String(nodeData[0].id) : ""));
        setRoles(roleData);
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

  const costTypeNameById = new Map(costTypes.map((costType) => [costType.id, costType.name]));
  const categoryNameById = new Map(categories.map((category) => [category.id, category.name]));
  const organizationRows = useMemo(
    () => flattenOrganization(nodes, collapsedNodeIds),
    [nodes, collapsedNodeIds],
  );
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
          <div className="master-detail">
          <section className="panel panel-stack">
            <h2>Organisation</h2>
            <form onSubmit={addNode}>
              <div className="table-scroll">
                <table className="table organization-table">
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
                        <tr key={node.id} className={selectedNodeId === node.id ? "organization-row-selected" : ""} onClick={() => selectNode(node.id)}>
                          <td>
                            <div className="row" style={{ gap: "0.35rem", paddingLeft: `${node.depth * 1.25}rem` }}>
                              {node.hasChildren ? <button className="btn btn-icon" type="button" aria-label={collapsedNodeIds.has(node.id) ? `Déplier ${node.name}` : `Replier ${node.name}`} onClick={() => toggleNodeCollapsed(node.id)}>{collapsedNodeIds.has(node.id) ? "▸" : "▾"}</button> : <span style={{ width: "2rem" }} />}
                              {editing ? <input aria-label={`Code de ${node.name}`} value={nodeDraft.code} onChange={(event) => setNodeDraft((previous) => ({ ...previous, code: event.target.value }))} /> : <strong>{node.code}</strong>}
                            </div>
                          </td>
                          <td>
                            {editing ? <input aria-label={`Nom de ${node.code}`} value={nodeDraft.name} onChange={(event) => setNodeDraft((previous) => ({ ...previous, name: event.target.value }))} /> : <span>{node.name}</span>}
                          </td>
                          <td className="table-actions">
                            {editing ? (
                              <div className="row" style={{ justifyContent: "flex-end" }}>
                                <select aria-label={`Parent de ${node.code}`} value={nodeDraft.parentId} onChange={(event) => setNodeDraft((previous) => ({ ...previous, parentId: event.target.value }))}>
                                  <option value="">Racine</option>
                                  {organizationRows.filter((candidate) => candidate.id !== node.id).map((candidate) => <option key={candidate.id} value={candidate.id}>{"  ".repeat(candidate.depth)}{candidate.code} - {candidate.name}</option>)}
                                </select>
                                <button className="btn btn-primary" type="button" disabled={actionBusy} onClick={(event) => { event.stopPropagation(); void saveNode(node); }}>Enregistrer</button>
                                <button className="btn" type="button" onClick={(event) => { event.stopPropagation(); setEditingNodeId(null); }}>Annuler</button>
                              </div>
                            ) : <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn" type="button" onClick={(event) => { event.stopPropagation(); startEditNode(node); }}>Modifier</button><button className="btn btn-danger" type="button" disabled={actionBusy} onClick={(event) => { event.stopPropagation(); void removeNode(node); }}>Supprimer</button></div>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </form>
          </section>

          <div className="panel panel-stack">
            <h2>Rôles {selectedNode ? `de ${selectedNode.name}` : ""}</h2>
            <form onSubmit={addRole}>
              <div className="field"><label htmlFor="role-code">Code</label><input id="role-code" value={roleCode} onChange={(event) => setRoleCode(event.target.value)} required /></div>
              <div className="field"><label htmlFor="role-name">Nom</label><input id="role-name" value={roleName} onChange={(event) => setRoleName(event.target.value)} required /></div>
              <div className="field"><label htmlFor="role-node">Nœud</label><select id="role-node" value={roleNodeId} onChange={(event) => { setRoleNodeId(event.target.value); setSelectedNodeId(Number(event.target.value)); }} required><option value="">Sélectionner</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
              <div className="field"><label htmlFor="role-category">Code comptable</label><select id="role-category" value={roleCategoryId} onChange={(event) => setRoleCategoryId(event.target.value)} required><option value="">Sélectionner</option>{categories.filter((category) => category.is_active && costTypes.some((costType) => costType.id === category.cost_type_id && costType.kind === "labor")).map((category) => <option key={category.id} value={category.id}>{category.accounting_code} - {category.name}</option>)}</select></div>
              <button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button>
            </form>
            <ul className="resource-list">{selectedRoles.map((role) => <li key={role.id}><strong>{role.code}</strong> {role.name}<span>{categoryNameById.get(role.cost_category_id) ?? "?"}</span></li>)}</ul>
          </div>

          </div>
          <div className="panel panel-stack"><h2>Capacités</h2><div className="table-scroll"><table className="table"><thead><tr><th scope="col">Rôle</th><th scope="col">Nombre de personnes</th><th scope="col">Heures disponibles</th><th scope="col">Actions</th></tr></thead><tbody>{roles.map((role) => { const draft = capacityDrafts[role.id] ?? { personCount: "0.00", availableHours: "0.00" }; return <tr key={role.id}><td><strong>{role.code}</strong> {role.name}</td><td><input type="number" min="0" step="0.01" value={draft.personCount} onChange={(event) => setCapacityDrafts((previous) => ({ ...previous, [role.id]: { ...draft, personCount: event.target.value } }))} /></td><td><input type="number" min="0" step="0.01" value={draft.availableHours} onChange={(event) => setCapacityDrafts((previous) => ({ ...previous, [role.id]: { ...draft, availableHours: event.target.value } }))} /></td><td className="table-actions"><button className="btn btn-primary" type="button" disabled={actionBusy} onClick={() => void saveRoleCapacity(role.id)}>Enregistrer</button></td></tr>; })}</tbody></table></div></div>
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
                          <td className="table-actions">
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

          <section className="panel panel-stack">
              <h2>Catégories de coût</h2>
              <form onSubmit={addCategory}>
                <div className="table-scroll">
                  <table className="table">
                    <thead><tr><th scope="col">Type</th><th scope="col">Code comptable</th><th scope="col">Catégorie comptable</th><th scope="col">Nom</th><th scope="col">Actions</th></tr></thead>
                    <tbody>
                      <tr>
                        <td><select id="category-type" aria-label="Type de la nouvelle catégorie" value={categoryCostTypeId} onChange={(event) => setCategoryCostTypeId(event.target.value)} required><option value="">Sélectionner</option>{costTypes.filter((costType) => costType.is_active).map((costType) => <option key={costType.id} value={costType.id}>{costType.code} - {costType.name}</option>)}</select></td>
                        <td><input id="category-code" aria-label="Code comptable de la nouvelle catégorie" value={categoryCode} onChange={(event) => setCategoryCode(event.target.value)} required /></td>
                        <td><input id="accounting-code" aria-label="Catégorie comptable de la nouvelle catégorie" value={accountingCode} onChange={(event) => setAccountingCode(event.target.value)} /></td>
                        <td><input id="category-name" aria-label="Nom de la nouvelle catégorie" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} required /></td>
                        <td><button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button></td>
                      </tr>
                      {categories.map((category) => {
                        const editing = editingCategoryId === category.id;
                        return (
                          <tr key={category.id} style={{ opacity: category.is_active ? 1 : 0.55 }}>
                            <td>{costTypeNameById.get(category.cost_type_id) ?? "?"}</td>
                            <td>{editing ? <input aria-label={`Code comptable de ${category.accounting_code}`} value={categoryDraft.code} onChange={(event) => setCategoryDraft((previous) => ({ ...previous, code: event.target.value }))} /> : <strong>{category.accounting_code}</strong>}</td>
                            <td>{editing ? <input aria-label={`Catégorie comptable de ${category.accounting_code}`} value={categoryDraft.accountingCode} onChange={(event) => setCategoryDraft((previous) => ({ ...previous, accountingCode: event.target.value }))} /> : (category.category_code ?? "Sans catégorie")}</td>
                            <td>{editing ? <input aria-label={`Nom de ${category.accounting_code}`} value={categoryDraft.name} onChange={(event) => setCategoryDraft((previous) => ({ ...previous, name: event.target.value }))} /> : category.name}{category.is_active ? null : <span className="tag" style={{ marginLeft: "0.4rem" }}>Inactive</span>}</td>
                            <td className="table-actions">
                              <div className="row" style={{ justifyContent: "flex-end" }}>
                                {editing ? <><button className="btn btn-primary" type="button" disabled={actionBusy} onClick={() => void saveCategory(category)}>Enregistrer</button><button className="btn" type="button" onClick={() => setEditingCategoryId(null)}>Annuler</button></> : <button className="btn" type="button" onClick={() => startEditCategory(category)}>Modifier</button>}
                                <button className="btn" type="button" disabled={actionBusy} onClick={() => void toggleCategoryActive(category)}>{category.is_active ? "Désactiver" : "Réactiver"}</button>
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

          <section className="panel panel-stack">
            <h2>Valorisation</h2>
            <div className="grid-3">
              <div className="field"><label htmlFor="display-currency">Devise</label><select id="display-currency" value={displayCurrency} onChange={(event) => setDisplayCurrency(event.target.value)}><option value="EUR">EUR</option><option value="USD">Dollar</option></select></div>
              <div>
                <div className="field"><label htmlFor="inflation-year">Inflation ({inflationYear})</label><div className="row"><input id="inflation-value" type="number" min="-100" step="0.01" value={inflationValue} onChange={(event) => setInflationValue(event.target.value)} placeholder="Pourcentage" /><span>%</span></div></div>
              </div>
            </div>
            <div className="table-scroll">
              <table className="table">
                <thead><tr><th scope="col">Code comptable</th>{[-4, -3, -2, -1, 0].map((offset) => { const year = new Date().getFullYear() + offset; return <th scope="col" key={year} style={offset === 0 ? { background: "var(--accent-soft)" } : undefined}>{year}</th>; })}</tr></thead>
                <tbody>{categories.filter((category) => costTypes.find((type) => type.id === category.cost_type_id)?.kind === "labor").map((category) => <tr key={category.id}><td><strong>{category.accounting_code}</strong></td>{[-4, -3, -2, -1, 0].map((offset) => { const year = new Date().getFullYear() + offset; const key = `${category.id}:${year}`; return <td key={year} style={offset === 0 ? { background: "var(--accent-soft)" } : undefined}><input aria-label={`${category.accounting_code} ${year}`} type="number" step="0.01" min="0" value={rateDrafts[key] ?? ""} onChange={(event) => setRateDrafts((previous) => ({ ...previous, [key]: event.target.value }))} placeholder="-" /></td>; })}</tr>)}</tbody>
              </table>
            </div>
            <div className="row" style={{ justifyContent: "flex-end" }}><button className="btn btn-primary" type="button" disabled={actionBusy} onClick={() => void saveAllValuation()}>Enregistrer</button></div>
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

