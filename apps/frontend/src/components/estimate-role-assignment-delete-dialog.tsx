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
import type { EstimateRoleAssignment } from "@/lib/backend";

export type EstimateRoleAssignmentDeleteDialogProps = {
  pendingDelete: EstimateRoleAssignment | null;
  onCancel: () => void;
  onConfirm: (assignment: EstimateRoleAssignment) => void;
};

// E12-06/#278: the role-assignment ("MO" line) deletion confirmation dialog -- same
// AlertDialog-based pattern as cost-line-delete-dialog.tsx's own non-labor sibling, rather than a
// raw `window.confirm`.
export function EstimateRoleAssignmentDeleteDialog({
  pendingDelete,
  onCancel,
  onConfirm,
}: EstimateRoleAssignmentDeleteDialogProps) {
  return (
    <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Supprimer cette ligne MO ?</AlertDialogTitle>
          <AlertDialogDescription>
            {pendingDelete
              ? `L'affectation du rôle "${pendingDelete.role_name}" sera supprimée définitivement.`
              : ""}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Annuler</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              const assignment = pendingDelete;
              onCancel();
              if (assignment) onConfirm(assignment);
            }}
          >
            Supprimer
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
