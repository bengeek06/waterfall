import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CostCategory,
  CostRate,
  ResourceNode,
  ResourceRole,
  RevisionNode,
} from "@/lib/backend";
import { EstimateGridTreeTable, type EstimateGridTreeTableProps } from "./estimate-grid-tree-table";

// --------------------------------------------------------------------------------------------
// Fixtures: nodes of **one** tree. A cost line is not a second list keyed by a negative uid any
// more, it is a node with a cost facet -- which is what the whole of #337 is about.
// --------------------------------------------------------------------------------------------

function taskNode(
  nodeId: number,
  options: {
    parentId?: number | null;
    position?: number;
    level?: number;
    rowNumber?: number;
    name?: string;
    milestone?: boolean;
    externalUid?: number | null;
    startAt?: string | null;
    finishAt?: string | null;
  } = {},
): RevisionNode {
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "task",
    parent_id: options.parentId ?? null,
    position: options.position ?? 1,
    // Deliberately unrelated to node_id, so an assertion on the displayed identifier cannot pass
    // by accident against a leftover technical id (E9).
    row_number: options.rowNumber ?? nodeId + 90,
    level: options.level ?? 1,
    external_uid: options.externalUid ?? null,
    description: null,
    planning: {
      name: options.name ?? `T${nodeId}`,
      calendar_id: null,
      calendar_source: null,
      is_milestone: options.milestone ?? false,
      duration_minutes: 480,
      duration_format: null,
      start_at: options.startAt ?? null,
      // Both bounds, always: a bearing task dated at one end only prices nothing at all (the
      // engine's `_bearing_years` answers `None`), and no test here is about that case -- it is
      // asserted where the rule lives, in `revision-cost-grid.test.ts`.
      finish_at: options.finishAt ?? null,
      work_minutes: null,
      percent_complete: 0,
      is_manual: true,
    },
    cost: null,
    predecessors: [],
  };
}

type CostNodeOptions = {
  parentId?: number | null;
  position?: number;
  level?: number;
  rowNumber?: number;
  label?: string;
  nature?: "labor" | "non_labor";
  quantity?: string;
  hours?: string | null;
  unitCost?: string | null;
  roleId?: number | null;
  categoryId?: number | null;
  bearingNodeId?: number | null;
  // The attributes that belong to the line rather than to its nature, and which a change of
  // nature must therefore carry over (M-3 of #337's review).
  costCodeId?: number | null;
  comment?: string | null;
  description?: string | null;
  plannedDate?: string | null;
  supplyStatus?: "planned" | "ordered" | "received" | "cancelled" | null;
};

/** The cost facet of a fixture line, in its own function so `costNode` stays readable. */
function costFacet(
  nodeId: number,
  parentId: number | null,
  options: CostNodeOptions,
): NonNullable<RevisionNode["cost"]> {
  const {
    nature = "non_labor",
    label = `L${nodeId}`,
    quantity = "2.00",
    hours = "10.00",
    unitCost = "50.00",
    roleId = 7,
    categoryId = 4,
    bearingNodeId = parentId,
    costCodeId = null,
    comment = null,
    plannedDate = null,
    supplyStatus = null,
  } = options;
  // The two natures carry disjoint attribute sets (INV-19 / INV-20), so the fixture builds one or
  // the other outright rather than nulling six fields inline -- a facet shaped like neither is not
  // a case any of these tests should be able to express by accident.
  const shape =
    nature === "labor"
      ? { role_id: roleId, hours, cost_type_id: null, cost_category_id: null, unit_cost: null }
      : { role_id: null, hours: null, cost_type_id: 1, cost_category_id: categoryId, unit_cost: unitCost };
  return {
    nature,
    label,
    quantity,
    ...shape,
    supply_status: supplyStatus,
    planned_date: plannedDate,
    cost_code_id: costCodeId,
    comment,
    bearing_task_node_id: bearingNodeId,
    bearing_task_name: null,
  };
}

function costNode(nodeId: number, options: CostNodeOptions = {}): RevisionNode {
  const parentId = options.parentId ?? null;
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "cost",
    parent_id: parentId,
    position: options.position ?? 1,
    row_number: options.rowNumber ?? nodeId + 90,
    level: options.level ?? 1,
    external_uid: null,
    description: options.description ?? null,
    planning: null,
    cost: costFacet(nodeId, parentId, options),
    predecessors: [],
  };
}

const resourceNodes: ResourceNode[] = [
  { id: 1, parent_id: null, code: "DIR", name: "Direction", is_active: true, created_at: "", updated_at: "" } as never,
  { id: 2, parent_id: 1, code: "ETU", name: "Études", is_active: true, created_at: "", updated_at: "" } as never,
  { id: 3, parent_id: 1, code: "TRV", name: "Travaux", is_active: true, created_at: "", updated_at: "" } as never,
];

const resourceRoles: ResourceRole[] = [
  { id: 7, node_id: 2, cost_category_id: 40, name: "Ingénieur" } as never,
  { id: 8, node_id: 3, cost_category_id: 41, name: "Chef de chantier" } as never,
];

const costCategories: CostCategory[] = [
  { id: 4, cost_type_id: 2, accounting_code: "604", category_code: null, name: "Fournitures" } as never,
  { id: 5, cost_type_id: 3, accounting_code: "605", category_code: null, name: "Sous-traitance" } as never,
];

const allCostCategories: CostCategory[] = [
  ...costCategories,
  { id: 40, cost_type_id: 1, accounting_code: "601", category_code: null, name: "Études" } as never,
  { id: 41, cost_type_id: 1, accounting_code: "602", category_code: null, name: "Chantier" } as never,
];

