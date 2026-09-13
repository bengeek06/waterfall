import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { RevisionNode, RevisionPlanFacet } from "@/lib/backend";
import { buildPlanningRows } from "@/lib/planning-tree";
import { rowNumberByNodeId } from "@/lib/revision-tree";
import { PlanningTreeTable } from "./planning-tree-table";

function facet(overrides: Partial<RevisionPlanFacet> = {}): RevisionPlanFacet {
  return {
    name: "Tâche",
    calendar_id: null,
    calendar_source: null,
    is_milestone: false,
    duration_minutes: 480,
    duration_format: null,
    start_at: null,
    finish_at: null,
    work_minutes: null,
    percent_complete: 0,
    is_manual: true,
    ...overrides,
  };
}

function taskNode(
  nodeId: number,
  options: {
    parentId?: number | null;
    position?: number;
    level?: number;
    rowNumber?: number;
    name?: string;
    milestone?: boolean;
    predecessors?: RevisionNode["predecessors"];
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
    external_uid: null,
    description: null,
    planning: facet({ name: options.name ?? `T${nodeId}`, is_milestone: options.milestone ?? false }),
    cost: null,
    predecessors: options.predecessors ?? [],
  };
}

// Poste > Lot > Livrable, plus a second root.
function threeLevelNodes(): RevisionNode[] {
  return [
    taskNode(1, { name: "Poste", position: 1, level: 1, rowNumber: 91 }),
    taskNode(2, { name: "Lot", parentId: 1, position: 1, level: 2, rowNumber: 92 }),
    taskNode(3, { name: "Livrable", parentId: 2, position: 1, level: 3, rowNumber: 93 }),
    taskNode(4, { name: "Autre poste", position: 2, level: 1, rowNumber: 94 }),
  ];
}

function renderTable(nodes: RevisionNode[], props: Partial<Parameters<typeof PlanningTreeTable>[0]> = {}) {
  return render(
    <TooltipProvider>
      <PlanningTreeTable
        rows={buildPlanningRows(nodes)}
        treeNodes={nodes}
        rowNumberByNodeId={rowNumberByNodeId(nodes)}
        revisionKey={1}
        {...props}
      />
    </TooltipProvider>,
  );
}

/** The data rows, header excluded. */
function dataRows() {
  return screen.getAllByRole("row").slice(1);
}

