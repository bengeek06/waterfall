"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  CostCategory,
  createPlanningStructure,
  createEstimateCostLine,
  createImportBatch,
  createProjectEstimate,
  deleteEstimateCostLine,
  EstimateAggregates,
  EstimateCostLine,
  exportEstimateExcel,
  exportProjectXml,
  getCostCategories,
  getCostTypes,
  getEstimateAggregates,
  getImportBatchStatus,
  getImportBatchDiff,
  getPlanning,
  getPlanningStructureDraft,
  getProject,
  listPlannings,
  listEstimateCostLines,
  listEstimateTaskRows,
  listProjectEstimates,
  Project,
  Planning,
  PlanningDetail,
  movePlanningTasks,
  ProjectEstimate,
  runImportBatch,
  savePlanningStructureDraft,
  SessionExpiredError,
  type ImportDiff,
  type PlanningTaskScheduleUpdate,
  restoreSession,
  reopenPlanningStructure,
  setDisplayedPlanning,
  setPlanningReference,
  updateEstimateCostLine,
  updatePlanningTaskSchedule,
  updateProject,
  uploadImportSourceXml,
  validatePlanning,
  validateProjectEstimate,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";
import {
  buildPlanningStructurePayload,
  getPlanningStructureDraftRows,
  structureToDraftRows,
  type PlanningStructureDraftRow,
} from "@/lib/planning-structure";
import { PlanningTreeTable } from "@/components/planning-tree-table";
import type { PlanningMoveCommand } from "@/lib/planning-tree";
import { ReadOnlyGantt } from "@/components/read-only-gantt";
import { ProjectTabs, type ProjectTab } from "@/components/project-tabs";

