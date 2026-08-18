"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  CostCategory,
  createEstimateCostLine,
  createImportBatch,
  createProjectEstimate,
  createProjectTask,
  deleteEstimateCostLine,
  deleteProjectTask,
  EstimateAggregates,
  EstimateCostLine,
  exportEstimateExcel,
  exportProjectXml,
  getCostCategories,
  getCostTypes,
  getEstimateAggregates,
  getImportBatchStatus,
  getProject,
  listEstimateCostLines,
  listEstimateTaskRows,
  listProjectEstimates,
  Project,
  ProjectEstimate,
  runImportBatch,
  SessionExpiredError,
  Task,
  getProjectTasks,
  restoreSession,
  updateEstimateCostLine,
  updateProject,
  updateTaskDescription,
  uploadImportSourceXml,
  validateProjectEstimate,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";
import { ReadOnlyGantt } from "@/components/read-only-gantt";

const TASK_PAGE_SIZE = 200;
const MAX_IMPORT_FILE_SIZE = 25 * 1024 * 1024;
type ProjectTab = "planning" | "estimate" | "commitments" | "analytics";

export default function ProjectDetailsPage() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId);

  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [tasks, setTasks] = useState<Task[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [editingProjectInfo, setEditingProjectInfo] = useState(false);
  const [projectInfoDraft, setProjectInfoDraft] = useState({ name: "", shortDescription: "" });
  const [projectInfoBusy, setProjectInfoBusy] = useState(false);
  const [planningExportBusy, setPlanningExportBusy] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [estimates, setEstimates] = useState<ProjectEstimate[]>([]);
  const [selectedEstimateId, setSelectedEstimateId] = useState<number | null>(null);
  const [estimateTaskRowCount, setEstimateTaskRowCount] = useState(0);
  const [costLines, setCostLines] = useState<EstimateCostLine[]>([]);
  const [costCategories, setCostCategories] = useState<CostCategory[]>([]);
  const [costLineDraft, setCostLineDraft] = useState({
    categoryId: "",
    label: "",
    quantity: "1",
    unitCost: "0",
  });
  const [editingLineId, setEditingLineId] = useState<number | null>(null);
  const [editingLineDraft, setEditingLineDraft] = useState({ label: "", quantity: "", unitCost: "" });
  const [estimateBusy, setEstimateBusy] = useState(false);
  const [aggregates, setAggregates] = useState<EstimateAggregates | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<ProjectTab>("planning");
  const [taskOffset, setTaskOffset] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [savingTaskUid, setSavingTaskUid] = useState<number | null>(null);
  const [taskDraft, setTaskDraft] = useState({ name: "", parentTaskId: "", isMilestone: false });
  const [taskBusy, setTaskBusy] = useState(false);
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
        setCostLines([]);
        return;
      }
      try {
        const [taskRows, lines] = await Promise.all([
          listEstimateTaskRows(projectId, selectedEstimateId, session, onSessionRefresh),
          listEstimateCostLines(projectId, selectedEstimateId, session, onSessionRefresh),
        ]);
        setEstimateTaskRowCount(taskRows.length);
        setCostLines(lines);
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

  useEffect(() => {
    async function loadCostCategories() {
      if (!session) {
        return;
      }
      try {
        const [categories, types] = await Promise.all([
          getCostCategories(session, onSessionRefresh),
          getCostTypes(session, onSessionRefresh),
        ]);
        const laborTypeIds = new Set(types.filter((type) => type.code === "MO").map((type) => type.id));
        setCostCategories(categories.filter((category) => !laborTypeIds.has(category.cost_type_id)));
      } catch {
        // Non-blocking: the add-line form simply stays disabled without categories.
      }
    }

    void loadCostCategories();
  }, [onSessionRefresh, session]);

  useEffect(() => {
    async function loadAggregates() {
      if (!session || selectedEstimateId === null || activeTab !== "analytics") {
        return;
      }
      try {
        const data = await getEstimateAggregates(projectId, selectedEstimateId, session, onSessionRefresh);
        setAggregates(data);
      } catch (cause) {
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger les agrégats.");
      }
    }

    void loadAggregates();
  }, [activeTab, onSessionRefresh, projectId, router, selectedEstimateId, session]);

  const selectedEstimate = estimates.find((estimate) => estimate.id === selectedEstimateId) ?? null;
  const canEditEstimate = selectedEstimate?.status === "draft";

  async function exportExcel() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    setExportBusy(true);
    setError(null);
    try {
      const blob = await exportEstimateExcel(projectId, selectedEstimateId, session, onSessionRefresh);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `devis-${project?.name ?? projectId}-v${selectedEstimate?.version_number ?? ""}.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'exporter le devis.");
    } finally {
      setExportBusy(false);
    }
  }

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

  async function addCostLine() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const categoryId = Number(costLineDraft.categoryId);
    const quantity = Number(costLineDraft.quantity);
    const unitCost = Number(costLineDraft.unitCost);
    if (!categoryId || !costLineDraft.label.trim() || !(quantity > 0) || unitCost < 0) {
      setError("Renseigne une catégorie, un libellé, une quantité et un coût unitaire valides.");
      return;
    }

    setEstimateBusy(true);
    setError(null);
    try {
      const line = await createEstimateCostLine(
        projectId,
        selectedEstimateId,
        {
          cost_category_id: categoryId,
          label: costLineDraft.label.trim(),
          quantity,
          unit_cost: unitCost,
        },
        session,
        onSessionRefresh,
      );
      setCostLines((previous) => [...previous, line]);
      setCostLineDraft({ categoryId: "", label: "", quantity: "1", unitCost: "0" });
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'ajouter la ligne de coût.");
    } finally {
      setEstimateBusy(false);
    }
  }

  function startEditCostLine(line: EstimateCostLine) {
    setEditingLineId(line.id);
    setEditingLineDraft({
      label: line.label,
      quantity: String(line.quantity),
      unitCost: String(line.unit_cost),
    });
  }

  async function saveCostLine(line: EstimateCostLine) {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const quantity = Number(editingLineDraft.quantity);
    const unitCost = Number(editingLineDraft.unitCost);
    if (!editingLineDraft.label.trim() || !(quantity > 0) || unitCost < 0) {
      setError("Libellé, quantité et coût unitaire doivent être valides.");
      return;
    }

    setEstimateBusy(true);
    setError(null);
    try {
      const updated = await updateEstimateCostLine(
        projectId,
        selectedEstimateId,
        line.id,
        { label: editingLineDraft.label.trim(), quantity, unit_cost: unitCost },
        session,
        onSessionRefresh,
      );
      setCostLines((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
      setEditingLineId(null);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier la ligne de coût.");
    } finally {
      setEstimateBusy(false);
    }
  }

  async function removeCostLine(line: EstimateCostLine) {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const confirmed = window.confirm(`Supprimer la ligne "${line.label}" ?`);
    if (!confirmed) {
      return;
    }

    setEstimateBusy(true);
    setError(null);
    try {
      await deleteEstimateCostLine(projectId, selectedEstimateId, line.id, session, onSessionRefresh);
      setCostLines((previous) => previous.filter((item) => item.id !== line.id));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de supprimer la ligne de coût.");
    } finally {
      setEstimateBusy(false);
    }
  }

  async function validateEstimate() {
    if (!session || selectedEstimateId === null) {
      return;
    }
    const confirmed = window.confirm("Valider ce devis ? Il deviendra immuable.");
    if (!confirmed) {
      return;
    }

    setEstimateBusy(true);
    setError(null);
    try {
      const validated = await validateProjectEstimate(
        projectId,
        selectedEstimateId,
        session,
        onSessionRefresh,
      );
      setEstimates((previous) => previous.map((item) => (item.id === validated.id ? validated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de valider le devis.");
    } finally {
      setEstimateBusy(false);
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

  async function addTask() {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!taskDraft.name.trim()) {
      setError("Le nom de la tâche est obligatoire.");
      return;
    }

    setTaskBusy(true);
    setError(null);
    try {
      const created = await createProjectTask(
        projectId,
        {
          name: taskDraft.name.trim(),
          parent_task_id: taskDraft.parentTaskId ? Number(taskDraft.parentTaskId) : null,
          is_milestone: taskDraft.isMilestone,
        },
        session,
        onSessionRefresh,
      );
      setTasks((previous) => [...previous, created]);
      setDrafts((previous) => ({ ...previous, [created.uid]: "" }));
      setTaskDraft({ name: "", parentTaskId: "", isMilestone: false });
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'ajouter la tâche.");
    } finally {
      setTaskBusy(false);
    }
  }

  async function removeTask(task: Task) {
    if (!session) {
      return;
    }
    const confirmed = window.confirm(`Supprimer la tâche "${task.name}" ?`);
    if (!confirmed) {
      return;
    }

    setTaskBusy(true);
    setError(null);
    try {
      await deleteProjectTask(projectId, task.uid, session, onSessionRefresh);
      setTasks((previous) => previous.filter((item) => item.uid !== task.uid));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de supprimer la tâche.");
    } finally {
      setTaskBusy(false);
    }
  }

  function startEditProjectInfo() {
    if (!project) {
      return;
    }
    setProjectInfoDraft({ name: project.name, shortDescription: project.short_description ?? "" });
    setEditingProjectInfo(true);
  }

  async function saveProjectInfo() {
    if (!session || !project) {
      return;
    }
    if (!projectInfoDraft.name.trim()) {
      setError("Le nom du projet est obligatoire.");
      return;
    }

    setProjectInfoBusy(true);
    setError(null);
    try {
      const updated = await updateProject(
        projectId,
        {
          name: projectInfoDraft.name.trim(),
          short_description: projectInfoDraft.shortDescription.trim() || null,
        },
        session,
        onSessionRefresh,
      );
      setProject(updated);
      setEditingProjectInfo(false);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le projet.");
    } finally {
      setProjectInfoBusy(false);
    }
  }

  async function exportPlanningXml() {
    if (!session || !project) {
      return;
    }
    setPlanningExportBusy(true);
    setError(null);
    try {
      const blob = await exportProjectXml(projectId, session, onSessionRefresh);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${project.name || `project-${projectId}`}.xml`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'exporter le planning.");
    } finally {
      setPlanningExportBusy(false);
    }
  }

  async function importPlanningXml() {
    if (!session || !project || !importFile) {
      return;
    }
    setImportBusy(true);
    setError(null);
    try {
      const batch = await createImportBatch(projectId, project.name, session, onSessionRefresh);
      await uploadImportSourceXml(batch.id, importFile, session, onSessionRefresh);
      await runImportBatch(batch.id, session, onSessionRefresh);

      let batchStatus = await getImportBatchStatus(batch.id, session, onSessionRefresh);
      for (let index = 0; index < 20; index += 1) {
        if (batchStatus.status === "success" || batchStatus.status === "failed") {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        batchStatus = await getImportBatchStatus(batch.id, session, onSessionRefresh);
      }
      if (batchStatus.status !== "success") {
        throw new Error(batchStatus.errorMessage ?? "Import en échec.");
      }

      const tasksData = await getProjectTasks(
        projectId,
        session,
        onSessionRefresh,
        TASK_PAGE_SIZE,
        taskOffset,
      );
      setTasks(tasksData);
      const refreshedDrafts: Record<number, string> = {};
      for (const task of tasksData) {
        refreshedDrafts[task.uid] = task.description ?? "";
      }
      setDrafts(refreshedDrafts);
      setImportFile(null);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'importer le planning.");
    } finally {
      setImportBusy(false);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div style={{ flex: 1 }}>
            {editingProjectInfo ? (
              <div style={{ maxWidth: "34rem" }}>
                <div className="field">
                  <label htmlFor="project-info-name">Nom du projet</label>
                  <input
                    id="project-info-name"
                    value={projectInfoDraft.name}
                    onChange={(event) =>
                      setProjectInfoDraft((prev) => ({ ...prev, name: event.target.value }))
                    }
                    maxLength={255}
                  />
                </div>
                <div className="field">
                  <label htmlFor="project-info-description">Description courte</label>
                  <textarea
                    id="project-info-description"
                    rows={2}
                    value={projectInfoDraft.shortDescription}
                    onChange={(event) =>
                      setProjectInfoDraft((prev) => ({ ...prev, shortDescription: event.target.value }))
                    }
                    maxLength={500}
                  />
                </div>
                <div className="row">
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={projectInfoBusy}
                    onClick={() => void saveProjectInfo()}
                  >
                    Sauver
                  </button>
                  <button className="btn" type="button" onClick={() => setEditingProjectInfo(false)}>
                    Annuler
                  </button>
                </div>
              </div>
            ) : (
              <>
                <h1 className="title">{project?.name ?? `Projet #${projectId}`}</h1>
                <p className="subtitle">
                  {project?.short_description ?? "Pilotage du planning et des versions de devis."}
                </p>
                <button className="btn" type="button" onClick={startEditProjectInfo}>
                  Modifier
                </button>
              </>
            )}
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

        {activeTab === "planning" ? (
          <div className="row cost-line-form" style={{ marginBottom: "1rem", justifyContent: "space-between" }}>
            <div className="row">
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="planning-import-file">Importer un planning MS Project (.xml)</label>
                <input
                  id="planning-import-file"
                  type="file"
                  accept=".xml,application/xml,text/xml"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    if (file && file.size > MAX_IMPORT_FILE_SIZE) {
                      setImportFile(null);
                      setError("Le fichier XML ne doit pas dépasser 25 MiB.");
                      event.target.value = "";
                      return;
                    }
                    setError(null);
                    setImportFile(file);
                  }}
                />
              </div>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!importFile || importBusy}
                onClick={() => void importPlanningXml()}
              >
                {importBusy ? "Import..." : "Importer"}
              </button>
            </div>
            <button
              className="btn"
              type="button"
              disabled={planningExportBusy}
              onClick={() => void exportPlanningXml()}
            >
              {planningExportBusy ? "Export..." : "Export XML"}
            </button>
          </div>
        ) : null}

        {activeTab === "planning" ? (
          <div className="row cost-line-form" style={{ marginBottom: "1rem" }}>
            <div className="field">
              <label htmlFor="task-name">Nom de la tâche</label>
              <input
                id="task-name"
                value={taskDraft.name}
                onChange={(event) => setTaskDraft((prev) => ({ ...prev, name: event.target.value }))}
              />
            </div>
            <label className="estimate-select-label">
              Tâche parente
              <select
                value={taskDraft.parentTaskId}
                onChange={(event) =>
                  setTaskDraft((prev) => ({ ...prev, parentTaskId: event.target.value }))
                }
              >
                <option value="">Aucune (racine)</option>
                {tasks.map((task) => (
                  <option key={task.id} value={task.id}>
                    {task.outline_number ?? task.uid} — {task.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="row" style={{ gap: "0.4rem" }}>
              <input
                type="checkbox"
                checked={taskDraft.isMilestone}
                onChange={(event) =>
                  setTaskDraft((prev) => ({ ...prev, isMilestone: event.target.checked }))
                }
              />
              Jalon
            </label>
            <button className="btn btn-primary" type="button" disabled={taskBusy} onClick={() => void addTask()}>
              Ajouter la tâche
            </button>
          </div>
        ) : null}

        {activeTab === "planning" && !busy && !tasks.length ? <p className="muted">Aucune tâche.</p> : null}

        {activeTab === "planning" && !busy && tasks.length ? (
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">UID</th>
                <th scope="col">Nom</th>
                <th scope="col">Début</th>
                <th scope="col">Fin</th>
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
                    <strong>
                      {task.is_milestone ? "◆ " : ""}
                      {task.name}
                    </strong>
                    <div className="muted">{task.outline_number ?? "-"}</div>
                  </td>
                  <td>{task.start_at ? new Date(task.start_at).toLocaleDateString("fr-FR") : "-"}</td>
                  <td>{task.finish_at ? new Date(task.finish_at).toLocaleDateString("fr-FR") : "-"}</td>
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
                    <div className="row">
                      <button
                        className="btn btn-primary"
                        disabled={savingTaskUid === task.uid}
                        onClick={() => void saveDescription(task)}
                      >
                        {savingTaskUid === task.uid ? "Sauvegarde..." : "Sauver"}
                      </button>
                      <button
                        className="btn btn-danger"
                        type="button"
                        disabled={taskBusy}
                        onClick={() => void removeTask(task)}
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

        {activeTab === "planning" && !busy && tasks.length ? <ReadOnlyGantt tasks={tasks} /> : null}

        {activeTab === "estimate" ? (
          <div className="tab-content">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>Versions de devis</h2>
                <p className="muted">
                  {canEditEstimate
                    ? "Le brouillon sélectionné est éditable."
                    : "Cette version n'est plus modifiable."}
                </p>
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
                        <option key={estimate.id} value={estimate.id}>
                          V{estimate.version_number} ({estimate.status})
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <button className="btn btn-primary" type="button" onClick={() => void createDraftEstimate()}>
                  Nouveau brouillon
                </button>
                {estimates.length ? (
                  <button
                    className="btn"
                    type="button"
                    disabled={exportBusy}
                    onClick={() => void exportExcel()}
                  >
                    {exportBusy ? "Export..." : "Export Excel"}
                  </button>
                ) : null}
                {canEditEstimate ? (
                  <button
                    className="btn"
                    type="button"
                    disabled={estimateBusy}
                    onClick={() => void validateEstimate()}
                  >
                    Valider le devis
                  </button>
                ) : null}
              </div>
            </div>
            {!estimates.length ? <p className="muted empty-state">Aucune version de devis.</p> : null}

            {estimates.length ? (
              <div className="estimate-summary">
                <div className="estimate-metric">
                  <strong>{estimateTaskRowCount}</strong>
                  <span>tâches snapshotées</span>
                </div>
                <div className="estimate-metric">
                  <strong>{costLines.length}</strong>
                  <span>lignes de coût</span>
                </div>

                {canEditEstimate ? (
                  <div className="cost-line-form row">
                    <label className="estimate-select-label">
                      Catégorie
                      <select
                        value={costLineDraft.categoryId}
                        onChange={(event) =>
                          setCostLineDraft((prev) => ({ ...prev, categoryId: event.target.value }))
                        }
                      >
                        <option value="">Choisir...</option>
                        {costCategories.map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="field">
                      <label htmlFor="cost-line-label">Libellé</label>
                      <input
                        id="cost-line-label"
                        value={costLineDraft.label}
                        onChange={(event) =>
                          setCostLineDraft((prev) => ({ ...prev, label: event.target.value }))
                        }
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="cost-line-quantity">Quantité</label>
                      <input
                        id="cost-line-quantity"
                        type="number"
                        min="0"
                        step="0.01"
                        value={costLineDraft.quantity}
                        onChange={(event) =>
                          setCostLineDraft((prev) => ({ ...prev, quantity: event.target.value }))
                        }
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="cost-line-unit-cost">Coût unitaire</label>
                      <input
                        id="cost-line-unit-cost"
                        type="number"
                        min="0"
                        step="0.01"
                        value={costLineDraft.unitCost}
                        onChange={(event) =>
                          setCostLineDraft((prev) => ({ ...prev, unitCost: event.target.value }))
                        }
                      />
                    </div>
                    <button
                      className="btn btn-primary"
                      type="button"
                      disabled={estimateBusy}
                      onClick={() => void addCostLine()}
                    >
                      Ajouter la ligne
                    </button>
                  </div>
                ) : null}

                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">Catégorie</th>
                        <th scope="col">Libellé</th>
                        <th scope="col">Quantité</th>
                        <th scope="col">Coût unitaire</th>
                        <th scope="col">Montant</th>
                        {canEditEstimate ? <th scope="col">Action</th> : null}
                      </tr>
                    </thead>
                    <tbody>
                      {costLines.map((line) => {
                        const editing = editingLineId === line.id;
                        return (
                          <tr key={line.id}>
                            <td>{line.cost_category_code}</td>
                            <td>
                              {editing ? (
                                <input
                                  value={editingLineDraft.label}
                                  onChange={(event) =>
                                    setEditingLineDraft((prev) => ({ ...prev, label: event.target.value }))
                                  }
                                />
                              ) : (
                                line.label
                              )}
                            </td>
                            <td>
                              {editing ? (
                                <input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={editingLineDraft.quantity}
                                  onChange={(event) =>
                                    setEditingLineDraft((prev) => ({ ...prev, quantity: event.target.value }))
                                  }
                                />
                              ) : (
                                line.quantity
                              )}
                            </td>
                            <td>
                              {editing ? (
                                <input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={editingLineDraft.unitCost}
                                  onChange={(event) =>
                                    setEditingLineDraft((prev) => ({ ...prev, unitCost: event.target.value }))
                                  }
                                />
                              ) : (
                                line.unit_cost
                              )}
                            </td>
                            <td>{line.purchase_cost}</td>
                            {canEditEstimate ? (
                              <td>
                                <div className="row">
                                  {editing ? (
                                    <button
                                      className="btn btn-primary"
                                      type="button"
                                      disabled={estimateBusy}
                                      onClick={() => void saveCostLine(line)}
                                    >
                                      Sauver
                                    </button>
                                  ) : (
                                    <button className="btn" type="button" onClick={() => startEditCostLine(line)}>
                                      Modifier
                                    </button>
                                  )}
                                  <button
                                    className="btn btn-danger"
                                    type="button"
                                    disabled={estimateBusy}
                                    onClick={() => void removeCostLine(line)}
                                  >
                                    Supprimer
                                  </button>
                                </div>
                              </td>
                            ) : null}
                          </tr>
                        );
                      })}
                      {!costLines.length ? (
                        <tr>
                          <td colSpan={canEditEstimate ? 6 : 5} className="muted">
                            Aucune ligne de coût.
                          </td>
                        </tr>
                      ) : null}
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
            <p className="muted">
              Le suivi budget de référence / engagé / reste à engager sera construit sur les versions
              « forecast_remaining » du jalon 9.
            </p>
          </div>
        ) : null}

        {activeTab === "analytics" ? (
          <div className="tab-content">
            <h2>Analytique</h2>
            {!selectedEstimateId ? <p className="muted">Sélectionne un devis dans l&apos;onglet Devis.</p> : null}
            {selectedEstimateId && !aggregates ? <p className="muted">Chargement des agrégats...</p> : null}
            {aggregates ? (
              <div className="estimate-summary">
                <div className="row">
                  <div className="estimate-metric">
                    <strong>{Number(aggregates.total_labor_cost).toFixed(2)}</strong>
                    <span>Total MO</span>
                  </div>
                  <div className="estimate-metric">
                    <strong>{Number(aggregates.total_purchase_cost).toFixed(2)}</strong>
                    <span>Total Achat</span>
                  </div>
                  <div className="estimate-metric">
                    <strong>{Number(aggregates.total_unburdened_cost).toFixed(2)}</strong>
                    <span>PRU non chargé</span>
                  </div>
                </div>

                <div className="analytics-breakdown">
                  <h3 className="gantt-title">Répartition par catégorie</h3>
                  {Object.keys(aggregates.by_category).length === 0 ? (
                    <p className="muted">Aucun montant à répartir pour ce devis.</p>
                  ) : (
                    (() => {
                      const entries = Object.entries(aggregates.by_category);
                      const max = Math.max(...entries.map(([, amount]) => Number(amount)), 1);
                      return (
                        <div className="gantt-rows">
                          {entries.map(([category, amount]) => (
                            <div className="gantt-row" key={category}>
                              <span className="gantt-label">{category}</span>
                              <div className="gantt-track">
                                <div
                                  className="gantt-bar"
                                  style={{ width: `${(Number(amount) / max) * 100}%` }}
                                />
                              </div>
                              <span className="muted">{Number(amount).toFixed(2)}</span>
                            </div>
                          ))}
                        </div>
                      );
                    })()
                  )}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </>
  );
}
