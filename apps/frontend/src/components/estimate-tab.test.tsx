import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Revision, RevisionAggregates, RevisionNode, RevisionTree } from "@/lib/backend";
import { EstimateTab, type EstimateTabProps } from "./estimate-tab";

function revision(overrides: Partial<Revision> = {}): Revision {
  return {
    revision_id: 7,
    project_id: 1,
    version_number: 1,
    kind: "initial",
    status: "draft",
    lock_version: 0,
    note: null,
    created_at: "2026-09-01T00:00:00Z",
    validated_at: null,
    ...overrides,
  };
}

function costNode(nodeId: number, label: string): RevisionNode {
  return {
    node_id: nodeId,
    work_item_id: nodeId * 10,
    kind: "cost",
    parent_id: null,
    position: 1,
    row_number: nodeId,
    level: 1,
    external_uid: null,
    description: null,
    planning: null,
    cost: {
      nature: "non_labor",
      label,
      quantity: "2.00",
      role_id: null,
      hours: null,
      cost_type_id: 1,
      cost_category_id: 4,
      unit_cost: "50.00",
      supply_status: null,
      planned_date: null,
      cost_code_id: null,
      comment: null,
      bearing_task_node_id: null,
      bearing_task_name: null,
    },
    predecessors: [],
  };
}

function tree(overrides: Partial<RevisionTree> = {}): RevisionTree {
  return {
    revision_id: 7,
    project_id: 1,
    version_number: 1,
    kind: "initial",
    status: "draft",
    lock_version: 0,
    note: null,
    nodes: [costNode(1, "Béton")],
    ...overrides,
  };
}

function aggregates(overrides: Partial<RevisionAggregates> = {}): RevisionAggregates {
  return {
    revision_id: 7,
    total_labor_cost: "1000.00",
    total_purchase_cost: "100.00",
    total_unburdened_cost: "1100.00",
    by_category: {},
    by_cost_code: {},
    unpriceable_facets: [],
    missing_cost_rates: [],
    missing_inflation_years: [],
    ...overrides,
  };
}

function renderTab(overrides: Partial<EstimateTabProps> = {}) {
  const props: EstimateTabProps = {
    active: true,
    revisions: [revision()],
    selectedRevision: revision(),
    selectedRevisionId: 7,
    referenceRevisionId: null,
    revisionsBusy: false,
    treeBusy: false,
    tree: tree(),
    mutationBusy: false,
    conflict: null,
    feedback: null,
    hasError: false,
    isReadOnlyProject: false,
    onSelectRevision: vi.fn(),
    onCreateDraft: vi.fn(),
    onValidateRevision: vi.fn(),
    onReloadConflict: vi.fn(),
    exportBusy: false,
    onExport: vi.fn(),
    aggregates: aggregates(),
    aggregatesBusy: false,
    costCategories: [],
    allCostCategories: [],
    resourceNodes: [],
    resourceRoles: [],
    costRates: [],
    projectCostCodes: [],
    bulkCostCodeId: "",
    onBulkCostCodeIdChange: vi.fn(),
    bulkAssignBusy: false,
    onAssignCostCode: vi.fn(),
    onMove: vi.fn(),
    onUpdatePlanning: vi.fn().mockResolvedValue(true),
    onUpdateCost: vi.fn().mockResolvedValue(true),
    onSwitchNature: vi.fn().mockResolvedValue(true),
    onCreateCostLine: vi.fn(),
    onCreateTask: vi.fn(),
    onDeleteNodes: vi.fn(),
    ...overrides,
  };
  return render(<EstimateTab {...props} />);
}

