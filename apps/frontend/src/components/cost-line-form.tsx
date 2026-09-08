"use client";

import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CostCategory } from "@/lib/backend";

export type CostLineDraft = { categoryId: string; label: string; quantity: string; unitCost: string };

export type CostLineFormProps = {
  costCategories: CostCategory[];
  costLineDraft: CostLineDraft;
  onCategoryChange: (value: string) => void;
  onLabelChange: (value: string) => void;
  onQuantityChange: (value: string) => void;
  onUnitCostChange: (value: string) => void;
  estimateBusy: boolean;
  onAdd: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the add-cost-line form. Rendering is gated by
// the caller (canEditEstimate), so this component always renders unconditionally when mounted.
// Verbatim JSX move -- see page.tsx call site for wiring.
export function CostLineForm({
  costCategories,
  costLineDraft,
  onCategoryChange,
  onLabelChange,
  onQuantityChange,
  onUnitCostChange,
  estimateBusy,
  onAdd,
}: CostLineFormProps) {
  // Live DOM refs for the two constrained fields, so "Ajouter la ligne" can
  // run native HTML5 validation on them before calling `onAdd` -- same fix as
  // `cost-lines-table.tsx`'s "Sauver" (#201), extended here to this pinned
  // create row per review (same precedent as #194, which fixed both the
  // pinned create row and the edit rows of `calendars-table.tsx` together).
  // `label`/`categoryId` are free text/a `<select>` with no HTML5 numeric
  // constraints, so they're intentionally excluded. See `cost-lines-table.tsx`
  // for why `quantity` uses `min="0.01"` + `required` (backend
  // `quantity > 0`, strict) while `unitCost` keeps `min="0"` without
  // `required` (backend `unit_cost >= 0`, 0 is a legitimate free line item).
  const quantityRef = useRef<HTMLInputElement>(null);
  const unitCostRef = useRef<HTMLInputElement>(null);

  function handleAdd() {
    const fields = [quantityRef.current, unitCostRef.current].filter(
      (field): field is HTMLInputElement => field !== null,
    );
    const firstInvalid = fields.find((field) => !field.checkValidity());
    if (firstInvalid) {
      firstInvalid.reportValidity();
      return;
    }
    onAdd();
  }

  return (
    <Card>
      <CardContent className="grid gap-4 pt-6 md:grid-cols-5">
        <div className="grid gap-2">
          <Label htmlFor="cost-line-category">Catégorie</Label>
          <select
            id="cost-line-category"
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            value={costLineDraft.categoryId}
            onChange={(event) => onCategoryChange(event.target.value)}
          >
            <option value="">Choisir...</option>
            {costCategories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="cost-line-label">Libellé</Label>
          <Input
            id="cost-line-label"
            value={costLineDraft.label}
            onChange={(event) => onLabelChange(event.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="cost-line-quantity">Quantité</Label>
          <Input
            ref={quantityRef}
            id="cost-line-quantity"
            type="number"
            min="0.01"
            step="0.01"
            required
            value={costLineDraft.quantity}
            onChange={(event) => onQuantityChange(event.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="cost-line-unit-cost">Coût unitaire</Label>
          <Input
            ref={unitCostRef}
            id="cost-line-unit-cost"
            type="number"
            min="0"
            step="0.01"
            value={costLineDraft.unitCost}
            onChange={(event) => onUnitCostChange(event.target.value)}
          />
        </div>
        <div className="flex items-end">
          <Button type="button" disabled={estimateBusy} onClick={handleAdd}>
            Ajouter la ligne
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
