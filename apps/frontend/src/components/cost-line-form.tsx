"use client";

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
            id="cost-line-quantity"
            type="number"
            min="0"
            step="0.01"
            value={costLineDraft.quantity}
            onChange={(event) => onQuantityChange(event.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="cost-line-unit-cost">Coût unitaire</Label>
          <Input
            id="cost-line-unit-cost"
            type="number"
            min="0"
            step="0.01"
            value={costLineDraft.unitCost}
            onChange={(event) => onUnitCostChange(event.target.value)}
          />
        </div>
        <div className="flex items-end">
          <Button type="button" disabled={estimateBusy} onClick={onAdd}>
            Ajouter la ligne
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
