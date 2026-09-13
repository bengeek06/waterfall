"use client";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { ProjectCostCode } from "@/lib/backend";

export type BulkCostCodeAssignmentBarProps = {
  selectedCount: number;
  projectCostCodes: ProjectCostCode[];
  bulkCostCodeId: string;
  onBulkCostCodeIdChange: (value: string) => void;
  bulkAssignBusy: boolean;
  /**
   * Any other write in flight on the same revision (E14-11/#337).
   *
   * The assignment goes through the revision's single optimistic-lock counter, and the hook that
   * owns it refuses to start a second write while one is running: left out, the button stayed
   * clickable and the click was a no-op with nothing said. A command that cannot act says so.
   */
  mutationBusy: boolean;
  onAssign: () => void;
};

// New for E6-03 (#64): appears above CostLinesTable as soon as at least one row is selected,
// letting the user assign a single project cost code (E6-01/E6-02) to every selected row in one
// action. The flat `<select>` reuses roles-panel.tsx's exact pattern (`{code.code} - {code.name}`
// options, no tree indentation) rather than a dedicated tree widget. Gated by `canEditEstimate`
// at the call site (EstimateTab), same guard as the table's own selection checkboxes.
export function BulkCostCodeAssignmentBar({
  selectedCount,
  projectCostCodes,
  bulkCostCodeId,
  onBulkCostCodeIdChange,
  bulkAssignBusy,
  mutationBusy,
  onAssign,
}: BulkCostCodeAssignmentBarProps) {
  if (selectedCount === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-end gap-4 rounded-lg border bg-muted/40 px-4 py-3">
      <span className="text-sm text-muted-foreground">
        {selectedCount} ligne{selectedCount > 1 ? "s" : ""} sélectionnée{selectedCount > 1 ? "s" : ""}
      </span>
      <div className="grid gap-2">
        <Label htmlFor="bulk-cost-code">Code d&apos;imputation</Label>
        <select
          id="bulk-cost-code"
          className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          value={bulkCostCodeId}
          onChange={(event) => onBulkCostCodeIdChange(event.target.value)}
        >
          <option value="">Sélectionner</option>
          {projectCostCodes.map((code) => (
            <option key={code.id} value={code.id}>
              {code.code} - {code.name}
            </option>
          ))}
        </select>
      </div>
      <Button
        type="button"
        disabled={bulkAssignBusy || mutationBusy || !bulkCostCodeId}
        title={mutationBusy && !bulkAssignBusy ? "Une autre écriture est en cours sur cette révision." : undefined}
        onClick={onAssign}
      >
        Affecter
      </Button>
    </div>
  );
}
