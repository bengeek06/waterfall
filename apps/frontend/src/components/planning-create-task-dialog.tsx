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
import type { CreateTaskPositionMode } from "@/hooks/use-planning-create-task-dialog";
import type { Task } from "@/lib/backend";

export type PlanningCreateTaskDialogProps = Readonly<{
  open: boolean;
  name: string;
  isMilestone: boolean;
  positionMode: CreateTaskPositionMode;
  error: string | null;
  singleSelectedTask: Task | null;
  mutationBusy: boolean;
  onNameChange: (value: string) => void;
  onMilestoneChange: (value: boolean) => void;
  onPositionModeChange: (value: CreateTaskPositionMode) => void;
  onClose: () => void;
  onSubmit: () => void;
}>;

// Extracted from PlanningTreeTable (E4-12 / #152): the "Ajouter une tâche" dialog, verbatim JSX
// move -- see that component's use-planning-create-task-dialog hook for the state/logic it is
// driven by.
export function PlanningCreateTaskDialog({
  open,
  name,
  isMilestone,
  positionMode,
  error,
  singleSelectedTask,
  mutationBusy,
  onNameChange,
  onMilestoneChange,
  onPositionModeChange,
  onClose,
  onSubmit,
}: PlanningCreateTaskDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ajouter une tâche</DialogTitle>
          <DialogDescription>Créez une nouvelle tâche dans le planning.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="new-task-name" className="text-sm font-medium">
              Nom
            </label>
            <Input
              id="new-task-name"
              aria-label="Nom de la nouvelle tâche"
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              maxLength={512}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={isMilestone} onCheckedChange={(checked) => onMilestoneChange(Boolean(checked))} />
            Jalon
          </label>
          <div className="flex flex-col gap-1">
            <label htmlFor="new-task-position" className="text-sm font-medium">
              Position
            </label>
            <select
              id="new-task-position"
              aria-label="Position de la nouvelle tâche"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={positionMode}
              onChange={(event) => onPositionModeChange(event.target.value as CreateTaskPositionMode)}
            >
              <option value="root">Ajouter en tête du planning</option>
              {singleSelectedTask ? (
                <option value="after">Ajouter après « {singleSelectedTask.name} » (même niveau)</option>
              ) : null}
              {singleSelectedTask && !singleSelectedTask.is_milestone ? (
                <option value="child">Ajouter comme enfant de « {singleSelectedTask.name} »</option>
              ) : null}
            </select>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Annuler
          </Button>
          <Button type="button" disabled={mutationBusy} onClick={onSubmit}>
            Ajouter
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
