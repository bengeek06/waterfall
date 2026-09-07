import type { FormEvent } from "react";
import { useState } from "react";
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

  it("keeps focus on an edited type's name field across keystrokes, even though it round-trips through the parent's draft prop", () => {
    // Regression test for a real bug, already live in production (this table
    // was merged before the bug was found in the parallel EPIC E8 migrations
    // built on it as their reference implementation -- #121/#123/#124/#125):
    // TanStack Table's `flexRender` passes each cell renderer to React as a
    // component *type*. Rebuilding `columns` inline on every render (as this
    // component used to) gives every cell a new function identity whenever
    // `draft` changes -- which happens on every keystroke, since the parent
    // stores the draft in its own state and passes it back down. React then
    // treats the cell as a *different* component and unmounts/remounts the
    // DOM node, dropping focus right after the keystroke. A component
    // wrapping `CostTypesTable` in real `useState` (not a static props
    // object, unlike the other tests in this file) is required to reproduce
    // this: it's specifically the round-trip through a re-render with a new
    // `draft` that triggers the remount.
    const item = costType({});
    // Mirrors production (`resources/page.tsx`): `items` is its own separate
    // state, untouched by a draft-only update, and therefore keeps a stable
    // identity across a re-render triggered by `setDraft` alone -- unlike an
    // inline literal in JSX, which would be recreated (a new reference) on
    // every render regardless, masking the very bug this test exists to
    // catch.
    const items = [item];

    function Wrapper() {
      const [editingId, setEditingId] = useState<number | null>(null);
      const [draft, setDraft] = useState("");
      return (
        <CostTypesTable
          items={items}
          pagination={{ total: 1, limit: 20, offset: 0 }}
          onPaginationChange={() => {}}
          sort={null}
          onSortChange={() => {}}
          search=""
          onSearchChange={() => {}}
          isLoading={false}
          code=""
          name=""
          kind="other"
          draft={draft}
          editingId={editingId}
          busy={false}
          labels={labels}
          onSubmit={(event) => event.preventDefault()}
          onCodeChange={() => {}}
          onNameChange={() => {}}
          onKindChange={() => {}}
          onStartEdit={() => {
            setEditingId(item.id);
            setDraft(item.name);
          }}
          onDraftChange={setDraft}
          onSave={() => {}}
          onCancel={() => setEditingId(null)}
          onToggle={() => {}}
        />
      );
    }

    render(<Wrapper />);
    fireEvent.click(screen.getByRole("button", { name: "Modifier" }));
    const input = screen.getByLabelText("Nom de MO") as HTMLInputElement;
    input.focus();

    fireEvent.change(input, { target: { value: "Main d'œuvre 2" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("Main d'œuvre 2");

    fireEvent.change(input, { target: { value: "Main d'œuvre 23" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("Main d'œuvre 23");
  });
});
