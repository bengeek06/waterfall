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
import type { PlanningImportTarget } from "@/components/planning-import-panel";
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
import { validateImportFile } from "@/lib/planning-import-validation";
import { usePlanningDetailEffect } from "@/hooks/use-planning-detail";
import { usePlanningImport } from "@/hooks/use-planning-import";
import { usePlanningStructureEditor } from "@/hooks/use-planning-structure-editor";
import { useRevisionPlanning } from "@/hooks/use-revision-planning";
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

function didInitialLoadFail(busy: boolean, project: Project | null, error: string | null): boolean {
  return !busy && project === null && error !== null;
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
  // Write-only: nothing renders a busy state for the legacy planning detail any more. The detail
  // itself is still loaded, for the Devis tab's parent-task selector and its post-create refresh,
  // until E14-11 (#337) moves that side onto the revision too.
  const [, setPlanningDetailBusy] = useState(false);
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
  // Where the last confirmed import landed. The client does not choose the target revision -- the
  // import always writes into the latest one by version number -- so the screen has to say which
  // one it was, and whether it had to be created (#332).
  const [importTarget, setImportTarget] = useState<PlanningImportTarget | null>(null);
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
    setPlanningDetail,
    setPlanningDetailBusy,
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

  const revisionPlanning = useRevisionPlanning({
    session,
    projectId,
    onSessionRefresh,
    router,
    setError,
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

  /**
   * Clears everything the *previous* candidate file left on screen.
   *
   * `importReview.batchId` refers to whatever file was uploaded when "Prévisualiser l'import" was
   * last clicked, and confirming it after the candidate changed would silently apply the wrong
   * batch. `importTarget` is the "Import appliqué" banner naming the revision an earlier file
   * landed in: left up next to a freshly picked file it reads as if *that* file had already been
   * imported. Both are called in every branch of both handlers below, not just the happy path.
   */
  function resetImportBanners() {
    setImportReview(null);
    setImportTarget(null);
  }

  function onImportFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (file) {
      const validationError = validateImportFile(file);
      if (validationError) {
        setImportFile(null);
        latestImportFileRef.current = null;
        resetImportBanners();
        setError(validationError);
        event.target.value = "";
        return;
      }
    }
    setError(null);
    setImportFile(file);
    latestImportFileRef.current = file;
    resetImportBanners();
  }

  function onImportFilesDrop(files: FileList) {
    if (files.length === 0) {
      setImportFile(null);
      latestImportFileRef.current = null;
      resetImportBanners();
      setError("Le dépôt ne contient aucun fichier exploitable (dossier non pris en charge ou élément invalide).");
      return;
    }
    if (files.length > 1) {
      setImportFile(null);
      latestImportFileRef.current = null;
      resetImportBanners();
      setError("Dépose un seul fichier à la fois.");
      return;
    }
    const file = files[0];
    const validationError = validateImportFile(file);
    if (validationError) {
      setImportFile(null);
      latestImportFileRef.current = null;
      resetImportBanners();
      setError(validationError);
      return;
    }
    setError(null);
    setImportFile(file);
    latestImportFileRef.current = file;
    resetImportBanners();
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
    onImported: async ({ revisionId, revisionCreated }) => {
      if (revisionId === null) {
        return;
      }
      // Displays the revision the file actually landed in, and records where that was so the panel
      // can say it: the client never chooses the target (#332).
      const list = await revisionPlanning.reload(revisionId);
      const landed = list?.items.find((revision) => revision.revision_id === revisionId) ?? null;
      setImportTarget({
        revisionId,
        versionLabel: landed ? `V${landed.version_number}` : null,
        created: revisionCreated ?? false,
      });
    },
  });

  // A retry replays the write with the tree -- and therefore the `expected_lock_version` -- that
  // was on screen when it failed. Offered while another revision is displayed, it would write
  // into a revision the user has left, and its re-read would be dropped as stale: the write would
  // land with nothing on screen to say so. So the affordance exists only on its own revision.
  //
  // Defence in depth, and inert as things stand: `ProjectStatusBanners` only draws "Réessayer"
  // when `retryableActionMessage === error`, and `reportFailureFor` has already suppressed the
  // `setError` for a revision the user has left -- so the button has nothing to hang under
  // anyway. Same for `runWrite`'s own guard before `setRetryableAction`. Kept because each layer
  // stands on its own, and read as *coverage* by nobody: no test can distinguish them.
  const retryableAction =
    revisionPlanning.retryableAction?.revisionId === revisionPlanning.selectedRevisionId
      ? revisionPlanning.retryableAction
      : null;

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
          importTarget={importTarget}
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
          revisions={revisionPlanning.revisions}
          selectedRevision={revisionPlanning.selectedRevision}
          selectedRevisionId={revisionPlanning.selectedRevisionId}
          referenceRevisionId={revisionPlanning.referenceRevisionId}
          revisionsBusy={revisionPlanning.revisionsBusy}
          onSelectRevision={(revisionId) => revisionPlanning.selectRevision(revisionId)}
          onCreateDraft={() => void revisionPlanning.createDraftFromSelected()}
          onValidateRevision={() => void revisionPlanning.validateSelected()}
          onReopenStructure={() => void structureEditor.reopenStructure()}
          planningMutationBusy={revisionPlanning.mutationBusy}
          revisionFeedback={revisionPlanning.feedback}
          conflict={revisionPlanning.conflict}
          onReloadConflict={() => void revisionPlanning.reload()}
          hasError={error !== null}
          treeBusy={revisionPlanning.treeBusy}
          tree={revisionPlanning.tree}
          onMove={(mode, nodeIds) => void revisionPlanning.moveNodes(mode, nodeIds)}
          onScheduleUpdate={(nodeId, payload) => revisionPlanning.updatePlanning(nodeId, payload)}
          onEditLinks={(payload) => revisionPlanning.replacePredecessors(payload.nodeId, payload.predecessors)}
          onCreateTask={(command) =>
            void revisionPlanning.createTask({
              name: command.name,
              is_milestone: command.isMilestone,
              parent_id: command.parentId,
              position: command.position,
            })
          }
          onDeleteNodes={(nodeIds) => void revisionPlanning.deleteNodes(nodeIds)}
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
            void structureEditor.reopenStructure();
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
            void structureEditor.reopenStructure();
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
          onOpenRoleAssignmentDialogForRow={estimateCostLines.openRoleAssignmentDialogForRow}
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
