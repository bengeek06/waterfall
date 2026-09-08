import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CostLinesTable, type CostLinesTableProps } from "./cost-lines-table";

const line = {
  id: 1,
  accounting_code: "6011",
  label: "Achat licences",
  quantity: "2.00",
  unit_cost: "100.00",
  purchase_cost: "200.00",
} as never;

function renderTable(overrides: Partial<CostLinesTableProps> = {}) {
  const props: CostLinesTableProps = {
    costLines: [line],
    canEditEstimate: true,
    editingLineId: null,
    editingLineDraft: { label: "", quantity: "", unitCost: "" },
    onEditLabelChange: vi.fn(),
    onEditQuantityChange: vi.fn(),
    onEditUnitCostChange: vi.fn(),
    estimateBusy: false,
    onStartEdit: vi.fn(),
    onSave: vi.fn(),
    onRequestDelete: vi.fn(),
    ...overrides,
  };
  return render(<CostLinesTable {...props} />);
}

describe("CostLinesTable", () => {
  afterEach(() => cleanup());

  it("saves a cost line when both quantity and unit cost are within their native HTML5 bounds", () => {
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "3.00", unitCost: "150.00" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).toHaveBeenCalledWith(line);
  });

  it("blocks Sauver and does not call onSave when the quantity is set below its native HTML5 minimum", () => {
    // Regression test for #201: before the fix, "Sauver" was a raw
    // `type="button"` that called `onSave` directly, bypassing the
    // `min`/`step`/`required` constraints declared on this field entirely.
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "-2", unitCost: "150.00" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("blocks Sauver and does not call onSave when the unit cost is set below its native HTML5 minimum", () => {
    // Regression test for #201, symmetric with the quantity case above.
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "-10" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("blocks Sauver and does not call onSave when the quantity is exactly 0", () => {
    // Regression test: `quantity`'s `min` must be the backend's exact bound
    // (`ck_wf_estimate_cost_line_quantity`, `quantity > 0`, strict), not a
    // looser `min="0"` -- 0 is mathematically `>= 0`, so a `min="0"` would let
    // `checkValidity()` pass and `onSave` would still be called, only to be
    // rejected by the backend afterwards.
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "0", unitCost: "150.00" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("still saves when the unit cost is exactly 0, since 0 is a legitimate purchase cost", () => {
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "0" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).toHaveBeenCalledWith(line);
  });

  it("blocks Sauver and does not call onSave when the quantity is left blank", () => {
    // `quantity` is `required`: unlike `unitCost` (0 is a legitimate purchase
    // cost, matching the backend's `unit_cost >= 0` constraint), the backend
    // rejects a cost line with a quantity of 0
    // (`ck_wf_estimate_cost_line_quantity`, `quantity > 0`), so a blank field
    // silently coercing to `Number("") === 0` must not slip through either.
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "", unitCost: "150.00" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("still saves when the unit cost is left blank, since 0 is a legitimate purchase cost", () => {
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).toHaveBeenCalledWith(line);
  });

  it("does not validate the free-text label field", () => {
    // `label` has no HTML5 constraints (no `type="number"`, no `required`) --
    // an empty label must not block Sauver.
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "", quantity: "2.00", unitCost: "150.00" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).toHaveBeenCalledWith(line);
  });

  it("does not render an editable row for a line that is not being edited", () => {
    renderTable({ editingLineId: null });

    expect(screen.getByText("Achat licences")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sauver" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
  });
});
