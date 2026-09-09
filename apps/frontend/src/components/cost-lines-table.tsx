"use client";

import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { EstimateCostLine } from "@/lib/backend";

export type EditingLineDraft = { label: string; quantity: string; unitCost: string };

export type CostLinesTableProps = {
  costLines: EstimateCostLine[];
  canEditEstimate: boolean;
  editingLineId: number | null;
  editingLineDraft: EditingLineDraft;
  onEditLabelChange: (value: string) => void;
  onEditQuantityChange: (value: string) => void;
  onEditUnitCostChange: (value: string) => void;
  estimateBusy: boolean;
  onStartEdit: (line: EstimateCostLine) => void;
  onSave: (line: EstimateCostLine) => void;
  onRequestDelete: (line: EstimateCostLine) => void;
  selectedCostLineIds: Set<number>;
  onSelectedCostLineIdsChange: (next: Set<number>) => void;
  bulkAssignBusy: boolean;
};

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
  estimateBusy,
  onStartEdit,
  onSave,
  onRequestDelete,
  selectedCostLineIds,
  onSelectedCostLineIdsChange,
  bulkAssignBusy,
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
          <TableHead>Montant</TableHead>
          {canEditEstimate ? <TableHead>Action</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {costLines.map((line) => {
          const editing = editingLineId === line.id;
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
            <TableCell colSpan={canEditEstimate ? 7 : 5} className="text-muted-foreground">
              Aucune ligne de coût.
            </TableCell>
          </TableRow>
        ) : null}
      </TableBody>
    </Table>
  );
}
