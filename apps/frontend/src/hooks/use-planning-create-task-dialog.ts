import { useState } from "react";

import type { Task } from "@/lib/backend";

export type CreateTaskPositionMode = "root" | "after" | "child";

type UsePlanningCreateTaskDialogParams = {
  onCreateTask?: (command: {
    name: string;
    isMilestone: boolean;
    targetParentUid?: number;
    insertAfterUid?: number;
  }) => void;
  // Recomputed by the caller on every render from its own selection state; only meaningful when
  // exactly one row is selected (see PlanningTreeTable) -- with zero or several rows selected
  // there is no single unambiguous "relative to this task" position.
  singleSelectedTask: Task | null;
};

function resolvePositionTarget(
  positionMode: CreateTaskPositionMode,
  singleSelectedTask: Task | null,
): { targetParentUid?: number; insertAfterUid?: number } {
  if (positionMode === "after" && singleSelectedTask) {
    return { targetParentUid: singleSelectedTask.parent_uid ?? undefined, insertAfterUid: singleSelectedTask.uid };
  }
  if (positionMode === "child" && singleSelectedTask) {
    return { targetParentUid: singleSelectedTask.uid };
  }
  return {};
}

// Extracted from PlanningTreeTable (E4-12 / #152): the "add a task" dialog's form state and
// submit flow. Owns its own reset() called from PlanningTreeTable's render-phase versionKey-
// change block -- see that component for why this must stay a synchronous render-body reset, not
// a useEffect.
export function usePlanningCreateTaskDialog({ onCreateTask, singleSelectedTask }: UsePlanningCreateTaskDialogParams) {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createTaskName, setCreateTaskName] = useState("");
  const [createTaskIsMilestone, setCreateTaskIsMilestone] = useState(false);
  const [createPositionMode, setCreatePositionMode] = useState<CreateTaskPositionMode>("root");
  const [createTaskError, setCreateTaskError] = useState<string | null>(null);

  function openCreateTaskDialog() {
    setCreateTaskName("");
    setCreateTaskIsMilestone(false);
    setCreatePositionMode(singleSelectedTask ? "after" : "root");
    setCreateTaskError(null);
    setCreateDialogOpen(true);
  }

  function closeCreateTaskDialog() {
    setCreateDialogOpen(false);
    setCreateTaskName("");
    setCreateTaskIsMilestone(false);
    setCreatePositionMode("root");
    setCreateTaskError(null);
  }

  function submitCreateTask() {
    if (!onCreateTask) {
      return;
    }
    const trimmedName = createTaskName.trim();
    if (!trimmedName) {
      setCreateTaskError("Le nom de la tâche est obligatoire.");
      return;
    }
    const { targetParentUid, insertAfterUid } = resolvePositionTarget(createPositionMode, singleSelectedTask);
    onCreateTask({ name: trimmedName, isMilestone: createTaskIsMilestone, targetParentUid, insertAfterUid });
    closeCreateTaskDialog();
  }

  function reset() {
    setCreateDialogOpen(false);
    setCreateTaskName("");
    setCreateTaskIsMilestone(false);
    setCreatePositionMode("root");
    setCreateTaskError(null);
  }

  return {
    createDialogOpen,
    createTaskName,
    createTaskIsMilestone,
    createPositionMode,
    createTaskError,
    setCreateTaskName,
    setCreateTaskIsMilestone,
    setCreatePositionMode,
    openCreateTaskDialog,
    closeCreateTaskDialog,
    submitCreateTask,
    reset,
  };
}
