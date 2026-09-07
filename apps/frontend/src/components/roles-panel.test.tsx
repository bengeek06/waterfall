import type { FormEvent } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RolesPanel, type RolesPanelProps } from "./roles-panel";
import type { ResourceRole } from "@/lib/backend";

afterEach(() => cleanup());

const role = (overrides: Partial<ResourceRole> = {}): ResourceRole =>
  ({
    id: 5,
    name: "Développeur",
    node_id: 1,
    cost_category_id: 1,
    calendar_id: null,
    is_active: true,
    ...overrides,
  }) as ResourceRole;

function renderPanel(overrides: Partial<RolesPanelProps> = {}) {
  const props: RolesPanelProps = {
    selectedNode: { id: 1, code: "IT", name: "Informatique" } as never,
    items: [role({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    nodes: [],
    categories: [],
    costTypes: [],
    roleName: "",
    roleNodeId: "",
    roleCategoryId: "",
    actionBusy: false,
    categoryNames: new Map(),
    onSubmit: (event) => event.preventDefault(),
    onNameChange: vi.fn(),
    onNodeChange: vi.fn(),
    onCategoryChange: vi.fn(),
    ...overrides,
  };
  return render(<RolesPanel {...props} />);
}

describe("RolesPanel", () => {
  it("only offers categories attached to labor cost types", () => {
    renderPanel({
      categories: [
        { id: 1, cost_type_id: 10, accounting_code: "MO-DEV", category_code: null, name: "Développement", is_active: true } as never,
        { id: 2, cost_type_id: 20, accounting_code: "FO-CABLE", category_code: null, name: "Câbles", is_active: true } as never,
      ],
      costTypes: [
        { id: 10, code: "MO", name: "Main d'œuvre", kind: "labor" } as never,
        { id: 20, code: "FO", name: "Fourniture", kind: "supply" } as never,
      ],
    });

    expect(screen.getByRole("option", { name: /MO-DEV/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /FO-CABLE/ })).not.toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name and category within the same node using role id", () => {
    renderPanel({
      items: [
        role({ id: 5, name: "Développeur", cost_category_id: 1 }),
        role({ id: 6, name: "Développeur", cost_category_id: 1 }),
      ],
      pagination: { total: 2, limit: 20, offset: 0 },
      categoryNames: new Map([[1, "MO-DEV"]]),
    });

    // Both roles share the same name and the same accounting category, so within
    // this single node's list only the trailing "(#<role.id>)" discriminant can
    // tell them apart. If that suffix were dropped, both list items would render
    // identical text ("Développeur" + the "MO-DEV" badge) and would be
    // indistinguishable from one another.
    expect(screen.getByText("Développeur (#5)")).toBeInTheDocument();
    expect(screen.getByText("Développeur (#6)")).toBeInTheDocument();
  });

  it("renders the search box, sortable name column, and pagination controls", () => {
    renderPanel();
    expect(screen.getByLabelText("Rechercher un rôle")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nom" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeInTheDocument();
  });

  it("calls onSortChange with the server column name when the name header is clicked", () => {
    const onSortChange = vi.fn();
    renderPanel({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Nom" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("name");
  });

  it("submits the create form independently from the DataTable below it", () => {
    const onSubmit = vi.fn((event: FormEvent) => event.preventDefault());
    renderPanel({
      onSubmit,
      roleName: "Chef de projet",
      roleNodeId: "1",
      roleCategoryId: "1",
      nodes: [{ id: 1, code: "IT", name: "Informatique" } as never],
      costTypes: [{ id: 10, code: "MO", name: "Main d'œuvre", kind: "labor" } as never],
      categories: [
        { id: 1, cost_type_id: 10, accounting_code: "MO-DEV", category_code: null, name: "Développement", is_active: true } as never,
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("shows a prompt to select a node when none is selected, instead of an empty-list message", () => {
    renderPanel({ selectedNode: null, items: [], pagination: { total: 0, limit: 20, offset: 0 } });
    expect(screen.getByText("Sélectionnez un nœud pour voir ses rôles.")).toBeInTheDocument();
  });

  it("shows a node-specific empty message once a node is selected but has no roles", () => {
    renderPanel({ items: [], pagination: { total: 0, limit: 20, offset: 0 } });
    expect(screen.getByText("Aucun rôle pour ce nœud.")).toBeInTheDocument();
  });
});
