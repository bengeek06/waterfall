import type { FormEvent } from "react";
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CostCategoriesTable, type CostCategoriesTableProps } from "./cost-categories-table";
import type { CostCategory, CostType } from "@/lib/backend";

afterEach(() => cleanup());

const costType = (overrides: Partial<CostType>): CostType =>
  ({
    id: 1,
    code: "SUP",
    name: "Fourniture",
    kind: "supply",
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as CostType;

const category = (overrides: Partial<CostCategory>): CostCategory =>
  ({
    id: 1,
    cost_type_id: 1,
    accounting_code: "601",
    category_code: "MAT",
    name: "Matériel",
    is_active: true,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as CostCategory;

function renderTable(overrides: Partial<CostCategoriesTableProps> = {}) {
  const props: CostCategoriesTableProps = {
    items: [category({})],
    types: [costType({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    typeId: "",
    accountingCode: "",
    categoryCode: "",
    name: "",
    draft: { code: "", name: "", accountingCode: "" },
    editingId: null,
    busy: false,
    onSubmit: (event: FormEvent<HTMLFormElement>) => event.preventDefault(),
    onTypeChange: vi.fn(),
    onAccountingCodeChange: vi.fn(),
    onCategoryCodeChange: vi.fn(),
    onNameChange: vi.fn(),
    onStartEdit: vi.fn(),
    onDraftChange: vi.fn(),
    onSave: vi.fn(),
    onCancel: vi.fn(),
    onToggle: vi.fn(),
    ...overrides,
  };
  return render(<CostCategoriesTable {...props} />);
}

describe("CostCategoriesTable", () => {
  it("renders active cost types, the resolved type name, and existing category actions", () => {
    renderTable();
    expect(screen.getByRole("option", { name: "SUP - Fourniture" })).toBeInTheDocument();
    expect(screen.getByText("Fourniture")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
    expect(screen.getByLabelText("Code comptable de la nouvelle catégorie")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajouter" })).toBeInTheDocument();
  });

  it("only lists active cost types in the create-row dropdown", () => {
    renderTable({ types: [costType({ id: 1, is_active: true }), costType({ id: 2, code: "MO", name: "Main d'œuvre", is_active: false })] });
    expect(screen.getByRole("option", { name: "SUP - Fourniture" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "MO - Main d'œuvre" })).not.toBeInTheDocument();
  });

  it("dims inactive rows but still lets them be reactivated, without an edit action", () => {
    renderTable({ items: [category({ id: 2, is_active: false })] });
    expect(screen.queryByRole("button", { name: "Modifier" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Réactiver" })).toBeInTheDocument();
    const row = screen.getByText("601").closest("tr");
    expect(row).toHaveClass("opacity-55");
  });

  it("renders an active row with no dimming class", () => {
    renderTable({ items: [category({ is_active: true })] });
    const row = screen.getByText("601").closest("tr");
    expect(row).not.toHaveClass("opacity-55");
  });

  it("calls onSortChange with the server column name when the accounting code header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Code comptable" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("accounting_code");
  });

  it("shows an input in place of the name cell while that row is being edited", () => {
    renderTable({ editingId: 1, draft: { code: "601", name: "Matériel modifié", accountingCode: "MAT" } });
    expect(screen.getByLabelText("Nom de 601")).toHaveValue("Matériel modifié");
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annuler" })).toBeInTheDocument();
  });

  it("freezes the DataTable (search and pagination) while a row is being edited", () => {
    renderTable({
      editingId: 1,
      pagination: { total: 40, limit: 20, offset: 20 },
    });
    expect(screen.getByLabelText("Rechercher une catégorie de coût")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });

  it("submits the pinned create row through the wrapping form", () => {
    const onSubmit = vi.fn((event: FormEvent) => event.preventDefault());
    renderTable({ onSubmit, typeId: "1", accountingCode: "602", name: "Sous-traitance" });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("keeps focus on an edited category's accounting-code field across keystrokes, even though it round-trips through the parent's draft prop", () => {
    // Regression test for a real bug: TanStack Table's `flexRender` passes each
    // cell renderer to React as a component *type*. Rebuilding `columns`
    // inline on every render (as this component used to) gives every cell a
    // new function identity whenever `draft` changes -- which happens on
    // every keystroke, since the parent stores the draft in its own state and
    // passes it back down. React then treats the cell as a *different*
    // component and unmounts/remounts the DOM node, dropping focus right
    // after the keystroke. A component wrapping `CostCategoriesTable` in real
    // `useState` (not a static props object, unlike the other tests in this
    // file) is required to reproduce this: it's specifically the round-trip
    // through a re-render with a new `draft` that triggers the remount.
    const item = category({});
    // Mirrors production (`resources/page.tsx`): `items`/`types` are their own
    // separate state, untouched by a draft-only update, and therefore keep a
    // stable identity across a re-render triggered by `setDraft` alone --
    // unlike an inline literal in JSX, which would be recreated (a new
    // reference) on every render regardless, masking the very bug this test
    // exists to catch.
    const items = [item];
    const types = [costType({})];

    function Wrapper() {
      const [editingId, setEditingId] = useState<number | null>(null);
      const [draft, setDraft] = useState<CostCategoriesTableProps["draft"]>({ code: "", name: "", accountingCode: "" });
      return (
        <CostCategoriesTable
          items={items}
          types={types}
          pagination={{ total: 1, limit: 20, offset: 0 }}
          onPaginationChange={() => {}}
          sort={null}
          onSortChange={() => {}}
          search=""
          onSearchChange={() => {}}
          isLoading={false}
          typeId=""
          accountingCode=""
          categoryCode=""
          name=""
          draft={draft}
          editingId={editingId}
          busy={false}
          onSubmit={(event) => event.preventDefault()}
          onTypeChange={() => {}}
          onAccountingCodeChange={() => {}}
          onCategoryCodeChange={() => {}}
          onNameChange={() => {}}
          onStartEdit={() => {
            setEditingId(item.id);
            setDraft({ code: item.accounting_code, name: item.name ?? "", accountingCode: item.category_code ?? "" });
          }}
          onDraftChange={(field, value) => setDraft((previous) => ({ ...previous, [field]: value }))}
          onSave={() => {}}
          onCancel={() => setEditingId(null)}
          onToggle={() => {}}
        />
      );
    }

    render(<Wrapper />);
    fireEvent.click(screen.getByRole("button", { name: "Modifier" }));
    const input = screen.getByLabelText("Code comptable de 601") as HTMLInputElement;
    input.focus();

    fireEvent.change(input, { target: { value: "6011" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("6011");

    fireEvent.change(input, { target: { value: "60112" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("60112");
  });
});