const costRates: CostRate[] = [
  { id: 1, cost_category_id: 40, year: 2031, hourly_rate: 100, currency_code: "EUR" } as never,
];

function gridProps(
  nodes: RevisionNode[],
  overrides: Partial<EstimateGridTreeTableProps> = {},
): EstimateGridTreeTableProps {
  return {
    nodes,
    revisionKey: 1,
    readOnly: false,
    mutationBusy: false,
    costCategories,
    allCostCategories,
    resourceNodes,
    resourceRoles,
    costRates,
    projectCostCodes: [],
    bulkCostCodeId: "",
    onBulkCostCodeIdChange: vi.fn(),
    bulkAssignBusy: false,
    ...overrides,
  };
}

function renderGrid(nodes: RevisionNode[], overrides: Partial<EstimateGridTreeTableProps> = {}) {
  return render(<EstimateGridTreeTable {...gridProps(nodes, overrides)} />);
}

/** The data rows, header excluded. */
function dataRows() {
  return screen.getAllByRole("row").slice(1);
}

function rowOf(accessibleName: string): HTMLElement {
  return screen.getByLabelText(accessibleName).closest("tr") as HTMLElement;
}

// --------------------------------------------------------------------------------------------
// Criterion 1 -- one tree, depth-first, a rank on every row
// --------------------------------------------------------------------------------------------

describe("the grid renders one tree", () => {
  afterEach(() => cleanup());

  it("renders tasks and cost lines as rows of the same tree, in the order the server sent them", () => {
    // No explicit row_number here: the fixture's default is deliberately unrelated to the node id
    // (nodeId + 90), so an assertion on the displayed identifier cannot pass against a leftover
    // technical id (E9).
    renderGrid([
      taskNode(1, { name: "Poste" }),
      taskNode(2, { name: "Lot", parentId: 1, level: 2 }),
      costNode(3, { parentId: 2, level: 3, label: "Béton" }),
      costNode(4, { parentId: 1, position: 2, level: 2, label: "Étude", nature: "labor" }),
    ]);

    const rows = dataRows();
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("91")).toBeInTheDocument();
    expect(within(rows[2]).getByText("93")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("1")).not.toBeInTheDocument();
    expect(rows[2]).toHaveAttribute("aria-level", "3");
    expect(rows[3]).toHaveAttribute("aria-level", "2");
  });

  it("numbers the rows of a project imported from MS Project the same way", () => {
    // An imported node is told apart by its external_uid; its row_number is still computed on read
    // and is the one and only identifier the grid shows.
    renderGrid([
      taskNode(1, { name: "Ouvrage", externalUid: 4212 }),
      costNode(2, { parentId: 1, level: 2, label: "Coffrage" }),
    ]);

    const rows = dataRows();
    expect(within(rows[0]).getByText("91")).toBeInTheDocument();
    expect(within(rows[1]).getByText("92")).toBeInTheDocument();
    // Neither the technical node id nor the MS Project uid is ever displayed.
    expect(screen.queryByText("4212")).not.toBeInTheDocument();
    expect(within(rows[0]).queryByText("1")).not.toBeInTheDocument();
  });

  it("shows an empty state when the revision holds no node", () => {
    renderGrid([]);

    expect(screen.getByText("Cette révision ne contient aucune ligne.")).toBeInTheDocument();
  });

  it("folds a branch and hides its descendants", () => {
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1 }),
      costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Béton" }),
    ]);

    expect(dataRows()).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Replier Poste" }));
    expect(dataRows()).toHaveLength(1);
  });

  it("totals a récapitulatif row over its whole subtree", () => {
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1, startAt: "2031-02-01T00:00:00Z", finishAt: "2031-06-01T00:00:00Z" }),
      costNode(2, {
        parentId: 1,
        level: 2,
        rowNumber: 2,
        label: "Étude",
        nature: "labor",
        quantity: "2.00",
        hours: "10.00",
        roleId: 7,
        bearingNodeId: 1,
      }),
      costNode(3, { parentId: 1, position: 2, level: 2, rowNumber: 3, label: "Béton", quantity: "3.00", unitCost: "50.00" }),
    ]);

    const summary = dataRows()[0];
    // 2 + 3 quantités, 10 heures, 50 de débours, et 2 x 10 x 100 + 3 x 50 de PRU.
    expect(within(summary).getByText("5")).toBeInTheDocument();
    expect(within(summary).getByText("10")).toBeInTheDocument();
    expect(within(summary).getByText(/2\s*150,00/)).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------------------------
// #380, devis half -- the treegrid semantics
// --------------------------------------------------------------------------------------------

