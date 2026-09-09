"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { EstimateCostLineMilestonesCreate } from "@/lib/backend";

export type MilestoneTemplateValue = EstimateCostLineMilestonesCreate["template"];

export type EstimateMilestoneTemplateDialogProps = {
  open: boolean;
  costLineLabel: string;
  template: MilestoneTemplateValue;
  intermediateMilestonesCount: string;
  lagMinutes: string;
  busy: boolean;
  error: string | null;
  requiresPlanningDraft: boolean;
  onTemplateChange: (value: MilestoneTemplateValue) => void;
  onIntermediateMilestonesCountChange: (value: string) => void;
  onLagMinutesChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
  onReopenStructure: () => void;
};

// E6-07/#68: "Appliquer un gabarit de jalons" dialog, launched from a single row of
// cost-lines-table.tsx. Modeled after estimate-create-task-dialog.tsx (#67), including reusing
// the same "reopen the structure" affordance for the identical
// ESTIMATE_TASK_CREATE_REQUIRES_PLANNING_DRAFT 409 the backend raises on both endpoints.
//
// The delay between consecutive milestones is entered in minutes, not days: this mirrors the
// only other lag input already in this codebase (planning-task-links.ts's own "Décalage" field,
// also minutes, also converted to the backend's lag_tenth_minute unit by the caller) rather than
// introducing a second, inconsistent unit convention for the same concept.
export function EstimateMilestoneTemplateDialog({
  open,
  costLineLabel,
  template,
  intermediateMilestonesCount,
  lagMinutes,
  busy,
  error,
  requiresPlanningDraft,
  onTemplateChange,
  onIntermediateMilestonesCountChange,
  onLagMinutesChange,
  onClose,
  onSubmit,
  onReopenStructure,
}: EstimateMilestoneTemplateDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Appliquer un gabarit de jalons</DialogTitle>
          <DialogDescription>
            Crée une série de jalons chaînés dans le planning brouillon affiché pour la ligne de
            coût « {costLineLabel} ».
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="milestone-template-select" className="text-sm font-medium">
              Gabarit
            </label>
            <select
              id="milestone-template-select"
              aria-label="Gabarit de jalons"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={template}
              onChange={(event) => onTemplateChange(event.target.value as MilestoneTemplateValue)}
            >
              <option value="fourniture">Fourniture (Commande, Réception)</option>
              <option value="sous_traitance">
                Sous-traitance (Commande, jalons intermédiaires, Livraison)
              </option>
            </select>
          </div>
          {template === "sous_traitance" ? (
            <div className="flex flex-col gap-1">
              <label htmlFor="milestone-intermediate-count" className="text-sm font-medium">
                Nombre de jalons intermédiaires
              </label>
              <Input
                id="milestone-intermediate-count"
                aria-label="Nombre de jalons intermédiaires"
                type="number"
                min="0"
                max="50"
                step="1"
                value={intermediateMilestonesCount}
                onChange={(event) => onIntermediateMilestonesCountChange(event.target.value)}
              />
            </div>
          ) : null}
          <div className="flex flex-col gap-1">
            <label htmlFor="milestone-lag-minutes" className="text-sm font-medium">
              Délai entre jalons (minutes)
            </label>
            <Input
              id="milestone-lag-minutes"
              aria-label="Délai entre jalons, en minutes"
              type="number"
              min="0"
              max={7884000}
              step="1"
              value={lagMinutes}
              onChange={(event) => onLagMinutesChange(event.target.value)}
            />
          </div>
          {error ? (
            <div className="flex flex-col items-start gap-2">
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
              {requiresPlanningDraft ? (
                <Button type="button" size="sm" variant="outline" onClick={onReopenStructure}>
                  Rouvrir la structure
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Annuler
          </Button>
          <Button type="button" disabled={busy} onClick={onSubmit}>
            Appliquer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
