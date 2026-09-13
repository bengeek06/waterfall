"use client";

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

export type PlanningDeleteDialogProps = Readonly<{
  open: boolean;
  /** Row labels, in display order, exactly as the table shows them ("12 - Étude"). */
  rowLabels: string[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}>;

// E14-10 (#336), replacing planning-cascade-delete-dialog.tsx.
//
// The old dialog existed to answer a backend question: the delete endpoint refused a first attempt
// with CASCADE_CONFIRMATION_REQUIRED and the user confirmed the cascade. On the revision model the
// cascade is INV-02 and is not optional -- the endpoint deletes the subtree and *both* facets of
// every node it removes, in one call. So the confirmation is now entirely the screen's, asked
// before the request rather than between two of them, and it says what the deletion actually takes
// away: the sub-rows, and the chiffrage hung on them. What was lost is then named back by the
// response (`cost_losses`, Rule 3's safeguard) -- see use-revision-planning.ts.
export function PlanningDeleteDialog({ open, rowLabels, busy, onCancel, onConfirm }: PlanningDeleteDialogProps) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !busy) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Supprimer {rowLabels.length} ligne(s) du planning ?</AlertDialogTitle>
          <AlertDialogDescription>
            {rowLabels.join(", ")}. Leurs sous-lignes et les lignes de chiffrage qui leur sont
            rattachées seront supprimées avec elles, dans le planning comme dans le devis de cette
            révision. Cette suppression est définitive.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Annuler</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={busy} onClick={onConfirm}>
            {busy ? "Suppression..." : "Supprimer"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
