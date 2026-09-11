import { useState, type KeyboardEvent } from "react";

import type { EstimateGridTreeRow } from "@/lib/estimate-grid-tree";

export type EstimateGridRowDraft = {
  label: string;
  quantity: string;
  hours: string;
  unitCost: string;
};

function rowKey(row: EstimateGridTreeRow): string {
  if (row.kind === "task") {
    return `task-${row.taskRow.id}`;
  }
  if (row.kind === "line") {
    return `line-${row.line.id}`;
  }
  return `labor-${row.assignment.id}`;
}

function defaultDraft(row: EstimateGridTreeRow): EstimateGridRowDraft {
  if (row.kind === "task") {
    return { label: row.taskRow.task_name, quantity: "", hours: "", unitCost: "" };
  }
  if (row.kind === "line") {
    return { label: row.line.label, quantity: String(row.line.quantity), hours: "", unitCost: String(row.line.unit_cost) };
  }
  return {
    label: row.assignment.role_name,
    quantity: String(row.assignment.quantity),
    hours: String(row.assignment.hours),
    unitCost: "",
  };
}

type UseEstimateGridDraftsParams = {
  mutationBusy: boolean;
  // Only ever called for a "task" row -- a cost-line/role-assignment row's own Libellé goes
  // through onUpdateCostLine instead (a labor row's `role_name` is immutable once created, see
  // EstimateRoleAssignmentUpdate's own doc comment in lib/backend.ts, so it is never editable
  // here at all). Returns whether the rename actually persisted, so the draft is only discarded
  // on success -- same convention as usePlanningScheduleDrafts.commitScheduleEdit.
  onRenameTask?: (taskUid: number, name: string) => Promise<boolean>;
  onUpdateCostLine?: (
    lineId: number,
    payload: { label?: string; quantity?: number; unit_cost?: number },
  ) => Promise<boolean>;
  onUpdateRoleAssignment?: (id: number, payload: { quantity?: number; hours?: number }) => Promise<boolean>;
};

// E12-10/#292: per-row draft state (uncommitted Libellé/Qté/Heures/Débours) and the blur-commit
// logic that turns it into a single-field PATCH once the user leaves a field -- modeled directly
// after usePlanningScheduleDrafts (same "default from the row, commit on blur, discard only on
// confirmed success" shape), generalized to this grid's three row kinds. There is deliberately no
// "Sauver" button anywhere in this grid (see EstimateGridTreeTable): every field commits itself
// independently.
export function useEstimateGridDrafts({
  mutationBusy,
  onRenameTask,
  onUpdateCostLine,
  onUpdateRoleAssignment,
}: UseEstimateGridDraftsParams) {
  const [drafts, setDrafts] = useState<Record<string, EstimateGridRowDraft>>({});

  function draftFor(row: EstimateGridTreeRow): EstimateGridRowDraft {
    return drafts[rowKey(row)] ?? defaultDraft(row);
  }

  function updateDraftField(row: EstimateGridTreeRow, field: keyof EstimateGridRowDraft, value: string) {
    const key = rowKey(row);
    setDrafts((current) => ({ ...current, [key]: { ...(current[key] ?? defaultDraft(row)), [field]: value } }));
  }

  function clearDraft(row: EstimateGridTreeRow) {
    const key = rowKey(row);
    setDrafts((current) => {
      if (!(key in current)) {
        return current;
      }
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  // No draft entry means the user never actually typed into this row's field (e.g. just tabbed
  // through on focus/blur) -- nothing changed, so nothing should be committed.
  function hasPendingDraft(row: EstimateGridTreeRow): boolean {
    return rowKey(row) in drafts;
  }

  async function commitLabel(row: EstimateGridTreeRow) {
    if (mutationBusy || !hasPendingDraft(row)) {
      return;
    }
    const trimmed = draftFor(row).label.trim();
    if (!trimmed) {
      return;
    }
    if (row.kind === "task") {
      // Deliberately `row.taskRow.task_uid` here, NOT `row.uid`: this tree's shared `uid` space
      // is built from `task_id` (`MsTask.id`, the global PK -- see lib/estimate-grid-tree.ts's own
      // doc comment), but the rename endpoint (`onRenameTask` -> updateTaskName ->
      // `PATCH .../tasks/{taskUid}`) resolves the task via `MsTask.uid`, the project-scoped
      // business identifier `EstimateTaskRowRead.task_uid` exposes separately. A row with no
      // `task_uid` (the same pre-existing degenerate case `row_number` itself falls back for, see
      // EstimateTaskRowRead's own doc comment) has no valid target for that PATCH at all, so it
      // is never editable in the first place -- see renderLabelCell's own `editable` guard, which
      // this mirrors defensively.
      const taskUid = row.taskRow.task_uid;
      if (taskUid == null || !onRenameTask || trimmed === row.taskRow.task_name) {
        clearDraft(row);
        return;
      }
      if (await onRenameTask(taskUid, trimmed)) {
        clearDraft(row);
      }
      return;
    }
    if (row.kind === "line") {
      if (!onUpdateCostLine || trimmed === row.line.label) {
        clearDraft(row);
        return;
      }
      if (await onUpdateCostLine(row.line.id, { label: trimmed })) {
        clearDraft(row);
      }
    }
    // A labor row's own label (role_name) is immutable -- see this hook's own doc comment.
  }

  async function commitQuantity(row: EstimateGridTreeRow) {
    if (mutationBusy || !hasPendingDraft(row) || row.kind === "task") {
      return;
    }
    const quantity = Number(draftFor(row).quantity);
    if (!(quantity > 0)) {
      return;
    }
    if (row.kind === "line") {
      if (!onUpdateCostLine || quantity === row.line.quantity) {
        clearDraft(row);
        return;
      }
      if (await onUpdateCostLine(row.line.id, { quantity })) {
        clearDraft(row);
      }
      return;
    }
    if (!onUpdateRoleAssignment || quantity === row.assignment.quantity) {
      clearDraft(row);
      return;
    }
    if (await onUpdateRoleAssignment(row.assignment.id, { quantity })) {
      clearDraft(row);
    }
  }

  async function commitHours(row: EstimateGridTreeRow) {
    if (mutationBusy || !hasPendingDraft(row) || row.kind !== "labor") {
      return;
    }
    const hours = Number(draftFor(row).hours);
    if (!(hours >= 0)) {
      return;
    }
    if (!onUpdateRoleAssignment || hours === row.assignment.hours) {
      clearDraft(row);
      return;
    }
    if (await onUpdateRoleAssignment(row.assignment.id, { hours })) {
      clearDraft(row);
    }
  }

  async function commitUnitCost(row: EstimateGridTreeRow) {
    if (mutationBusy || !hasPendingDraft(row) || row.kind !== "line") {
      return;
    }
    const unitCost = Number(draftFor(row).unitCost);
    if (!(unitCost >= 0)) {
      return;
    }
    if (!onUpdateCostLine || unitCost === row.line.unit_cost) {
      clearDraft(row);
      return;
    }
    if (await onUpdateCostLine(row.line.id, { unit_cost: unitCost })) {
      clearDraft(row);
    }
  }

  // Enter validates and blurs the field (triggering the same commit as a plain blur), mirroring
  // usePlanningScheduleDrafts.onScheduleFieldKeyDown -- also stops the keystroke from bubbling up
  // to any row-level selection/keyboard handler.
  function onFieldKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
    }
  }

  function reset() {
    setDrafts({});
  }

  return {
    draftFor,
    updateDraftField,
    commitLabel,
    commitQuantity,
    commitHours,
    commitUnitCost,
    onFieldKeyDown,
    reset,
  };
}
