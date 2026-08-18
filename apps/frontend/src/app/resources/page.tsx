"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiError,
  CostCategory,
  CostRate,
  InflationRate,
  ResourceNode,
  ResourceRole,
  RoleCapacity,
  SessionExpiredError,
  createCostCategory,
  createCostRate,
  createResourceNode,
  createResourceRole,
  createRoleCapacity,
  getCostCategories,
  getCostRates,
  getInflationRates,
  getResourceNodes,
  getResourceRoles,
  getRoleCapacities,
  restoreSession,
  setInflationRate,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

type Notice = { kind: "error" | "success"; message: string } | null;

export default function ResourcesPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [nodes, setNodes] = useState<ResourceNode[]>([]);
  const [roles, setRoles] = useState<ResourceRole[]>([]);
  const [categories, setCategories] = useState<CostCategory[]>([]);
  const [rates, setRates] = useState<CostRate[]>([]);
  const [inflation, setInflation] = useState<InflationRate[]>([]);
  const [capacities, setCapacities] = useState<RoleCapacity[]>([]);
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const [nodeCode, setNodeCode] = useState("");
  const [nodeName, setNodeName] = useState("");
  const [nodeParentId, setNodeParentId] = useState("");
  const [categoryCode, setCategoryCode] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [calendarCode, setCalendarCode] = useState("");
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
        const [nodeData, roleData, categoryData, rateData, inflationData, capacityData] =
          await Promise.all([
            getResourceNodes(session, onSessionRefresh),
            getResourceRoles(session, onSessionRefresh),
            getCostCategories(session, onSessionRefresh),
            getCostRates(session, onSessionRefresh),
            getInflationRates(session, onSessionRefresh),
            getRoleCapacities(session, onSessionRefresh),
          ]);
        setNodes(nodeData);
        setRoles(roleData);
        setCategories(categoryData);
        setRates(rateData);
        setInflation(inflationData);
        setCapacities(capacityData);
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

  function logout() {
    clearSession();
    router.push("/login");
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
    }, "Noeud créé.");
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    await submitAction(async () => {
      const created = await createCostCategory(
        { code: categoryCode, name: categoryName, calendar_code: calendarCode || null },
        session,
        onSessionRefresh,
      );
      setCategories((prev) => [...prev, created].sort((left, right) => left.code.localeCompare(right.code)));
      setCategoryCode("");
      setCategoryName("");
      setCalendarCode("");
    }, "Catégorie créée.");
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

  const nodeNameById = new Map(nodes.map((node) => [node.id, node.name]));
  const categoryNameById = new Map(categories.map((category) => [category.id, category.name]));
  const roleNameById = new Map(roles.map((role) => [role.id, role.name]));

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">Paramétrage des ressources</h1>
            <p className="subtitle">Référentiel entreprise réservé aux administrateurs.</p>
          </div>
          <button className="btn" onClick={logout} type="button">Déconnexion</button>
        </div>
      </section>

      {notice ? <p className={notice.kind === "error" ? "error" : "success"} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</p> : null}
      {busy ? <section className="panel"><p className="muted" role="status">Chargement...</p></section> : null}

      {!busy ? (
        <>
          <section className="grid-3">
            <div className="panel">
              <h2>Nœuds</h2>
              <form onSubmit={addNode}>
                <div className="field"><label htmlFor="node-code">Code</label><input id="node-code" value={nodeCode} onChange={(event) => setNodeCode(event.target.value)} required /></div>
                <div className="field"><label htmlFor="node-name">Nom</label><input id="node-name" value={nodeName} onChange={(event) => setNodeName(event.target.value)} required /></div>
                <div className="field"><label htmlFor="node-parent">Parent</label><select id="node-parent" value={nodeParentId} onChange={(event) => setNodeParentId(event.target.value)}><option value="">Racine</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
                <button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button>
              </form>
              <ul className="resource-list">{nodes.map((node) => <li key={node.id}><strong>{node.code}</strong> {node.name}<span>{node.parent_id ? `sous ${nodeNameById.get(node.parent_id) ?? "?"}` : "racine"}</span></li>)}</ul>
            </div>

            <div className="panel">
              <h2>Catégories de coût</h2>
              <form onSubmit={addCategory}>
                <div className="field"><label htmlFor="category-code">Code</label><input id="category-code" value={categoryCode} onChange={(event) => setCategoryCode(event.target.value)} required /></div>
                <div className="field"><label htmlFor="category-name">Nom</label><input id="category-name" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} required /></div>
                <div className="field"><label htmlFor="calendar-code">Calendrier</label><input id="calendar-code" value={calendarCode} onChange={(event) => setCalendarCode(event.target.value)} /></div>
                <button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button>
              </form>
              <ul className="resource-list">{categories.map((category) => <li key={category.id}><strong>{category.code}</strong> {category.name}<span>{category.calendar_code ?? "Sans calendrier"}</span></li>)}</ul>
            </div>

            <div className="panel">
              <h2>Rôles</h2>
              <form onSubmit={addRole}>
                <div className="field"><label htmlFor="role-code">Code</label><input id="role-code" value={roleCode} onChange={(event) => setRoleCode(event.target.value)} required /></div>
                <div className="field"><label htmlFor="role-name">Nom</label><input id="role-name" value={roleName} onChange={(event) => setRoleName(event.target.value)} required /></div>
                <div className="field"><label htmlFor="role-node">Nœud</label><select id="role-node" value={roleNodeId} onChange={(event) => setRoleNodeId(event.target.value)} required><option value="">Sélectionner</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
                <div className="field"><label htmlFor="role-category">Catégorie</label><select id="role-category" value={roleCategoryId} onChange={(event) => setRoleCategoryId(event.target.value)} required><option value="">Sélectionner</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.code} - {category.name}</option>)}</select></div>
                <button className="btn btn-primary" disabled={actionBusy} type="submit">Ajouter</button>
              </form>
              <ul className="resource-list">{roles.map((role) => <li key={role.id}><strong>{role.code}</strong> {role.name}<span>{nodeNameById.get(role.node_id) ?? "?"} / {categoryNameById.get(role.cost_category_id) ?? "?"}</span></li>)}</ul>
            </div>
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

          <section className="grid-3">
            <div className="panel"><h2>Inflation</h2><form onSubmit={saveInflation}><div className="field"><label htmlFor="inflation-year">Année</label><input id="inflation-year" type="number" min="2000" value={inflationYear} onChange={(event) => setInflationYear(event.target.value)} required /></div><div className="field"><label htmlFor="inflation-value">Coefficient</label><input id="inflation-value" type="number" min="0.0001" step="0.0001" value={inflationValue} onChange={(event) => setInflationValue(event.target.value)} required /></div><button className="btn btn-primary" disabled={actionBusy} type="submit">Enregistrer</button></form><ul className="resource-list">{inflation.map((item) => <li key={item.id}><strong>{item.year}</strong><span>{item.coefficient}</span></li>)}</ul></div>
            <div className="panel"><h2>Capacités</h2><form onSubmit={addCapacity}><div className="field"><label htmlFor="capacity-role">Rôle</label><select id="capacity-role" value={capacityRoleId} onChange={(event) => setCapacityRoleId(event.target.value)} required><option value="">Sélectionner</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.code} - {role.name}</option>)}</select></div><div className="field"><label htmlFor="capacity-start">Début</label><input id="capacity-start" type="date" value={capacityStart} onChange={(event) => setCapacityStart(event.target.value)} required /></div><div className="field"><label htmlFor="capacity-end">Fin</label><input id="capacity-end" type="date" value={capacityEnd} onChange={(event) => setCapacityEnd(event.target.value)} required /></div><div className="field"><label htmlFor="person-count">Nombre de personnes</label><input id="person-count" type="number" min="0" step="0.01" value={personCount} onChange={(event) => setPersonCount(event.target.value)} required /></div><div className="field"><label htmlFor="available-hours">Heures disponibles</label><input id="available-hours" type="number" min="0" step="0.01" value={availableHours} onChange={(event) => setAvailableHours(event.target.value)} required /></div><button className="btn btn-primary" disabled={actionBusy} type="submit">Enregistrer</button></form></div>
            <div className="panel"><h2>Capacités enregistrées</h2><ul className="resource-list">{capacities.map((capacity) => <li key={capacity.id}><strong>{roleNameById.get(capacity.role_id) ?? "?"}</strong><span>{capacity.period_start} {"->"} {capacity.period_end}</span><span>{capacity.person_count} personnes / {capacity.available_hours} h</span></li>)}</ul></div>
          </section>
        </>
      ) : null}
    </>
  );
}
