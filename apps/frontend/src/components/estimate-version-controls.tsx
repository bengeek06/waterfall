"use client";

import { Button } from "@/components/ui/button";
import type { ProjectEstimate } from "@/lib/backend";

export type EstimateVersionControlsProps = {
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
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the estimate version selector plus the
// new-draft/export/validate action buttons. Verbatim JSX move -- see page.tsx call site for
// wiring.
export function EstimateVersionControls({
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
}: EstimateVersionControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {estimates.length ? (
        <label className="grid gap-1 text-xs text-muted-foreground">
          Version
          <select
            className="h-8 min-w-24 rounded-md border border-input bg-background px-2 text-sm text-foreground"
            value={selectedEstimateId ?? ""}
            onChange={(event) => onSelectEstimate(Number(event.target.value))}
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
        <Button type="button" onClick={onNewDraft}>
          Nouveau brouillon
        </Button>
      ) : null}
      {estimates.length ? (
        <Button variant="outline" type="button" disabled={exportBusy || isReadOnlyProject} onClick={onExport}>
          {exportBusy ? "Export..." : "Export Excel"}
        </Button>
      ) : null}
      {canEditEstimate ? (
        <Button variant="outline" type="button" disabled={estimateBusy} onClick={onOpenValidation}>
          Valider le devis
        </Button>
      ) : null}
    </div>
  );
}
