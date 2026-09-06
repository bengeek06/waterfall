"use client";

import { Button } from "@/components/ui/button";
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
}: CostLinesTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
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
                    type="number"
                    min="0"
                    step="0.01"
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
                      <Button size="sm" type="button" disabled={estimateBusy} onClick={() => onSave(line)}>
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
            <TableCell colSpan={canEditEstimate ? 6 : 5} className="text-muted-foreground">
              Aucune ligne de coût.
            </TableCell>
          </TableRow>
        ) : null}
      </TableBody>
    </Table>
  );
}
