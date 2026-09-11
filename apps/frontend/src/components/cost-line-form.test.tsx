import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CostLineForm, type CostLineFormProps } from "./cost-line-form";

const costCategories = [{ id: 1, name: "Achats" }] as never;

function renderForm(overrides: Partial<CostLineFormProps> = {}) {
  const props: CostLineFormProps = {
    costCategories,
    estimateTaskRows: [],
    costLineDraft: {
      categoryId: "1",
      label: "Achat licences",
      quantity: "2.00",
      unitCost: "150.00",
      plannedDate: "",
      taskId: "",
    },
    onCategoryChange: vi.fn(),
    onLabelChange: vi.fn(),
    onQuantityChange: vi.fn(),
    onUnitCostChange: vi.fn(),
    onPlannedDateChange: vi.fn(),
    onTaskIdChange: vi.fn(),
    estimateBusy: false,
    onAdd: vi.fn(),
    ...overrides,
  };
  return render(<CostLineForm {...props} />);
}

describe("CostLineForm", () => {
  afterEach(() => cleanup());

  it("adds a cost line when both quantity and unit cost are within their native HTML5 bounds", () => {
    const onAdd = vi.fn();
    renderForm({ onAdd });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).toHaveBeenCalledOnce();
  });

  it("blocks Ajouter la ligne and does not call onAdd when the quantity is set below its native HTML5 minimum", () => {
    // Regression test for #201: before the fix, "Ajouter la ligne" was a raw
    // `type="button"` that called `onAdd` directly, bypassing the
    // `min`/`step`/`required` constraints declared on this field entirely.
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "-2", unitCost: "150.00", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).not.toHaveBeenCalled();
  });

  it("blocks Ajouter la ligne and does not call onAdd when the quantity is exactly 0", () => {
    // Regression test: `quantity`'s `min` must be the backend's exact bound
    // (`ck_wf_estimate_cost_line_quantity`, `quantity > 0`, strict), not a
    // looser `min="0"` -- 0 is mathematically `>= 0`, so a `min="0"` would let
    // `checkValidity()` pass and `onAdd` would still be called, only to be
    // rejected by the backend afterwards.
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "0", unitCost: "150.00", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).not.toHaveBeenCalled();
  });

  it("blocks Ajouter la ligne and does not call onAdd when the unit cost is set below its native HTML5 minimum", () => {
    // Regression test for #201, symmetric with the quantity case above.
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "2.00", unitCost: "-10", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).not.toHaveBeenCalled();
  });

  it("blocks Ajouter la ligne and does not call onAdd when the quantity is left blank", () => {
    // `quantity` is `required`: unlike `unitCost` (0 is a legitimate purchase
    // cost, matching the backend's `unit_cost >= 0` constraint), the backend
    // rejects a cost line with a quantity of 0
    // (`ck_wf_estimate_cost_line_quantity`, `quantity > 0`), so a blank field
    // silently coercing to `Number("") === 0` must not slip through either.
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "", unitCost: "150.00", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).not.toHaveBeenCalled();
  });

  it("still adds when the unit cost is exactly 0, since 0 is a legitimate purchase cost", () => {
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "2.00", unitCost: "0", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).toHaveBeenCalledOnce();
  });

  it("still adds when the unit cost is left blank, since 0 is a legitimate purchase cost", () => {
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "2.00", unitCost: "", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).toHaveBeenCalledOnce();
  });

  it("does not validate the free-text label field", () => {
    const onAdd = vi.fn();
    renderForm({
      costLineDraft: { categoryId: "1", label: "", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
      onAdd,
    });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

    expect(onAdd).toHaveBeenCalledOnce();
  });

  // #66 (E6-05): planned_date is optional, independent from task_id -- an empty value must never
  // block "Ajouter la ligne" (unlike quantity, it carries no `required`/HTML5 numeric constraint).
  describe("planned date (E6-05)", () => {
    it("still adds when the planned date is left blank, since the field is optional", () => {
      const onAdd = vi.fn();
      renderForm({
        costLineDraft: { categoryId: "1", label: "Achat licences", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
        onAdd,
      });

      fireEvent.click(screen.getByRole("button", { name: "Ajouter la ligne" }));

      expect(onAdd).toHaveBeenCalledOnce();
    });

    it("reports a change to the planned date field", () => {
      const onPlannedDateChange = vi.fn();
      renderForm({ onPlannedDateChange });

      fireEvent.change(screen.getByLabelText("Date prévisionnelle"), { target: { value: "2026-10-01" } });

      expect(onPlannedDateChange).toHaveBeenCalledWith("2026-10-01");
    });
  });

  // E12-04/#276: the "Tâche" selector, optional, wired to CostLineDraft.taskId (task_id in the
  // create payload).
  describe("task selector (E12-04)", () => {
    const estimateTaskRows = [
      {
        id: 1,
        estimate_id: 1,
        task_id: 42,
        parent_task_id: null,
        position: 1,
        task_name: "Terrassement",
        outline_number: "1",
        outline_level: 0,
        is_milestone: false,
      },
      {
        id: 2,
        estimate_id: 1,
        task_id: null,
        parent_task_id: 42,
        position: 2,
        task_name: "Sous-tâche sans jumeau",
        outline_number: "1.1",
        outline_level: 1,
        is_milestone: false,
      },
    ] as never;

    it("always offers 'Aucune' and defaults to it", () => {
      renderForm({ estimateTaskRows });

      expect(screen.getByRole("combobox", { name: "Tâche" })).toHaveValue("");
      expect(screen.getByRole("option", { name: "Aucune" })).toBeInTheDocument();
    });

    it("offers every task row that has a task_id (a MsTask twin)", () => {
      renderForm({ estimateTaskRows });

      expect(screen.getByRole("option", { name: "Terrassement" })).toBeInTheDocument();
    });

    it("does not offer a task row with no task_id (no MsTask twin)", () => {
      renderForm({ estimateTaskRows });

      expect(screen.queryByRole("option", { name: /Sous-tâche sans jumeau/ })).not.toBeInTheDocument();
    });

    it("reports a change to the selected task", () => {
      const onTaskIdChange = vi.fn();
      renderForm({ estimateTaskRows, onTaskIdChange });

      fireEvent.change(screen.getByRole("combobox", { name: "Tâche" }), { target: { value: "42" } });

      expect(onTaskIdChange).toHaveBeenCalledWith("42");
    });
  });
});
