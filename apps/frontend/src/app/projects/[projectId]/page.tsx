"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { AnalyticsTab } from "@/components/analytics-tab";
import { CommitmentsTabPlaceholder } from "@/components/commitments-tab-placeholder";
import { CostLineDeleteDialog } from "@/components/cost-line-delete-dialog";
import { EstimateRoleAssignmentDeleteDialog } from "@/components/estimate-role-assignment-delete-dialog";
import { EstimateTab } from "@/components/estimate-tab";
import { EstimateValidationDialog } from "@/components/estimate-validation-dialog";
import { PlanningTab } from "@/components/planning-tab";
import { ProjectHeaderCard } from "@/components/project-header-card";
import { ProjectLoadFailedCard } from "@/components/project-load-failed-card";
import { ProjectStatusBanners } from "@/components/project-status-banners";
import { ProjectTabs, type ProjectTab } from "@/components/project-tabs";
import {
  ApiError,
  CostCategory,
  CostRate,
  createImportBatch,
  EstimateAggregates,
  EstimateCostLine,
  EstimateRoleAssignment,
  EstimateTaskRow,
  exportProjectXml,
  getCostCategories,
  getCostRates,
  getCostTypes,
  getEstimateAggregates,
  getImportBatchDiff,
  getProject,
  getResourceNodes,
  getResourceRoles,
  listPlannings,
  listEstimateCostLines,
  listEstimateRoleAssignments,
  listEstimateTaskRows,
  listProjectEstimates,
  Project,
  Planning,
  PlanningDetail,
  ProjectEstimate,
  ResourceNode,
  ResourceRole,
  runImportBatch,
  SessionExpiredError,
  type ImportDiff,
  restoreSession,
  uploadImportSourceXml,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";
import { canRedo, canUndo, getPlanningHistory, type PlanningHistoryByPlanningId } from "@/lib/planning-history";
import { validateImportFile } from "@/lib/planning-import-validation";
import { usePlanningDetailEffect, type PlanningRevisionConflict } from "@/hooks/use-planning-detail";
import { usePlanningHistoryCommand } from "@/hooks/use-planning-history-command";
import { usePlanningImport } from "@/hooks/use-planning-import";
import { usePlanningStructureEditor } from "@/hooks/use-planning-structure-editor";
import { usePlanningTreeMutations } from "@/hooks/use-planning-tree-mutations";
import { useEstimateCostLines } from "@/hooks/use-estimate-cost-lines";
import { useProjectInfoEditor } from "@/hooks/use-project-info-editor";

function describeInitialProjectLoadError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status >= 500) {
      return "Le projet est temporairement indisponible. Réessaie dans quelques instants.";
    }
    return cause.message || "Impossible de charger le projet.";
  }
  return "Erreur inattendue lors du chargement du projet.";
}

// A project stops being editable once it reaches one of these terminal statuses -- mirrors the
// guard duplicated across every mutation handler previously inlined in this component.
function isProjectReadOnly(project: Project | null): boolean {
  return project?.status === "perdu" || project?.status === "termine" || project?.status === "abandonne";
}

function canEditSelectedEstimate(estimate: ProjectEstimate | null, isReadOnlyProject: boolean): boolean {
  return estimate?.status === "draft" && !isReadOnlyProject;
}

function getSelectedPlanningConflict(
  selectedPlanning: Planning | null,
  conflicts: Record<number, PlanningRevisionConflict>,
): PlanningRevisionConflict | null {
  return selectedPlanning ? (conflicts[selectedPlanning.id] ?? null) : null;
}

function hasSelectedPlanningConflict(
  selectedPlanning: Planning | null,
  conflicts: Record<number, PlanningRevisionConflict>,
): boolean {
  return getSelectedPlanningConflict(selectedPlanning, conflicts) !== null;
}

function didInitialLoadFail(busy: boolean, project: Project | null, error: string | null): boolean {
  return !busy && project === null && error !== null;
}

function canUndoSelectedPlanning(history: PlanningHistoryByPlanningId, selectedPlanning: Planning | null): boolean {
  return canUndo(getPlanningHistory(history, selectedPlanning?.id ?? -1));
}

function canRedoSelectedPlanning(history: PlanningHistoryByPlanningId, selectedPlanning: Planning | null): boolean {
  return canRedo(getPlanningHistory(history, selectedPlanning?.id ?? -1));
}

