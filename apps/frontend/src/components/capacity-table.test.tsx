import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CapacityTable, type CapacityTableProps } from "./capacity-table";

const nodeCodeById = new Map([[1, "IT"]]);

function renderTable(overrides: Partial<CapacityTableProps> = {}) {
  const props: CapacityTableProps = {
    items: [{ id: 1, name: "Développeur", node_id: 1 } as never],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    drafts: {},
    actionBusy: false,
    nodeCodeById,
    onDraftChange: vi.fn(),
    onSave: vi.fn(),
    ...overrides,
  };
  return render(<CapacityTable {...props} />);
}

describe("CapacityTable", () => {
  afterEach(() => cleanup());

  it("updates a role draft and exposes its save action", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    renderTable({
      drafts: { 1: { personCount: "2.00", availableHours: "3200.00" } },
      onDraftChange,
      onSave,
    });

    fireEvent.change(screen.getByDisplayValue("2.00"), { target: { value: "3.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(onDraftChange).toHaveBeenCalledWith(1, { personCount: "3.00", availableHours: "3200.00" });
    expect(onSave).toHaveBeenCalledWith(1);
  });

  it("defaults a role without an existing capacity draft to 0.00/0.00, still editable and creatable inline", () => {
    renderTable({ drafts: {} });

    expect(screen.getByLabelText("Nombre de personnes pour Développeur — IT (#1)")).toHaveValue(0);
    expect(screen.getByLabelText("Heures disponibles pour Développeur — IT (#1)")).toHaveValue(0);
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name but belong to different nodes", () => {
    const twoNodeCodeById = new Map([
      [1, "IT"],
      [2, "DTSI"],
    ]);
    renderTable({
      items: [
        { id: 1, name: "Développeur", node_id: 1 } as never,
        { id: 2, name: "Développeur", node_id: 2 } as never,
      ],
      nodeCodeById: twoNodeCodeById,
    });

    expect(screen.getByText("Développeur — IT (#1)")).toBeInTheDocument();
    expect(screen.getByText("Développeur — DTSI (#2)")).toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name within the same node using role id", () => {
    renderTable({
      items: [
        { id: 5, name: "Développeur", node_id: 1 } as never,
        { id: 6, name: "Développeur", node_id: 1 } as never,
      ],
    });

    // Same name AND same node code ("IT") — only "(#<role.id>)" can tell them apart.
    // Without that suffix both cells would render identical text "Développeur — IT".
    expect(screen.getByText("Développeur — IT (#5)")).toBeInTheDocument();
    expect(screen.getByText("Développeur — IT (#6)")).toBeInTheDocument();
  });

  it("calls onSortChange with the server column name when the role header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Rôle" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("name");
  });

  it("searches through the shared DataTable search input", () => {
    const onSearchChange = vi.fn();
    renderTable({ onSearchChange, search: "dev" });
    expect(screen.getByLabelText("Rechercher un rôle")).toHaveValue("dev");
  });

  it("paginates through the shared DataTable controls", () => {
    const onPaginationChange = vi.fn();
    renderTable({
      pagination: { total: 40, limit: 20, offset: 0 },
      onPaginationChange,
    });
    fireEvent.click(screen.getByRole("button", { name: "Suivant" }));
    expect(onPaginationChange).toHaveBeenCalledWith({ offset: 20, limit: 20 });
  });

  it("shows the loading skeleton while a page is being fetched", () => {
    renderTable({ isLoading: true });
    expect(screen.getByRole("status", { name: "Chargement des données" })).toBeInTheDocument();
  });

  it("keeps focus on a capacity input across keystrokes, even though every keystroke round-trips through the parent's drafts prop", () => {
    // Regression test for a real bug: TanStack Table's `flexRender` passes each
    // cell renderer to React as a component *type*. Rebuilding `columns` inline
    // on every render (as this component used to) gives every cell a new
    // function identity whenever `drafts` changes -- which happens on every
    // keystroke, since the parent stores drafts in its own state and passes
    // them back down. React then treats each cell as a *different* component
    // and unmounts/remounts the DOM node, dropping focus after every single
    // character. A component wrapping `CapacityTable` in real `useState` (not
    // a static props object, unlike the other tests in this file) is required
    // to reproduce this: it's specifically the round-trip through a re-render
    // with new `drafts` that triggers the remount.
    function Wrapper() {
      const [drafts, setDrafts] = useState<CapacityTableProps["drafts"]>({});
      return (
        <CapacityTable
          items={[{ id: 1, name: "Développeur", node_id: 1 } as never]}
          pagination={{ total: 1, limit: 20, offset: 0 }}
          onPaginationChange={vi.fn()}
          sort={null}
          onSortChange={vi.fn()}
          search=""
          onSearchChange={vi.fn()}
          isLoading={false}
          drafts={drafts}
          actionBusy={false}
          nodeCodeById={nodeCodeById}
          onDraftChange={(id, draft) => setDrafts((previous) => ({ ...previous, [id]: draft }))}
          onSave={vi.fn()}
        />
      );
    }

    render(<Wrapper />);
    const input = screen.getByLabelText("Nombre de personnes pour Développeur — IT (#1)") as HTMLInputElement;
    input.focus();

    fireEvent.change(input, { target: { value: "3" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("3");

    fireEvent.change(input, { target: { value: "35" } });
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("35");
  });
});