describe("the grid's accessibility semantics", () => {
  afterEach(() => cleanup());

  it("declares itself a treegrid and states each row's level and expansion", () => {
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1 }),
      costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Béton" }),
    ]);

    expect(screen.getByRole("treegrid", { name: "Devis de la révision" })).toBeInTheDocument();
    const rows = dataRows();
    expect(rows[0]).toHaveAttribute("aria-level", "1");
    expect(rows[0]).toHaveAttribute("aria-expanded", "true");
    // Only a row that can actually be folded carries aria-expanded.
    expect(rows[1]).not.toHaveAttribute("aria-expanded");
    expect(within(rows[1]).getAllByRole("gridcell").length).toBe(11);
  });

  it("ranks a row among the very rows it renders, tasks and cost lines together", () => {
    // The trap #336 fell into: a posinset taken from the stored `position` next to a setsize
    // counted over a filtered set announces "2 sur 1". Here both come from one and the same set.
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1 }),
      costNode(2, { parentId: 1, position: 1, level: 2, rowNumber: 2, label: "Béton" }),
      taskNode(3, { name: "Lot", parentId: 1, position: 2, level: 2, rowNumber: 3 }),
    ]);

    const rows = dataRows();
    expect(rows[1]).toHaveAttribute("aria-posinset", "1");
    expect(rows[1]).toHaveAttribute("aria-setsize", "2");
    expect(rows[2]).toHaveAttribute("aria-posinset", "2");
    expect(rows[2]).toHaveAttribute("aria-setsize", "2");
  });

  it("gives the focused row a visible focus indicator that survives a table-row display", () => {
    renderGrid([taskNode(1, { name: "Poste", rowNumber: 1 })]);

    // An outline, not a ring: a box-shadow on `display: table-row` is unreliable across browsers.
    expect(dataRows()[0].className).toContain("focus-visible:outline-2");
  });

  // #335's lesson, and what #336 was caught missing at its first review: every focusable control
  // inside a row must stop its own keystrokes, or the row's keyboard handler swallows them and the
  // control cannot be operated (WCAG 2.1.1). This asserts the whole inventory of them at once.
  it("lets every in-row control keep its own keystrokes", () => {
    // Both branches of the Type column in one fixture: the MO row carries the Dpt/Rôle cascade and
    // the Heures field, the non-MO one carries the Catégorie select and the Débours field. Testing
    // only the MO branch would leave the two non-MO controls unguarded -- the exact shape of the
    // omission #336 was caught on.
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1 }),
      costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Étude", nature: "labor", roleId: 7 }),
      costNode(3, { parentId: 1, position: 2, level: 2, rowNumber: 3, label: "Béton", nature: "non_labor" }),
    ]);

    const laborRow = rowOf("Libellé de Étude");
    const nonLaborRow = rowOf("Libellé de Béton");
    const controls = [
      screen.getByRole("button", { name: "Replier Poste" }),
      screen.getByLabelText("Libellé de Étude"),
      screen.getByLabelText("Type de Étude"),
      screen.getByLabelText("Dpt 1er niveau de Étude"),
      screen.getByLabelText("Dpt 2eme niveau de Étude"),
      screen.getByLabelText("Rôle de Étude"),
      screen.getByLabelText("Qté de Étude"),
      screen.getByLabelText("Heures de Étude"),
      screen.getByLabelText("Catégorie de Béton"),
      screen.getByLabelText("Débours de Béton"),
    ];

    for (const control of controls) {
      fireEvent.keyDown(control, { key: " ", bubbles: true });
    }

    // Space on a row selects it. Reaching the row from any of those controls would mean the
    // control's own Space (type a space, open a select, press a button) was eaten instead.
    expect(laborRow).toHaveAttribute("aria-selected", "false");
    expect(nonLaborRow).toHaveAttribute("aria-selected", "false");
  });
});

// --------------------------------------------------------------------------------------------
// Criteria 2, 3 and 5 -- moves, from the devis, on the same tree
// --------------------------------------------------------------------------------------------

describe("moving rows from the devis grid", () => {
  afterEach(() => cleanup());

  it("moves a cost line under the preceding task, on the same endpoint the planning uses", () => {
    const onMove = vi.fn();
    renderGrid(
      [
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, { parentId: null, position: 2, level: 1, rowNumber: 2, label: "Béton" }),
      ],
      { onMove },
    );

    fireEvent.click(rowOf("Libellé de Béton"));
    fireEvent.click(screen.getByRole("button", { name: "Indenter" }));

    expect(onMove).toHaveBeenCalledWith("indent", [2]);
  });

  // Criterion 3, and the restriction E12 carried: a task row was not even selectable there.
  it("selects and moves a task row, which the devis grid never could before", () => {
    const onMove = vi.fn();
    renderGrid(
      [
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        taskNode(2, { name: "Lot", position: 2, rowNumber: 2 }),
      ],
      { onMove },
    );

    const row = rowOf("Libellé de Lot");
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("button", { name: "Monter" }));
    expect(onMove).toHaveBeenCalledWith("up", [2]);
  });

  // Criterion 5: a cost line outdented all the way out of its task becomes a project-wide cost.
  it("offers Désindenter on a nested cost line and dispatches it", () => {
    const onMove = vi.fn();
    renderGrid(
      [
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Béton" }),
      ],
      { onMove },
    );

    fireEvent.click(rowOf("Libellé de Béton"));
    const outdent = screen.getByRole("button", { name: "Désindenter" });
    expect(outdent).not.toBeDisabled();

    fireEvent.click(outdent);
    expect(onMove).toHaveBeenCalledWith("outdent", [2]);
  });

  it("stops offering Désindenter once the cost line has reached the root", () => {
    // The other half of criterion 5: the root is where the outdent ends, and the command says so
    // rather than sending a move the backend would refuse.
    renderGrid(
      [taskNode(1, { name: "Poste", rowNumber: 1 }), costNode(2, { position: 2, rowNumber: 2, label: "Béton" })],
      { onMove: vi.fn() },
    );

    fireEvent.click(rowOf("Libellé de Béton"));
    expect(screen.getByRole("button", { name: "Désindenter" })).toBeDisabled();
  });

  it("refuses to indent a task under a cost line, and says why (INV-14)", () => {
    const onMove = vi.fn();
    renderGrid(
      [
        costNode(1, { position: 1, rowNumber: 1, label: "Béton" }),
        taskNode(2, { name: "Lot", position: 2, rowNumber: 2 }),
      ],
      { onMove },
    );

    fireEvent.click(rowOf("Libellé de Lot"));

    expect(screen.getByRole("button", { name: "Indenter" })).toBeDisabled();
    expect(
      screen.getByText(/un chiffrage ne porte aucune tâche/i),
    ).toBeInTheDocument();
  });

  it("deletes the selection through the shared confirmation, naming what goes with it", async () => {
    const onDeleteNodes = vi.fn();
    renderGrid([taskNode(1, { name: "Poste" }), costNode(2, { parentId: 1, level: 2, label: "Béton" })], {
      onDeleteNodes,
    });

    fireEvent.click(rowOf("Libellé de Béton"));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));

    const dialog = await screen.findByRole("alertdialog");
    // The number the user reads (92 here), never the node id.
    expect(within(dialog).getByText(/92 - Béton/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Supprimer" }));

    expect(onDeleteNodes).toHaveBeenCalledWith([2]);
  });
});

