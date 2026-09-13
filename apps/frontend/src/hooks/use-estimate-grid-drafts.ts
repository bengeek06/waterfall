import { useTreeRowDrafts } from "@/hooks/use-tree-row-drafts";
import { costNumber, isCostRow, type RevisionCostGridRow } from "@/lib/revision-cost-grid";

export type EstimateGridRowDraft = {
  label: string;
  quantity: string;
  hours: string;
  unitCost: string;
};

function rowKey(row: RevisionCostGridRow): number {
  return row.node_id;
}

function defaultDraft(row: RevisionCostGridRow): EstimateGridRowDraft {
  if (!isCostRow(row)) {
    return { label: row.planning?.name ?? "", quantity: "", hours: "", unitCost: "" };
  }
  return {
    label: row.cost.label,
    quantity: String(costNumber(row.cost.quantity)),
    hours: row.cost.hours === null ? "" : String(costNumber(row.cost.hours)),
    unitCost: row.cost.unit_cost === null ? "" : String(costNumber(row.cost.unit_cost)),
  };
}

type UseEstimateGridDraftsParams = {
  mutationBusy: boolean;
  /** Renames a task node: `PATCH .../nodes/{nodeId}/planning`, the very call the Planning tab makes. */
  onUpdatePlanning?: (nodeId: number, payload: { name: string }) => Promise<boolean>;
  /**
   * Edits a cost node's facet: `PATCH .../nodes/{nodeId}/cost`.
   *
   * Only ever sends the one field the user just left, never the whole row: the endpoint is partial
   * and `null` is a *value* there, so sending a field the user did not touch would be a write.
   */
  onUpdateCost?: (
    nodeId: number,
    payload: { label?: string; quantity?: number; hours?: number; unit_cost?: number },
  ) => Promise<boolean>;
};

// E14-11 (#337): per-row uncommitted Libellé/Qté/Heures/Débours and the blur-commit that turns
// each of them into a single-field write on the node it belongs to. There is deliberately no
// "Sauver" button anywhere in this grid: every cell commits itself independently.
//
// What changed with the revision model is only *where* a commit goes: a row is a node, so a task's
// label is a planning-facet write and a cost line's is a cost-facet one, both on the same tree and
// under the same optimistic lock -- instead of the three endpoints of three parallel row kinds.
// The draft bookkeeping itself (the per-row record, the never-edited fallback, discard-only-on-
// confirmed-success, Enter = blur = commit) stays in the shared useTreeRowDrafts (#335).
export function useEstimateGridDrafts({
  mutationBusy,
  onUpdatePlanning,
  onUpdateCost,
}: UseEstimateGridDraftsParams) {
  const drafts = useTreeRowDrafts<RevisionCostGridRow, EstimateGridRowDraft>({
    rowKeyOf: rowKey,
    defaultDraftFor: defaultDraft,
    busy: mutationBusy,
  });

  // Every commit below follows the same contract with the shared hook: return `true` once the
  // row's draft may be discarded (persisted, or nothing left to persist), `false` to keep the
  // user's uncommitted value on screen. commitDraft itself already short-circuits when a mutation
  // is in flight or when the row holds no draft at all.
  async function commitLabel(row: RevisionCostGridRow) {
    await drafts.commitDraft(row, async (draft) => {
      const trimmed = draft.label.trim();
      if (!trimmed) {
        return false;
      }
      if (!isCostRow(row)) {
        if (!onUpdatePlanning || trimmed === row.planning?.name) {
          return true;
        }
        return onUpdatePlanning(row.node_id, { name: trimmed });
      }
      if (!onUpdateCost || trimmed === row.cost.label) {
        return true;
      }
      return onUpdateCost(row.node_id, { label: trimmed });
    });
  }

  async function commitQuantity(row: RevisionCostGridRow) {
    if (!isCostRow(row)) {
      return;
    }
    await drafts.commitDraft(row, async (draft) => {
      const quantity = Number(draft.quantity);
      // `quantity` is `gt=0` on the contract: a 0 or a blank field is refused here rather than
      // sent to be refused there, and the typed value is kept on screen so nothing is lost.
      if (!(quantity > 0)) {
        return false;
      }
      if (!onUpdateCost || quantity === costNumber(row.cost.quantity)) {
        return true;
      }
      return onUpdateCost(row.node_id, { quantity });
    });
  }

  async function commitHours(row: RevisionCostGridRow) {
    // INV-19 ↔ INV-20: only a labour facet has hours at all. A non-MO row never renders the cell,
    // and this guard keeps a stray commit from writing a field its nature forbids.
    if (!isCostRow(row) || row.cost.nature !== "labor") {
      return;
    }
    await drafts.commitDraft(row, async (draft) => {
      const hours = Number(draft.hours);
      if (!(hours >= 0)) {
        return false;
      }
      if (!onUpdateCost || hours === costNumber(row.cost.hours)) {
        return true;
      }
      return onUpdateCost(row.node_id, { hours });
    });
  }

  async function commitUnitCost(row: RevisionCostGridRow) {
    // The other half of the same rule: a disbursement is a non-MO attribute (INV-20).
    if (!isCostRow(row) || row.cost.nature === "labor") {
      return;
    }
    await drafts.commitDraft(row, async (draft) => {
      const unitCost = Number(draft.unitCost);
      if (!(unitCost >= 0)) {
        return false;
      }
      if (!onUpdateCost || unitCost === costNumber(row.cost.unit_cost)) {
        return true;
      }
      return onUpdateCost(row.node_id, { unit_cost: unitCost });
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
