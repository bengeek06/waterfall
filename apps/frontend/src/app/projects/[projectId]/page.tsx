"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { AnalyticsTab } from "@/components/analytics-tab";
import { CommitmentsTabPlaceholder } from "@/components/commitments-tab-placeholder";
import { CostLineDeleteDialog } from "@/components/cost-line-delete-dialog";
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
  createImportBatch,
  EstimateAggregates,
  EstimateCostLine,
  exportProjectXml,
  getCostCategories,
  getCostTypes,
  getEstimateAggregates,
  getImportBatchDiff,
  getProject,
  listPlannings,
  listEstimateCostLines,
  listEstimateTaskRows,
  listProjectEstimates,
  Project,
  Planning,
  PlanningDetail,
  ProjectEstimate,
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
  const [estimateTaskRowCount, setEstimateTaskRowCount] = useState(0);
  const [costLines, setCostLines] = useState<EstimateCostLine[]>([]);
  const [costCategories, setCostCategories] = useState<CostCategory[]>([]);
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
        setEstimateTaskRowCount(0);
        setCostLines([]);
        return;
      }
      try {
        const [taskRows, lines] = await Promise.all([
          listEstimateTaskRows(projectId, selectedEstimateId, session, onSessionRefresh),
          listEstimateCostLines(projectId, selectedEstimateId, session, onSessionRefresh),
        ]);
        if (!cancelled) {
          setEstimateTaskRowCount(taskRows.length);
          setCostLines(lines);
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
        const [categoriesPage, typesPage] = await Promise.all([
          getCostCategories(session, onSessionRefresh),
          getCostTypes(session, onSessionRefresh),
        ]);
        const laborTypeIds = new Set(
          typesPage.items.filter((type) => type.kind === "labor").map((type) => type.id),
        );
        setCostCategories(categoriesPage.items.filter((category) => !laborTypeIds.has(category.cost_type_id)));
      } catch {
        // Non-blocking: the add-line form simply stays disabled without categories.
      }
    }

    void loadCostCategories();
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
    setEstimateTaskRowCount,
    selectedPlanningId,
    selectedPlanningIdRef,
    setPlanningDetail,
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
          estimateTaskRowCount={estimateTaskRowCount}
          costLines={costLines}
          costCategories={costCategories}
          costLineDraft={estimateCostLines.costLineDraft}
          onCategoryChange={estimateCostLines.updateCostLineDraftCategory}
          onLabelChange={estimateCostLines.updateCostLineDraftLabel}
          onQuantityChange={estimateCostLines.updateCostLineDraftQuantity}
          onUnitCostChange={estimateCostLines.updateCostLineDraftUnitCost}
          onPlannedDateChange={estimateCostLines.updateCostLineDraftPlannedDate}
          onAddCostLine={() => void estimateCostLines.addCostLine()}
          editingLineId={estimateCostLines.editingLineId}
          editingLineDraft={estimateCostLines.editingLineDraft}
          onEditLabelChange={estimateCostLines.updateEditingLineDraftLabel}
          onEditQuantityChange={estimateCostLines.updateEditingLineDraftQuantity}
          onEditUnitCostChange={estimateCostLines.updateEditingLineDraftUnitCost}
          onEditPlannedDateChange={estimateCostLines.updateEditingLineDraftPlannedDate}
          onStartEditCostLine={estimateCostLines.startEditCostLine}
          onSaveCostLine={(line) => void estimateCostLines.saveCostLine(line)}
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
        />

        <CommitmentsTabPlaceholder active={activeTab === "commitments"} />

        <AnalyticsTab active={activeTab === "analytics"} selectedEstimateId={selectedEstimateId} aggregates={aggregates} />
      </div>

      <CostLineDeleteDialog
        pendingDelete={estimateCostLines.costLinePendingDelete}
        onCancel={estimateCostLines.cancelDeleteCostLine}
        onConfirm={(line) => void estimateCostLines.removeCostLine(line)}
      />

      <EstimateValidationDialog
        open={estimateCostLines.estimateValidationOpen}
        onOpenChange={estimateCostLines.setEstimateValidationOpen}
        onConfirm={() => void estimateCostLines.validateEstimate()}
      />
    </>
  );
}
