"use client";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { Task } from "@/lib/backend";

export type EstimateCreateTaskDialogProps = {
  open: boolean;
  name: string;
  isMilestone: boolean;
  parentTaskUid: string;
  // The project's displayed draft planning's own tasks (see lib/backend.ts's createEstimateTask
  // doc comment for why this must come from Task/uid, not from the EstimateTaskRow list this
  // tab otherwise displays). A milestone cannot be a parent, mirroring
  // planning-create-task-dialog.tsx's own "child" option.
  parentTaskOptions: Task[];
  busy: boolean;
  error: string | null;
  requiresPlanningDraft: boolean;
  onNameChange: (value: string) => void;
  onMilestoneChange: (value: boolean) => void;
  onParentTaskUidChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
  onReopenStructure: () => void;
};

// E6-06/#67: "Ajouter une tâche au planning" dialog, launched from the Devis tab. See
// use-estimate-cost-lines.ts's submitCreateTask for the state/logic this is driven by, and
// planning-create-task-dialog.tsx for the sibling dialog this one is modeled after.
export function EstimateCreateTaskDialog({
  open,
  name,
  isMilestone,
  parentTaskUid,
  parentTaskOptions,
  busy,
  error,
  requiresPlanningDraft,
  onNameChange,
  onMilestoneChange,
  onParentTaskUidChange,
  onClose,
  onSubmit,
  onReopenStructure,
}: EstimateCreateTaskDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ajouter une tâche au planning</DialogTitle>
          <DialogDescription>
            Crée une tâche dans le planning brouillon affiché et l&apos;ajoute au devis courant.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="estimate-new-task-name" className="text-sm font-medium">
              Nom
            </label>
            <Input
              id="estimate-new-task-name"
              aria-label="Nom de la nouvelle tâche"
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              maxLength={512}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="estimate-new-task-parent" className="text-sm font-medium">
              Tâche parente
            </label>
            <select
              id="estimate-new-task-parent"
              aria-label="Tâche parente de la nouvelle tâche"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={parentTaskUid}
              onChange={(event) => onParentTaskUidChange(event.target.value)}
            >
              <option value="">Aucune (tâche racine)</option>
              {parentTaskOptions
                .filter((task) => !task.is_milestone)
                .map((task) => (
                  <option key={task.uid} value={task.uid}>
                    {task.outline_number ? `${task.outline_number} — ${task.name}` : task.name}
                  </option>
                ))}
            </select>
            {/* Basse review finding on #67: this dialog never sends insert_after_uid, so the
                backend always inserts the new task at the head of its siblings (root list, or
                the chosen parent's children) -- same clarification as
                planning-create-task-dialog.tsx's "Ajouter en tête du planning" option. */}
            <p className="text-xs text-muted-foreground">
              La tâche est ajoutée en tête de la liste de ses tâches sœurs (racine ou enfants du
              parent choisi).
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={isMilestone} onCheckedChange={(checked) => onMilestoneChange(Boolean(checked))} />
            Jalon
          </label>
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
            Ajouter
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
