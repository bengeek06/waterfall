import type { PlanningDetail, PlanningLinkSnapshotWrite, PlanningTaskSnapshotWrite } from "./backend";

/** Full raw state of every task/link in a planning at one point in time, capturing exactly
 * what a previous response already contained -- restoring it verbatim (never recalculated)
 * is what makes undo/redo exact (E4-01). */
export type PlanningSnapshotDelta = {
  tasks: PlanningTaskSnapshotWrite[];
  links: PlanningLinkSnapshotWrite[];
};

export function snapshotFromPlanningDetail(
  detail: Pick<PlanningDetail, "tasks" | "links">,
): PlanningSnapshotDelta {
  return {
    tasks: detail.tasks.map((task) => ({
      uid: task.uid,
      id_display: task.id_display,
      structure_key: task.structure_key,
      structure_kind: task.structure_kind,
      parent_uid: task.parent_uid,
      position: task.position,
      name: task.name,
      outline_number: task.outline_number,
      outline_level: task.outline_level,
      wbs: task.wbs,
      start_at: task.start_at,
      finish_at: task.finish_at,
      duration_minutes: task.duration_minutes,
      duration_format: task.duration_format,
      work_minutes: task.work_minutes,
      task_type: task.task_type,
      percent_complete: task.percent_complete,
      is_summary: task.is_summary,
      is_milestone: task.is_milestone,
      is_manual: task.is_manual,
      calendar_uid: task.calendar_uid,
      notes: task.description,
    })),
    links: detail.links.map((link) => ({
      task_uid: link.task_uid,
      predecessor_uid: link.predecessor_uid,
      link_type: link.link_type,
      lag_tenth_minute: link.lag_tenth_minute,
      lag_format: link.lag_format,
    })),
  };
}

export type PlanningCommandKind = "move" | "create" | "delete" | "schedule" | "links";

/** One undoable/redoable mutation: the exact tasks/links snapshot right before it (undo
 * target) and right after it (redo target), plus a short label for the undo/redo UI. */
export type PlanningCommand = {
  id: string;
  kind: PlanningCommandKind;
  label: string;
  before: PlanningSnapshotDelta;
  after: PlanningSnapshotDelta;
};

export type PlanningHistoryState = {
  undoStack: PlanningCommand[];
  redoStack: PlanningCommand[];
};

export function createEmptyPlanningHistory(): PlanningHistoryState {
  return { undoStack: [], redoStack: [] };
}

/** Records a newly-succeeded command: pushed on the undo stack, clearing any redo stack
 * (the usual "a new action invalidates the old redo branch" rule). */
export function pushCommand(
  history: PlanningHistoryState,
  command: PlanningCommand,
): PlanningHistoryState {
  return { undoStack: [...history.undoStack, command], redoStack: [] };
}

export function canUndo(history: PlanningHistoryState): boolean {
  return history.undoStack.length > 0;
}

export function canRedo(history: PlanningHistoryState): boolean {
  return history.redoStack.length > 0;
}

/** Moves the top undo command to the redo stack, once its inverse mutation has actually
 * succeeded server-side -- callers must not call this speculatively before that. */
export function commitUndo(history: PlanningHistoryState): PlanningHistoryState {
  const command = history.undoStack.at(-1);
  if (!command) {
    return history;
  }
  return {
    undoStack: history.undoStack.slice(0, -1),
    redoStack: [...history.redoStack, command],
  };
}

/** Moves the top redo command back to the undo stack, once its forward mutation has
 * actually succeeded server-side -- callers must not call this speculatively before that. */
export function commitRedo(history: PlanningHistoryState): PlanningHistoryState {
  const command = history.redoStack.at(-1);
  if (!command) {
    return history;
  }
  return {
    undoStack: [...history.undoStack, command],
    redoStack: history.redoStack.slice(0, -1),
  };
}

export function peekUndo(history: PlanningHistoryState): PlanningCommand | null {
  return history.undoStack.at(-1) ?? null;
}

export function peekRedo(history: PlanningHistoryState): PlanningCommand | null {
  return history.redoStack.at(-1) ?? null;
}

let nextCommandId = 1;

export function nextPlanningCommandId(): string {
  const id = `cmd-${nextCommandId}`;
  nextCommandId += 1;
  return id;
}

/** Per-planning_id isolation (E4-01): each planning keeps its own independent undo/redo
 * stacks, so switching the displayed version never mixes histories. */
export type PlanningHistoryByPlanningId = Record<number, PlanningHistoryState>;

export function getPlanningHistory(
  historyByPlanningId: PlanningHistoryByPlanningId,
  planningId: number,
): PlanningHistoryState {
  return historyByPlanningId[planningId] ?? createEmptyPlanningHistory();
}

export function setPlanningHistory(
  historyByPlanningId: PlanningHistoryByPlanningId,
  planningId: number,
  history: PlanningHistoryState,
): PlanningHistoryByPlanningId {
  return { ...historyByPlanningId, [planningId]: history };
}

/** A revision conflict must never replace local data (E4-01): the caller resets only the
 * conflicting planning's history once the user confirms a reload, discarding stacks whose
 * captured revisions no longer match the server. */
export function resetPlanningHistory(
  historyByPlanningId: PlanningHistoryByPlanningId,
  planningId: number,
): PlanningHistoryByPlanningId {
  return setPlanningHistory(historyByPlanningId, planningId, createEmptyPlanningHistory());
}
