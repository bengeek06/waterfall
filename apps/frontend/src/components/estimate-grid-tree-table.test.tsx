import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EstimateCostLine, EstimateRoleAssignment, EstimateTaskRow } from "@/lib/backend";
import { EstimateGridTreeTable, type EstimateGridTreeTableProps } from "./estimate-grid-tree-table";

function makeTaskRow(overrides: Partial<EstimateTaskRow> = {}): EstimateTaskRow {
  return {
    id: 1,
    estimate_id: 1,
    task_id: 1,
    task_uid: 1,
    row_number: 1,
    parent_task_id: null,
    position: 1,
    task_name: "Terrassement",
    is_milestone: false,
    ...overrides,
  };
}

function makeLine(overrides: Partial<EstimateCostLine> = {}): EstimateCostLine {
  return {
    id: 1,
    estimate_id: 1,
    task_id: null,
    cost_type_id: 1,
    cost_category_id: 1,
    accounting_code: "6011",
    label: "Ligne",
    quantity: 1,
    unit_cost: 1,
    purchase_cost: 1,
    uid: -1,
    parent_uid: null,
    position: 1,
    row_number: 2,
    ...overrides,
  } as EstimateCostLine;
}

function makeAssignment(overrides: Partial<EstimateRoleAssignment> = {}): EstimateRoleAssignment {
  return {
    id: 1,
    estimate_id: 1,
    task_id: null,
    role_id: 1,
    role_code: "DEV",
    role_name: "Développeur",
    cost_category_id: 1,
    accounting_code: "6410",
    quantity: 1,
    hours: 8,
    uid: -2,
    parent_uid: null,
    position: 1,
    row_number: 3,
    ...overrides,
  } as EstimateRoleAssignment;
}

function renderTable(overrides: Partial<EstimateGridTreeTableProps> = {}) {
  const props: EstimateGridTreeTableProps = {
    taskRows: [],
    costLines: [],
    roleAssignments: [],
    versionKey: 1,
    canEditEstimate: true,
    mutationBusy: false,
    costCategories: [],
    allCostCategories: [],
    resourceNodes: [],
    resourceRoles: [],
    costRates: [],
    planningTasks: [],
    onMove: vi.fn(),
    onRenameTask: vi.fn().mockResolvedValue(true),
    onUpdateCostLine: vi.fn().mockResolvedValue(true),
    onUpdateRoleAssignment: vi.fn().mockResolvedValue(true),
    selectedCostLineIds: new Set(),
    onSelectedCostLineIdsChange: vi.fn(),
    bulkAssignBusy: false,
    onOpenMilestoneDialog: vi.fn(),
    milestoneTaskIds: new Set(),
    onRequestDeleteCostLine: vi.fn(),
    onRequestDeleteRoleAssignment: vi.fn(),
    onAddRoleAssignmentForRow: vi.fn(),
    ...overrides,
  };
  return { ...render(<EstimateGridTreeTable {...props} />), props };
}