describe("EstimateTab", () => {
  afterEach(() => cleanup());

  it("renders nothing at all when it is not the active tab", () => {
    const { container } = renderTab({ active: false });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the revision's grid and lets its commands through", () => {
    renderTab();

    expect(screen.getByRole("treegrid", { name: "Devis de la révision" })).toBeInTheDocument();
    expect(screen.getByLabelText("Libellé de Béton")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Indenter" })).toBeInTheDocument();
  });

  it("publishes the revision's three totals, each under its own label", () => {
    renderTab();

    // Read through the label, not the amount: "100,00 €" is a substring of "1 100,00 €", and a
    // bare text query would happily match the wrong card.
    const cardFor = (label: string) => screen.getByText(label).closest("div") as HTMLElement;
    expect(cardFor("Total MO")).toHaveTextContent("1 000,00 €");
    expect(cardFor("Total achats")).toHaveTextContent("100,00 €");
    expect(cardFor("Total déboursé sec")).toHaveTextContent("1 100,00 €");
  });

  it("shows a dash rather than a zero for a total it could not read", () => {
    // A revision with no chiffrage really does total 0 €; a total that failed to load must not
    // look like one.
    renderTab({ aggregates: null, aggregatesBusy: false });

    expect(screen.getAllByText("—")).toHaveLength(3);
  });

  it("names the lines no total can count, instead of letting them vanish from the figures", () => {
    renderTab({
      aggregates: aggregates({
        unpriceable_facets: [
          {
            node_id: 3,
            work_item_id: 30,
            label: "Étude",
            hours: "10.00",
            bearing_node_id: 1,
            bearing_work_item_id: 10,
            bearing_task_name: "Poste",
            reason: "bearing_task_has_no_dates",
          } as never,
        ],
      }),
    });

    expect(screen.getByText("Lignes non valorisables")).toBeInTheDocument();
    expect(screen.getByText(/Étude \(Poste\)/)).toBeInTheDocument();
  });

  it("validates the displayed revision from the devis, on the Planning tab's own command", () => {
    const onValidateRevision = vi.fn();
    const onCreateDraft = vi.fn();
    renderTab({ onValidateRevision, onCreateDraft });

    fireEvent.click(screen.getByRole("button", { name: "Valider la révision" }));

    expect(onValidateRevision).toHaveBeenCalledTimes(1);
    // Asserted, not implied: the two commands sit next to each other and a swap would otherwise
    // pass with both of them called once.
    expect(onCreateDraft).not.toHaveBeenCalled();
  });

  it("opens a draft from the devis, which is the only way to change a validated revision", () => {
    const onValidateRevision = vi.fn();
    const onCreateDraft = vi.fn();
    renderTab({ onValidateRevision, onCreateDraft });

    fireEvent.click(screen.getByRole("button", { name: "Créer un brouillon" }));

    expect(onCreateDraft).toHaveBeenCalledTimes(1);
    expect(onValidateRevision).not.toHaveBeenCalled();
  });

  it("exports the displayed revision's workbook", () => {
    const onExport = vi.fn();
    renderTab({ onExport });

    fireEvent.click(screen.getByRole("button", { name: "Exporter le devis" }));
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("has nothing to export while no revision is displayed", () => {
    renderTab({ selectedRevisionId: null, tree: null, revisions: [], selectedRevision: null });

    expect(screen.getByRole("button", { name: "Exporter le devis" })).toBeDisabled();
    expect(screen.getByText(/Aucune révision à chiffrer/)).toBeInTheDocument();
  });

  it("says nothing about an empty devis while the revision is still loading", () => {
    renderTab({ revisions: [], tree: null, treeBusy: true });

    expect(screen.queryByText(/Aucune révision à chiffrer/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Chargement de la révision...");
  });

  // Criterion 6, at the tab's own level: the read-only rule is the planning's, not a second one.
  it("locks the grid on a validated revision", () => {
    renderTab({
      selectedRevision: revision({ status: "validated" }),
      tree: tree({ status: "validated" }),
    });

    expect(screen.getByText(/Cette révision n'est plus modifiable/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Libellé de Béton")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Indenter" })).not.toBeInTheDocument();
  });

  it("locks the grid on a read-only project, even though its revision is a draft", () => {
    renderTab({ isReadOnlyProject: true });

    expect(screen.queryByLabelText("Libellé de Béton")).not.toBeInTheDocument();
  });

  it("locks the grid behind an unresolved lock conflict, and offers to reload", () => {
    const onReloadConflict = vi.fn();
    renderTab({
      conflict: { revisionId: 7, expectedLockVersion: 1, currentLockVersion: 2 },
      onReloadConflict,
    });

    expect(screen.getByText("Révision modifiée")).toBeInTheDocument();
    expect(screen.queryByLabelText("Libellé de Béton")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Recharger la révision" }));
    expect(onReloadConflict).toHaveBeenCalledTimes(1);
  });

  it("relays what a write reported back", () => {
    renderTab({ feedback: "Révision V1 validée : elle est désormais en lecture seule (3 ligne(s) figée(s))." });

    expect(screen.getByText(/3 ligne\(s\) figée\(s\)/)).toBeInTheDocument();
  });
});
