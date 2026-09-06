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
import type { EstimateCostLine } from "@/lib/backend";

export type CostLineDeleteDialogProps = {
  pendingDelete: EstimateCostLine | null;
  onCancel: () => void;
  onConfirm: (line: EstimateCostLine) => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the cost-line deletion confirmation dialog.
// Verbatim JSX move -- see page.tsx call site for wiring.
export function CostLineDeleteDialog({ pendingDelete, onCancel, onConfirm }: CostLineDeleteDialogProps) {
  return (
    <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Supprimer cette ligne de coût ?</AlertDialogTitle>
          <AlertDialogDescription>
            {pendingDelete ? `La ligne "${pendingDelete.label}" sera supprimée définitivement.` : ""}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Annuler</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              const line = pendingDelete;
              onCancel();
              if (line) onConfirm(line);
            }}
          >
            Supprimer
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
