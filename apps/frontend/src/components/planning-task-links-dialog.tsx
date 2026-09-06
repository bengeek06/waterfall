"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Task } from "@/lib/backend";
import { LINK_TYPE_OPTIONS, type LinkRowDraft } from "@/lib/planning-links";

export type PlanningTaskLinksDialogProps = Readonly<{
  editingTask: Task | null;
  linkCandidateTasks: Task[];
  linkRows: LinkRowDraft[];
  linkFormError: string | null;
  linkFormBusy: boolean;
  mutationBusy: boolean;
  onClose: () => void;
  onAddRow: () => void;
  onRemoveRow: (rowId: string) => void;
  onUpdateRow: (rowId: string, patch: Partial<LinkRowDraft>) => void;
  onSubmit: () => void;
}>;

// Extracted from PlanningTreeTable (E4-12 / #152): the "Prédécesseurs de <tâche>" dialog, verbatim
// JSX move -- see that component's use-planning-task-links hook for the state/logic it is driven by.
export function PlanningTaskLinksDialog({
  editingTask,
  linkCandidateTasks,
  linkRows,
  linkFormError,
  linkFormBusy,
  mutationBusy,
  onClose,
  onAddRow,
  onRemoveRow,
  onUpdateRow,
  onSubmit,
}: PlanningTaskLinksDialogProps) {
  return (
    <Dialog
      open={editingTask !== null}
      onOpenChange={(open) => {
        // Ignore close attempts (Escape, backdrop click, the header X) while a submission is
        // in flight, otherwise the dialog could close before we know if it actually succeeded.
        if (!open && !linkFormBusy) onClose();
      }}
    >
      <DialogContent>
        {editingTask ? (
          <>
            <DialogHeader>
              <DialogTitle>Prédécesseurs de {editingTask.name}</DialogTitle>
              <DialogDescription>
                Ajoutez, modifiez ou supprimez les tâches prédécesseures de cette tâche.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              {linkRows.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucun prédécesseur.</p>
              ) : null}
              {linkRows.map((row, rowIndex) => (
                <div key={row.rowId} className="flex flex-wrap items-center gap-2">
                  <select
                    aria-label="Tâche prédécesseure"
                    className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                    value={row.predecessorUid ?? ""}
                    disabled={linkFormBusy}
                    onChange={(event) =>
                      onUpdateRow(row.rowId, {
                        predecessorUid: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                  >
                    <option value="">Sélectionner une tâche</option>
                    {linkCandidateTasks.map((candidate) => (
                      <option key={candidate.uid} value={candidate.uid}>
                        {candidate.id_display ?? candidate.uid} - {candidate.name}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Type de lien"
                    className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                    value={row.linkType}
                    disabled={linkFormBusy}
                    onChange={(event) => onUpdateRow(row.rowId, { linkType: Number(event.target.value) })}
                  >
                    {LINK_TYPE_OPTIONS.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <Input
                    aria-label="Décalage en minutes"
                    type="number"
                    className="w-24"
                    value={row.lagMinutes}
                    disabled={linkFormBusy}
                    onChange={(event) => onUpdateRow(row.rowId, { lagMinutes: event.target.value })}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={linkFormBusy}
                    aria-label={`Supprimer la ligne de prédécesseur ${rowIndex + 1}`}
                    onClick={() => onRemoveRow(row.rowId)}
                  >
                    Supprimer
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={linkCandidateTasks.length === 0 || linkFormBusy}
                onClick={onAddRow}
              >
                Ajouter une ligne
              </Button>
              {linkFormError ? (
                <p role="alert" className="text-sm text-destructive">
                  {linkFormError}
                </p>
              ) : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" disabled={linkFormBusy} onClick={onClose}>
                Annuler
              </Button>
              <Button type="button" disabled={linkFormBusy || mutationBusy} onClick={onSubmit}>
                {linkFormBusy ? "Enregistrement..." : "Enregistrer"}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