const MAX_IMPORT_FILE_SIZE = 25 * 1024 * 1024;
let nextStructureRowId = 2;
export default function ProjectDetailsPage() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId);

  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [project, setProject] = useState<Project | null>(null);
  const [plannings, setPlannings] = useState<Planning[]>([]);
  const [selectedPlanningId, setSelectedPlanningId] = useState<number | null>(null);
  const selectedPlanningIdRef = useRef(selectedPlanningId);
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
  const [structureOpen, setStructureOpen] = useState(false);
  const [editingProjectInfo, setEditingProjectInfo] = useState(false);
  const [projectInfoDraft, setProjectInfoDraft] = useState({ name: "", shortDescription: "" });
  const [projectInfoBusy, setProjectInfoBusy] = useState(false);
  const [planningExportBusy, setPlanningExportBusy] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importReview, setImportReview] = useState<{ batchId: number; diff: ImportDiff } | null>(null);
  const [importFeedback, setImportFeedback] = useState<string | null>(null);
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
  const [costLinePendingDelete, setCostLinePendingDelete] = useState<EstimateCostLine | null>(null);
  const [estimateValidationOpen, setEstimateValidationOpen] = useState(false);
  const [estimateBusy, setEstimateBusy] = useState(false);
  const [aggregates, setAggregates] = useState<EstimateAggregates | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<ProjectTab>("planning");
  const [structureDraft, setStructureDraft] = useState<PlanningStructureDraftRow[]>([
    { rowId: "row-1", postKey: "post-1", postName: "", lotKey: "lot-1", lotName: "", deliverables: "" },
  ]);
  const [structureBusy, setStructureBusy] = useState(false);
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
        if (cancelled) {
          return;
        }
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
          setError("Erreur inattendue lors du chargement du projet.");
        }
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

  useEffect(() => {
    let cancelled = false;

    async function loadPlanningDetail() {
      if (!session || selectedPlanningId === null) {
        setPlanningDetail(null);
        setPlanningDetailBusy(false);
        return;
      }
      setPlanningDetail(null);
      setPlanningDetailBusy(true);
      try {
        const detail = await getPlanning(projectId, selectedPlanningId, session, onSessionRefresh);
        const savedDraft = await getPlanningStructureDraft(projectId, session, onSessionRefresh);
        if (!cancelled) {
          setPlanningDetail(detail);
          const rows = savedDraft
            ? structureToDraftRows(savedDraft.structure)
            : getPlanningStructureDraftRows(detail);
          if (
            rows.length &&
            rows.every(
              (row) =>
                row.postKey.trim() &&
                row.postName.trim() &&
                row.lotKey.trim() &&
                row.lotName.trim() &&
                row.deliverables.trim(),
            )
          ) {
            setStructureDraft(rows);
          }
        }
      } catch (cause) {
        if (cancelled) {
          return;
        }
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "Impossible de charger le planning.");
      } finally {
        if (!cancelled) {
          setPlanningDetailBusy(false);
        }
      }
    }

    void loadPlanningDetail();
    return () => {
      cancelled = true;
    };
  }, [onSessionRefresh, projectId, router, selectedPlanningId, session]);

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
        if (cancelled) {
          return;
        }
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
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
        const [categories, types] = await Promise.all([
          getCostCategories(session, onSessionRefresh),
          getCostTypes(session, onSessionRefresh),
        ]);
        const laborTypeIds = new Set(types.filter((type) => type.kind === "labor").map((type) => type.id));
        setCostCategories(categories.filter((category) => !laborTypeIds.has(category.cost_type_id)));
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
        if (cancelled) {
          return;
        }
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
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
  const isReadOnlyProject = project?.status === "perdu" || project?.status === "termine" || project?.status === "abandonne";
  const canEditEstimate = selectedEstimate?.status === "draft" && !isReadOnlyProject;
  const selectedPlanning = plannings.find((planning) => planning.id === selectedPlanningId) ?? null;

  async function selectPlanning(planningId: number) {
    if (!session || planningId === selectedPlanningId) {
      return;
    }
    if (isReadOnlyProject) {
      updateSelectedPlanningId(planningId);
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const updatedProject = await setDisplayedPlanning(
        projectId,
        planningId,
        session,
        onSessionRefresh,
      );
      updateSelectedPlanningId(planningId);
      setProject(updatedProject);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de sélectionner le planning.");
    } finally {
      setPlanningBusy(false);
    }
  }

  async function validateSelectedPlanning() {
    if (!session || !selectedPlanning || selectedPlanning.status !== "draft" || isReadOnlyProject) {
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const validated = await validatePlanning(
        projectId,
        selectedPlanning.id,
        session,
        onSessionRefresh,
      );
      setPlannings((previous) => previous.map((item) => (item.id === validated.id ? validated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de valider le planning.");
    } finally {
      setPlanningBusy(false);
    }
  }

  async function movePlanningTaskSelection(command: PlanningMoveCommand) {
    if (!session || !selectedPlanning || selectedPlanning.status !== "draft" || isReadOnlyProject) {
      return;
    }
    const requestedPlanningId = selectedPlanning.id;
    setPlanningMutationBusy(true);
    setError(null);
    try {
      const updated = await movePlanningTasks(
        projectId,
        requestedPlanningId,
        command,
        session,
        onSessionRefresh,
      );
      // The user may have switched to another planning version while this request was in flight;
      // applying it now would silently replace that version's tree with a stale one.
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setError(cause instanceof ApiError ? cause.message : "Impossible de déplacer les tâches sélectionnées.");
      }
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  // Returns whether the update was actually persisted server-side, so the caller (the tree
  // table's inline schedule edit) knows whether it is safe to discard the user's local draft.
  async function updateTaskScheduleSelection(
    taskUid: number,
    payload: PlanningTaskScheduleUpdate,
  ): Promise<boolean> {
    if (!session || !selectedPlanning || selectedPlanning.status !== "draft" || isReadOnlyProject) {
      return false;
    }
    const requestedPlanningId = selectedPlanning.id;
    setPlanningMutationBusy(true);
    setError(null);
    try {
      const updated = await updatePlanningTaskSchedule(
        projectId,
        requestedPlanningId,
        taskUid,
        payload,
        session,
        onSessionRefresh,
      );
      // The user may have switched to another planning version while this request was in flight;
      // applying it now would silently replace that version's tree with a stale one. The update
      // itself did succeed server-side though (only its local rendering is skipped here), so this
      // still reports success to the caller.
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setPlanningDetail(updated);
      }
      return true;
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return false;
      }
      if (selectedPlanningIdRef.current === requestedPlanningId) {
        setError(cause instanceof ApiError ? cause.message : "Impossible de mettre à jour la planification de la tâche.");
      }
      return false;
    } finally {
      setPlanningMutationBusy(false);
    }
  }

  async function setSelectedPlanningAsReference() {
    if (!session || !selectedPlanning || selectedPlanning.status !== "validated" || isReadOnlyProject) {
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const updatedProject = await setPlanningReference(
        projectId,
        selectedPlanning.id,
        session,
        onSessionRefresh,
      );
      const planningMetadata = await listPlannings(projectId, session, onSessionRefresh);
      setProject(updatedProject);
      setPlannings(planningMetadata);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de définir la référence.");
    } finally {
      setPlanningBusy(false);
    }
  }

  async function reopenStructure() {
    if (!session || isReadOnlyProject) {
      return;
    }
    setPlanningBusy(true);
    setError(null);
    try {
      const updatedProject = await reopenPlanningStructure(projectId, session, onSessionRefresh);
      const planningMetadata = await listPlannings(projectId, session, onSessionRefresh);
      const nextPlanningId = updatedProject.displayed_planning_id ?? planningMetadata.at(-1)?.id ?? null;
      const reopenedDetail = nextPlanningId
        ? await getPlanning(projectId, nextPlanningId, session, onSessionRefresh)
        : null;
      const savedDraft = await getPlanningStructureDraft(projectId, session, onSessionRefresh);
      setProject(updatedProject);
      setPlannings(planningMetadata);
      updateSelectedPlanningId(nextPlanningId);
      const rows = savedDraft
        ? structureToDraftRows(savedDraft.structure)
        : getPlanningStructureDraftRows(reopenedDetail);
      if (
        rows.length &&
        rows.every(
          (row) =>
            row.postKey.trim() &&
            row.postName.trim() &&
            row.lotKey.trim() &&
            row.lotName.trim() &&
            row.deliverables.trim(),
        )
      ) {
        setStructureDraft(rows);
      }
      setPlanningDetail(reopenedDetail);
      setStructureOpen(true);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de rouvrir la structure.");
    } finally {
      setPlanningBusy(false);
    }
  }

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

  const postGroups = useMemo(() => {
    const groups: { groupId: string; postKey: string; postName: string; lots: { row: PlanningStructureDraftRow }[] }[] = [];
    const byPostKey = new Map<string, (typeof groups)[number]>();
    for (const row of structureDraft) {
      let group = byPostKey.get(row.postKey);
      if (!group) {
        group = { groupId: row.rowId, postKey: row.postKey, postName: row.postName, lots: [] };
        byPostKey.set(row.postKey, group);
        groups.push(group);
      }
      group.lots.push({ row });
    }
    return groups;
  }, [structureDraft]);

  function updatePostField(postKey: string, field: "postKey" | "postName", value: string) {
    setStructureDraft((previous) => previous.map((row) => (row.postKey === postKey ? { ...row, [field]: value } : row)));
  }

  function updateLotField(rowId: string, field: "lotKey" | "lotName", value: string) {
    setStructureDraft((previous) => previous.map((row) => (row.rowId === rowId ? { ...row, [field]: value } : row)));
  }

  function updateDeliverable(rowId: string, deliverableIndex: number, value: string) {
    setStructureDraft((previous) =>
      previous.map((row) => {
        if (row.rowId !== rowId) return row;
        const deliverables = row.deliverables.split(",");
        deliverables[deliverableIndex] = value;
        return { ...row, deliverables: deliverables.join(",") };
      }),
    );
  }

  function addDeliverable(rowId: string) {
    setStructureDraft((previous) =>
      previous.map((row) => (row.rowId === rowId ? { ...row, deliverables: `${row.deliverables},` } : row)),
    );
  }

  function removeDeliverable(rowId: string, deliverableIndex: number) {
    setStructureDraft((previous) =>
      previous.map((row) => {
        if (row.rowId !== rowId) return row;
        const deliverables = row.deliverables.split(",").filter((_, index) => index !== deliverableIndex);
        return { ...row, deliverables: deliverables.join(",") };
      }),
    );
  }

  function removeLot(rowId: string) {
    setStructureDraft((previous) => previous.filter((row) => row.rowId !== rowId));
  }

  function addLotToPost(postKey: string, postName: string) {
    const id = nextStructureRowId++;
    setStructureDraft((previous) => [
      ...previous,
      { rowId: `row-${id}`, postKey, postName, lotKey: `lot-${id}`, lotName: "", deliverables: "" },
    ]);
  }

  function addPost() {
    const id = nextStructureRowId++;
    setStructureDraft((previous) => [
      ...previous,
      { rowId: `row-${id}`, postKey: `post-${id}`, postName: "", lotKey: `lot-${id}`, lotName: "", deliverables: "" },
    ]);
  }

  function getPlanningStructurePayload() {
    if (!session || isReadOnlyProject) {
      router.push("/login");
      return null;
    }
    const rows = structureDraft;
    const hasIncompleteRow = rows.some(
      (row) =>
        !row.postKey.trim() ||
        !row.postName.trim() ||
        !row.lotKey.trim() ||
        !row.lotName.trim() ||
        !row.deliverables.trim(),
    );
    if (!rows.length || hasIncompleteRow) {
      setError("Renseigne au moins un poste, un lot et un livrable.");
      return null;
    }
    return buildPlanningStructurePayload(rows);
  }

  async function savePlanningStructure() {
    const payload = getPlanningStructurePayload();
    if (!session || !payload) {
      return;
    }

    setStructureBusy(true);
    setError(null);
    try {
      await savePlanningStructureDraft(projectId, payload, session, onSessionRefresh);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'enregistrer la structure.");
    } finally {
      setStructureBusy(false);
    }
  }

  async function generatePlanningStructure() {
    const payload = getPlanningStructurePayload();
    if (!session || !payload) {
      return;
    }

    setStructureBusy(true);
    setError(null);
    try {
      await createPlanningStructure(projectId, payload, session, onSessionRefresh);
      const [updatedProject, planningMetadata] = await Promise.all([
        getProject(projectId, session, onSessionRefresh),
        listPlannings(projectId, session, onSessionRefresh),
      ]);
      const nextPlanningId =
        updatedProject.displayed_planning_id ?? planningMetadata.at(-1)?.id ?? null;
      const detail = nextPlanningId
        ? await getPlanning(projectId, nextPlanningId, session, onSessionRefresh)
        : null;
      setProject(updatedProject);
      setPlannings(planningMetadata);
      updateSelectedPlanningId(nextPlanningId);
      setPlanningDetail(detail);
      setStructureOpen(false);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible d'enregistrer la structure.");
    } finally {
      setStructureBusy(false);
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

  async function preparePlanningImport() {
    if (!session || !project || !importFile) {
      return;
    }
    setImportBusy(true);
    setError(null);
    setImportFeedback(null);
    try {
      const batch = await createImportBatch(projectId, project.name, session, onSessionRefresh);
      await uploadImportSourceXml(batch.id, importFile, session, onSessionRefresh);
      await runImportBatch(batch.id, session, onSessionRefresh, true, false);
      const diff = await getImportBatchDiff(batch.id, session, onSessionRefresh);
      setImportReview({ batchId: batch.id, diff });
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

  async function confirmPlanningImport() {
    if (!session || !project || !importReview) {
      return;
    }
    setImportBusy(true);
    setError(null);
    setImportFeedback(null);
    try {
      await runImportBatch(importReview.batchId, session, onSessionRefresh, false, true);
      let batchStatus = await getImportBatchStatus(importReview.batchId, session, onSessionRefresh);
      for (let index = 0; index < 20; index += 1) {
        if (batchStatus.status === "success" || batchStatus.status === "failed") {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        batchStatus = await getImportBatchStatus(importReview.batchId, session, onSessionRefresh);
      }
      if (batchStatus.status !== "success") {
        throw new Error(batchStatus.errorMessage ?? "Import en échec.");
      }

      setImportReview(null);
      setImportFile(null);
      setImportFeedback("Import réussi. Actualisation du projet en cours...");

      const [projectRefresh, planningsRefresh] = await Promise.allSettled([
        getProject(projectId, session, onSessionRefresh),
        listPlannings(projectId, session, onSessionRefresh),
      ]);
      const refreshFailures: string[] = [];
      if (projectRefresh.status === "fulfilled") {
        setProject(projectRefresh.value);
      } else {
        if (projectRefresh.reason instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        refreshFailures.push("le projet");
      }
      if (planningsRefresh.status === "fulfilled") {
        setPlannings(planningsRefresh.value);
      } else {
        if (planningsRefresh.reason instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        refreshFailures.push("les versions de planning");
      }

      const refreshedProject = projectRefresh.status === "fulfilled" ? projectRefresh.value : project;
      const refreshedPlannings = planningsRefresh.status === "fulfilled" ? planningsRefresh.value : plannings;
      const nextPlanningId =
        refreshedProject?.displayed_planning_id ?? refreshedPlannings.at(-1)?.id ?? null;
      if (nextPlanningId) {
        try {
          const updatedDetail = await getPlanning(projectId, nextPlanningId, session, onSessionRefresh);
          setPlanningDetail(updatedDetail);
        } catch (cause) {
          if (cause instanceof SessionExpiredError) {
            clearSession();
            router.push("/login");
            return;
          }
          refreshFailures.push("le détail du planning");
        }
      } else {
        setPlanningDetail(null);
      }
      updateSelectedPlanningId(nextPlanningId);
      setImportFeedback(
        refreshFailures.length
          ? `Import réussi, mais ${refreshFailures.join(" et ")} n'ont pas pu être actualisés. Recharge la page pour voir l'état à jour.`
          : "Import réussi. Le planning affiché a été actualisé.",
      );
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
      <Card>
        <CardContent className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            {editingProjectInfo ? (
              <div className="grid max-w-2xl gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="project-info-name">Nom du projet</Label>
                  <Input
                    id="project-info-name"
                    value={projectInfoDraft.name}
                    onChange={(event) =>
                      setProjectInfoDraft((prev) => ({ ...prev, name: event.target.value }))
                    }
                    maxLength={255}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="project-info-description">Description courte</Label>
                  <Textarea
                    id="project-info-description"
                    rows={2}
                    value={projectInfoDraft.shortDescription}
                    onChange={(event) =>
                      setProjectInfoDraft((prev) => ({ ...prev, shortDescription: event.target.value }))
                    }
                    maxLength={500}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    disabled={projectInfoBusy}
                    onClick={() => void saveProjectInfo()}
                  >
                    Sauver
                  </Button>
                  <Button variant="outline" type="button" onClick={() => setEditingProjectInfo(false)}>
                    Annuler
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-bold">{project?.name ?? `Projet #${projectId}`}</h1>
                  {project?.code ? <Badge variant="outline">{project.code}</Badge> : null}
                </div>
                <p className="mt-1 text-sm text-muted-foreground italic">
                  {project?.short_description ?? "Pilotage du planning et des versions de devis."}
                </p>
              </>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {!editingProjectInfo && !isReadOnlyProject ? (
              <Button variant="outline" type="button" onClick={startEditProjectInfo}>
                Modifier
              </Button>
            ) : null}
            <Button variant="outline" nativeButton={false} render={<Link href="/projects" />}>Retour projets</Button>
          </div>
        </CardContent>
      </Card>

      <div className="mt-4">
        <ProjectTabs activeTab={activeTab} onChange={setActiveTab} />
      </div>

      <div className="space-y-4">
        {busy ? <p className="text-sm text-muted-foreground" role="status">Chargement...</p> : null}
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
        {importFeedback ? <Alert><AlertDescription>{importFeedback}</AlertDescription></Alert> : null}

        {activeTab === "planning" && project?.status === "initialise" ? (
          <Card className="mb-4">
            <CardContent className="flex flex-wrap items-end justify-between gap-4 pt-6">
              <div className="flex flex-wrap items-end gap-3">
                <div className="grid gap-2">
                  <Label htmlFor="planning-import-file">Importer un planning MS Project (.xml)</Label>
                  <Input
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
                <Button
                type="button"
                disabled={!importFile || importBusy}
                onClick={() => void preparePlanningImport()}
              >
                {importBusy ? "Prévisualisation..." : "Prévisualiser l'import"}
                </Button>
              </div>
              <Button
              variant="outline"
              type="button"
              disabled={planningExportBusy}
              onClick={() => void exportPlanningXml()}
            >
              {planningExportBusy ? "Export..." : "Export XML"}
              </Button>
            </CardContent>
          </Card>
        ) : null}

        {activeTab === "planning" && importReview ? (
          <Alert className="mb-4">
            <AlertTitle><h2>Remplacement à confirmer</h2></AlertTitle>
            <AlertDescription>
              Cette prévisualisation contient {importReview.diff.items.length} changement(s).
              Le planning actuel ne sera remplacé qu&apos;après confirmation explicite.
            </AlertDescription>
            {importReview.diff.identicalSource ? (
              <AlertDescription>La source est identique à la dernière importation.</AlertDescription>
            ) : null}
            <Button
              className="mt-3"
              variant="destructive"
              type="button"
              disabled={importBusy}
              onClick={() => void confirmPlanningImport()}
            >
              {importBusy ? "Import..." : "Confirmer le remplacement"}
            </Button>
          </Alert>
        ) : null}

        {activeTab === "planning" && structureOpen && !isReadOnlyProject ? (
          <Card className="mb-4">
            <CardContent className="pt-6">
            <h2 className="text-lg font-semibold">Structure initiale</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Définis les postes, lots et livrables. L&apos;API enregistre la structure en générant le squelette.
            </p>
            {postGroups.map((group, postIndex) => (
              <div className="mt-4 rounded-lg border p-4" key={group.groupId}>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Input
                    aria-label={`Clé poste ${postIndex + 1}`}
                    placeholder="Clé poste"
                    value={group.postKey}
                    onChange={(event) => updatePostField(group.postKey, "postKey", event.target.value)}
                  />
                  <Input
                    aria-label={`Nom poste ${postIndex + 1}`}
                    placeholder="Poste"
                    value={group.postName}
                    onChange={(event) => updatePostField(group.postKey, "postName", event.target.value)}
                  />
                </div>

                {group.lots.map(({ row }, lotIndex) => {
                  const deliverables = row.deliverables.split(",");
                  return (
                    <div className="mt-3 grid gap-3 rounded-md border bg-muted/30 p-3" key={row.rowId}>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="grid flex-1 gap-3 sm:grid-cols-2">
                          <Input
                            aria-label={`Clé lot ${postIndex + 1}.${lotIndex + 1}`}
                            placeholder="Clé lot"
                            value={row.lotKey}
                            onChange={(event) => updateLotField(row.rowId, "lotKey", event.target.value)}
                          />
                          <Input
                            aria-label={`Nom lot ${postIndex + 1}.${lotIndex + 1}`}
                            placeholder="Lot"
                            value={row.lotName}
                            onChange={(event) => updateLotField(row.rowId, "lotName", event.target.value)}
                          />
                        </div>
                        {structureDraft.length > 1 ? (
                          <Button
                            variant="destructive"
                            size="sm"
                            type="button"
                            aria-label={`Supprimer le lot ${postIndex + 1}.${lotIndex + 1}`}
                            onClick={() => removeLot(row.rowId)}
                          >
                            Supprimer le lot
                          </Button>
                        ) : null}
                      </div>

                      <p className="text-xs font-medium text-muted-foreground">Livrables</p>
                      {deliverables.map((deliverable, deliverableIndex) => (
                        <div className="flex items-center gap-2" key={deliverableIndex}>
                          <Input
                            aria-label={`Livrable ${postIndex + 1}.${lotIndex + 1}.${deliverableIndex + 1}`}
                            placeholder="Nom du livrable"
                            value={deliverable}
                            onChange={(event) => updateDeliverable(row.rowId, deliverableIndex, event.target.value)}
                          />
                          <Button
                            variant="outline"
                            size="sm"
                            type="button"
                            aria-label={`Supprimer le livrable ${postIndex + 1}.${lotIndex + 1}.${deliverableIndex + 1}`}
                            onClick={() => removeDeliverable(row.rowId, deliverableIndex)}
                          >
                            Supprimer
                          </Button>
                        </div>
                      ))}
                      <Button variant="outline" size="sm" type="button" className="w-fit" onClick={() => addDeliverable(row.rowId)}>
                        Ajouter un livrable
                      </Button>
                    </div>
                  );
                })}

                <Button
                  variant="outline"
                  size="sm"
                  type="button"
                  className="mt-3"
                  onClick={() => addLotToPost(group.postKey, group.postName)}
                >
                  Ajouter un lot
                </Button>
              </div>
            ))}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="outline" type="button" onClick={addPost}>
                Ajouter un poste
              </Button>
              <Button
                type="button"
                disabled={structureBusy}
                onClick={() => void savePlanningStructure()}
              >
                {structureBusy ? "Enregistrement..." : "Enregistrer la structure"}
              </Button>
              <Button
                type="button"
                disabled={structureBusy}
                onClick={() => void generatePlanningStructure()}
              >
                {structureBusy ? "Génération..." : "Générer le squelette"}
              </Button>
            </div>
            </CardContent>
          </Card>
        ) : null}

        {activeTab === "planning" && !structureOpen ? (
          <div className="grid gap-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2>Planning affiché</h2>
                <p className="text-sm text-muted-foreground">
                  {selectedPlanning
                    ? `Version ${selectedPlanning.version_number} - ${selectedPlanning.status}`
                    : "Aucune version de planning."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {plannings.length ? (
                  <label className="grid gap-1 text-xs text-muted-foreground">
                    Version affichée
                    <select
                      aria-label="Version affichée"
                      className="h-8 min-w-24 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                      value={selectedPlanningId ?? ""}
                      disabled={planningBusy}
                      onChange={(event) => void selectPlanning(Number(event.target.value))}
                    >
                      {plannings.map((planning) => (
                        <option key={planning.id} value={planning.id}>
                          V{planning.version_number} ({planning.status})
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {selectedPlanning?.status === "draft" ? (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={planningBusy || isReadOnlyProject}
                    onClick={() => void validateSelectedPlanning()}
                  >
                    Valider le planning
                  </Button>
                ) : null}
                {selectedPlanning?.status === "validated" && project?.planning_reference_id !== selectedPlanning.id ? (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={planningBusy || isReadOnlyProject}
                    onClick={() => void setSelectedPlanningAsReference()}
                  >
                    Définir comme référence
                  </Button>
                ) : null}
                {(plannings.some((planning) => planning.status === "draft") || project?.planning_reference_id !== null) && !isReadOnlyProject ? (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={planningBusy || isReadOnlyProject}
                    onClick={() => void reopenStructure()}
                  >
                    Rouvrir la structure
                  </Button>
                ) : null}
              </div>
            </div>
            {planningDetailBusy ? <p className="text-sm text-muted-foreground" role="status">Chargement du planning...</p> : null}
            {!planningDetailBusy && !planningDetail ? <p className="py-6 text-sm text-muted-foreground">Aucun planning sélectionné.</p> : null}
            {planningDetail?.tasks.length ? <ReadOnlyGantt tasks={planningDetail.tasks} /> : null}
            {planningDetail ? (
              <PlanningTreeTable
                tasks={planningDetail.tasks}
                versionKey={selectedPlanning?.id ?? null}
                readOnly={isReadOnlyProject || (selectedPlanning ? selectedPlanning.status !== "draft" : false)}
                onMove={(command) => void movePlanningTaskSelection(command)}
                onScheduleUpdate={(taskUid, payload) => updateTaskScheduleSelection(taskUid, payload)}
                mutationBusy={planningMutationBusy}
              />
            ) : null}
          </div>
        ) : null}

        {activeTab === "estimate" ? (
          <div className="grid gap-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2>Versions de devis</h2>
                <p className="text-sm text-muted-foreground">
                  {canEditEstimate
                    ? "Le brouillon sélectionné est éditable."
                    : "Cette version n'est plus modifiable."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {estimates.length ? (
                  <label className="grid gap-1 text-xs text-muted-foreground">
                    Version
                    <select
                      className="h-8 min-w-24 rounded-md border border-input bg-background px-2 text-sm text-foreground"
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
                {!isReadOnlyProject ? (
                  <Button type="button" onClick={() => void createDraftEstimate()}>
                    Nouveau brouillon
                  </Button>
                ) : null}
                {estimates.length ? (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={exportBusy || isReadOnlyProject}
                    onClick={() => void exportExcel()}
                  >
                    {exportBusy ? "Export..." : "Export Excel"}
                  </Button>
                ) : null}
                {canEditEstimate ? (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={estimateBusy}
                    onClick={() => setEstimateValidationOpen(true)}
                  >
                    Valider le devis
                  </Button>
                ) : null}
              </div>
            </div>
            {!estimates.length ? <p className="py-6 text-sm text-muted-foreground">Aucune version de devis.</p> : null}

            {estimates.length ? (
              <div className="grid gap-4">
                <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
                  <strong>{estimateTaskRowCount}</strong>
                  <span>tâches snapshotées</span>
                </div>
                <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
                  <strong>{costLines.length}</strong>
                  <span>lignes de coût</span>
                </div>

                {canEditEstimate ? (
                  <Card>
                    <CardContent className="grid gap-4 pt-6 md:grid-cols-5">
                    <div className="grid gap-2">
                      <Label htmlFor="cost-line-category">Catégorie</Label>
                      <select
                        id="cost-line-category"
                        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
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
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="cost-line-label">Libellé</Label>
                      <Input
                        id="cost-line-label"
                        value={costLineDraft.label}
                        onChange={(event) =>
                          setCostLineDraft((prev) => ({ ...prev, label: event.target.value }))
                        }
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="cost-line-quantity">Quantité</Label>
                      <Input
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
                    <div className="grid gap-2">
                      <Label htmlFor="cost-line-unit-cost">Coût unitaire</Label>
                      <Input
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
                    <div className="flex items-end">
                    <Button
                      type="button"
                      disabled={estimateBusy}
                      onClick={() => void addCostLine()}
                    >
                      Ajouter la ligne
                    </Button>
                    </div>
                    </CardContent>
                  </Card>
                ) : null}

                <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Catégorie</TableHead>
                        <TableHead>Libellé</TableHead>
                        <TableHead>Quantité</TableHead>
                        <TableHead>Coût unitaire</TableHead>
                        <TableHead>Montant</TableHead>
                        {canEditEstimate ? <TableHead>Action</TableHead> : null}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {costLines.map((line) => {
                        const editing = editingLineId === line.id;
                        return (
                          <TableRow key={line.id}>
                            <TableCell>{line.accounting_code}</TableCell>
                            <TableCell>
                              {editing ? (
                                <Input
                                  value={editingLineDraft.label}
                                  onChange={(event) =>
                                    setEditingLineDraft((prev) => ({ ...prev, label: event.target.value }))
                                  }
                                />
                              ) : (
                                line.label
                              )}
                            </TableCell>
                            <TableCell>
                              {editing ? (
                                <Input
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
                            </TableCell>
                            <TableCell>
                              {editing ? (
                                <Input
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
                            </TableCell>
                            <TableCell>{line.purchase_cost}</TableCell>
                            {canEditEstimate ? (
                              <TableCell>
                                <div className="flex flex-wrap gap-2">
                                  {editing ? (
                                    <Button
                                      size="sm"
                                      type="button"
                                      disabled={estimateBusy}
                                      onClick={() => void saveCostLine(line)}
                                    >
                                      Sauver
                                    </Button>
                                  ) : (
                                    <Button size="sm" variant="outline" type="button" onClick={() => startEditCostLine(line)}>
                                      Modifier
                                    </Button>
                                  )}
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    type="button"
                                    disabled={estimateBusy}
                                    onClick={() => setCostLinePendingDelete(line)}
                                  >
                                    Supprimer
                                  </Button>
                                </div>
                              </TableCell>
                            ) : null}
                          </TableRow>
                        );
                      })}
                      {!costLines.length ? (
                        <TableRow>
                          <TableCell colSpan={canEditEstimate ? 6 : 5} className="text-muted-foreground">
                            Aucune ligne de coût.
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </TableBody>
                </Table>
              </div>
            ) : null}
          </div>
        ) : null}

        {activeTab === "commitments" ? (
          <div className="grid min-h-45 content-center justify-items-start gap-4">
            <h2>Reste à engager</h2>
            <p className="text-sm text-muted-foreground">
              Le suivi budget de référence / engagé / reste à engager sera construit sur les versions
              « forecast_remaining » du jalon 9.
            </p>
          </div>
        ) : null}

        {activeTab === "analytics" ? (
          <div className="grid gap-4">
            <h2>Analytique</h2>
            {!selectedEstimateId ? <p className="text-sm text-muted-foreground">Sélectionne un devis dans l&apos;onglet Devis.</p> : null}
            {selectedEstimateId && !aggregates ? <p className="text-sm text-muted-foreground">Chargement des agrégats...</p> : null}
            {aggregates ? (
              <div className="grid gap-4">
                <div className="flex flex-wrap gap-3">
                  <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
                    <strong>{Number(aggregates.total_labor_cost).toFixed(2)}</strong>
                    <span>Total MO</span>
                  </div>
                  <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
                    <strong>{Number(aggregates.total_purchase_cost).toFixed(2)}</strong>
                    <span>Total Achat</span>
                  </div>
                  <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
                    <strong>{Number(aggregates.total_unburdened_cost).toFixed(2)}</strong>
                    <span>PRU non chargé</span>
                  </div>
                </div>

                <div className="pt-2">
                  <h3 className="mb-3 text-sm font-medium text-muted-foreground">Répartition par catégorie</h3>
                  {Object.keys(aggregates.by_category).length === 0 ? (
                    <p className="text-sm text-muted-foreground">Aucun montant à répartir pour ce devis.</p>
                  ) : (
                    (() => {
                      const entries = Object.entries(aggregates.by_category);
                      const max = Math.max(...entries.map(([, amount]) => Number(amount)), 1);
                      return (
                        <div className="grid gap-2">
                          {entries.map(([category, amount]) => (
                            <div className="grid grid-cols-[minmax(7.5rem,13.75rem)_1fr_auto] items-center gap-3" key={category}>
                              <span className="truncate text-sm">{category}</span>
                              <div className="relative h-3.5 rounded-full bg-muted">
                                <div
                                  className="absolute h-full rounded-full bg-primary"
                                  style={{ width: `${(Number(amount) / max) * 100}%` }}
                                />
                              </div>
                              <span className="text-sm text-muted-foreground">{Number(amount).toFixed(2)}</span>
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
      </div>

      <AlertDialog open={Boolean(costLinePendingDelete)} onOpenChange={(open) => !open && setCostLinePendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Supprimer cette ligne de coût ?</AlertDialogTitle>
            <AlertDialogDescription>
              {costLinePendingDelete ? `La ligne "${costLinePendingDelete.label}" sera supprimée définitivement.` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => {
              const line = costLinePendingDelete;
              setCostLinePendingDelete(null);
              if (line) void removeCostLine(line);
            }}>Supprimer</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={estimateValidationOpen} onOpenChange={setEstimateValidationOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Valider ce devis ?</AlertDialogTitle>
            <AlertDialogDescription>Après validation, ce devis deviendra immuable.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction onClick={() => {
              setEstimateValidationOpen(false);
              void validateEstimate();
            }}>Valider le devis</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
