"use client";

import { useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { EstimateCostLine, EstimateTaskRow } from "@/lib/backend";
import { buildEstimateGridEntries } from "@/lib/estimate-grid";
import { buildAttachableTaskOptions } from "@/lib/estimate-task-options";

export type EditingLineDraft = {
  label: string;
  quantity: string;
  unitCost: string;
  plannedDate: string;
  taskId: string;
};

export type CostLinesTableProps = {
  costLines: EstimateCostLine[];
  // E12-04/#276: the selected estimate's task rows -- drives both the grid's task
  // hierarchy/grouping (see buildEstimateGridEntries) and the "Tâche" selector's options when a
  // row is being edited (buildAttachableTaskOptions).
  estimateTaskRows: EstimateTaskRow[];
  canEditEstimate: boolean;
  editingLineId: number | null;
  editingLineDraft: EditingLineDraft;
  onEditLabelChange: (value: string) => void;
  onEditQuantityChange: (value: string) => void;
  onEditUnitCostChange: (value: string) => void;
  onEditPlannedDateChange: (value: string) => void;
  onEditTaskIdChange: (value: string) => void;
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

// E12-04/#276: resolves the display name of the task a cost line is attached to, from this
// estimate's own task rows -- "-" for a line with no attachment (`task_id: null`) or, in
// practice never, one whose `task_id` doesn't match any row of this estimate (see
// buildEstimateGridEntries's own doc comment on why that can't happen from the UI).
function resolveAttachedTaskName(taskId: number | null | undefined, estimateTaskRows: EstimateTaskRow[]): string {
  if (taskId == null) {
    return "-";
  }
  return estimateTaskRows.find((row) => row.task_id === taskId)?.task_name ?? "-";
}

// Extracted from ProjectDetailsPage (E4-11 / #151): the cost lines table with inline editing.
// The row-rendering `.map` callback below is already its own function scope (and was already
// under the complexity threshold before this extraction) -- the extraction here is purely for
// file-size/readability, not for lowering complexity. Verbatim JSX move -- see page.tsx call
// site for wiring.
export function CostLinesTable({
  costLines,
  estimateTaskRows,
  canEditEstimate,
  editingLineId,
  editingLineDraft,
  onEditLabelChange,
  onEditQuantityChange,
  onEditUnitCostChange,
  onEditPlannedDateChange,
  onEditTaskIdChange,
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

  // E12-04/#276: the "Tâche" selector's options (create-form's own sibling in
  // cost-line-form.tsx), and the grid's task/cost-line/global-lines row order -- see
  // buildEstimateGridEntries's doc comment for the exact ordering rules
  // (docs/devis-v0.1-specification.md's "Grille de devis").
  const taskOptions = buildAttachableTaskOptions(estimateTaskRows);
  const gridEntries = buildEstimateGridEntries(costLines, estimateTaskRows);
  // Column realignment across task/line/global-lines rows is explicitly out of scope here (see
  // E12-05/#277) -- a task-header/"lignes globales" row simply spans every column instead.
  const columnCount = canEditEstimate ? 9 : 7;

  function renderTaskRow(taskRow: EstimateTaskRow) {
    return (
      <TableRow key={`task-${taskRow.id}`} className="bg-muted/30">
        <TableCell colSpan={columnCount}>
          <div
            className="flex items-center gap-2 font-medium"
            style={{ paddingLeft: `${(taskRow.outline_level ?? 0) * 1.25}rem` }}
          >
            <span>{taskRow.outline_number ? `${taskRow.outline_number} — ${taskRow.task_name}` : taskRow.task_name}</span>
            {taskRow.is_milestone ? <Badge variant="outline">Jalon</Badge> : null}
          </div>
        </TableCell>
      </TableRow>
    );
  }

  function renderGlobalHeaderRow() {
    return (
      <TableRow key="global-header" className="bg-muted/30">
        <TableCell colSpan={columnCount} className="font-medium">
          Lignes globales
        </TableCell>
      </TableRow>
    );
  }

  function renderLineRow(line: EstimateCostLine, indentLevel: number) {
    const editing = editingLineId === line.id;
    // Haute review finding on #68 -- see the milestoneTaskIds prop doc comment above.
    const attachedToMilestoneTask = line.task_id != null && milestoneTaskIds.has(line.task_id);
    return (
      <TableRow key={`line-${line.id}`}>
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
          <div style={{ paddingLeft: `${indentLevel * 1.25}rem` }}>
            {editing ? (
              <Input value={editingLineDraft.label} onChange={(event) => onEditLabelChange(event.target.value)} />
            ) : (
              line.label
            )}
          </div>
        </TableCell>
        <TableCell>
          {editing ? (
            <select
              aria-label={`Tâche de ${line.label}`}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={editingLineDraft.taskId}
              onChange={(event) => onEditTaskIdChange(event.target.value)}
            >
              <option value="">Aucune</option>
              {taskOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : (
            resolveAttachedTaskName(line.task_id, estimateTaskRows)
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
          <TableHead>Tâche</TableHead>
          <TableHead>Quantité</TableHead>
          <TableHead>Coût unitaire</TableHead>
          <TableHead>Date prévisionnelle</TableHead>
          <TableHead>Montant</TableHead>
          {canEditEstimate ? <TableHead>Action</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {gridEntries.map((entry) => {
          if (entry.kind === "task") {
            return renderTaskRow(entry.taskRow);
          }
          if (entry.kind === "global-header") {
            return renderGlobalHeaderRow();
          }
          return renderLineRow(entry.line, entry.indentLevel);
        })}
        {!gridEntries.length ? (
          <TableRow>
            <TableCell colSpan={columnCount} className="text-muted-foreground">
              Aucune ligne de coût.
            </TableCell>
          </TableRow>
        ) : null}
      </TableBody>
    </Table>
  );
}
