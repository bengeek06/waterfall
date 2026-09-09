import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  createEstimateCostLine,
  createProjectEstimate,
  deleteEstimateCostLine,
  EstimateCostLine,
  exportEstimateExcel,
  getProjectCostCodes,
  Project,
  ProjectCostCode,
  ProjectEstimate,
  SessionExpiredError,
  updateEstimateCostLine,
  validateProjectEstimate,
} from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";
import type { ProjectTab } from "@/components/project-tabs";

type AppRouter = ReturnType<typeof useRouter>;

export type CostLineDraft = { categoryId: string; label: string; quantity: string; unitCost: string };
export type EditingLineDraft = { label: string; quantity: string; unitCost: string };

interface UseEstimateCostLinesParams {
  session: SessionTokens | null;
  project: Project | null;
  projectId: number;
  selectedEstimateId: number | null;
  estimates: ProjectEstimate[];
  setEstimates: (updater: (previous: ProjectEstimate[]) => ProjectEstimate[]) => void;
  setSelectedEstimateId: (id: number) => void;
  setActiveTab: (tab: ProjectTab) => void;
  setCostLines: (updater: (previous: EstimateCostLine[]) => EstimateCostLine[]) => void;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  setError: (message: string | null) => void;
}

// Extracted from ProjectDetailsPage (E4-11 / #151): owns every piece of state and every handler
// specific to the "Devis" tab's cost lines (add/edit/delete/validate/export/new-draft). Pure
// mechanical move -- see page.tsx call site (Devis tab) for wiring.
export function useEstimateCostLines({
  session,
  project,
  projectId,
  selectedEstimateId,
  estimates,
  setEstimates,
  setSelectedEstimateId,
  setActiveTab,
  setCostLines,
  onSessionRefresh,
  router,
  setError,
}: UseEstimateCostLinesParams) {
  const [costLineDraft, setCostLineDraft] = useState<CostLineDraft>({
    categoryId: "",
    label: "",
    quantity: "1",
    unitCost: "0",
  });
  const [editingLineId, setEditingLineId] = useState<number | null>(null);
  const [editingLineDraft, setEditingLineDraft] = useState<EditingLineDraft>({ label: "", quantity: "", unitCost: "" });
  const [costLinePendingDelete, setCostLinePendingDelete] = useState<EstimateCostLine | null>(null);
  const [estimateValidationOpen, setEstimateValidationOpen] = useState(false);
  const [estimateBusy, setEstimateBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [projectCostCodes, setProjectCostCodes] = useState<ProjectCostCode[]>([]);
  const [selectedCostLineIds, setSelectedCostLineIds] = useState<Set<number>>(new Set());
  const [bulkCostCodeId, setBulkCostCodeId] = useState("");
  const [bulkAssignBusy, setBulkAssignBusy] = useState(false);

  const selectedEstimate = estimates.find((estimate) => estimate.id === selectedEstimateId) ?? null;

  // Loaded once per project, non-blocking: mirrors ProjectDetailsPage's loadCostCategories (the
  // cost-line "add" form's category picker) -- if it fails, the bulk-assignment selector below
  // simply has no options, it doesn't block or degrade the rest of the tab.
  useEffect(() => {
    async function loadProjectCostCodes() {
      if (!session) {
        return;
      }
      try {
        const codes = await getProjectCostCodes(projectId, session, onSessionRefresh);
        setProjectCostCodes(codes);
      } catch {
        // Non-blocking: the bulk-assignment selector simply stays empty without cost codes.
      }
    }

    void loadProjectCostCodes();
  }, [onSessionRefresh, projectId, session]);

  // A selection made on one estimate version's cost lines has no meaning once the user switches
  // to another version -- clear it so a stale set of ids can't silently carry over. Deliberate
  // synchronous render-body write (not a useEffect), same precedent as PlanningTreeTable's
  // versionKey-change reset: it must land within the same render as the selectedEstimateId prop
  // change, so no frame is ever painted with the previous version's selection still applied.
  const [renderedEstimateId, setRenderedEstimateId] = useState(selectedEstimateId);
  if (selectedEstimateId !== renderedEstimateId) {
    setRenderedEstimateId(selectedEstimateId);
    setSelectedCostLineIds(new Set());
  }
  // Read through this ref (not `selectedEstimateId` directly) after an `await` in
  // `bulkAssignCostCode`: the estimate version can switch while a bulk PATCH batch is
  // still in flight (nothing currently disables the version selector while busy), and a
  // stale batch's success/failure banner must never be attributed to whatever version
  // happens to be displayed once it resolves. React forbids writing to a ref during
  // render, so this is kept fresh via useLayoutEffect rather than a synchronous body
  // write -- same precedent as use-planning-delete-selection.ts's versionKeyRef.
  const selectedEstimateIdRef = useRef(selectedEstimateId);
  useLayoutEffect(() => {
    selectedEstimateIdRef.current = selectedEstimateId;
  }, [selectedEstimateId]);

  function updateCostLineDraftCategory(value: string) {
    setCostLineDraft((prev) => ({ ...prev, categoryId: value }));
  }
  function updateCostLineDraftLabel(value: string) {
    setCostLineDraft((prev) => ({ ...prev, label: value }));
  }
  function updateCostLineDraftQuantity(value: string) {
    setCostLineDraft((prev) => ({ ...prev, quantity: value }));
  }
  function updateCostLineDraftUnitCost(value: string) {
    setCostLineDraft((prev) => ({ ...prev, unitCost: value }));
  }
  function updateEditingLineDraftLabel(value: string) {
    setEditingLineDraft((prev) => ({ ...prev, label: value }));
  }
  function updateEditingLineDraftQuantity(value: string) {
    setEditingLineDraft((prev) => ({ ...prev, quantity: value }));
  }
  function updateEditingLineDraftUnitCost(value: string) {
    setEditingLineDraft((prev) => ({ ...prev, unitCost: value }));
  }

  function requestDeleteCostLine(line: EstimateCostLine) {
    setCostLinePendingDelete(line);
  }
  function cancelDeleteCostLine() {
    setCostLinePendingDelete(null);
  }
  function openEstimateValidation() {
    setEstimateValidationOpen(true);
  }

  function updateBulkCostCodeId(value: string) {
    setBulkCostCodeId(value);
  }

  // Applies each settled `updateEstimateCostLine` result to `costLines` (success only -- a
  // rejected line is simply left as-is so the user can retry it) and reports how many of each
  // there were, plus whether any failure was a session expiry (which, unlike a per-line error,
  // must interrupt the whole flow the same way every other handler in this file does).
  function applyBulkAssignResults(results: PromiseSettledResult<EstimateCostLine>[]) {
    let successCount = 0;
    let sessionExpired = false;
    for (const result of results) {
      if (result.status === "fulfilled") {
        successCount += 1;
        const updated = result.value;
        setCostLines((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
        continue;
      }
      const cause = result.reason;
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        sessionExpired = true;
      }
    }
    return { successCount, sessionExpired };
  }

  async function bulkAssignCostCode() {
    if (!session || selectedEstimateId === null || !bulkCostCodeId || selectedCostLineIds.size === 0) {
      return;
    }
    const costCodeId = Number(bulkCostCodeId);
    const lineIds = Array.from(selectedCostLineIds);
    const launchedEstimateId = selectedEstimateId;

    setBulkAssignBusy(true);
    setError(null);
    const results = await Promise.allSettled(
      lineIds.map((lineId) =>
        updateEstimateCostLine(
          projectId,
          launchedEstimateId,
          lineId,
          { cost_code_id: costCodeId },
          session,
          onSessionRefresh,
        ),
      ),
    );
    setBulkAssignBusy(false);
    const { successCount, sessionExpired } = applyBulkAssignResults(results);

    if (sessionExpired) {
      clearSession();
      router.push("/login");
      return;
    }
    // The estimate version may have changed while this batch was in flight (nothing
    // currently disables the version selector while busy) -- a stale batch must never
    // clear whatever selection the user has made since, nor attribute its
    // success/failure banner to a version it doesn't belong to.
    if (selectedEstimateIdRef.current !== launchedEstimateId) {
      return;
    }
    setSelectedCostLineIds(new Set());
    const failureCount = lineIds.length - successCount;
    if (failureCount > 0) {
      setError(
        `${successCount}/${lineIds.length} lignes affectées, ${failureCount} échec${failureCount > 1 ? "s" : ""}.`,
      );
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
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
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
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
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
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
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
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
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
      // A deleted line can no longer be part of a pending bulk cost-code assignment --
      // otherwise the selection count stays inflated and "Affecter" would send a doomed
      // PATCH for a line that no longer exists (#64/E6-03 review finding).
      setSelectedCostLineIds((previous) => {
        if (!previous.has(line.id)) {
          return previous;
        }
        const next = new Set(previous);
        next.delete(line.id);
        return next;
      });
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
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
      const validated = await validateProjectEstimate(projectId, selectedEstimateId, session, onSessionRefresh);
      setEstimates((previous) => previous.map((item) => (item.id === validated.id ? validated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de valider le devis.");
    } finally {
      setEstimateBusy(false);
    }
  }

  return {
    costLineDraft,
    editingLineId,
    editingLineDraft,
    costLinePendingDelete,
    estimateValidationOpen,
    setEstimateValidationOpen,
    estimateBusy,
    exportBusy,
    projectCostCodes,
    selectedCostLineIds,
    setSelectedCostLineIds,
    bulkCostCodeId,
    bulkAssignBusy,
    updateBulkCostCodeId,
    bulkAssignCostCode,
    updateCostLineDraftCategory,
    updateCostLineDraftLabel,
    updateCostLineDraftQuantity,
    updateCostLineDraftUnitCost,
    updateEditingLineDraftLabel,
    updateEditingLineDraftQuantity,
    updateEditingLineDraftUnitCost,
    requestDeleteCostLine,
    cancelDeleteCostLine,
    openEstimateValidation,
    exportExcel,
    createDraftEstimate,
    addCostLine,
    startEditCostLine,
    saveCostLine,
    removeCostLine,
    validateEstimate,
  };
}
