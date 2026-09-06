import { useState } from "react";
import type { useRouter } from "next/navigation";

import {
  ApiError,
  createEstimateCostLine,
  createProjectEstimate,
  deleteEstimateCostLine,
  EstimateCostLine,
  exportEstimateExcel,
  Project,
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

  const selectedEstimate = estimates.find((estimate) => estimate.id === selectedEstimateId) ?? null;

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
      const validated = await validateProjectEstimate(projectId, selectedEstimateId, session, onSessionRefresh);
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

  return {
    costLineDraft,
    editingLineId,
    editingLineDraft,
    costLinePendingDelete,
    estimateValidationOpen,
    setEstimateValidationOpen,
    estimateBusy,
    exportBusy,
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
