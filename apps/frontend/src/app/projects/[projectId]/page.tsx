"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createProjectEstimate,
  getProject,
  listEstimateCostLines,
  listEstimateTaskRows,
  listProjectEstimates,
  Project,
  ProjectEstimate,
  SessionExpiredError,
  Task,
  getProjectTasks,
  restoreSession,
  updateTaskDescription,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

const TASK_PAGE_SIZE = 200;
type ProjectTab = "planning" | "estimate" | "commitments" | "analytics";

export default function ProjectDetailsPage() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId);

  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [tasks, setTasks] = useState<Task[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [estimates, setEstimates] = useState<ProjectEstimate[]>([]);
  const [selectedEstimateId, setSelectedEstimateId] = useState<number | null>(null);
  const [estimateTaskRowCount, setEstimateTaskRowCount] = useState(0);
  const [estimateCostLineCount, setEstimateCostLineCount] = useState(0);
  const [activeTab, setActiveTab] = useState<ProjectTab>("planning");
  const [taskOffset, setTaskOffset] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [savingTaskUid, setSavingTaskUid] = useState<number | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  useEffect(() => {
    async function load() {
      if (!session || Number.isNaN(projectId)) {
        if (!session) {
          try {
            const restoredSession = await restoreSession();
            setSession(restoredSession);
            setSessionState(restoredSession);
          } catch {
            clearSession();
            router.push("/login");
          }
        }
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const [projectData, estimatesData] = await Promise.all([
          getProject(projectId, session, onSessionRefresh),
          listProjectEstimates(projectId, session, onSessionRefresh),
        ]);
        setProject(projectData);
        setEstimates(estimatesData);
        setSelectedEstimateId((current) => current ?? estimatesData.at(-1)?.id ?? null);
        const tasksData = await getProjectTasks(
          projectId,
          session,
          onSessionRefresh,
          TASK_PAGE_SIZE,
          taskOffset,
        );
        setTasks(tasksData);
        const initialDrafts: Record<number, string> = {};
        for (const task of tasksData) {
          initialDrafts[task.uid] = task.description ?? "";
        }
        setDrafts(initialDrafts);
      } catch (cause) {
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError) {
          if (cause.status === 401) {
            clearSession();
            router.push("/login");
            return;
          }
          setError(cause.message);
        } else {
          setError("Erreur inattendue lors du chargement des tâches");
        }
      } finally {
        setBusy(false);
      }
    }

    void load();
  }, [onSessionRefresh, projectId, router, session, taskOffset]);

  useEffect(() => {
    async function loadEstimateDetails() {
      if (!session || selectedEstimateId === null) {
        setEstimateTaskRowCount(0);
        setEstimateCostLineCount(0);
        return;
      }
      try {
        const [taskRows, costLines] = await Promise.all([
          listEstimateTaskRows(projectId, selectedEstimateId, session, onSessionRefresh),
          listEstimateCostLines(projectId, selectedEstimateId, session, onSessionRefresh),
        ]);
        setEstimateTaskRowCount(taskRows.length);
        setEstimateCostLineCount(costLines.length);
      } catch (cause) {
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger le devis.");
      }
    }

    void loadEstimateDetails();
  }, [onSessionRefresh, projectId, router, selectedEstimateId, session]);

  async function createDraftEstimate() {
    if (!session) {
      router.push("/login");
      return;
    }
    setError(null);
    try {
      const estimate = await createProjectEstimate(
        projectId,
        { kind: "initial", currency_code: project?.currency_code ?? "EUR" },
        session,
        onSessionRefresh,
      );
      setEstimates((previous) => [...previous, estimate]);
      setSelectedEstimateId(estimate.id);
      setActiveTab("estimate");
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de créer le devis.");
    }
  }

  async function saveDescription(task: Task) {
    if (!session) {
      return;
    }
    if (savingTaskUid === task.uid) {
      return;
    }

    const draft = (drafts[task.uid] ?? "").trim();
    const description = draft.length ? draft : null;

    setSavingTaskUid(task.uid);
    try {
      const updated = await updateTaskDescription(
        projectId,
        task.uid,
        description,
        session,
        onSessionRefresh,
      );
      setTasks((prev) => prev.map((item) => (item.uid === updated.uid ? updated : item)));
      setDrafts((prev) => ({ ...prev, [task.uid]: updated.description ?? "" }));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Sauvegarde impossible");
    } finally {
      setSavingTaskUid(null);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">{project?.name ?? `Projet #${projectId}`}</h1>
            <p className="subtitle">Pilotage du planning et des versions de devis.</p>
          </div>
          <Link href="/projects" className="btn">
            Retour projets
          </Link>
        </div>
      </section>

      <nav className="project-tabs" aria-label="Sections du projet">
        {([
          ["planning", "Planning"],
          ["estimate", "Devis"],
          ["commitments", "Reste à engager"],
          ["analytics", "Analytique"],
        ] as const).map(([tab, label]) => (
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

      <section className="panel">
        {busy ? <p className="muted" role="status">Chargement...</p> : null}
        {error ? <p className="error" role="alert">{error}</p> : null}

        {activeTab === "planning" && !busy && !tasks.length ? <p className="muted">Aucune tâche.</p> : null}

        {activeTab === "planning" && !busy && tasks.length ? (
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">UID</th>
                <th scope="col">Nom</th>
                <th scope="col">Avancement</th>
                <th scope="col">Description</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.uid}>
                  <td>{task.uid}</td>
                  <td>
                    <strong>{task.name}</strong>
                    <div className="muted">{task.outline_number ?? "-"}</div>
                  </td>
                  <td>{task.percent_complete ?? 0}%</td>
                  <td style={{ minWidth: "280px" }}>
                    <textarea
                      rows={3}
                      value={drafts[task.uid] ?? ""}
                      onChange={(event) =>
                        setDrafts((prev) => ({ ...prev, [task.uid]: event.target.value }))
                      }
                    />
                  </td>
                  <td>
                    <button
                      className="btn btn-primary"
                      disabled={savingTaskUid === task.uid}
                      onClick={() => void saveDescription(task)}
                    >
                      {savingTaskUid === task.uid ? "Sauvegarde..." : "Sauver"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : null}

        {activeTab === "planning" && !busy ? (
          <div className="row" style={{ marginTop: "1rem", justifyContent: "space-between" }}>
            <span className="muted">
              {tasks.length ? `Tâches ${taskOffset + 1} à ${taskOffset + tasks.length}` : ""}
            </span>
            <div className="row">
              <button
                className="btn"
                type="button"
                disabled={taskOffset === 0}
                onClick={() => setTaskOffset((current) => Math.max(0, current - TASK_PAGE_SIZE))}
              >
                Précédent
              </button>
              <button
                className="btn"
                type="button"
                disabled={tasks.length < TASK_PAGE_SIZE}
                onClick={() => setTaskOffset((current) => current + TASK_PAGE_SIZE)}
              >
                Suivant
              </button>
            </div>
          </div>
        ) : null}

        {activeTab === "estimate" ? (
          <div className="tab-content">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>Versions de devis</h2>
                <p className="muted">Les versions sont préparées par l’API et seront éditables dans le jalon 7.</p>
              </div>
              <div className="row">
                {estimates.length ? (
                  <label className="estimate-select-label">
                    Version
                    <select
                      value={selectedEstimateId ?? ""}
                      onChange={(event) => setSelectedEstimateId(Number(event.target.value))}
                    >
                      {estimates.map((estimate) => (
                        <option key={estimate.id} value={estimate.id}>V{estimate.version_number}</option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <button className="btn btn-primary" type="button" onClick={() => void createDraftEstimate()}>
                  Nouveau brouillon
                </button>
              </div>
            </div>
            {!estimates.length ? <p className="muted empty-state">Aucune version de devis.</p> : null}
            {estimates.length ? (
              <div className="estimate-summary">
                <div className="estimate-metric"><strong>{estimateTaskRowCount}</strong><span>tâches snapshotées</span></div>
                <div className="estimate-metric"><strong>{estimateCostLineCount}</strong><span>lignes de coût</span></div>
                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr><th scope="col">Version</th><th scope="col">Nature</th><th scope="col">Statut</th><th scope="col">Devise</th></tr>
                    </thead>
                    <tbody>
                      {estimates.map((estimate) => (
                        <tr key={estimate.id}>
                          <td>V{estimate.version_number}</td>
                          <td>{estimate.kind}</td>
                          <td><span className="tag">{estimate.status}</span></td>
                          <td>{estimate.currency_code}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {activeTab === "commitments" ? (
          <div className="tab-placeholder">
            <h2>Reste à engager</h2>
            <p className="muted">La saisie des engagements sera ajoutée avec l’analyse financière du jalon 8.</p>
          </div>
        ) : null}

        {activeTab === "analytics" ? (
          <div className="tab-placeholder">
            <h2>Analytique</h2>
            <p className="muted">Les agrégats et graphiques seront branchés sur les snapshots validés au jalon 8.</p>
          </div>
        ) : null}
      </section>
    </>
  );
}