describe("EstimateGridTreeTable", () => {
  afterEach(() => cleanup());

  it("never shows a 'Sauver' button on this grid -- every cell auto-saves on blur", () => {
    renderTable({
      taskRows: [makeTaskRow()],
      costLines: [makeLine({ parent_uid: 1 })],
      roleAssignments: [makeAssignment({ parent_uid: 1 })],
    });

    expect(screen.queryByRole("button", { name: /Sauver/i })).not.toBeInTheDocument();
  });

  // Critique review finding on #292: the rename must be sent with the row's `task_uid` (the
  // project-scoped business identifier the backend's rename endpoint resolves against), never
  // `task_id` (this tree's own shared `uid`, an `MsTask.id` global PK) -- `task_id: 7` and
  // `task_uid: 77` are deliberately different values here so a regression back to `row.uid`
  // would fail this assertion instead of passing by coincidence.
  it("renames a task by committing the Libellé field on blur, using the row's task_uid (not task_id)", () => {
    const onRenameTask = vi.fn().mockResolvedValue(true);
    renderTable({ taskRows: [makeTaskRow({ task_id: 7, task_uid: 77, row_number: 1 })], onRenameTask });

    const input = screen.getByLabelText("Libellé de Terrassement");
    fireEvent.change(input, { target: { value: "Terrassement lot 3" } });
    fireEvent.blur(input);

    expect(onRenameTask).toHaveBeenCalledWith(77, "Terrassement lot 3");
  });

  it("does not render the Libellé field as editable, and shows an explanatory title, for a task row with no task_uid", () => {
    const onRenameTask = vi.fn();
    renderTable({ taskRows: [makeTaskRow({ task_id: 7, task_uid: null, row_number: 1 })], onRenameTask });

    expect(screen.queryByLabelText("Libellé de Terrassement")).not.toBeInTheDocument();
    const label = screen.getByText("Terrassement");
    expect(label).toHaveAttribute(
      "title",
      "Cette tâche n'a pas d'identifiant projet valide et ne peut pas être renommée depuis le devis.",
    );
  });

  it("does not call onRenameTask when the label is blurred unchanged", () => {
    const onRenameTask = vi.fn().mockResolvedValue(true);
    renderTable({ taskRows: [makeTaskRow({ task_id: 7 })], onRenameTask });

    const input = screen.getByLabelText("Libellé de Terrassement");
    fireEvent.focus(input);
    fireEvent.blur(input);

    expect(onRenameTask).not.toHaveBeenCalled();
  });

  it("commits a cost line's Débours field on blur", () => {
    const onUpdateCostLine = vi.fn().mockResolvedValue(true);
    const line = makeLine({ id: 55, label: "Fourniture", unit_cost: 10 });
    renderTable({ costLines: [line], onUpdateCostLine });

    const input = screen.getByLabelText("Débours de Fourniture");
    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.blur(input);

    expect(onUpdateCostLine).toHaveBeenCalledWith(55, { unit_cost: 25 });
  });

  it("commits a role assignment's Heures field on blur, independently from Qté", () => {
    const onUpdateRoleAssignment = vi.fn().mockResolvedValue(true);
    const assignment = makeAssignment({ id: 77, hours: 8 });
    renderTable({ roleAssignments: [assignment], onUpdateRoleAssignment });

    const input = screen.getByLabelText("Heures de Développeur");
    fireEvent.change(input, { target: { value: "4" } });
    fireEvent.blur(input);

    expect(onUpdateRoleAssignment).toHaveBeenCalledWith(77, { hours: 4 });
  });

  it("shows a summary task's Taux horaire cell as empty ('-') and its Qté/Heures/Débours/PRU as the sum of its children", () => {
    const task = makeTaskRow({ task_id: 1, row_number: 1 });
    const line = makeLine({ id: 100, parent_uid: 1, row_number: 2, quantity: 2, unit_cost: 5, purchase_cost: 10 });
    const assignment = makeAssignment({ id: 200, parent_uid: 1, row_number: 3, quantity: 1, hours: 4 });
    renderTable({ taskRows: [task], costLines: [line], roleAssignments: [assignment], canEditEstimate: false });

    const taskRow = screen.getByText("Terrassement").closest("tr")!;
    const cells = taskRow.querySelectorAll("td");
    // Numéro, Libellé, Type, Dpt1, Dpt2, Rôle, Qté, Heures, Débours, Taux horaire, PRU
    expect(cells[6]).toHaveTextContent("3"); // Qté = 2 (line) + 1 (labor)
    expect(cells[7]).toHaveTextContent("4"); // Heures = 4 (labor only)
    expect(cells[8]).toHaveTextContent("5"); // Débours = unit_cost sum (line only)
    expect(cells[9]).toHaveTextContent("-"); // Taux horaire always empty on a summary task
    expect(cells[10]).toHaveTextContent("10"); // PRU = 10 (line purchase_cost) + 0 (no rate configured)
  });

  // Haute review finding on #292: `mutationBusy` is a single shared lock across every mutation of
  // this grid, but until now only the toolbar's buttons reacted to it -- a cell blurred while a
  // *different* row's mutation is still in flight would silently no-op (see
  // use-estimate-grid-drafts.ts's own `if (mutationBusy || ...) return;` guards) without ever
  // being retried, discarding the edit with no feedback. Disabling every editable cell while
  // `mutationBusy` is true (mirroring the toolbar's own buttons) prevents that edit from ever
  // being attempted in the first place.
  it("disables every editable cell while a mutation is in flight, so a second edit is never silently dropped", () => {
    const line1 = makeLine({ id: 1, label: "Ligne 1", uid: -1, row_number: 1 });
    const line2 = makeLine({ id: 2, label: "Ligne 2", uid: -2, row_number: 2 });
    const onUpdateCostLine = vi.fn().mockReturnValue(new Promise(() => {}));
    const { rerender, props } = renderTable({ costLines: [line1, line2], onUpdateCostLine });

    const firstInput = screen.getByLabelText("Libellé de Ligne 1");
    fireEvent.change(firstInput, { target: { value: "Ligne 1 modifiée" } });
    fireEvent.blur(firstInput);

    // Mirrors the real app: the page container reacts to the now-in-flight mutation by setting
    // estimateBusy (mutationBusy here) before the promise above ever resolves.
    rerender(<EstimateGridTreeTable {...props} mutationBusy />);

    expect(screen.getByLabelText("Libellé de Ligne 2")).toBeDisabled();
    expect(screen.getByLabelText("Qté de Ligne 2")).toBeDisabled();
    expect(screen.getByLabelText("Débours de Ligne 2")).toBeDisabled();
    expect(screen.getByLabelText("Type de Ligne 2")).toBeDisabled();
  });

  it("indents the selected cost line via the toolbar, dispatching the computed move command", () => {
    const onMove = vi.fn();
    const task = makeTaskRow({ task_id: 1, row_number: 1 });
    const line = makeLine({ id: 100, parent_uid: null, row_number: 2 });
    renderTable({ taskRows: [task], costLines: [line], onMove });

    fireEvent.click(screen.getByLabelText("Libellé de Ligne").closest("tr")!);
    fireEvent.click(screen.getByRole("button", { name: "Indenter" }));

    expect(onMove).toHaveBeenCalledWith({ node_uids: [-1], target_parent_uid: 1, position: 1 });
  });
});

