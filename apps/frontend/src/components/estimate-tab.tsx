"use client";

import { CostLineForm, type CostLineDraft } from "@/components/cost-line-form";
import { CostLinesTable, type EditingLineDraft } from "@/components/cost-lines-table";
import { EstimateVersionControls } from "@/components/estimate-version-controls";
import type { CostCategory, EstimateCostLine, ProjectEstimate } from "@/lib/backend";

export type EstimateTabProps = {
  active: boolean;
  estimates: ProjectEstimate[];
  selectedEstimateId: number | null;
  onSelectEstimate: (estimateId: number) => void;
  isReadOnlyProject: boolean;
  onNewDraft: () => void;
  exportBusy: boolean;
  onExport: () => void;
  canEditEstimate: boolean;
  estimateBusy: boolean;
  onOpenValidation: () => void;
  estimateTaskRowCount: number;
  costLines: EstimateCostLine[];
  costCategories: CostCategory[];
  costLineDraft: CostLineDraft;
  onCategoryChange: (value: string) => void;
  onLabelChange: (value: string) => void;
  onQuantityChange: (value: string) => void;
  onUnitCostChange: (value: string) => void;
  onAddCostLine: () => void;
  editingLineId: number | null;
  editingLineDraft: EditingLineDraft;
  onEditLabelChange: (value: string) => void;
  onEditQuantityChange: (value: string) => void;
  onEditUnitCostChange: (value: string) => void;
  onStartEditCostLine: (line: EstimateCostLine) => void;
  onSaveCostLine: (line: EstimateCostLine) => void;
  onRequestDeleteCostLine: (line: EstimateCostLine) => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): composes the whole "Devis" tab (version
// controls, cost-line form, cost lines table). Gates its own visibility via the `active` prop
// instead of a ternary at the call site, matching PlanningTab. Verbatim JSX move -- see page.tsx
// call site for wiring.
export function EstimateTab({
  active,
  estimates,
  selectedEstimateId,
  onSelectEstimate,
  isReadOnlyProject,
  onNewDraft,
  exportBusy,
  onExport,
  canEditEstimate,
  estimateBusy,
  onOpenValidation,
  estimateTaskRowCount,
  costLines,
  costCategories,
  costLineDraft,
  onCategoryChange,
  onLabelChange,
  onQuantityChange,
  onUnitCostChange,
  onAddCostLine,
  editingLineId,
  editingLineDraft,
  onEditLabelChange,
  onEditQuantityChange,
  onEditUnitCostChange,
  onStartEditCostLine,
  onSaveCostLine,
  onRequestDeleteCostLine,
}: EstimateTabProps) {
  if (!active) {
    return null;
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2>Versions de devis</h2>
          <p className="text-sm text-muted-foreground">
            {canEditEstimate ? "Le brouillon sélectionné est éditable." : "Cette version n'est plus modifiable."}
          </p>
        </div>
        <EstimateVersionControls
          estimates={estimates}
          selectedEstimateId={selectedEstimateId}
          onSelectEstimate={onSelectEstimate}
          isReadOnlyProject={isReadOnlyProject}
          onNewDraft={onNewDraft}
          exportBusy={exportBusy}
          onExport={onExport}
          canEditEstimate={canEditEstimate}
          estimateBusy={estimateBusy}
          onOpenValidation={onOpenValidation}
        />
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
            <CostLineForm
              costCategories={costCategories}
              costLineDraft={costLineDraft}
              onCategoryChange={onCategoryChange}
              onLabelChange={onLabelChange}
              onQuantityChange={onQuantityChange}
              onUnitCostChange={onUnitCostChange}
              estimateBusy={estimateBusy}
              onAdd={onAddCostLine}
            />
          ) : null}

          <CostLinesTable
            costLines={costLines}
            canEditEstimate={canEditEstimate}
            editingLineId={editingLineId}
            editingLineDraft={editingLineDraft}
            onEditLabelChange={onEditLabelChange}
            onEditQuantityChange={onEditQuantityChange}
            onEditUnitCostChange={onEditUnitCostChange}
            estimateBusy={estimateBusy}
            onStartEdit={onStartEditCostLine}
            onSave={onSaveCostLine}
            onRequestDelete={onRequestDeleteCostLine}
          />
        </div>
      ) : null}
    </div>
  );
}