describe("PlanningTreeTable", () => {
  afterEach(() => cleanup());

  it("renders the revision's tree with its positional identifiers", () => {
    renderTable(threeLevelNodes());

    const rows = dataRows();
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("91")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Poste")).toBeInTheDocument();
    expect(within(rows[2]).getByText("93")).toBeInTheDocument();
    // The technical node id is never displayed.
    expect(within(rows[0]).queryByText("1")).not.toBeInTheDocument();
  });

  it("shows an empty state when the revision holds no task", () => {
    renderTable([]);

    expect(screen.getByText("Cette révision ne contient aucune tâche.")).toBeInTheDocument();
  });

  it("names a task with task children a summary, and a milestone a jalon", () => {
    renderTable([
      taskNode(1, { name: "Poste" }),
      taskNode(2, { name: "Livrable", parentId: 1, level: 2 }),
      taskNode(3, { name: "Jalon", position: 2, milestone: true }),
    ]);

    const rows = dataRows();
    expect(within(rows[0]).getByText("Résumé")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Tâche")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Jalon")).toBeInTheDocument();
  });

  // ------------------------------------------------------------------------------------------
  // #380: the treegrid semantics the table has always implemented, now declared
  // ------------------------------------------------------------------------------------------

  it("declares itself a treegrid and states each row's level and expansion", () => {
    renderTable(threeLevelNodes());

    expect(screen.getByRole("treegrid", { name: "Planning de la révision" })).toBeInTheDocument();
    const rows = dataRows();
    expect(rows[0]).toHaveAttribute("aria-level", "1");
    expect(rows[1]).toHaveAttribute("aria-level", "2");
    expect(rows[2]).toHaveAttribute("aria-level", "3");
    // Only a row that can actually be folded carries aria-expanded.
    expect(rows[0]).toHaveAttribute("aria-expanded", "true");
    expect(rows[2]).not.toHaveAttribute("aria-expanded");
  });

  it("gives each row its rank among its own siblings", () => {
    renderTable(threeLevelNodes());

    const rows = dataRows();
    expect(rows[0]).toHaveAttribute("aria-posinset", "1");
    expect(rows[0]).toHaveAttribute("aria-setsize", "2");
    expect(rows[3]).toHaveAttribute("aria-posinset", "2");
  });

  it("counts aria-posinset and aria-setsize in the same set as the rows it renders", () => {
    // #380: `position` is the rank among **all** the children (INV-05 numbers cost nodes too), so
    // pairing it with a count of task rows announces "3 sur 2" -- an invalid set, and a lie.
    const costNode: RevisionNode = {
      ...taskNode(3, { name: "Chiffrage", parentId: 1, position: 2, level: 2 }),
      kind: "cost",
      planning: null,
    };
    renderTable([
      taskNode(1, { name: "Poste", position: 1 }),
      taskNode(2, { name: "Premier", parentId: 1, position: 1, level: 2 }),
      costNode,
      taskNode(4, { name: "Second", parentId: 1, position: 3, level: 2 }),
    ]);

    const rows = dataRows();
    expect(rows).toHaveLength(3); // the cost node is not a planning row
    const second = rows[2];
    expect(second).toHaveAttribute("aria-posinset", "2");
    expect(second).toHaveAttribute("aria-setsize", "2");
    for (const row of rows) {
      expect(Number(row.getAttribute("aria-posinset"))).toBeLessThanOrEqual(
        Number(row.getAttribute("aria-setsize")),
      );
    }
  });

  it("keeps a visible focus indicator rather than suppressing the outline", () => {
    renderTable(threeLevelNodes());

    // WCAG 2.4.7: `outline-none` alone leaves a focused row with nothing to show for it.
    expect(dataRows()[0].className).toContain("focus-visible:outline-2");
  });

  // ------------------------------------------------------------------------------------------
  // Folding and selection
  // ------------------------------------------------------------------------------------------

  it("folds and unfolds a subtree", () => {
    renderTable(threeLevelNodes());

    fireEvent.click(screen.getByRole("button", { name: "Replier Poste" }));

    expect(screen.queryByText("Lot")).not.toBeInTheDocument();
    expect(screen.queryByText("Livrable")).not.toBeInTheDocument();
    expect(dataRows()[0]).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByRole("button", { name: "Déplier Poste" }));

    expect(screen.getByText("Lot")).toBeInTheDocument();
  });

  // E14-09/#335 round-2 H1, kept alive across the revision rewrite: the row's own onKeyDown
  // preventDefault()s Enter/Space to drive the selection, which also cancels the native
  // activation of any <button> inside the row. Every such control spreads `stopRowKeys`; without
  // it, a keyboard user reaching one operates nothing and moves the selection instead (WCAG
  // 2.1.1). One test per in-row control, because each one had to be fixed separately.
  it("keeps the fold chevron operable with the keyboard: Space on it never reaches the row", () => {
    renderTable(threeLevelNodes());

    fireEvent.keyDown(screen.getByRole("button", { name: "Replier Poste" }), { key: " " });

    expect(screen.getByText("Lot")).toBeInTheDocument();
    expect(dataRows()[0]).toHaveAttribute("aria-selected", "false");
  });

  it("keeps the predecessors edit button operable: Enter on it never reaches the row", () => {
    renderTable(threeLevelNodes(), { onEditLinks: vi.fn() });

    const editButton = screen.getByRole("button", { name: "Éditer les prédécesseurs de Lot" });
    fireEvent.keyDown(editButton, { key: "Enter" });

    expect(editButton.closest("tr")).toHaveAttribute("aria-selected", "false");
  });

  it("does not let an arrow key on the mode selector bubble up to the row navigation", () => {
    renderTable(
      [
        taskNode(1, { name: "Premier", position: 1 }),
        taskNode(2, { name: "Second", position: 2 }),
      ],
      { onScheduleUpdate: vi.fn().mockResolvedValue(true) },
    );

    const trigger = screen.getByLabelText("Mode de Premier");
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });

    // Had the keydown bubbled, the row handler would have moved focus to the sibling row.
    expect(document.activeElement).toBe(trigger);
  });

  it("selects a single row on click and extends the selection with Ctrl+click", () => {
    renderTable(threeLevelNodes());

    fireEvent.click(dataRows()[1]);
    expect(dataRows()[1]).toHaveAttribute("aria-selected", "true");
    expect(dataRows()[0]).toHaveAttribute("aria-selected", "false");

    fireEvent.click(dataRows()[0], { ctrlKey: true });
    expect(dataRows()[0]).toHaveAttribute("aria-selected", "true");
    expect(dataRows()[1]).toHaveAttribute("aria-selected", "true");
  });

  it("navigates rows with the arrow keys", () => {
    renderTable(threeLevelNodes());

    const rows = dataRows();
    rows[0].focus();
    fireEvent.keyDown(rows[0], { key: "ArrowDown" });

    expect(dataRows()[1]).toHaveFocus();
  });

  it("resets selection when the displayed revision changes", () => {
    const nodes = threeLevelNodes();
    const { rerender } = renderTable(nodes);
    fireEvent.click(dataRows()[1]);
    expect(dataRows()[1]).toHaveAttribute("aria-selected", "true");

    rerender(
      <TooltipProvider>
        <PlanningTreeTable
          rows={buildPlanningRows(nodes)}
          treeNodes={nodes}
          rowNumberByNodeId={rowNumberByNodeId(nodes)}
          revisionKey={2}
        />
      </TooltipProvider>,
    );

    expect(dataRows()[1]).toHaveAttribute("aria-selected", "false");
  });

  // ------------------------------------------------------------------------------------------
  // Moves: the mode is asked for, the destination is the backend's business
  // ------------------------------------------------------------------------------------------

  it("asks for a move by mode and passes the raw selection", () => {
    const onMove = vi.fn();
    renderTable(threeLevelNodes(), { onMove });

    fireEvent.click(dataRows()[3]); // "Autre poste", second root
    fireEvent.click(screen.getByRole("button", { name: "Monter" }));

    expect(onMove).toHaveBeenCalledWith("up", [4]);
  });

  it("offers indent/outdent on a nested row and names the mode asked for", () => {
    const onMove = vi.fn();
    renderTable(
      [
        taskNode(1, { name: "Poste", position: 1 }),
        taskNode(2, { name: "A", parentId: 1, position: 1, level: 2 }),
        taskNode(3, { name: "B", parentId: 1, position: 2, level: 2 }),
      ],
      { onMove },
    );

    fireEvent.click(dataRows()[2]); // B
    fireEvent.click(screen.getByRole("button", { name: "Indenter" }));
    expect(onMove).toHaveBeenCalledWith("indent", [3]);

    fireEvent.click(screen.getByRole("button", { name: "Désindenter" }));
    expect(onMove).toHaveBeenCalledWith("outdent", [3]);
  });

  it("disables every move command while nothing is selected", () => {
    renderTable(threeLevelNodes(), { onMove: vi.fn() });

    for (const name of ["Indenter", "Désindenter", "Monter", "Descendre"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("refuses to outdent a jalon followed by siblings, and explains why (INV-27)", () => {
    const onMove = vi.fn();
    renderTable(
      [
        taskNode(1, { name: "Poste", position: 1 }),
        taskNode(2, { name: "Jalon", parentId: 1, position: 1, level: 2, milestone: true }),
        taskNode(3, { name: "Suivante", parentId: 1, position: 2, level: 2 }),
      ],
      { onMove },
    );

    fireEvent.click(dataRows()[1]); // the jalon

    expect(screen.getByRole("button", { name: "Désindenter" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/jalon/);
    fireEvent.click(screen.getByRole("button", { name: "Désindenter" }));
    expect(onMove).not.toHaveBeenCalled();
  });

  it("explains a Ctrl+click spanning two levels rather than greying the four buttons out", () => {
    // Nothing about the selection looks wrong on screen -- two highlighted rows, four dead
    // buttons and no word about why. The refusal is `mixed-parents`, and the user has to be told
    // it is the *combination* that is refused, not either row.
    renderTable(threeLevelNodes(), { onMove: vi.fn() });

    fireEvent.click(dataRows()[1]); // "Lot", a child of "Poste"
    fireEvent.click(dataRows()[3], { ctrlKey: true }); // "Autre poste", a root

    for (const name of ["Indenter", "Désindenter", "Monter", "Descendre"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("status")).toHaveTextContent(/même parent/);
  });

  it("explains a refused indentation under a jalon rather than greying out silently", () => {
    renderTable(
      [
        taskNode(1, { name: "Jalon", position: 1, milestone: true }),
        taskNode(2, { name: "Suivante", position: 2 }),
      ],
      { onMove: vi.fn() },
    );

    fireEvent.click(dataRows()[1]);

    expect(screen.getByRole("button", { name: "Indenter" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/jalon/);
  });

  // ------------------------------------------------------------------------------------------
  // Create / delete
  // ------------------------------------------------------------------------------------------

  it("creates a task after the selected row, at its own level", () => {
    const onCreateTask = vi.fn();
    renderTable(threeLevelNodes(), { onCreateTask });

    fireEvent.click(dataRows()[3]); // "Autre poste", position 2 at the root
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une tâche" }));
    fireEvent.change(screen.getByLabelText("Nom de la nouvelle tâche"), { target: { value: "Nouvelle" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));

    expect(onCreateTask).toHaveBeenCalledWith({
      name: "Nouvelle",
      isMilestone: false,
      parentId: null,
      position: 3,
    });
  });

  it("does not offer to hang a new task under a jalon", () => {
    renderTable([taskNode(1, { name: "Jalon", milestone: true })], { onCreateTask: vi.fn() });

    fireEvent.click(dataRows()[0]);
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une tâche" }));

    const positionSelect = screen.getByLabelText("Position de la nouvelle tâche");
    expect(within(positionSelect).queryByText(/enfant/)).not.toBeInTheDocument();
  });

  it("names what a deletion takes away before asking to confirm it", () => {
    const onDeleteNodes = vi.fn();
    renderTable(threeLevelNodes(), { onDeleteNodes });

    fireEvent.click(dataRows()[0]); // Poste, which carries a subtree
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));

    expect(screen.getByText(/91 - Poste/)).toBeInTheDocument();
    expect(screen.getByText(/lignes de chiffrage/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    expect(onDeleteNodes).toHaveBeenCalledWith([1]);
  });

  it("sends only the selection roots to the delete endpoint", () => {
    const onDeleteNodes = vi.fn();
    renderTable(threeLevelNodes(), { onDeleteNodes });

    fireEvent.click(dataRows()[0]);
    fireEvent.click(dataRows()[1], { ctrlKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Supprimer la sélection" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));

    expect(onDeleteNodes).toHaveBeenCalledWith([1]);
  });

  // ------------------------------------------------------------------------------------------
  // Editing a schedule and the predecessors
  // ------------------------------------------------------------------------------------------

  it("commits a duration edit as a planning-facet update on the node", async () => {
    const onScheduleUpdate = vi.fn().mockResolvedValue(true);
    renderTable([taskNode(1, { name: "Livrable" })], { onScheduleUpdate });

    const durationField = screen.getByLabelText("Durée de Livrable");
    fireEvent.change(durationField, { target: { value: "2j" } });
    fireEvent.blur(durationField);

    await waitFor(() => expect(onScheduleUpdate).toHaveBeenCalled());
    expect(onScheduleUpdate.mock.calls[0][0]).toBe(1);
    expect(onScheduleUpdate.mock.calls[0][1]).toMatchObject({ is_manual: true, duration_minutes: 960 });
  });

  it("shows a task's predecessors by positional identifier, never by node id", () => {
    const nodes = [
      taskNode(1, { name: "Amont", rowNumber: 91 }),
      taskNode(2, {
        name: "Aval",
        position: 2,
        rowNumber: 92,
        predecessors: [{ predecessor_node_id: 1, link_type: 1, lag_tenth_minute: 0, lag_format: null }],
      }),
    ];
    renderTable(nodes);

    expect(within(dataRows()[1]).getByText("91 (FS)")).toBeInTheDocument();
  });

  it("replaces a node's predecessors through the edit dialog", async () => {
    const onEditLinks = vi.fn().mockResolvedValue(undefined);
    const nodes = [taskNode(1, { name: "Amont", rowNumber: 91 }), taskNode(2, { name: "Aval", position: 2 })];
    renderTable(nodes, { onEditLinks });

    fireEvent.click(screen.getByRole("button", { name: "Éditer les prédécesseurs de Aval" }));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne" }));
    fireEvent.change(screen.getByLabelText("Tâche prédécesseure"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(onEditLinks).toHaveBeenCalled());
    expect(onEditLinks).toHaveBeenCalledWith({
      nodeId: 2,
      predecessors: [{ predecessor_node_id: 1, link_type: 1, lag_tenth_minute: 0, lag_format: 7 }],
    });
  });

  // ------------------------------------------------------------------------------------------
  // Read-only (a validated revision)
  // ------------------------------------------------------------------------------------------

  it("offers no edit command at all on a read-only revision", () => {
    renderTable(threeLevelNodes(), {
      readOnly: true,
      onMove: vi.fn(),
      onCreateTask: vi.fn(),
      onDeleteNodes: vi.fn(),
      onScheduleUpdate: vi.fn(),
      onEditLinks: vi.fn(),
    });

    expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ajouter une tâche" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supprimer la sélection" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Durée de Poste")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Éditer les prédécesseurs/ })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Révision validée ou projet en lecture seule/),
    ).toBeInTheDocument();
  });

  it("still says edition is disabled on a read-only revision that holds no task", () => {
    // A validated revision whose tasks have all been deleted -- and, once the devis grid shares
    // this tree (#337), a revision carrying cost lines only. The empty state alone would leave
    // the user thinking the table is editable and simply blank.
    renderTable([], { readOnly: true });

    expect(screen.getByText("Cette révision ne contient aucune tâche.")).toBeInTheDocument();
    expect(screen.getByText(/Révision validée ou projet en lecture seule/)).toBeInTheDocument();
  });

  it("still folds, unfolds and selects on a read-only revision", () => {
    renderTable(threeLevelNodes(), { readOnly: true });

    fireEvent.click(screen.getByRole("button", { name: "Replier Poste" }));
    expect(screen.queryByText("Lot")).not.toBeInTheDocument();

    fireEvent.click(dataRows()[0]);
    expect(dataRows()[0]).toHaveAttribute("aria-selected", "true");
  });
});