// --------------------------------------------------------------------------------------------
// Criterion 4 (#315) -- the Type column branches, and the cascade is inline
// --------------------------------------------------------------------------------------------

describe("the Type column and its two branches (#315)", () => {
  afterEach(() => cleanup());

  function laborTree() {
    return [
      taskNode(1, { name: "Poste", rowNumber: 1, startAt: "2031-02-01T00:00:00Z", finishAt: "2031-06-01T00:00:00Z" }),
      costNode(2, {
        parentId: 1,
        level: 2,
        rowNumber: 2,
        label: "Étude",
        nature: "labor",
        roleId: 7,
        bearingNodeId: 1,
      }),
    ];
  }

  it("offers MO / non-MO on a cost line, and nothing of the sort on a task row", () => {
    renderGrid(laborTree());

    const select = screen.getByLabelText("Type de Étude");
    expect(within(select).getByRole("option", { name: "MO" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "non-MO" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Type de Poste")).not.toBeInTheDocument();
    // A task carrying only cost lines is not a récapitulatif: the tree says what a row is.
    expect(within(dataRows()[0]).getByText("Tâche")).toBeInTheDocument();
  });

  it("shows an MO line's department, role and derived accounting category in the grid's own cells", () => {
    renderGrid(laborTree());

    expect(screen.getByLabelText("Dpt 1er niveau de Étude")).toHaveValue("1");
    expect(screen.getByLabelText("Dpt 2eme niveau de Étude")).toHaveValue("2");
    expect(screen.getByLabelText("Rôle de Étude")).toHaveValue("7");
    // Derived from the role, never stored on the facet (INV-19).
    expect(screen.getByText("Catégorie : Études")).toBeInTheDocument();
  });

  it("restricts Dpt 2eme niveau to the children of the chosen Dpt 1er niveau, and the roles to that", () => {
    renderGrid(laborTree());

    fireEvent.change(screen.getByLabelText("Dpt 1er niveau de Étude"), { target: { value: "1" } });
    const dept2 = screen.getByLabelText("Dpt 2eme niveau de Étude");
    expect(within(dept2).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Sélectionner",
      "Études",
      "Travaux",
    ]);

    fireEvent.change(dept2, { target: { value: "3" } });
    const role = screen.getByLabelText("Rôle de Étude");
    expect(within(role).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Sélectionner",
      "Chef de chantier",
    ]);
  });

  it("changes the role of an existing MO line in place, without deleting and recreating it", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    const onSwitchNature = vi.fn();
    renderGrid(laborTree(), { onUpdateCost, onSwitchNature });

    fireEvent.change(screen.getByLabelText("Dpt 2eme niveau de Étude"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Rôle de Étude"), { target: { value: "8" } });

    await waitFor(() => expect(onUpdateCost).toHaveBeenCalledWith(2, { role_id: 8 }));
    expect(onSwitchNature).not.toHaveBeenCalled();
  });

  it("offers the flat non-MO category list on a non-MO line, and never a category on an MO one", () => {
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton", nature: "non_labor", categoryId: 4 })]);

    const category = screen.getByLabelText("Catégorie de Béton");
    expect(category).toHaveValue("4");
    expect(within(category).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Sélectionner une catégorie",
      "Fournitures",
      "Sous-traitance",
    ]);
  });

  it("writes the category and the cost type together when a non-MO line is recategorised", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton", categoryId: 4 })], { onUpdateCost });

    fireEvent.change(screen.getByLabelText("Catégorie de Béton"), { target: { value: "5" } });

    await waitFor(() =>
      expect(onUpdateCost).toHaveBeenCalledWith(2, { cost_category_id: 5, cost_type_id: 3 }),
    );
  });

  // The amendment's second point, and #315's headline gap: switching nature is a change of shape.
  it("reveals the inline cascade when a non-MO line is switched to MO, and only writes once a role is chosen", async () => {
    const onSwitchNature = vi.fn().mockResolvedValue(true);
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton", quantity: "3.00" })], {
      onSwitchNature,
      onUpdateCost,
    });

    expect(screen.queryByLabelText("Dpt 1er niveau de Béton")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Type de Béton"), { target: { value: "labor" } });

    expect(screen.getByText("Choisis un rôle pour basculer cette ligne en MO.")).toBeInTheDocument();
    expect(screen.getByLabelText("Dpt 1er niveau de Béton")).toBeInTheDocument();
    // Nothing has been written yet: the line is still non-MO until its role is known.
    expect(onSwitchNature).not.toHaveBeenCalled();
    expect(onUpdateCost).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Dpt 1er niveau de Béton"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Dpt 2eme niveau de Béton"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Rôle de Béton"), { target: { value: "7" } });

    await waitFor(() =>
      expect(onSwitchNature).toHaveBeenCalledWith(
        expect.objectContaining({ node_id: 2 }),
        {
          nature: "labor",
          label: "Béton",
          quantity: 3,
          role_id: 7,
          hours: 0,
          // The nature-agnostic attributes travel with the line, empty here (see the two tests
          // below for a line that actually carries them).
          cost_code_id: null,
          comment: null,
          description: null,
          planned_date: null,
        },
      ),
    );
    // INV-19: not one of the non-MO attributes travels with it.
    const payload = onSwitchNature.mock.calls[0][1];
    expect(payload).not.toHaveProperty("cost_category_id");
    expect(payload).not.toHaveProperty("cost_type_id");
    expect(payload).not.toHaveProperty("unit_cost");
  });

  it("shows the derived category of the role being picked while the switch to MO is pending", () => {
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton" })], { onSwitchNature: vi.fn() });

    fireEvent.change(screen.getByLabelText("Type de Béton"), { target: { value: "labor" } });
    expect(screen.getByText("Catégorie : -")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Dpt 1er niveau de Béton"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Dpt 2eme niveau de Béton"), { target: { value: "3" } });
    expect(screen.getByText("Catégorie : -")).toBeInTheDocument();
  });

  it("reveals the flat category list when an MO line is switched to non-MO, and writes the whole new shape", async () => {
    const onSwitchNature = vi.fn().mockResolvedValue(true);
    renderGrid(laborTree(), { onSwitchNature });

    fireEvent.change(screen.getByLabelText("Type de Étude"), { target: { value: "non_labor" } });

    expect(screen.getByText("Choisis une catégorie pour basculer cette ligne en non-MO.")).toBeInTheDocument();
    const category = screen.getByLabelText("Catégorie de Étude");
    expect(category).toHaveValue("");
    expect(screen.queryByLabelText("Rôle de Étude")).not.toBeInTheDocument();
    expect(onSwitchNature).not.toHaveBeenCalled();

    fireEvent.change(category, { target: { value: "5" } });

    await waitFor(() =>
      expect(onSwitchNature).toHaveBeenCalledWith(expect.objectContaining({ node_id: 2 }), {
        nature: "non_labor",
        label: "Étude",
        quantity: 2,
        cost_type_id: 3,
        cost_category_id: 5,
        unit_cost: 0,
        cost_code_id: null,
        comment: null,
        description: null,
        planned_date: null,
      }),
    );
    // INV-20, symmetrically: no role and no hours travel with it.
    const payload = onSwitchNature.mock.calls[0][1];
    expect(payload).not.toHaveProperty("role_id");
    expect(payload).not.toHaveProperty("hours");
  });

  // M-3 of #337's review: the replacement is a *new* node, so every attribute the payload does not
  // name is gone. Four of them are not part of the INV-19 <-> INV-20 split at all, and two of
  // those (planned_date, comment) have no editor anywhere in this screen -- losing them here would
  // be irreversible through the interface. #386 relocates them into one.
  it("carries the line's nature-agnostic attributes into the MO replacement, minus the one INV-19 forbids", async () => {
    const onSwitchNature = vi.fn().mockResolvedValue(true);
    renderGrid(
      [
        costNode(2, {
          rowNumber: 2,
          label: "Béton",
          costCodeId: 31,
          comment: "Prix relevé en mars",
          description: "Béton de propreté",
          plannedDate: "2032-04-15",
          supplyStatus: "ordered",
        }),
      ],
      { onSwitchNature },
    );

    fireEvent.change(screen.getByLabelText("Type de Béton"), { target: { value: "labor" } });
    fireEvent.change(screen.getByLabelText("Dpt 1er niveau de Béton"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Dpt 2eme niveau de Béton"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Rôle de Béton"), { target: { value: "7" } });

    await waitFor(() => expect(onSwitchNature).toHaveBeenCalled());
    const payload = onSwitchNature.mock.calls[0][1];
    expect(payload.cost_code_id).toBe(31);
    expect(payload.comment).toBe("Prix relevé en mars");
    expect(payload.description).toBe("Béton de propreté");
    expect(payload.planned_date).toBe("2032-04-15");
    // INV-19 forbids a supply status on a labour facet: this one is dropped rather than carried,
    // and the domain would refuse the creation outright if it were not.
    expect(payload).not.toHaveProperty("supply_status");
  });

  it("carries them into the non-MO replacement too, in the other direction", async () => {
    const onSwitchNature = vi.fn().mockResolvedValue(true);
    renderGrid(
      [
        costNode(2, {
          rowNumber: 2,
          label: "Étude",
          nature: "labor",
          roleId: 7,
          costCodeId: 31,
          comment: "Chiffré au forfait",
          description: "Étude de sol",
          plannedDate: "2032-04-15",
        }),
      ],
      { onSwitchNature },
    );

    fireEvent.change(screen.getByLabelText("Type de Étude"), { target: { value: "non_labor" } });
    fireEvent.change(screen.getByLabelText("Catégorie de Étude"), { target: { value: "5" } });

    await waitFor(() => expect(onSwitchNature).toHaveBeenCalled());
    const payload = onSwitchNature.mock.calls[0][1];
    expect(payload.cost_code_id).toBe(31);
    expect(payload.comment).toBe("Chiffré au forfait");
    expect(payload.description).toBe("Étude de sol");
    expect(payload.planned_date).toBe("2032-04-15");
  });

  // M-4: the rule is known client-side, on the row itself, so the command is withheld instead of
  // walking the user through four interactions before refusing at the last one. The motif is
  // asserted as *shown text*, not as a `title`: a disabled `<select>` never takes focus, so a
  // tooltip would only ever reach a mouse.
  it("withholds the Type command on a line carrying sub-lines, and shows why", () => {
    renderGrid(
      [
        costNode(2, { rowNumber: 2, label: "Béton" }),
        costNode(3, { parentId: 2, level: 2, rowNumber: 3, label: "Coffrage" }),
      ],
      { onSwitchNature: vi.fn() },
    );

    const type = screen.getByLabelText("Type de Béton");
    expect(type).toBeDisabled();
    expect(
      screen.getByText(
        "Cette ligne porte des sous-lignes : changer sa nature la remplacerait et supprimerait son sous-arbre.",
      ),
    ).toBeInTheDocument();
    // The leaf underneath is untouched by the rule.
    expect(screen.getByLabelText("Type de Coffrage")).not.toBeDisabled();
  });

  // M-6: onDept1Change/onDept2Change blank the pending role, but the Taux horaire and PRU cells
  // read the role the line still *stores*. A cascade left open therefore showed a row with no role
  // and a price computed from one, until the revision changed.
  it("returns a row to its stored role when the cascade is left without choosing one", () => {
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1, startAt: "2031-02-01T00:00:00Z", finishAt: "2031-06-01T00:00:00Z" }),
      costNode(2, {
        parentId: 1,
        level: 2,
        rowNumber: 2,
        label: "Étude",
        nature: "labor",
        roleId: 7,
        bearingNodeId: 1,
      }),
    ]);

    const dept2 = screen.getByLabelText("Dpt 2eme niveau de Étude");
    fireEvent.change(dept2, { target: { value: "3" } });
    const role = screen.getByLabelText("Rôle de Étude");
    expect(role).toHaveValue("");

    // Moving from one select of the cascade to another is not leaving it.
    fireEvent.blur(role, { relatedTarget: dept2 });
    expect(screen.getByLabelText("Rôle de Étude")).toHaveValue("");

    fireEvent.blur(screen.getByLabelText("Rôle de Étude"), { relatedTarget: null });

    // Role, department and price back in agreement -- the rate cell never stopped showing 100 €.
    expect(screen.getByLabelText("Rôle de Étude")).toHaveValue("7");
    expect(screen.getByLabelText("Dpt 2eme niveau de Étude")).toHaveValue("2");
    expect(within(rowOf("Libellé de Étude")).getByText(/100,00/)).toBeInTheDocument();
  });

  it("keeps a pending change of nature open on blur, there being no stored state to fall back to", () => {
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton" })], { onSwitchNature: vi.fn() });

    fireEvent.change(screen.getByLabelText("Type de Béton"), { target: { value: "labor" } });
    fireEvent.blur(screen.getByLabelText("Rôle de Béton"), { relatedTarget: null });

    expect(screen.getByText("Choisis un rôle pour basculer cette ligne en MO.")).toBeInTheDocument();
    expect(screen.getByLabelText("Dpt 1er niveau de Béton")).toBeInTheDocument();
  });

  it("abandons a pending switch, writing nothing, when the original nature is picked again", () => {
    const onSwitchNature = vi.fn();
    renderGrid(laborTree(), { onSwitchNature });

    const type = screen.getByLabelText("Type de Étude");
    fireEvent.change(type, { target: { value: "non_labor" } });
    fireEvent.change(type, { target: { value: "labor" } });

    expect(onSwitchNature).not.toHaveBeenCalled();
    expect(screen.queryByText(/Choisis une catégorie/)).not.toBeInTheDocument();
    // The row is back on its own role and department.
    expect(screen.getByLabelText("Rôle de Étude")).toHaveValue("7");
  });
});

