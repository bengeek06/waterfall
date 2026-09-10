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
    estimateTaskRows: [],
    allCostCategories: [],
    canEditEstimate: true,
    editingLineId: null,
    editingLineDraft: { label: "", quantity: "", unitCost: "", plannedDate: "", taskId: "" },
    onEditLabelChange: vi.fn(),
    onEditQuantityChange: vi.fn(),
    onEditUnitCostChange: vi.fn(),
    onEditPlannedDateChange: vi.fn(),
    onEditTaskIdChange: vi.fn(),
    estimateBusy: false,
    onStartEdit: vi.fn(),
    onSave: vi.fn(),
    onRequestDelete: vi.fn(),
    selectedCostLineIds: new Set(),
    onSelectedCostLineIdsChange: vi.fn(),
    bulkAssignBusy: false,
    onOpenMilestoneDialog: vi.fn(),
    milestoneTaskIds: new Set(),
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
      editingLineDraft: { label: "Achat licences", quantity: "3.00", unitCost: "150.00", plannedDate: "", taskId: "" },
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
      editingLineDraft: { label: "Achat licences", quantity: "-2", unitCost: "150.00", plannedDate: "", taskId: "" },
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
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "-10", plannedDate: "", taskId: "" },
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
      editingLineDraft: { label: "Achat licences", quantity: "0", unitCost: "150.00", plannedDate: "", taskId: "" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("still saves when the unit cost is exactly 0, since 0 is a legitimate purchase cost", () => {
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "0", plannedDate: "", taskId: "" },
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
      editingLineDraft: { label: "Achat licences", quantity: "", unitCost: "150.00", plannedDate: "", taskId: "" },
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("still saves when the unit cost is left blank, since 0 is a legitimate purchase cost", () => {
    const onSave = vi.fn();
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "", plannedDate: "", taskId: "" },
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
      editingLineDraft: { label: "", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
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

  // E12-05/#277 review finding: the quantity/unit-cost inline `<Input>`s' aria-labels must stay in
  // sync with their (E12-05-renamed) column headers ("Qté", "Débours"), not the older "Quantité"/
  // "Coût unitaire" wording that no longer appears anywhere in the visible UI.
  it("labels the edited line's quantity input after the current 'Qté' column header", () => {
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
    });

    expect(screen.getByLabelText("Qté de Achat licences")).toBeInTheDocument();
    expect(screen.queryByLabelText("Quantité de Achat licences")).not.toBeInTheDocument();
  });

  it("labels the edited line's unit cost input after the current 'Débours' column header", () => {
    renderTable({
      editingLineId: 1,
      editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
    });

    expect(screen.getByLabelText("Débours de Achat licences")).toBeInTheDocument();
    expect(screen.queryByLabelText("Coût unitaire de Achat licences")).not.toBeInTheDocument();
  });

  // #66 (E6-05): planned_date is optional, independent from task_id -- an empty value must never
  // block "Sauver" (unlike quantity, it carries no `required`/HTML5 numeric constraint).
  describe("planned date (E6-05)", () => {
    it("still saves when the planned date is left blank, since the field is optional", () => {
      const onSave = vi.fn();
      renderTable({
        editingLineId: 1,
        editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
        onSave,
      });

      fireEvent.click(screen.getByRole("button", { name: "Sauver" }));

      expect(onSave).toHaveBeenCalledWith(line);
    });

    it("reports a change to the edited line's planned date field", () => {
      const onEditPlannedDateChange = vi.fn();
      renderTable({
        editingLineId: 1,
        editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "150.00", plannedDate: "", taskId: "" },
        onEditPlannedDateChange,
      });

      fireEvent.change(screen.getByLabelText("Date prévisionnelle de Achat licences"), {
        target: { value: "2026-10-01" },
      });

      expect(onEditPlannedDateChange).toHaveBeenCalledWith("2026-10-01");
    });

    it("pre-fills the edited line's planned date input from editingLineDraft", () => {
      renderTable({
        editingLineId: 1,
        editingLineDraft: { label: "Achat licences", quantity: "2.00", unitCost: "150.00", plannedDate: "2026-10-01", taskId: "" },
      });

      expect(screen.getByLabelText("Date prévisionnelle de Achat licences")).toHaveValue("2026-10-01");
    });

    it("renders a placeholder for a line with no planned date when not editing", () => {
      renderTable({ editingLineId: null });

      expect(screen.getAllByText("-").length).toBeGreaterThan(0);
    });

    it("renders the formatted planned date for a line that has one, when not editing", () => {
      const lineWithDate = {
        id: 1,
        accounting_code: "6011",
        label: "Achat licences",
        quantity: "2.00",
        unit_cost: "100.00",
        purchase_cost: "200.00",
        planned_date: "2026-10-01T00:00:00+00:00",
      } as never;
      renderTable({ costLines: [lineWithDate], editingLineId: null });

      expect(screen.getByText("01/10/2026")).toBeInTheDocument();
    });
  });

  // E6-07/#68: "apply a milestone template" action, one per row. The backend alone decides
  // whether a line's *cost type* is eligible (non-labor) -- see cost-lines-table.tsx's own doc
  // comment on onOpenMilestoneDialog -- so this table never disables/hides the button on that
  // axis. It does, however, disable the button (Haute review finding on #68) when the line's
  // `task_id` points at a milestone task: that case is a structural invariant the backend
  // rejects unconditionally, and is knowable client-side from `milestoneTaskIds`.
  describe("milestone template action (E6-07)", () => {
    it("opens the milestone dialog for the clicked line", () => {
      const onOpenMilestoneDialog = vi.fn();
      renderTable({ onOpenMilestoneDialog });

      fireEvent.click(screen.getByRole("button", { name: "Gabarit de jalons" }));

      expect(onOpenMilestoneDialog).toHaveBeenCalledWith(line);
    });

    it("hides the action entirely when the estimate is not editable", () => {
      renderTable({ canEditEstimate: false });

      expect(screen.queryByRole("button", { name: "Gabarit de jalons" })).not.toBeInTheDocument();
    });

    // Haute review finding on #68: a cost line attached to a milestone task can never accept the
    // milestone-template action -- `create_planning_task` unconditionally rejects attaching
    // children to a milestone (409) -- so the button is disabled client-side and never sends a
    // request doomed to fail.
    it("disables the action and does not open the dialog for a line attached to a milestone task", () => {
      const milestoneLine = {
        id: 2,
        accounting_code: "6011",
        label: "Livraison lot 3",
        quantity: "1.00",
        unit_cost: "0.00",
        purchase_cost: "0.00",
        task_id: 42,
      } as never;
      const onOpenMilestoneDialog = vi.fn();
      renderTable({
        costLines: [milestoneLine],
        milestoneTaskIds: new Set([42]),
        onOpenMilestoneDialog,
      });

      const button = screen.getByRole("button", { name: "Gabarit de jalons" });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute(
        "title",
        "Cette ligne est rattachée à une tâche-jalon, qui ne peut pas recevoir de sous-tâches.",
      );

      fireEvent.click(button);

      expect(onOpenMilestoneDialog).not.toHaveBeenCalled();
    });

    it("keeps the action enabled for a line whose task_id is not in milestoneTaskIds", () => {
      const nonMilestoneLine = {
        id: 3,
        accounting_code: "6011",
        label: "Fourniture lot 2",
        quantity: "1.00",
        unit_cost: "0.00",
        purchase_cost: "0.00",
        task_id: 7,
      } as never;
      renderTable({ costLines: [nonMilestoneLine], milestoneTaskIds: new Set([42]) });

      const button = screen.getByRole("button", { name: "Gabarit de jalons" });
      expect(button).not.toBeDisabled();
      expect(button).not.toHaveAttribute("title");
    });

    it("keeps the action enabled for a line with no task_id at all", () => {
      renderTable({ milestoneTaskIds: new Set([42]) });

      expect(screen.getByRole("button", { name: "Gabarit de jalons" })).not.toBeDisabled();
    });
  });

  describe("row/select-all selection (E6-03)", () => {
    it("hides the selection column entirely when the estimate is not editable", () => {
      renderTable({ canEditEstimate: false });

      expect(screen.queryByRole("checkbox", { name: "Tout sélectionner" })).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox", { name: "Sélectionner Achat licences" })).not.toBeInTheDocument();
    });

    it("toggles a single line's selection on click", () => {
      const onSelectedCostLineIdsChange = vi.fn();
      renderTable({ onSelectedCostLineIdsChange });

      fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Achat licences" }));

      expect(onSelectedCostLineIdsChange).toHaveBeenCalledWith(new Set([1]));
    });

    it("reflects an already-selected line as checked", () => {
      renderTable({ selectedCostLineIds: new Set([1]) });

      expect(screen.getByRole("checkbox", { name: "Sélectionner Achat licences" })).toBeChecked();
    });

    it("selects every visible line when 'Tout sélectionner' is checked", () => {
      const secondLine = {
        id: 2,
        accounting_code: "6011",
        label: "Achat matériel",
        quantity: "1.00",
        unit_cost: "50.00",
        purchase_cost: "50.00",
      } as never;
      const onSelectedCostLineIdsChange = vi.fn();
      renderTable({ costLines: [line, secondLine], onSelectedCostLineIdsChange });

      fireEvent.click(screen.getByRole("checkbox", { name: "Tout sélectionner" }));

      expect(onSelectedCostLineIdsChange).toHaveBeenCalledWith(new Set([1, 2]));
    });

    it("deselects every visible line when 'Tout sélectionner' is unchecked", () => {
      const secondLine = {
        id: 2,
        accounting_code: "6011",
        label: "Achat matériel",
        quantity: "1.00",
        unit_cost: "50.00",
        purchase_cost: "50.00",
      } as never;
      const onSelectedCostLineIdsChange = vi.fn();
      renderTable({
        costLines: [line, secondLine],
        selectedCostLineIds: new Set([1, 2]),
        onSelectedCostLineIdsChange,
      });

      const selectAll = screen.getByRole("checkbox", { name: "Tout sélectionner" });
      expect(selectAll).toBeChecked();

      fireEvent.click(selectAll);

      expect(onSelectedCostLineIdsChange).toHaveBeenCalledWith(new Set());
    });

    // E12-04/#276 review finding: select-all/select-one must keep operating on `costLines` only,
    // never on the merged grid's full-width task-row/"Lignes globales" entries, once those start
    // interleaving with cost-line rows (see buildEstimateGridEntries in lib/estimate-grid.ts).
    it("selects only cost lines, not task rows, when the grid mixes task rows and cost lines", () => {
      const taskRow = {
        id: 1,
        estimate_id: 1,
        task_id: 42,
        parent_task_id: null,
        position: 1,
        task_name: "Terrassement",
        outline_number: "1",
        outline_level: 0,
        is_milestone: false,
      } as never;
      const attachedLine = {
        id: 2,
        accounting_code: "6011",
        label: "Béton",
        quantity: "1",
        unit_cost: "500",
        purchase_cost: "500",
        task_id: 42,
      } as never;
      const onSelectedCostLineIdsChange = vi.fn();
      renderTable({
        costLines: [line, attachedLine],
        estimateTaskRows: [taskRow],
        onSelectedCostLineIdsChange,
      });

      expect(screen.queryByRole("checkbox", { name: "Sélectionner Terrassement" })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("checkbox", { name: "Tout sélectionner" }));

      expect(onSelectedCostLineIdsChange).toHaveBeenCalledWith(new Set([1, 2]));
    });

    it("toggles a single cost line's selection when the grid mixes task rows and cost lines", () => {
      const taskRow = {
        id: 1,
        estimate_id: 1,
        task_id: 42,
        parent_task_id: null,
        position: 1,
        task_name: "Terrassement",
        outline_number: "1",
        outline_level: 0,
        is_milestone: false,
      } as never;
      const attachedLine = {
        id: 2,
        accounting_code: "6011",
        label: "Béton",
        quantity: "1",
        unit_cost: "500",
        purchase_cost: "500",
        task_id: 42,
      } as never;
      const onSelectedCostLineIdsChange = vi.fn();
      renderTable({
        costLines: [line, attachedLine],
        estimateTaskRows: [taskRow],
        selectedCostLineIds: new Set([1]),
        onSelectedCostLineIdsChange,
      });

      fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Béton" }));

      expect(onSelectedCostLineIdsChange).toHaveBeenCalledWith(new Set([1, 2]));
    });
  });

  // E12-04/#276: the Devis grid now lists the estimate's own task rows, ordered by `position`
  // (the planning's own depth-first order), each cost line grouped under the task it's attached
  // to, and a trailing "Lignes globales" section for cost lines with no task attachment. See
  // lib/estimate-grid.ts's buildEstimateGridEntries for the ordering rules this exercises.
  describe("Devis grid (E12-04)", () => {
    const rootTask = {
      id: 1,
      estimate_id: 1,
      task_id: 42,
      parent_task_id: null,
      position: 1,
      task_name: "Terrassement",
      outline_number: "1",
      outline_level: 0,
      is_milestone: false,
    };
    const childTask = {
      id: 2,
      estimate_id: 1,
      task_id: 43,
      parent_task_id: 42,
      position: 2,
      task_name: "Coulage dalle",
      outline_number: "1.1",
      outline_level: 1,
      is_milestone: true,
    };
    // A snapshot-only task row with no MsTask twin (`task_id: null`) -- can never receive a
    // cost line, but still appears in the grid as a task row.
    const orphanTask = {
      id: 3,
      estimate_id: 1,
      task_id: null,
      parent_task_id: null,
      position: 3,
      task_name: "Sous-tâche sans jumeau",
      outline_number: "2",
      outline_level: 0,
      is_milestone: false,
    };
    // Deliberately out of position order, to exercise the sort.
    const estimateTaskRows = [childTask, rootTask, orphanTask] as never;

    function rowTexts() {
      return screen.getAllByRole("row").map((row) => row.textContent ?? "");
    }

    it("lists every task row in position order, regardless of array order", () => {
      renderTable({ costLines: [], estimateTaskRows });

      const rows = rowTexts();
      const terrassementIndex = rows.findIndex((text) => text.includes("Terrassement"));
      const coulageIndex = rows.findIndex((text) => text.includes("Coulage dalle"));
      const orphanIndex = rows.findIndex((text) => text.includes("Sous-tâche sans jumeau"));

      expect(terrassementIndex).toBeGreaterThan(-1);
      expect(terrassementIndex).toBeLessThan(coulageIndex);
      expect(coulageIndex).toBeLessThan(orphanIndex);
    });

    it("marks a milestone task row with a 'Jalon' badge", () => {
      renderTable({ costLines: [], estimateTaskRows });

      expect(screen.getByText("Jalon")).toBeInTheDocument();
    });

    it("displays a cost line attached to a task right under that task", () => {
      const attachedLine = {
        id: 10,
        accounting_code: "6011",
        label: "Béton",
        quantity: "1",
        unit_cost: "500",
        purchase_cost: "500",
        task_id: 42,
      } as never;
      renderTable({ costLines: [attachedLine], estimateTaskRows });

      const rows = rowTexts();
      const terrassementIndex = rows.findIndex((text) => text.includes("Terrassement"));
      const betonIndex = rows.findIndex((text) => text.includes("Béton"));

      expect(terrassementIndex).toBeGreaterThan(-1);
      expect(betonIndex).toBe(terrassementIndex + 1);
    });

    it("displays a cost line with no task attachment in a trailing 'Lignes globales' section", () => {
      const globalLine = {
        id: 11,
        accounting_code: "6011",
        label: "Frais généraux",
        quantity: "1",
        unit_cost: "100",
        purchase_cost: "100",
        task_id: null,
      } as never;
      renderTable({ costLines: [globalLine], estimateTaskRows });

      const rows = rowTexts();
      const orphanTaskIndex = rows.findIndex((text) => text.includes("Sous-tâche sans jumeau"));
      const globalHeaderIndex = rows.findIndex((text) => text.includes("Lignes globales"));
      const lineIndex = rows.findIndex((text) => text.includes("Frais généraux"));

      expect(globalHeaderIndex).toBeGreaterThan(orphanTaskIndex);
      expect(lineIndex).toBe(globalHeaderIndex + 1);
    });
  });

  // E12-04/#276: the "Tâche" selector, shown when a cost line row is being edited, and the
  // read-only attached-task name shown otherwise.
  describe("task attachment selector (E12-04)", () => {
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
        parent_task_id: null,
        position: 2,
        task_name: "Sous-tâche sans jumeau",
        outline_number: "2",
        outline_level: 0,
        is_milestone: false,
      },
    ] as never;

    it("displays the attached task's name when the line is not being edited", () => {
      const attachedLine = {
        id: 1,
        accounting_code: "6011",
        label: "Achat licences",
        quantity: "2.00",
        unit_cost: "100.00",
        purchase_cost: "200.00",
        task_id: 42,
      } as never;
      renderTable({ costLines: [attachedLine], estimateTaskRows, editingLineId: null });

      expect(screen.getByText("Terrassement")).toBeInTheDocument();
    });

    it("displays a placeholder for a line with no attached task when not editing", () => {
      renderTable({ costLines: [line], estimateTaskRows, editingLineId: null });

      expect(screen.getAllByText("-").length).toBeGreaterThan(0);
    });

    it("offers every attachable task (task_id set) and excludes a task row with no task_id", () => {
      renderTable({ estimateTaskRows, editingLineId: 1 });

      expect(screen.getByRole("option", { name: "Terrassement" })).toBeInTheDocument();
      expect(screen.queryByRole("option", { name: "Sous-tâche sans jumeau" })).not.toBeInTheDocument();
    });

    it("reports a change to the edited line's task attachment", () => {
      const onEditTaskIdChange = vi.fn();
      renderTable({ estimateTaskRows, editingLineId: 1, onEditTaskIdChange });

      fireEvent.change(screen.getByLabelText("Tâche de Achat licences"), { target: { value: "42" } });

      expect(onEditTaskIdChange).toHaveBeenCalledWith("42");
    });
  });

  // E12-05/#277: realigns the grid's column set on docs/devis-v0.1-specification.md's "Grille de
  // devis" target (Cpt, Dept, Type, Catégorie, Cat, Libellé, Qté, Heures, Taux horaire, Débours,
  // MO, Achat, PRU non chargé), plus Tâche/Date prévisionnelle/Action at their chosen positions.
  describe("target column set (E12-05)", () => {
    it("renders every target column, in the spec's order, plus Tâche and Date prévisionnelle at their chosen positions", () => {
      renderTable();

      const headerRow = screen.getAllByRole("row")[0];
      const headerTexts = Array.from(headerRow.querySelectorAll("th")).map((cell) => cell.textContent);

      expect(headerTexts).toEqual([
        "", // select-all checkbox column
        "Cpt",
        "Dept",
        "Type",
        "Catégorie",
        "Cat",
        "Libellé",
        "Tâche",
        "Qté",
        "Heures",
        "Taux horaire",
        "Débours",
        "Date prévisionnelle",
        "MO",
        "Achat",
        "PRU non chargé",
        "Action",
      ]);
    });

    // Regression test for the exact bug documented by this issue: the "Catégorie" column used to
    // display `accounting_code` (meant for "Cpt") instead of the category's own name.
    it("displays a non-labor line's category by its name, not its accounting_code or category_code", () => {
      const categoryLine = {
        id: 1,
        accounting_code: "6011",
        category_code: "CAT-01",
        cost_category_id: 99,
        label: "Achat licences",
        quantity: "2.00",
        unit_cost: "100.00",
        purchase_cost: "200.00",
      } as never;
      const category = {
        id: 99,
        name: "Fournitures informatiques",
        accounting_code: "6011",
        category_code: "CAT-01",
        cost_type_id: 1,
        is_active: true,
      } as never;
      renderTable({ costLines: [categoryLine], allCostCategories: [category] });

      expect(screen.getByText("Fournitures informatiques")).toBeInTheDocument();
      // "6011" (accounting_code) and "CAT-01" (category_code) are still legitimately shown in
      // their own "Cpt"/"Cat" columns -- what this regression test guards against is the
      // "Catégorie" column itself ever showing either of those codes instead of the name, so it
      // asserts on the count of matches rather than their absence.
      expect(screen.getAllByText("6011")).toHaveLength(1);
      expect(screen.getAllByText("CAT-01")).toHaveLength(1);
    });

    it("still displays the category's name when the category is inactive (includeInactive: true resolution)", () => {
      const categoryLine = {
        id: 1,
        accounting_code: "6011",
        category_code: "CAT-01",
        cost_category_id: 99,
        label: "Achat licences",
        quantity: "2.00",
        unit_cost: "100.00",
        purchase_cost: "200.00",
      } as never;
      const inactiveCategory = {
        id: 99,
        name: "Fournitures informatiques (obsolète)",
        accounting_code: "6011",
        category_code: "CAT-01",
        cost_type_id: 1,
        is_active: false,
      } as never;
      renderTable({ costLines: [categoryLine], allCostCategories: [inactiveCategory] });

      expect(screen.getByText("Fournitures informatiques (obsolète)")).toBeInTheDocument();
    });

    it("falls back to the category_code when the category can't be resolved at all", () => {
      const categoryLine = {
        id: 1,
        accounting_code: "6011",
        category_code: "CAT-01",
        cost_category_id: 404,
        label: "Achat licences",
        quantity: "2.00",
        unit_cost: "100.00",
        purchase_cost: "200.00",
      } as never;
      renderTable({ costLines: [categoryLine], allCostCategories: [] });

      // Both the "Catégorie" (falling back) and "Cat" columns show "CAT-01" here.
      expect(screen.getAllByText("CAT-01")).toHaveLength(2);
    });

    it("shows a non-labor line's PRU non chargé equal to purchase_cost (Achat)", () => {
      const costLine = {
        id: 1,
        accounting_code: "6011",
        category_code: "CAT-01",
        cost_category_id: 99,
        label: "Achat licences",
        quantity: "2.00",
        unit_cost: "100.00",
        purchase_cost: "321.50",
      } as never;
      renderTable({ costLines: [costLine], allCostCategories: [] });

      // Located via the line's own label rather than a fixed row index -- with no
      // estimateTaskRows, this line falls into the "Lignes globales" section, which adds its own
      // header row ahead of the line's own row (see buildEstimateGridEntries).
      const dataRow = screen.getByText("Achat licences").closest("tr");
      const cellTexts = Array.from(dataRow?.querySelectorAll("td") ?? []).map((cell) => cell.textContent);

      expect(cellTexts.filter((text) => text === "321.50")).toHaveLength(2);
    });

    it("leaves Dept/Heures/Taux horaire/MO empty for a displayed line", () => {
      renderTable();

      const dataRow = screen.getByText("Achat licences").closest("tr");
      const cellTexts = Array.from(dataRow?.querySelectorAll("td") ?? []).map((cell) => cell.textContent);

      // Dept, Heures, Taux horaire, MO all render as "-" (this table's existing empty-cell
      // convention) -- at least 4 dashes must be present among this row's cells.
      expect(cellTexts.filter((text) => text === "-").length).toBeGreaterThanOrEqual(4);
    });
  });
});
