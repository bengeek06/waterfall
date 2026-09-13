import { useState } from "react";

import type { PlanningRow } from "@/lib/planning-tree";

export type CreateTaskPositionMode = "root" | "after" | "child";

/** Where a new task lands, in the terms `POST .../revisions/{id}/tasks` takes. */
export type CreateTaskCommand = {
  name: string;
  isMilestone: boolean;
  /** Absent/null = at the root of the revision. */
  parentId: number | null;
  /** Absent/null = last child of that parent. Positions are 1-based and contiguous (INV-05). */
  position: number | null;
};

type UsePlanningCreateTaskDialogParams = {
  onCreateTask?: (command: CreateTaskCommand) => void;
  // Recomputed by the caller on every render from its own selection state; only meaningful when
  // exactly one row is selected (see PlanningTreeTable) -- with zero or several rows selected
  // there is no single unambiguous "relative to this task" position.
  singleSelectedRow: PlanningRow | null;
};

function resolvePositionTarget(
  positionMode: CreateTaskPositionMode,
  singleSelectedRow: PlanningRow | null,
): { parentId: number | null; position: number | null } {
  if (positionMode === "after" && singleSelectedRow) {
    // Right after the selected row among its own siblings: positions are contiguous, so the slot
    // to ask for is simply its own plus one.
    return { parentId: singleSelectedRow.parent_id, position: singleSelectedRow.position + 1 };
  }
  if (positionMode === "child" && singleSelectedRow) {
    return { parentId: singleSelectedRow.node_id, position: null };
  }
  return { parentId: null, position: null };
}

// Extracted from PlanningTreeTable (E4-12 / #152): the "add a task" dialog's form state and
// submit flow. Owns its own reset() called from PlanningTreeTable's render-phase versionKey-
// change block -- see that component for why this must stay a synchronous render-body reset, not
// a useEffect.
export function usePlanningCreateTaskDialog({ onCreateTask, singleSelectedRow }: UsePlanningCreateTaskDialogParams) {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createTaskName, setCreateTaskName] = useState("");
  const [createTaskIsMilestone, setCreateTaskIsMilestone] = useState(false);
  const [createPositionMode, setCreatePositionMode] = useState<CreateTaskPositionMode>("root");
  const [createTaskError, setCreateTaskError] = useState<string | null>(null);

  function openCreateTaskDialog() {
    setCreateTaskName("");
    setCreateTaskIsMilestone(false);
    setCreatePositionMode(singleSelectedRow ? "after" : "root");
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
    const { parentId, position } = resolvePositionTarget(createPositionMode, singleSelectedRow);
    onCreateTask({ name: trimmedName, isMilestone: createTaskIsMilestone, parentId, position });
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