// E12-11/#293: right-click context menu -- "Ajouter ressource" on a labor row, "Gabarit de
// jalons" on a non-MO cost-line row (replacing that action's former dedicated button), never
// both on the same row, never any menu at all on a task row.
describe("EstimateGridTreeTable context menu (E12-11/#293)", () => {
  afterEach(() => cleanup());

  it("shows only 'Ajouter ressource' (never 'Gabarit de jalons') on a labor row, and calls onAddRoleAssignmentForRow with that row's own assignment", () => {
    const onAddRoleAssignmentForRow = vi.fn();
    const assignment = makeAssignment({ id: 5, task_id: 42, parent_uid: 42, uid: -9, role_name: "Développeur" });
    renderTable({ roleAssignments: [assignment], onAddRoleAssignmentForRow });

    const row = screen.getByLabelText("Heures de Développeur").closest("tr")!;
    fireEvent.contextMenu(row);

    expect(screen.getByRole("menuitem", { name: "Ajouter ressource" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Gabarit de jalons" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "Ajouter ressource" }));

    // The exact same assignment object the row itself renders -- never a value copied/derived
    // from it (see openRoleAssignmentDialogForRow in use-estimate-cost-lines.ts, which is the
    // one place responsible for turning this into an entirely blank draft attached to the same
    // task, never a duplicate of the origin row's own Role/Qté/Heures).
    expect(onAddRoleAssignmentForRow).toHaveBeenCalledWith(assignment);
  });

  it("shows only 'Gabarit de jalons' (never 'Ajouter ressource') on a non-MO cost-line row, and calls the exact same onOpenMilestoneDialog prop the former dedicated button used", () => {
    const onOpenMilestoneDialog = vi.fn();
    const line = makeLine({ id: 7, label: "Fourniture" });
    renderTable({ costLines: [line], onOpenMilestoneDialog });

    const row = screen.getByLabelText("Libellé de Fourniture").closest("tr")!;
    fireEvent.contextMenu(row);

    expect(screen.getByRole("menuitem", { name: "Gabarit de jalons" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Ajouter ressource" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "Gabarit de jalons" }));

    expect(onOpenMilestoneDialog).toHaveBeenCalledWith(line);
  });

  it("never shows a context menu on a task row", () => {
    const task = makeTaskRow({ task_id: 1, row_number: 1 });
    renderTable({ taskRows: [task] });

    const row = screen.getByLabelText("Libellé de Terrassement").closest("tr")!;
    fireEvent.contextMenu(row);

    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  // E12-07's own root-labor-row case: a role assignment with no task ancestor (`task_id: null`)
  // can never be duplicated -- EstimateRoleAssignmentCreate.task_id is required, so there is no
  // payload this action could ever submit successfully for it.
  it("disables 'Ajouter ressource' for a root labor row with no task ancestor", () => {
    const onAddRoleAssignmentForRow = vi.fn();
    const assignment = makeAssignment({ id: 5, task_id: null, parent_uid: null, uid: -9, role_name: "Développeur" });
    renderTable({ roleAssignments: [assignment], onAddRoleAssignmentForRow });

    const row = screen.getByLabelText("Heures de Développeur").closest("tr")!;
    fireEvent.contextMenu(row);

    const item = screen.getByRole("menuitem", { name: "Ajouter ressource" });
    expect(item).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);
    expect(onAddRoleAssignmentForRow).not.toHaveBeenCalled();
  });

  // Same gating the former dedicated button applied (E6-07/#68 review finding): a cost line
  // attached to a milestone task can never accept the milestone-template action.
  it("disables 'Gabarit de jalons' for a cost line attached to a milestone task", () => {
    const onOpenMilestoneDialog = vi.fn();
    const line = makeLine({ id: 7, label: "Livraison", task_id: 42 });
    renderTable({ costLines: [line], onOpenMilestoneDialog, milestoneTaskIds: new Set([42]) });

    const row = screen.getByLabelText("Libellé de Livraison").closest("tr")!;
    fireEvent.contextMenu(row);

    const item = screen.getByRole("menuitem", { name: "Gabarit de jalons" });
    expect(item).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);
    expect(onOpenMilestoneDialog).not.toHaveBeenCalled();
  });

  it("shows no context menu at all when the estimate is not editable (canEditEstimate: false)", () => {
    const line = makeLine({ id: 7, label: "Fourniture" });
    renderTable({ costLines: [line], canEditEstimate: false });

    const row = screen.getByText("Fourniture").closest("tr")!;
    fireEvent.contextMenu(row);

    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });
});
