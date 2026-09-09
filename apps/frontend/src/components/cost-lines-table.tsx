"use client";

import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { EstimateCostLine } from "@/lib/backend";

export type EditingLineDraft = { label: string; quantity: string; unitCost: string; plannedDate: string };

export type CostLinesTableProps = {
  costLines: EstimateCostLine[];
  canEditEstimate: boolean;
  editingLineId: number | null;
  editingLineDraft: EditingLineDraft;
  onEditLabelChange: (value: string) => void;
  onEditQuantityChange: (value: string) => void;
  onEditUnitCostChange: (value: string) => void;
  onEditPlannedDateChange: (value: string) => void;
  estimateBusy: boolean;
  onStartEdit: (line: EstimateCostLine) => void;
  onSave: (line: EstimateCostLine) => void;
  onRequestDelete: (line: EstimateCostLine) => void;
  selectedCostLineIds: Set<number>;
  onSelectedCostLineIdsChange: (next: Set<number>) => void;
  bulkAssignBusy: boolean;
  // E6-07/#68: opens the "apply a milestone template" dialog for a single line. The backend
  // (not this table) remains the sole authority on whether a line's *cost type* is eligible
  // (non-labor) -- see estimate-milestone-template-dialog.tsx's doc comment -- so the action
  // still stays visible for every line on that axis rather than trying to infer a labor line's
  // `kind` from fields this table doesn't otherwise load (EstimateCostLineRead exposes
  // `cost_type_code`, not `cost_type.kind`).
  onOpenMilestoneDialog: (line: EstimateCostLine) => void;
  // Haute review finding on #68: unlike the labor-line case above, whether `line.task_id` points
  // at a milestone task *is* known client-side (it's the same `Task.is_milestone` flag
  // estimate-create-task-dialog.tsx already filters parent options on) and the backend rejects it
  // unconditionally -- `create_planning_task` raises `PlanningTreeInvariantError("A milestone
  // cannot contain children")`, mapped to a 409 -- so there is no scenario where retrying helps.
  // Set of `Task.id`s (not uids) that are milestones, resolved by the caller from
  // `parentTaskOptions`/`planningDetail.tasks`.
  milestoneTaskIds: Set<number>;
};

// `planned_date` (#66 / E6-05) is returned by the backend as a full ISO datetime (the column is
// `DateTime(timezone=True)`, always carrying an explicit offset, e.g. "2026-10-01T00:00:00+00:00"
// -- unlike the naive-UTC planning schedule fields in lib/planning-schedule.ts, which need the
// "append Z if missing" workaround documented there). Read-only display only ever needs the
// calendar date, so it's formatted the same way as that file's own `formatDate` (`fr-FR`, forced
// to the UTC calendar day so it never disagrees with the editable `<input type="date">` below).
function formatPlannedDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleDateString("fr-FR", { timeZone: "UTC" });
}

