import type { FormEvent } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CostTypesTable, type CostTypesTableProps } from "./cost-types-table";
import type { CostType } from "@/lib/backend";

afterEach(() => cleanup());

const labels = { labor: "Main d'œuvre", supply: "Fourniture", other: "Autres" };

const costType = (overrides: Partial<CostType>): CostType =>
  ({
    id: 1,
    code: "MO",
    name: "Main d'œuvre",
    kind: "labor",
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as CostType;

function renderTable(overrides: Partial<CostTypesTableProps> = {}) {
  const props: CostTypesTableProps = {
    items: [costType({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    code: "",
    name: "",
    kind: "other",
    draft: "",
    editingId: null,
    busy: false,
    labels,
    onSubmit: (event) => event.preventDefault(),
    onCodeChange: vi.fn(),
    onNameChange: vi.fn(),
    onKindChange: vi.fn(),
    onStartEdit: vi.fn(),
    onDraftChange: vi.fn(),
    onSave: vi.fn(),
    onCancel: vi.fn(),
    onToggle: vi.fn(),
    ...overrides,
  };
  return render(<CostTypesTable {...props} />);
}

describe("CostTypesTable", () => {
  it("renders the behavior selector, existing type actions, and the pinned create row", () => {
    renderTable();
    expect(screen.getByRole("option", { name: "Main d'œuvre" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
    expect(screen.getByLabelText("Code du nouveau type")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajouter" })).toBeInTheDocument();
  });

  it("dims inactive rows but still lets them be reactivated, without an edit action", () => {
    renderTable({ items: [costType({ id: 2, is_active: false })] });
    expect(screen.queryByRole("button", { name: "Modifier" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Réactiver" })).toBeInTheDocument();
    const row = screen.getByText("MO").closest("tr");
    expect(row).toHaveClass("opacity-55");
  });

  it("renders an active row with no dimming class", () => {
    renderTable({ items: [costType({ is_active: true })] });
    const row = screen.getByText("MO").closest("tr");
    expect(row).not.toHaveClass("opacity-55");
  });

  it("calls onSortChange with the server column name when the code header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Code" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("code");
  });

  it("shows an input in place of the name cell while that row is being edited", () => {
    renderTable({ editingId: 1, draft: "Main d'œuvre modifiée" });
    expect(screen.getByLabelText("Nom de MO")).toHaveValue("Main d'œuvre modifiée");
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annuler" })).toBeInTheDocument();
  });

  it("freezes the DataTable (search and pagination) while a row is being edited", () => {
    renderTable({
      editingId: 1,
      pagination: { total: 40, limit: 20, offset: 20 },
    });
    expect(screen.getByLabelText("Rechercher un type de coût")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });

  it("submits the pinned create row through the wrapping form", () => {
    const onSubmit = vi.fn((event: FormEvent) => event.preventDefault());
    renderTable({ onSubmit, code: "MO2", name: "Sous-traitance" });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
