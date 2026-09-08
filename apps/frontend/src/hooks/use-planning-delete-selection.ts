import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { getPlanningTaskDeleteConflict, type Task } from "@/lib/backend";

type CascadeConflict = {
  taskUids: number[];
  descendantUids: number[];
  // The planning version the initial (non-cascade) delete request was made against; re-sent
  // unchanged on confirmation so the caller can detect a version switch that happened while
  // this dialog was open (see the onDeleteTasks prop contract on PlanningTreeTable).
  versionKey: number | string | null;
};

type UsePlanningDeleteSelectionParams = {
  tasks: Task[];
  versionKey: number | string | null;
  selectedUids: Set<number>;
  mutationBusy: boolean;
  onDeleteTasks?: (
    taskUids: number[],
    confirmCascade: boolean,
    versionKey: number | string | null,
  ) => Promise<void>;
  // Called once a delete (outright or confirmed cascade) actually succeeds, so the caller's own
  // selection state (owned by use-planning-tree-selection) no longer references deleted uids.
  onSelectionCleared: () => void;
};

function describeCascadeDescendants(descendantUids: number[], tasksByUid: Map<number, Task>): string {
  if (descendantUids.length === 0) {
    return "Les tâches sélectionnées et leurs éventuelles sous-tâches seront supprimées définitivement.";
  }
  const names = descendantUids.map((uid) => {
    const descendant = tasksByUid.get(uid);
    return descendant ? `${descendant.row_number} - ${descendant.name}` : String(uid);
  });
  return `Cette suppression entraînera aussi celle de ${descendantUids.length} tâche(s) enfant(s) : ${names.join(", ")}.`;
}

// Extracted from PlanningTreeTable (E4-12 / #152): the delete-selection flow, including the
// cascade-confirmation dialog opened when the backend answers a first (non-cascade) delete
// attempt with CASCADE_CONFIRMATION_REQUIRED. Owns its own reset() called from PlanningTreeTable's
// render-phase versionKey-change block -- see that component for why this must stay a synchronous
// render-body reset, not a useEffect.
export function usePlanningDeleteSelection({
  tasks,
  versionKey,
  selectedUids,
  mutationBusy,
  onDeleteTasks,
  onSelectionCleared,
}: UsePlanningDeleteSelectionParams) {
  const [cascadeConflict, setCascadeConflict] = useState<CascadeConflict | null>(null);
  const [cascadeBusy, setCascadeBusy] = useState(false);

  const tasksByUid = useMemo(() => new Map(tasks.map((task) => [task.uid, task])), [tasks]);

  // Tracks the *current* versionKey prop, unlike the `requestedVersionKey` requestDeleteSelection
  // captures in its own closure at request time: that closure keeps referencing whatever value
  // was current when the request started, for the lifetime of that async call, so it cannot be
  // used to detect a version switch that happened later while the request was still in flight.
  // React forbids writing to a ref during render (see the `react-hooks/refs` lint rule), so this
  // cannot be a synchronous body write like PlanningTreeTable's renderedVersionKey state sync; it
  // is instead kept fresh via useLayoutEffect rather than useEffect, so the write happens
  // synchronously in the commit phase, before the browser can paint or run any other queued task
  // (including a pending fetch's resolution) — closing the staleness window a passive useEffect
  // would otherwise leave open between commit and its own (deferred) flush.
  const versionKeyRef = useRef(versionKey);
  useLayoutEffect(() => {
    versionKeyRef.current = versionKey;
  }, [versionKey]);

  async function requestDeleteSelection() {
    if (!onDeleteTasks || selectedUids.size === 0 || mutationBusy) {
      return;
    }
    const taskUids = [...selectedUids];
    // Captured now, not re-read later: this is what identifies "the planning version this
    // deletion was requested against" for the caller's own freshness check on a cascade retry
    // (see the onDeleteTasks prop contract on PlanningTreeTable).
    const requestedVersionKey = versionKey;
    try {
      await onDeleteTasks(taskUids, false, requestedVersionKey);
      onSelectionCleared();
    } catch (cause) {
      const conflict = getPlanningTaskDeleteConflict(cause);
      // The version-mismatch reset in PlanningTreeTable's render-phase block only fires *while*
      // versionKey is changing; if the displayed planning version already changed and settled on
      // a different one by the time this late 409 response arrives, versionKey (current) and
      // renderedVersionKey (also already updated) match again, so that reset alone would not
      // catch this. Re-check explicitly against what was captured when *this* request started:
      // opening a cascade dialog for task uids from a version that is no longer displayed would
      // show a confirmation the user has no way to correctly interpret.
      if (conflict?.code === "CASCADE_CONFIRMATION_REQUIRED" && versionKeyRef.current === requestedVersionKey) {
        // Not an error yet: ask the user to confirm the cascade instead of showing a failure.
        setCascadeConflict({
          taskUids,
          descendantUids: conflict.descendantUids ?? [],
          versionKey: requestedVersionKey,
        });
      }
      // Covers both a TASK_REFERENCED conflict (never confirmable, regardless of confirm_cascade)
      // and any other failure (including the caller rejecting a stale planning version). Nothing
      // to do locally: errors are reported through the parent's own error state, mirroring
      // onCreateTask.
    }
  }

  async function confirmCascadeDelete() {
    if (!onDeleteTasks || !cascadeConflict) {
      return;
    }
    setCascadeBusy(true);
    try {
      await onDeleteTasks(cascadeConflict.taskUids, true, cascadeConflict.versionKey);
      onSelectionCleared();
    } catch {
      // Reported through the parent's own error state; just close the dialog below.
    } finally {
      setCascadeConflict(null);
      setCascadeBusy(false);
    }
  }

  const cascadeDescription = cascadeConflict
    ? describeCascadeDescendants(cascadeConflict.descendantUids, tasksByUid)
    : null;

  function reset() {
    setCascadeConflict(null);
    setCascadeBusy(false);
  }

  return {
    cascadeConflict,
    cascadeBusy,
    cascadeDescription,
    requestDeleteSelection,
    confirmCascadeDelete,
    reset,
  };
}
