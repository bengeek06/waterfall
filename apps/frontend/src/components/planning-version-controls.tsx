"use client";

import { Button } from "@/components/ui/button";
import type { Planning } from "@/lib/backend";

export type PlanningVersionControlsProps = {
  plannings: Planning[];
  selectedPlanningId: number | null;
  planningBusy: boolean;
  onSelectPlanning: (planningId: number) => void;
  selectedPlanning: Planning | null;
  isReadOnlyProject: boolean;
  selectedPlanningHasConflict: boolean;
  onValidate: () => void;
  projectPlanningReferenceId: number | null | undefined;
  onSetReference: () => void;
  showReopenStructure: boolean;
  onReopenStructure: () => void;
  planningMutationBusy: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
};

// Grouped local predicates rather than inline `||` chains in the JSX below: each disabled state
// combines several independent flags, and keeping them as small named functions here (own,
// separate complexity score) is what keeps this component's own cyclomatic complexity low --
// see E4-11 / #151 for the full rationale on why inline boolean chains in JSX are what drove
// ProjectDetailsPage's original complexity score.
function isValidateDisabled(planningBusy: boolean, isReadOnlyProject: boolean, hasConflict: boolean): boolean {
  return planningBusy || isReadOnlyProject || hasConflict;
}

function isReferenceOrReopenDisabled(planningBusy: boolean, isReadOnlyProject: boolean): boolean {
  return planningBusy || isReadOnlyProject;
}

function isUndoRedoDisabled(
  planningMutationBusy: boolean,
  isReadOnlyProject: boolean,
  selectedPlanning: Planning | null,
  hasConflict: boolean,
  canApply: boolean,
): boolean {
  return (
    planningMutationBusy ||
    isReadOnlyProject ||
    !selectedPlanning ||
    selectedPlanning.status !== "draft" ||
    hasConflict ||
    !canApply
  );
}

// Extracted from ProjectDetailsPage (E4-11 / #151): the planning version selector plus the
// validate/set-reference/reopen-structure/undo/redo action buttons. Verbatim JSX move -- see
// page.tsx call site for wiring.
export function PlanningVersionControls({
  plannings,
  selectedPlanningId,
  planningBusy,
  onSelectPlanning,
  selectedPlanning,
  isReadOnlyProject,
  selectedPlanningHasConflict,
  onValidate,
  projectPlanningReferenceId,
  onSetReference,
  showReopenStructure,
  onReopenStructure,
  planningMutationBusy,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}: PlanningVersionControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {plannings.length ? (
        <label className="grid gap-1 text-xs text-muted-foreground">
          Version affichée
          <select
            aria-label="Version affichée"
            className="h-8 min-w-24 rounded-md border border-input bg-background px-2 text-sm text-foreground"
            value={selectedPlanningId ?? ""}
            disabled={planningBusy}
            onChange={(event) => onSelectPlanning(Number(event.target.value))}
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
          disabled={isValidateDisabled(planningBusy, isReadOnlyProject, selectedPlanningHasConflict)}
          onClick={onValidate}
        >
          Valider le planning
        </Button>
      ) : null}
      {selectedPlanning?.status === "validated" && projectPlanningReferenceId !== selectedPlanning.id ? (
        <Button
          variant="outline"
          type="button"
          disabled={isReferenceOrReopenDisabled(planningBusy, isReadOnlyProject)}
          onClick={onSetReference}
        >
          Définir comme référence
        </Button>
      ) : null}
      {showReopenStructure ? (
        <Button
          variant="outline"
          type="button"
          disabled={isReferenceOrReopenDisabled(planningBusy, isReadOnlyProject)}
          onClick={onReopenStructure}
        >
          Rouvrir la structure
        </Button>
      ) : null}
      {selectedPlanning ? (
        <>
          <Button
            variant="outline"
            size="sm"
            type="button"
            disabled={isUndoRedoDisabled(
              planningMutationBusy,
              isReadOnlyProject,
              selectedPlanning,
              selectedPlanningHasConflict,
              canUndo,
            )}
            onClick={onUndo}
          >
            Annuler
          </Button>
          <Button
            variant="outline"
            size="sm"
            type="button"
            disabled={isUndoRedoDisabled(
              planningMutationBusy,
              isReadOnlyProject,
              selectedPlanning,
              selectedPlanningHasConflict,
              canRedo,
            )}
            onClick={onRedo}
          >
            Rétablir
          </Button>
        </>
      ) : null}
    </div>
  );
}
