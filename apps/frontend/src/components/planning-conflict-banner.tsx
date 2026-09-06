"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { PlanningRevisionConflict } from "@/hooks/use-planning-detail";

export type PlanningConflictBannerProps = {
  conflict: PlanningRevisionConflict | null;
  planningId: number | null;
  onReload: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the revision-conflict banner shown for the
// currently-selected planning. Verbatim JSX move -- see page.tsx call site for wiring.
export function PlanningConflictBanner({ conflict, planningId, onReload }: PlanningConflictBannerProps) {
  if (!conflict) {
    return null;
  }

  return (
    <Alert variant="destructive">
      <AlertTitle>Planning modifié</AlertTitle>
      <AlertDescription>
        {conflict.message}
        <div className="text-xs text-muted-foreground">
          Projet {conflict.projectId}, planning {planningId} :
          révision attendue {conflict.expectedRevision}, révision actuelle{" "}
          {conflict.currentRevision}.
        </div>
        <div className="mt-2">
          <Button size="sm" onClick={onReload}>
            Recharger le planning
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
