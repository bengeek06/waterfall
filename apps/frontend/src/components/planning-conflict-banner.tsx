"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { RevisionLockConflict } from "@/hooks/use-revision-planning";

export type PlanningConflictBannerProps = {
  conflict: RevisionLockConflict | null;
  onReload: () => void;
};

// E14-10 (#336): the same banner, now driven by the revision's optimistic-lock counter rather than
// by a planning's `revision` column. Deliberately not auto-reloading and not auto-retrying: the
// tree the user acted on is not the one the server holds, so replaying the command against a tree
// they have not seen is how a silent wrong move happens. The counters are shown because they are
// what a support conversation needs, not because a user is expected to interpret them.
export function PlanningConflictBanner({ conflict, onReload }: PlanningConflictBannerProps) {
  if (!conflict) {
    return null;
  }

  return (
    <Alert variant="destructive">
      <AlertTitle>Révision modifiée</AlertTitle>
      <AlertDescription>
        Cette révision a été modifiée entre-temps : recharge-la avant de continuer. Rien n&apos;a été
        enregistré.
        <div className="text-xs text-muted-foreground">
          Révision {conflict.revisionId ?? "?"} : version attendue {conflict.expectedLockVersion ?? "?"},
          version actuelle {conflict.currentLockVersion ?? "?"}.
        </div>
        <div className="mt-2">
          <Button size="sm" onClick={onReload}>
            Recharger la révision
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