// --------------------------------------------------------------------------------------------
// The editable cells and their blur-commit
// --------------------------------------------------------------------------------------------

describe("the editable cells", () => {
  afterEach(() => cleanup());

  it("saves a cost line's label on blur, with no Sauver button anywhere", async () => {
    const onUpdateCost = vi.fn().mockResolvedValue(true);
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton" })], { onUpdateCost });

    const input = screen.getByLabelText("Libellé de Béton");
    fireEvent.change(input, { target: { value: "Béton armé" } });
    fireEvent.blur(input);

    await waitFor(() => expect(onUpdateCost).toHaveBeenCalledWith(2, { label: "Béton armé" }));
    expect(screen.queryByRole("button", { name: /Sauver/i })).not.toBeInTheDocument();
  });

  it("saves a task's name through its planning facet, from the devis grid", async () => {
    const onUpdatePlanning = vi.fn().mockResolvedValue(true);
    renderGrid([taskNode(1, { name: "Poste", rowNumber: 1 })], { onUpdatePlanning });

    const input = screen.getByLabelText("Libellé de Poste");
    fireEvent.change(input, { target: { value: "Poste 1" } });
    fireEvent.blur(input);

    await waitFor(() => expect(onUpdatePlanning).toHaveBeenCalledWith(1, { name: "Poste 1" }));
  });

  it("offers heures on an MO line and débours on a non-MO one, never both on either", () => {
    renderGrid([
      costNode(2, { rowNumber: 2, label: "Étude", nature: "labor", roleId: 7 }),
      costNode(3, { position: 2, rowNumber: 3, label: "Béton" }),
    ]);

    expect(screen.getByLabelText("Heures de Étude")).toBeInTheDocument();
    expect(screen.queryByLabelText("Débours de Étude")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Débours de Béton")).toBeInTheDocument();
    expect(screen.queryByLabelText("Heures de Béton")).not.toBeInTheDocument();
  });

  it("shows the indicative hourly rate and PRU of an MO line, and a dash when no rate is configured", () => {
    renderGrid([
      taskNode(1, { name: "Poste", rowNumber: 1, startAt: "2031-02-01T00:00:00Z", finishAt: "2031-06-01T00:00:00Z" }),
      costNode(2, {
        parentId: 1,
        level: 2,
        rowNumber: 2,
        label: "Étude",
        nature: "labor",
        quantity: "2.00",
        hours: "10.00",
        roleId: 7,
        bearingNodeId: 1,
      }),
      costNode(3, {
        parentId: 1,
        position: 2,
        level: 2,
        rowNumber: 3,
        label: "Chantier",
        nature: "labor",
        roleId: 8,
        bearingNodeId: 1,
      }),
    ]);

    const priced = rowOf("Libellé de Étude");
    expect(within(priced).getByText(/100,00/)).toBeInTheDocument();
    expect(within(priced).getByText(/2\s*000,00/)).toBeInTheDocument();
    // Role 8's category has no rate for that year: "—", never 0 €.
    const unpriced = rowOf("Libellé de Chantier");
    expect(within(unpriced).getAllByText("—").length).toBe(2);
  });
});

// --------------------------------------------------------------------------------------------
// Creation, and the context menu
// --------------------------------------------------------------------------------------------

describe("creating lines from the grid", () => {
  afterEach(() => cleanup());

  it("adds a non-MO line under the selected task, ready to be typed into", () => {
    const onCreateCostLine = vi.fn();
    renderGrid([taskNode(1, { name: "Poste", rowNumber: 1 })], { onCreateCostLine });

    fireEvent.click(rowOf("Libellé de Poste"));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne de coût" }));

    expect(onCreateCostLine).toHaveBeenCalledWith({
      nature: "non_labor",
      label: "Nouvelle ligne",
      quantity: 1,
      cost_type_id: 2,
      cost_category_id: 4,
      unit_cost: 0,
      parent_id: 1,
    });
  });

  it("adds it at the root when a cost line -- not a task -- is selected", () => {
    const onCreateCostLine = vi.fn();
    // A task is deliberately present *and* not selected: a creation that landed under it anyway
    // would be reading the tree instead of the selection.
    renderGrid(
      [taskNode(1, { name: "Poste", rowNumber: 1 }), costNode(2, { position: 2, rowNumber: 2, label: "Béton" })],
      { onCreateCostLine },
    );

    fireEvent.click(rowOf("Libellé de Béton"));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne de coût" }));

    expect(onCreateCostLine).toHaveBeenCalledWith(expect.objectContaining({ parent_id: null }));
  });

  it("refuses to offer the action when no non-MO category is configured, and says so in visible text", () => {
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton" })], {
      onCreateCostLine: vi.fn(),
      costCategories: [],
    });

    const button = screen.getByRole("button", { name: "Ajouter une ligne de coût" });
    expect(button).toBeDisabled();
    // The motif is shown, not merely hung on a `title`: a disabled button takes no focus, so a
    // tooltip only opens on hover and tells nothing to a keyboard or screen-reader user -- and
    // this refusal lasts until the referential is configured, so there is nothing to wait for.
    // The assertion is on the rendered copy and on the tie to the button, not on the attribute.
    const refusal = screen.getByText(/Aucune catégorie de coût non-MO n'est configurée/);
    expect(refusal).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-describedby", refusal.id);
  });

  it("leaves no refusal text beside the action once a category is configured", () => {
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton" })], { onCreateCostLine: vi.fn() });

    expect(screen.getByRole("button", { name: "Ajouter une ligne de coût" })).not.toBeDisabled();
    expect(screen.queryByText(/Aucune catégorie de coût non-MO n'est configurée/)).not.toBeInTheDocument();
  });

  it("adds a task to the planning from the devis, on the revision's own endpoint", async () => {
    const onCreateTask = vi.fn();
    renderGrid([taskNode(1, { name: "Poste", rowNumber: 1 })], { onCreateTask });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter une tâche" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nom de la nouvelle tâche"), {
      target: { value: "Terrassement" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ajouter" }));

    expect(onCreateTask).toHaveBeenCalledWith({
      name: "Terrassement",
      isMilestone: false,
      parentId: null,
      position: null,
    });
  });

  it("duplicates an MO resource blank, on the same bearing task and never with its amounts", () => {
    const onCreateCostLine = vi.fn();
    renderGrid(
      [
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, {
          parentId: 1,
          level: 2,
          rowNumber: 2,
          label: "Étude",
          nature: "labor",
          roleId: 7,
          quantity: "4.00",
          hours: "35.00",
        }),
      ],
      { onCreateCostLine },
    );

    fireEvent.contextMenu(rowOf("Libellé de Étude"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Ajouter une ressource" }));

    expect(onCreateCostLine).toHaveBeenCalledWith({
      nature: "labor",
      label: "Étude",
      quantity: 1,
      role_id: 7,
      hours: 0,
      parent_id: 1,
    });
  });

  it("offers the milestone template on a non-MO line only, and says it is not available yet", () => {
    renderGrid([costNode(2, { rowNumber: 2, label: "Béton" })], { onCreateCostLine: vi.fn() });

    fireEvent.contextMenu(rowOf("Libellé de Béton"));
    const item = screen.getByRole("menuitem", { name: /Gabarit de jalons/ });
    expect(item).toHaveAttribute("aria-disabled", "true");
    // The reason belongs to the entry's own accessible name, not to a `title`: a disabled menu
    // item takes no focus, so it is never reached by keyboard, and a tooltip that only opens on
    // hover tells nothing to anyone who does not use a mouse. #387 tracks the missing endpoint.
    expect(item).toHaveAccessibleName(/Pas encore disponible sur le modèle de révision/);
    expect(screen.queryByRole("menuitem", { name: "Ajouter une ressource" })).not.toBeInTheDocument();
  });

  it("never opens a context menu on a task row", () => {
    renderGrid([taskNode(1, { name: "Poste", rowNumber: 1 })], { onCreateCostLine: vi.fn() });

    fireEvent.contextMenu(rowOf("Libellé de Poste"));
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------------------------
// Criterion 6 -- a validated revision is read-only, menu included
// --------------------------------------------------------------------------------------------

describe("a read-only revision", () => {
  afterEach(() => cleanup());

  const nodes = () => [
    taskNode(1, { name: "Poste", rowNumber: 1 }),
    costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Étude", nature: "labor", roleId: 7 }),
    costNode(3, { parentId: 1, position: 2, level: 2, rowNumber: 3, label: "Béton" }),
  ];

  it("renders no editable cell at all", () => {
    renderGrid(nodes(), {
      readOnly: true,
      onUpdateCost: vi.fn(),
      onUpdatePlanning: vi.fn(),
      onSwitchNature: vi.fn(),
    });

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    // The values are still readable, only not editable.
    expect(screen.getByText("Étude")).toBeInTheDocument();
    expect(screen.getByText("Ingénieur")).toBeInTheDocument();
  });

  it("offers no write command in the toolbar", () => {
    renderGrid(nodes(), {
      readOnly: true,
      onMove: vi.fn(),
      onCreateCostLine: vi.fn(),
      onCreateTask: vi.fn(),
      onDeleteNodes: vi.fn(),
    });

    expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ajouter une ligne de coût" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supprimer la sélection" })).not.toBeInTheDocument();
  });

  it("offers no context-menu action on any row", () => {
    renderGrid(nodes(), { readOnly: true, onCreateCostLine: vi.fn() });

    fireEvent.contextMenu(screen.getByText("Étude").closest("tr") as HTMLElement);
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();

    fireEvent.contextMenu(screen.getByText("Béton").closest("tr") as HTMLElement);
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  // M-7 of #337's review: `readOnly` can turn on **without** the revision changing -- a lock
  // conflict posts the banner and turns the very same tree read-only. A draft the user typed and
  // never committed would then be rendered as plain text, indistinguishable from a saved value
  // (and as "NaN" for a half-typed one). The Libellé cell already reads the stored label; the
  // numeric cells now do the same.
  it("shows the stored value, not an uncommitted draft, when the revision turns read-only under the user", () => {
    const props = gridProps(
      [costNode(2, { rowNumber: 92, label: "Béton", quantity: "2.00", unitCost: "50.00" })],
      { onUpdateCost: vi.fn() },
    );
    const { rerender } = render(<EstimateGridTreeTable {...props} />);

    fireEvent.change(screen.getByLabelText("Qté de Béton"), { target: { value: "999" } });
    rerender(<EstimateGridTreeTable {...props} readOnly />);

    const row = screen.getByText("Béton").closest("tr") as HTMLElement;
    expect(within(row).queryByText("999")).not.toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
  });

  it("still shows each line's nature and its department path", () => {
    renderGrid(nodes(), { readOnly: true });

    const row = screen.getByText("Étude").closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("gridcell");
    // Type, then the two Dpt columns and the role, by position: the derived category ("Études")
    // is also displayed in the Type cell, so a text query alone could not tell the two apart.
    expect(cells[2]).toHaveTextContent("MO");
    expect(cells[2]).toHaveTextContent("Études");
    expect(cells[3]).toHaveTextContent("Direction");
    expect(cells[4]).toHaveTextContent("Études");
    expect(cells[5]).toHaveTextContent("Ingénieur");
  });
});

// --------------------------------------------------------------------------------------------
// The bulk cost-code bar, carried over to the revision's own selection
// --------------------------------------------------------------------------------------------

describe("bulk cost-code assignment", () => {
  afterEach(() => cleanup());

  it("appears once a cost row is selected and assigns to exactly those rows", () => {
    const onAssignCostCode = vi.fn();
    renderGrid(
      [
        taskNode(1, { name: "Poste", rowNumber: 1 }),
        costNode(2, { parentId: 1, level: 2, rowNumber: 2, label: "Béton" }),
      ],
      {
        onAssignCostCode,
        bulkCostCodeId: "3",
        projectCostCodes: [{ id: 3, code: "C1", name: "Chantier" } as never],
      },
    );

    expect(screen.queryByLabelText("Code d'imputation")).not.toBeInTheDocument();

    fireEvent.click(rowOf("Libellé de Béton"));
    fireEvent.click(screen.getByRole("button", { name: "Affecter" }));

    expect(onAssignCostCode).toHaveBeenCalledWith([2]);
  });

  it("does not count a task row, which carries no cost facet to assign to", () => {
    const onAssignCostCode = vi.fn();
    renderGrid([taskNode(1, { name: "Poste", rowNumber: 1 })], {
      onAssignCostCode,
      bulkCostCodeId: "3",
      projectCostCodes: [{ id: 3, code: "C1", name: "Chantier" } as never],
    });

    fireEvent.click(rowOf("Libellé de Poste"));
    expect(screen.queryByRole("button", { name: "Affecter" })).not.toBeInTheDocument();
  });
});
