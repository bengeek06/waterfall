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

export type PlanningCascadeDeleteDialogProps = Readonly<{
  open: boolean;
  description: string | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}>;

// Extracted from PlanningTreeTable (E4-12 / #152): the cascade-delete confirmation dialog opened
// when the backend answers a delete attempt with CASCADE_CONFIRMATION_REQUIRED. Verbatim JSX move
// -- see that component's use-planning-delete-selection hook for the state/logic it is driven by.
export function PlanningCascadeDeleteDialog({ open, description, busy, onCancel, onConfirm }: PlanningCascadeDeleteDialogProps) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !busy) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Confirmer la suppression en cascade ?</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
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