export default function ProjectDetailsPage() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId);

  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [project, setProject] = useState<Project | null>(null);
  const [plannings, setPlannings] = useState<Planning[]>([]);
  const [selectedPlanningId, setSelectedPlanningId] = useState<number | null>(null);
  const selectedPlanningIdRef = useRef(selectedPlanningId);
  const planningLoadGenerationRef = useRef(0);
  // Updated synchronously (not via effect) so an in-flight move can never observe a stale ID:
  // an effect only runs after commit, leaving a window where a race could still slip through.
  function updateSelectedPlanningId(next: number | null) {
    selectedPlanningIdRef.current = next;
    setSelectedPlanningId(next);
  }
  const [planningDetail, setPlanningDetail] = useState<PlanningDetail | null>(null);
  const [planningBusy, setPlanningBusy] = useState(false);
  const [planningDetailBusy, setPlanningDetailBusy] = useState(false);
  const [planningMutationBusy, setPlanningMutationBusy] = useState(false);
  // Per-planning_id undo/redo stacks (E4-01): isolated by construction, since each key is its
  // own independent history. A revision conflict never replaces planningDetail/history itself;
  // it sets planningConflict instead, and only a confirmed reload clears the stale history.
  const [historyByPlanningId, setHistoryByPlanningIdState] = useState<PlanningHistoryByPlanningId>({});
  const historyByPlanningIdRef = useRef(historyByPlanningId);
  // Updated synchronously (not via effect) for the same reason as updateSelectedPlanningId above:
  // this ref is read from use-planning-detail.ts to detect a stale revision conflict, and an
  // effect only runs after commit, leaving a window where a race could still slip through. Every
  // write to historyByPlanningId must go through this wrapper instead of the raw setState.
  function updateHistoryByPlanningId(
    updater: (current: PlanningHistoryByPlanningId) => PlanningHistoryByPlanningId,
  ) {
    const next = updater(historyByPlanningIdRef.current);
    historyByPlanningIdRef.current = next;
    setHistoryByPlanningIdState(next);
  }
  // Per-planning conflict tracking (E4-02): a conflict on planning A survives if user switches
  // to B; undo/redo is disabled until the conflict is explicitly cleared by a successful reload.
  const [planningConflictByPlanningId, setPlanningConflictByPlanningId] = useState<
    Record<number, PlanningRevisionConflict>
  >({});
  // A network/unclassified failure (not a session expiry, not a revision conflict) keeps the
  // just-attempted mutation retryable instead of silently dropping it (E4-01).
  const [retryableAction, setRetryableAction] = useState<{
    message: string;
    retry: () => void;
  } | null>(null);
  const [structureOpen, setStructureOpen] = useState(false);
  const [planningExportBusy, setPlanningExportBusy] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  // Kept in sync with `importFile` synchronously (not via a separate effect) so that an in-flight
  // preview request can tell, once it resolves, whether the candidate file changed while it was
  // waiting -- see the freshness guard in `preparePlanningImport`.
  const latestImportFileRef = useRef<File | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importReview, setImportReview] = useState<{ batchId: number; diff: ImportDiff } | null>(null);
  const [importFeedback, setImportFeedback] = useState<string | null>(null);
  const [estimates, setEstimates] = useState<ProjectEstimate[]>([]);
  const [selectedEstimateId, setSelectedEstimateId] = useState<number | null>(null);
  const [estimateTaskRows, setEstimateTaskRows] = useState<EstimateTaskRow[]>([]);
  const [costLines, setCostLines] = useState<EstimateCostLine[]>([]);
  const [costCategories, setCostCategories] = useState<CostCategory[]>([]);
  // E12-05/#277: the full (including inactive) cost-category referential -- distinct from
  // `costCategories` above (active-only, feeds CostLineForm's create-line `<select>`) -- used to
  // resolve a historical cost line's category *name* even after that category was deactivated.
  // See loadCostCategories below and cost-lines-table.tsx's `allCostCategories` prop doc comment.
  const [allCostCategories, setAllCostCategories] = useState<CostCategory[]>([]);
  // E12-06/#278: the organization/role/rate referentials feeding CostLinesTable's labor ("MO")
  // row resolution (Dept/Type/Catégorie/Cat/Taux horaire/MO columns) -- loaded once per project,
  // not per row. `resourceRoles` here is the *complete* (unfiltered by node) referential, unlike
  // the dialog's own node-scoped `roleAssignmentRoles` (use-estimate-cost-lines.ts), which is
  // loaded on demand only once a node is chosen in the "Ajouter une ligne MO" form.
  const [resourceNodes, setResourceNodes] = useState<ResourceNode[]>([]);
  const [resourceRoles, setResourceRoles] = useState<ResourceRole[]>([]);
  const [costRates, setCostRates] = useState<CostRate[]>([]);
  const [estimateRoleAssignments, setEstimateRoleAssignments] = useState<EstimateRoleAssignment[]>([]);
  const [aggregates, setAggregates] = useState<EstimateAggregates | null>(null);
  const [activeTab, setActiveTab] = useState<ProjectTab>("planning");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function setRetryableError(message: string, retry: () => void) {
    setError(message);
    setRetryableAction({ message, retry });
  }

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

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
        const [projectData, estimatesData, planningsData] = await Promise.all([
          getProject(projectId, session, onSessionRefresh),
          listProjectEstimates(projectId, session, onSessionRefresh),
          listPlannings(projectId, session, onSessionRefresh),
        ]);
        if (cancelled) {
          return;
        }
        setProject(projectData);
        setEstimates(estimatesData);
        setPlannings(planningsData);
        setStructureOpen(projectData.status === "cree");
        updateSelectedPlanningId(
          projectData.displayed_planning_id ?? planningsData.at(-1)?.id ?? null,
        );
        setSelectedEstimateId((current) => current ?? estimatesData.at(-1)?.id ?? null);
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
        if (cancelled) {
          return;
        }
        setError(describeInitialProjectLoadError(cause));
      } finally {
        if (!cancelled) {
          setBusy(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [onSessionRefresh, projectId, router, session]);

  const structureEditor = usePlanningStructureEditor({
    session,
    projectId,
    isReadOnlyProject: isProjectReadOnly(project),
    onSessionRefresh,
    router,
    setError,
    setProject,
    setPlannings,
    updateSelectedPlanningId,
    setPlanningDetail,
    setStructureOpen,
  });

  usePlanningDetailEffect({
    session,
    selectedPlanningId,
    projectId,
    onSessionRefresh,
    router,
    planningLoadGenerationRef,
    selectedPlanningIdRef,
    historyByPlanningIdRef,
    setPlanningDetail,
    setPlanningDetailBusy,
    setPlanningConflictByPlanningId,
    setStructureDraft: structureEditor.setStructureDraft,
    setError,
  });

  useEffect(() => {
    let cancelled = false;

    async function loadEstimateDetails() {
      if (!session || selectedEstimateId === null) {
        setEstimateTaskRows([]);
        setCostLines([]);
        setEstimateRoleAssignments([]);
        return;
      }
      try {
        // E12-06/#278: role assignments are refetched here alongside task rows/cost lines, on
        // the exact same "reload whenever the selected estimate version changes" model.
        const [taskRows, lines, roleAssignments] = await Promise.all([
          listEstimateTaskRows(projectId, selectedEstimateId, session, onSessionRefresh),
          listEstimateCostLines(projectId, selectedEstimateId, session, onSessionRefresh),
          listEstimateRoleAssignments(projectId, selectedEstimateId, session, onSessionRefresh),
        ]);
        if (!cancelled) {
          setEstimateTaskRows(taskRows);
          setCostLines(lines);
          setEstimateRoleAssignments(roleAssignments);
        }
      } catch (cause) {
        if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cancelled) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger le devis.");
      }
    }

    void loadEstimateDetails();
    return () => {
      cancelled = true;
    };
  }, [onSessionRefresh, projectId, router, selectedEstimateId, session]);

  useEffect(() => {
    async function loadCostCategories() {
      if (!session) {
        return;
      }
      try {
        // E12-05/#277: `allCategoriesPage` (includeInactive: true) is fetched alongside the
        // existing active-only `categoriesPage` rather than replacing it -- the two feed different
        // consumers with different requirements (see the `allCostCategories` state's own doc
        // comment above and cost-lines-table.tsx's `allCostCategories` prop doc comment).
        const [categoriesPage, typesPage, allCategoriesPage] = await Promise.all([
          getCostCategories(session, onSessionRefresh),
          getCostTypes(session, onSessionRefresh),
          getCostCategories(session, onSessionRefresh, true),
        ]);
        const laborTypeIds = new Set(
          typesPage.items.filter((type) => type.kind === "labor").map((type) => type.id),
        );
        setCostCategories(categoriesPage.items.filter((category) => !laborTypeIds.has(category.cost_type_id)));
        setAllCostCategories(allCategoriesPage.items);
      } catch {
        // Non-blocking: the add-line form simply stays disabled without categories.
      }
    }

    void loadCostCategories();
  }, [onSessionRefresh, session]);

  useEffect(() => {
    async function loadRoleAssignmentReferentials() {
      if (!session) {
        return;
      }
      try {
        // E12-06/#278: loaded once per project, not per Devis row -- `resourceRolesPage` here is
        // the *complete* referential (no node_id filter), used only to resolve an existing
        // EstimateRoleAssignment's `node_id`/`cost_category_id` from its `role_id` for display
        // (CostLinesTable's Dept/Catégorie/Cat columns). The "Ajouter une ligne MO" dialog's own
        // role selector is populated separately, on demand, once a node is chosen (see
        // use-estimate-cost-lines.ts's updateRoleAssignmentNodeId), and deliberately stays
        // active-only there (a disabled role/node must not be selectable for a *new* assignment).
        // `includeInactive: true` here mirrors `allCostCategories` above -- an existing assignment
        // referencing a role or node disabled after the fact must still resolve to a real Dept/
        // name instead of the "-"/truncated-path fallback (E12-06's original "Haute" finding).
        const [nodes, resourceRolesPage, rates] = await Promise.all([
          getResourceNodes(session, onSessionRefresh, true),
          getResourceRoles(session, onSessionRefresh, undefined, false, {}, true),
          getCostRates(session, onSessionRefresh),
        ]);
        setResourceNodes(nodes);
        setResourceRoles(resourceRolesPage.items);
        setCostRates(rates);
      } catch {
        // Non-blocking: the Devis grid's Dept/Taux horaire/MO columns simply show their "-"/"—"
        // fallbacks without these referentials, same convention as loadCostCategories above.
      }
    }

    void loadRoleAssignmentReferentials();
  }, [onSessionRefresh, session]);

  useEffect(() => {
    let cancelled = false;

    async function loadAggregates() {
      if (!session || selectedEstimateId === null || activeTab !== "analytics") {
        return;
      }
      try {
        const data = await getEstimateAggregates(projectId, selectedEstimateId, session, onSessionRefresh);
        if (!cancelled) {
          setAggregates(data);
        }
      } catch (cause) {
        if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cancelled) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger les agrégats.");
      }
    }

    void loadAggregates();
    return () => {
      cancelled = true;
    };
  }, [activeTab, onSessionRefresh, projectId, router, selectedEstimateId, session]);

  const selectedEstimate = estimates.find((estimate) => estimate.id === selectedEstimateId) ?? null;
  const isReadOnlyProject = isProjectReadOnly(project);
  const canEditEstimate = canEditSelectedEstimate(selectedEstimate, isReadOnlyProject);
  const selectedPlanning = plannings.find((planning) => planning.id === selectedPlanningId) ?? null;
  const selectedPlanningHasConflict = hasSelectedPlanningConflict(selectedPlanning, planningConflictByPlanningId);
  const initialLoadFailed = didInitialLoadFail(busy, project, error);

  const projectInfoEditor = useProjectInfoEditor({
    session,
    project,
    projectId,
    onSessionRefresh,
    router,
    setProject,
    setError,
  });

  const planningMutations = usePlanningTreeMutations({
    session,
    projectId,
    setProject,
    setPlannings,
    selectedPlanningId,
    selectedPlanning,
    isReadOnlyProject,
    planningDetail,
    setPlanningDetail,
    selectedPlanningIdRef,
    updateSelectedPlanningId,
    setHistoryByPlanningId: updateHistoryByPlanningId,
    planningConflictByPlanningId,
    setPlanningConflictByPlanningId,
    onSessionRefresh,
    router,
    setError,
    setRetryableAction,
    setRetryableError,
    setPlanningBusy,
    setPlanningDetailBusy,
    setPlanningMutationBusy,
    setStructureDraft: structureEditor.setStructureDraft,
    setStructureOpen,
  });

  const applyPlanningHistoryCommand = usePlanningHistoryCommand({
    session,
    selectedPlanning,
    isReadOnlyProject,
    planningDetail,
    historyByPlanningId,
    projectId,
    onSessionRefresh,
    router,
    selectedPlanningIdRef,
    setPlanningMutationBusy,
    setError,
    setRetryableAction,
    setPlanningDetail,
    setPlanningConflictByPlanningId,
    setHistoryByPlanningId: updateHistoryByPlanningId,
    setRetryableError,
  });

  const estimateCostLines = useEstimateCostLines({
    session,
    project,
    projectId,
    selectedEstimateId,
    estimates,
    setEstimates,
    setSelectedEstimateId,
    setActiveTab,
    setCostLines,
    setEstimateTaskRows,
    selectedPlanningId,
    selectedPlanningIdRef,
    setPlanningDetail,
    setEstimateRoleAssignments,
    resourceNodes,
    onSessionRefresh,
    router,
    setError,
  });

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
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'exporter le planning.");
    } finally {
      setPlanningExportBusy(false);
    }
  }

  async function preparePlanningImport() {
    if (!session || !project || !importFile) {
      return;
    }
    const requestFile = importFile;
    setImportBusy(true);
    setError(null);
    setImportFeedback(null);
    try {
      const batch = await createImportBatch(projectId, project.name, session, onSessionRefresh);
      await uploadImportSourceXml(batch.id, requestFile, session, onSessionRefresh);
      await runImportBatch(batch.id, session, onSessionRefresh, true, false);
      const diff = await getImportBatchDiff(batch.id, session, onSessionRefresh);
      // The user may have selected a different candidate file while this request was in flight;
      // if so, this result is stale and must be dropped silently rather than shown as a review
      // for a file that is no longer selected (see fix for #132).
      if (latestImportFileRef.current !== requestFile) {
        return;
      }
      setImportReview({ batchId: batch.id, diff });
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      if (latestImportFileRef.current !== requestFile) {
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'importer le planning.");
    } finally {
      setImportBusy(false);
    }
  }

  // Any change to the candidate file -- accepted or rejected -- invalidates a pending import
  // preview: `importReview.batchId` refers to whatever file was uploaded when "Prévisualiser
  // l'import" was last clicked, and confirming it after the candidate changed would silently
  // apply the wrong batch. Clear it in every branch of both handlers below, not just the
  // happy path.
  function onImportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (file) {
      const validationError = validateImportFile(file);
      if (validationError) {
        setImportFile(null);
        latestImportFileRef.current = null;
        setImportReview(null);
        setError(validationError);
        event.target.value = "";
        return;
      }
    }
    setError(null);
    setImportFile(file);
    latestImportFileRef.current = file;
    setImportReview(null);
  }

  function onImportFilesDrop(files: FileList) {
    if (files.length === 0) {
      setImportFile(null);
      latestImportFileRef.current = null;
      setImportReview(null);
      setError("Le dépôt ne contient aucun fichier exploitable (dossier non pris en charge ou élément invalide).");
      return;
    }
    if (files.length > 1) {
      setImportFile(null);
      latestImportFileRef.current = null;
      setImportReview(null);
      setError("Dépose un seul fichier à la fois.");
      return;
    }
    const file = files[0];
    const validationError = validateImportFile(file);
    if (validationError) {
      setImportFile(null);
      latestImportFileRef.current = null;
      setImportReview(null);
      setError(validationError);
      return;
    }
    setError(null);
    setImportFile(file);
    latestImportFileRef.current = file;
    setImportReview(null);
  }

  const confirmPlanningImport = usePlanningImport({
    session,
    project,
    importReview,
    projectId,
    onSessionRefresh,
    router,
    plannings,
    setProject,
    setPlannings,
    setPlanningDetail,
    updateSelectedPlanningId,
    setImportReview,
    setImportFile,
    setImportFeedback,
    setImportBusy,
    setError,
  });

  if (initialLoadFailed) {
    return <ProjectLoadFailedCard projectId={projectId} error={error} />;
  }

  return (
    <>
      <ProjectHeaderCard
        project={project}
        projectId={projectId}
        editingProjectInfo={projectInfoEditor.editingProjectInfo}
        projectInfoDraft={projectInfoEditor.projectInfoDraft}
        projectInfoBusy={projectInfoEditor.projectInfoBusy}
        isReadOnlyProject={isReadOnlyProject}
        onNameChange={projectInfoEditor.updateProjectInfoName}
        onDescriptionChange={projectInfoEditor.updateProjectInfoDescription}
        onStartEdit={projectInfoEditor.startEditProjectInfo}
        onCancelEdit={projectInfoEditor.cancelEditProjectInfo}
        onSave={() => void projectInfoEditor.saveProjectInfo()}
      />

      <div className="mt-4">
        <ProjectTabs activeTab={activeTab} onChange={setActiveTab} />
      </div>

      <div className="space-y-4">
        <ProjectStatusBanners
          busy={busy}
          error={error}
          retryableActionMessage={retryableAction?.message ?? null}
          importFeedback={importFeedback}
          onRetry={() => retryableAction?.retry()}
        />

        <PlanningTab
          active={activeTab === "planning"}
          project={project}
          isReadOnlyProject={isReadOnlyProject}
          importFile={importFile}
          importBusy={importBusy}
          onFileChange={onImportFileChange}
          onFilesDrop={onImportFilesDrop}
          onPreviewImport={() => void preparePlanningImport()}
          planningExportBusy={planningExportBusy}
          onExportXml={() => void exportPlanningXml()}
          importReview={importReview}
          onConfirmImport={() => void confirmPlanningImport()}
          structureOpen={structureOpen}
          postGroups={structureEditor.postGroups}
          structureDraft={structureEditor.structureDraft}
          structureBusy={structureEditor.structureBusy}
          structureAction={structureEditor.structureAction}
          onUpdatePostField={structureEditor.updatePostField}
          onUpdateLotField={structureEditor.updateLotField}
          onUpdateDeliverable={structureEditor.updateDeliverable}
          onAddDeliverable={structureEditor.addDeliverable}
          onRemoveDeliverable={structureEditor.removeDeliverable}
          onRemoveLot={structureEditor.removeLot}
          onAddLotToPost={structureEditor.addLotToPost}
          onAddPost={structureEditor.addPost}
          onSaveStructure={() => void structureEditor.savePlanningStructure()}
          onGenerateStructure={() => void structureEditor.generatePlanningStructure()}
          onSkipStructure={() => void structureEditor.skipStructure()}
          plannings={plannings}
          selectedPlanningId={selectedPlanningId}
          planningBusy={planningBusy}
          onSelectPlanning={(planningId) => void planningMutations.selectPlanning(planningId)}
          selectedPlanning={selectedPlanning}
          selectedPlanningHasConflict={selectedPlanningHasConflict}
          onValidatePlanning={() => void planningMutations.validateSelectedPlanning()}
          onSetReference={() => void planningMutations.setSelectedPlanningAsReference()}
          onCreateVersion={() => void planningMutations.createPlanningVersionFromSelected()}
          onReopenStructure={() => void planningMutations.reopenStructure()}
          planningMutationBusy={planningMutationBusy}
          canUndo={canUndoSelectedPlanning(historyByPlanningId, selectedPlanning)}
          canRedo={canRedoSelectedPlanning(historyByPlanningId, selectedPlanning)}
          onUndo={() => void applyPlanningHistoryCommand("undo")}
          onRedo={() => void applyPlanningHistoryCommand("redo")}
          conflict={getSelectedPlanningConflict(selectedPlanning, planningConflictByPlanningId)}
          onReloadConflict={() => void planningMutations.reloadPlanningAfterConflict()}
          planningDetailBusy={planningDetailBusy}
          planningDetail={planningDetail}
          onMove={(command) => void planningMutations.movePlanningTaskSelection(command)}
          onScheduleUpdate={(taskUid, payload) => planningMutations.updateTaskScheduleSelection(taskUid, payload)}
          onEditLinks={(payload) => planningMutations.editTaskPredecessorLinksSelection(payload.taskUid, payload.links)}
          onCreateTask={(command) => void planningMutations.createPlanningTaskSelection(command)}
          onDeleteTasks={(taskUids, confirmCascade, requestedVersionKey) =>
            planningMutations.deletePlanningTasksSelection(taskUids, confirmCascade, requestedVersionKey)
          }
        />

        <EstimateTab
          active={activeTab === "estimate"}
          estimates={estimates}
          selectedEstimateId={selectedEstimateId}
          onSelectEstimate={setSelectedEstimateId}
          isReadOnlyProject={isReadOnlyProject}
          onNewDraft={() => void estimateCostLines.createDraftEstimate()}
          exportBusy={estimateCostLines.exportBusy}
          onExport={() => void estimateCostLines.exportExcel()}
          canEditEstimate={canEditEstimate}
          estimateBusy={estimateCostLines.estimateBusy}
          onOpenValidation={estimateCostLines.openEstimateValidation}
          validationWarnings={estimateCostLines.validationWarnings}
          onDismissValidationWarnings={estimateCostLines.dismissValidationWarnings}
          estimateTaskRows={estimateTaskRows}
          costLines={costLines}
          costCategories={costCategories}
          allCostCategories={allCostCategories}
          costLineDraft={estimateCostLines.costLineDraft}
          onCategoryChange={estimateCostLines.updateCostLineDraftCategory}
          onLabelChange={estimateCostLines.updateCostLineDraftLabel}
          onQuantityChange={estimateCostLines.updateCostLineDraftQuantity}
          onUnitCostChange={estimateCostLines.updateCostLineDraftUnitCost}
          onPlannedDateChange={estimateCostLines.updateCostLineDraftPlannedDate}
          onTaskIdChange={estimateCostLines.updateCostLineDraftTaskId}
          onAddCostLine={() => void estimateCostLines.addCostLine()}
          mutationBusy={estimateCostLines.estimateBusy}
          onMoveGridSelection={(command) => void estimateCostLines.moveGridSelection(command)}
          onRenameTask={(taskUid, name) => estimateCostLines.renameGridTask(taskUid, name)}
          onUpdateCostLine={(lineId, payload) => estimateCostLines.updateCostLineField(lineId, payload)}
          onUpdateRoleAssignment={(id, payload) => estimateCostLines.updateRoleAssignmentField(id, payload)}
          onRequestDeleteCostLine={estimateCostLines.requestDeleteCostLine}
          selectedCostLineIds={estimateCostLines.selectedCostLineIds}
          onSelectedCostLineIdsChange={estimateCostLines.setSelectedCostLineIds}
          projectCostCodes={estimateCostLines.projectCostCodes}
          bulkCostCodeId={estimateCostLines.bulkCostCodeId}
          onBulkCostCodeIdChange={estimateCostLines.updateBulkCostCodeId}
          bulkAssignBusy={estimateCostLines.bulkAssignBusy}
          onBulkAssignCostCode={() => void estimateCostLines.bulkAssignCostCode()}
          taskDialogOpen={estimateCostLines.taskDialogOpen}
          taskDraftName={estimateCostLines.taskDraftName}
          taskDraftIsMilestone={estimateCostLines.taskDraftIsMilestone}
          taskDraftParentUid={estimateCostLines.taskDraftParentUid}
          parentTaskOptions={planningDetail?.tasks ?? []}
          taskCreateBusy={estimateCostLines.estimateBusy}
          taskCreateError={estimateCostLines.taskCreateError}
          taskCreateRequiresPlanningDraft={estimateCostLines.taskCreateRequiresPlanningDraft}
          onOpenCreateTaskDialog={estimateCostLines.openCreateTaskDialog}
          onCloseCreateTaskDialog={estimateCostLines.closeCreateTaskDialog}
          onTaskDraftNameChange={estimateCostLines.updateTaskDraftName}
          onTaskDraftIsMilestoneChange={estimateCostLines.updateTaskDraftIsMilestone}
          onTaskDraftParentUidChange={estimateCostLines.updateTaskDraftParentUid}
          onSubmitCreateTask={() => void estimateCostLines.submitCreateTask()}
          onReopenStructure={() => {
            estimateCostLines.closeCreateTaskDialog();
            setActiveTab("planning");
            void planningMutations.reopenStructure();
          }}
          milestoneDialogOpen={estimateCostLines.milestoneDialogOpen}
          milestoneLineId={estimateCostLines.milestoneLineId}
          milestoneTemplate={estimateCostLines.milestoneTemplate}
          milestoneIntermediateCount={estimateCostLines.milestoneIntermediateCount}
          milestoneLagMinutes={estimateCostLines.milestoneLagMinutes}
          milestoneBusy={estimateCostLines.estimateBusy}
          milestoneError={estimateCostLines.milestoneError}
          milestoneRequiresPlanningDraft={estimateCostLines.milestoneRequiresPlanningDraft}
          onOpenMilestoneDialog={estimateCostLines.openMilestoneDialog}
          onCloseMilestoneDialog={estimateCostLines.closeMilestoneDialog}
          onMilestoneTemplateChange={estimateCostLines.updateMilestoneTemplate}
          onMilestoneIntermediateCountChange={estimateCostLines.updateMilestoneIntermediateCount}
          onMilestoneLagMinutesChange={estimateCostLines.updateMilestoneLagMinutes}
          onSubmitMilestoneTemplate={() => void estimateCostLines.submitMilestoneTemplate()}
          onReopenStructureForMilestone={() => {
            estimateCostLines.closeMilestoneDialog();
            setActiveTab("planning");
            void planningMutations.reopenStructure();
          }}
          estimateRoleAssignments={estimateRoleAssignments}
          resourceNodes={resourceNodes}
          resourceRoles={resourceRoles}
          costRates={costRates}
          onRequestDeleteRoleAssignment={estimateCostLines.requestDeleteRoleAssignment}
          roleAssignmentDialogOpen={estimateCostLines.roleAssignmentDialogOpen}
          roleAssignmentDept1Id={estimateCostLines.roleAssignmentDept1Id}
          onRoleAssignmentDept1IdChange={estimateCostLines.updateRoleAssignmentDept1Id}
          roleAssignmentDept2Id={estimateCostLines.roleAssignmentDept2Id}
          onRoleAssignmentDept2IdChange={estimateCostLines.updateRoleAssignmentDept2Id}
          roleAssignmentRoles={estimateCostLines.roleAssignmentRoles}
          roleAssignmentRolesLoading={estimateCostLines.roleAssignmentRolesLoading}
          roleAssignmentRoleId={estimateCostLines.roleAssignmentRoleId}
          onRoleAssignmentRoleIdChange={(value) => void estimateCostLines.updateRoleAssignmentRoleId(value)}
          roleAssignmentTaskId={estimateCostLines.roleAssignmentTaskId}
          onRoleAssignmentTaskIdChange={estimateCostLines.updateRoleAssignmentTaskId}
          roleAssignmentQuantity={estimateCostLines.roleAssignmentQuantity}
          onRoleAssignmentQuantityChange={estimateCostLines.updateRoleAssignmentQuantity}
          roleAssignmentHours={estimateCostLines.roleAssignmentHours}
          onRoleAssignmentHoursChange={estimateCostLines.updateRoleAssignmentHours}
          roleAssignmentCostCodeId={estimateCostLines.roleAssignmentCostCodeId}
          onRoleAssignmentCostCodeIdChange={estimateCostLines.updateRoleAssignmentCostCodeId}
          roleAssignmentComment={estimateCostLines.roleAssignmentComment}
          onRoleAssignmentCommentChange={estimateCostLines.updateRoleAssignmentComment}
          roleAssignmentBusy={estimateCostLines.estimateBusy}
          roleAssignmentError={estimateCostLines.roleAssignmentError}
          onOpenRoleAssignmentDialog={estimateCostLines.openRoleAssignmentDialog}
          onCloseRoleAssignmentDialog={estimateCostLines.closeRoleAssignmentDialog}
          onSubmitRoleAssignment={() => void estimateCostLines.submitCreateRoleAssignment()}
        />

        <CommitmentsTabPlaceholder active={activeTab === "commitments"} />

        <AnalyticsTab active={activeTab === "analytics"} selectedEstimateId={selectedEstimateId} aggregates={aggregates} />
      </div>

      <CostLineDeleteDialog
        pendingDelete={estimateCostLines.costLinePendingDelete}
        onCancel={estimateCostLines.cancelDeleteCostLine}
        onConfirm={(line) => void estimateCostLines.removeCostLine(line)}
      />

      <EstimateRoleAssignmentDeleteDialog
        pendingDelete={estimateCostLines.roleAssignmentPendingDelete}
        onCancel={estimateCostLines.cancelDeleteRoleAssignment}
        onConfirm={(assignment) => void estimateCostLines.removeRoleAssignment(assignment)}
      />

      <EstimateValidationDialog
        open={estimateCostLines.estimateValidationOpen}
        onOpenChange={estimateCostLines.setEstimateValidationOpen}
        onConfirm={() => void estimateCostLines.validateEstimate()}
      />
    </>
  );
}
