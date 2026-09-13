import { useTreeRowDrafts } from "@/hooks/use-tree-row-drafts";
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
// logic that turns it into a single-field PATCH once the user leaves a field, over this grid's
// three row kinds. There is deliberately no "Sauver" button anywhere in this grid (see
// EstimateGridTreeTable): every field commits itself independently.
//
// E14-09 (#335): the draft bookkeeping this used to duplicate from usePlanningScheduleDrafts (the
// per-row record, the never-edited fallback, discard-only-on-confirmed-success, Enter = blur =
// commit) now comes from the shared useTreeRowDrafts. What stays here is which endpoint each
// column commits to and what makes a value not worth sending.
export function useEstimateGridDrafts({
  mutationBusy,
  onRenameTask,
  onUpdateCostLine,
  onUpdateRoleAssignment,
}: UseEstimateGridDraftsParams) {
  const drafts = useTreeRowDrafts<EstimateGridTreeRow, EstimateGridRowDraft>({
    rowKeyOf: rowKey,
    defaultDraftFor: defaultDraft,
    busy: mutationBusy,
  });

  // Every commit below follows the same contract with the shared hook: return `true` once the
  // row's draft may be discarded (persisted, or nothing left to persist), `false` to keep the
  // user's uncommitted value on screen. commitDraft itself already short-circuits when a mutation
  // is in flight or when the row holds no draft at all.
  async function commitLabel(row: EstimateGridTreeRow) {
    await drafts.commitDraft(row, async (draft) => {
      const trimmed = draft.label.trim();
      if (!trimmed) {
        return false;
      }
      if (row.kind === "task") {
        // Deliberately `row.taskRow.task_uid` here, NOT `row.uid`: this tree's shared `uid` space
        // is built from `task_id` (`MsTask.id`, the global PK -- see lib/estimate-grid-tree.ts's
        // own doc comment), but the rename endpoint (`onRenameTask` -> updateTaskName ->
        // `PATCH .../tasks/{taskUid}`) resolves the task via `MsTask.uid`, the project-scoped
        // business identifier `EstimateTaskRowRead.task_uid` exposes separately. A row with no
        // `task_uid` (the same pre-existing degenerate case `row_number` itself falls back for,
        // see EstimateTaskRowRead's own doc comment) has no valid target for that PATCH at all, so
        // it is never editable in the first place -- see renderLabelCell's own `editable` guard,
        // which this mirrors defensively.
        const taskUid = row.taskRow.task_uid;
        if (taskUid == null || !onRenameTask || trimmed === row.taskRow.task_name) {
          return true;
        }
        return onRenameTask(taskUid, trimmed);
      }
      if (row.kind === "line") {
        if (!onUpdateCostLine || trimmed === row.line.label) {
          return true;
        }
        return onUpdateCostLine(row.line.id, { label: trimmed });
      }
      // A labor row's own label (role_name) is immutable -- see this hook's own doc comment.
      return false;
    });
  }

  async function commitQuantity(row: EstimateGridTreeRow) {
    if (row.kind === "task") {
      return;
    }
    await drafts.commitDraft(row, async (draft) => {
      const quantity = Number(draft.quantity);
      if (!(quantity > 0)) {
        return false;
      }
      if (row.kind === "line") {
        if (!onUpdateCostLine || quantity === row.line.quantity) {
          return true;
        }
        return onUpdateCostLine(row.line.id, { quantity });
      }
      if (!onUpdateRoleAssignment || quantity === row.assignment.quantity) {
        return true;
      }
      return onUpdateRoleAssignment(row.assignment.id, { quantity });
    });
  }

  async function commitHours(row: EstimateGridTreeRow) {
    if (row.kind !== "labor") {
      return;
    }
    await drafts.commitDraft(row, async (draft) => {
      const hours = Number(draft.hours);
      if (!(hours >= 0)) {
        return false;
      }
      if (!onUpdateRoleAssignment || hours === row.assignment.hours) {
        return true;
      }
      return onUpdateRoleAssignment(row.assignment.id, { hours });
    });
  }

  async function commitUnitCost(row: EstimateGridTreeRow) {
    if (row.kind !== "line") {
      return;
    }
    await drafts.commitDraft(row, async (draft) => {
      const unitCost = Number(draft.unitCost);
      if (!(unitCost >= 0)) {
        return false;
      }
      if (!onUpdateCostLine || unitCost === row.line.unit_cost) {
        return true;
      }
      return onUpdateCostLine(row.line.id, { unit_cost: unitCost });
    });
  }

  return {
    draftFor: drafts.draftFor,
    updateDraftField: drafts.updateDraftField,
    commitLabel,
    commitQuantity,
    commitHours,
    commitUnitCost,
    // Enter validates and blurs the field (triggering the same commit as a plain blur), and stops
    // the keystroke from bubbling up to the row's own selection/navigation handler -- both come
    // from the shared hook.
    onFieldKeyDown: drafts.onFieldKeyDown,
    reset: drafts.reset,
  };
}