// Extracted from ProjectDetailsPage (E4-11 / #151): the cost lines table with inline editing.
// The row-rendering `.map` callback below is already its own function scope (and was already
// under the complexity threshold before this extraction) -- the extraction here is purely for
// file-size/readability, not for lowering complexity. Verbatim JSX move -- see page.tsx call
// site for wiring.
export function CostLinesTable({
  costLines,
  canEditEstimate,
  editingLineId,
  editingLineDraft,
  onEditLabelChange,
  onEditQuantityChange,
  onEditUnitCostChange,
  onEditPlannedDateChange,
  estimateBusy,
  onStartEdit,
  onSave,
  onRequestDelete,
  selectedCostLineIds,
  onSelectedCostLineIdsChange,
  bulkAssignBusy,
  onOpenMilestoneDialog,
  milestoneTaskIds,
}: CostLinesTableProps) {
  // Live DOM refs for the two constrained fields (`min`/`step`, `quantity` also
  // `required` -- see below) of whichever row is currently being edited, so
  // "Sauver" can run native HTML5 validation on them before calling `onSave`.
  // Only one row is ever in edit mode at a time here (`editingLineId`, unlike
  // `capacity-table.tsx` where every row is simultaneously editable), so a
  // single pair of refs is enough: they're naturally reset as the previous
  // row's `<Input>`s unmount and the newly-edited row's mount (same reasoning
  // as `calendars-table.tsx`'s single-editing-row case). `label` is free text
  // with no HTML5 constraints on it, so it's intentionally excluded.
  //
  // `quantity`'s `min="0.01"` (not `"0"`) and `required` both mirror the
  // backend's actual constraint (`ck_wf_estimate_cost_line_quantity`,
  // `quantity > 0`, strict) -- same precedent as `weeksPerYear`'s `min="1"` in
  // `calendars-table.tsx`, an exact bound rather than a looser one. `0` is not
  // a legitimate quantity (a `min="0"` would let it slip past `checkValidity`
  // and fail on the backend instead), so it's excluded on both ends: blank
  // (`required`) and zero (`min="0.01"`). `unitCost` keeps `min="0"`: the
  // backend allows `unit_cost >= 0` (a free line item is legitimate), so it's
  // deliberately left without `required` too -- same precedent as
  // `capacity-table.tsx`'s `personCount`/`availableHours` (#194).
  const quantityRef = useRef<HTMLInputElement>(null);
  const unitCostRef = useRef<HTMLInputElement>(null);

  // "Select all" mirrors ProjectsTable's own header checkbox (E5): it only ever applies to the
  // rows currently rendered here, merging/subtracting their ids into `selectedCostLineIds` rather
  // than replacing the whole set outright.
  const allSelected = costLines.length > 0 && costLines.every((line) => selectedCostLineIds.has(line.id));

  function toggleCostLine(lineId: number, checked: boolean) {
    const next = new Set(selectedCostLineIds);
    if (checked) {
      next.add(lineId);
    } else {
      next.delete(lineId);
    }
    onSelectedCostLineIdsChange(next);
  }

  function toggleAllCostLines(checked: boolean) {
    const next = new Set(selectedCostLineIds);
    for (const line of costLines) {
      if (checked) {
        next.add(line.id);
      } else {
        next.delete(line.id);
      }
    }
    onSelectedCostLineIdsChange(next);
  }

  function handleSave(line: EstimateCostLine) {
    // Before this fix, "Sauver" was a raw `type="button"` that called `onSave`
    // directly, bypassing the `min`/`step`/`required` constraints declared on
    // these two fields entirely (see #201).
    const fields = [quantityRef.current, unitCostRef.current].filter(
      (field): field is HTMLInputElement => field !== null,
    );
    const firstInvalid = fields.find((field) => !field.checkValidity());
    if (firstInvalid) {
      firstInvalid.reportValidity();
      return;
    }
    onSave(line);
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {canEditEstimate ? (
            <TableHead>
              <Checkbox
                aria-label="Tout sélectionner"
                checked={allSelected}
                disabled={bulkAssignBusy}
                onCheckedChange={(checked) => toggleAllCostLines(Boolean(checked))}
              />
            </TableHead>
          ) : null}
          <TableHead>Catégorie</TableHead>
          <TableHead>Libellé</TableHead>
          <TableHead>Quantité</TableHead>
          <TableHead>Coût unitaire</TableHead>
          <TableHead>Date prévisionnelle</TableHead>
          <TableHead>Montant</TableHead>
          {canEditEstimate ? <TableHead>Action</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {costLines.map((line) => {
          const editing = editingLineId === line.id;
          // Haute review finding on #68 -- see the milestoneTaskIds prop doc comment above.
          const attachedToMilestoneTask = line.task_id != null && milestoneTaskIds.has(line.task_id);
          return (
            <TableRow key={line.id}>
              {canEditEstimate ? (
                <TableCell>
                  <Checkbox
                    aria-label={`Sélectionner ${line.label}`}
                    checked={selectedCostLineIds.has(line.id)}
                    disabled={bulkAssignBusy}
                    onCheckedChange={(checked) => toggleCostLine(line.id, Boolean(checked))}
                  />
                </TableCell>
              ) : null}
              <TableCell>{line.accounting_code}</TableCell>
              <TableCell>
                {editing ? (
                  <Input value={editingLineDraft.label} onChange={(event) => onEditLabelChange(event.target.value)} />
                ) : (
                  line.label
                )}
              </TableCell>
              <TableCell>
                {editing ? (
                  <Input
                    ref={quantityRef}
                    aria-label={`Quantité de ${line.label}`}
                    type="number"
                    min="0.01"
                    step="0.01"
                    required
                    value={editingLineDraft.quantity}
                    onChange={(event) => onEditQuantityChange(event.target.value)}
                  />
                ) : (
                  line.quantity
                )}
              </TableCell>
              <TableCell>
                {editing ? (
                  <Input
                    ref={unitCostRef}
                    aria-label={`Coût unitaire de ${line.label}`}
                    type="number"
                    min="0"
                    step="0.01"
                    value={editingLineDraft.unitCost}
                    onChange={(event) => onEditUnitCostChange(event.target.value)}
                  />
                ) : (
                  line.unit_cost
                )}
              </TableCell>
              <TableCell>
                {editing ? (
                  <Input
                    aria-label={`Date prévisionnelle de ${line.label}`}
                    type="date"
                    value={editingLineDraft.plannedDate}
                    onChange={(event) => onEditPlannedDateChange(event.target.value)}
                  />
                ) : (
                  formatPlannedDate(line.planned_date)
                )}
              </TableCell>
              <TableCell>{line.purchase_cost}</TableCell>
              {canEditEstimate ? (
                <TableCell>
                  <div className="flex flex-wrap gap-2">
                    {editing ? (
                      <Button size="sm" type="button" disabled={estimateBusy} onClick={() => handleSave(line)}>
                        Sauver
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" type="button" onClick={() => onStartEdit(line)}>
                        Modifier
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      type="button"
                      disabled={estimateBusy || attachedToMilestoneTask}
                      title={
                        attachedToMilestoneTask
                          ? "Cette ligne est rattachée à une tâche-jalon, qui ne peut pas recevoir de sous-tâches."
                          : undefined
                      }
                      onClick={() => onOpenMilestoneDialog(line)}
                    >
                      Gabarit de jalons
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      type="button"
                      disabled={estimateBusy}
                      onClick={() => onRequestDelete(line)}
                    >
                      Supprimer
                    </Button>
                  </div>
                </TableCell>
              ) : null}
            </TableRow>
          );
        })}
        {!costLines.length ? (
          <TableRow>
            <TableCell colSpan={canEditEstimate ? 8 : 6} className="text-muted-foreground">
              Aucune ligne de coût.
            </TableCell>
          </TableRow>
        ) : null}
      </TableBody>
    </Table>
  );
}
