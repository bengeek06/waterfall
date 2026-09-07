import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable, type DataTableProps } from "./data-table";

afterEach(() => cleanup());

type Item = { id: number; name: string };

const columns: ColumnDef<Item>[] = [
  { accessorKey: "id", header: "ID", meta: { sortColumn: "id" } },
  { accessorKey: "name", header: "Nom", meta: { sortColumn: "name" } },
];

function renderTable(overrides: Partial<DataTableProps<Item>> = {}) {
  const props: DataTableProps<Item> = {
    columns,
    data: [],
    getRowId: (item) => String(item.id),
    pagination: { total: 0, limit: 10, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    ...overrides,
  };
  const view = render(<DataTable {...props} />);
  return { ...view, props };
}

function getDataRows() {
  // First row is the header row inside <thead>; getAllByRole("row") includes both
  // header and body rows, so the body rows start at index 1.
  return screen.getAllByRole("row").slice(1);
}

describe("DataTable", () => {
  it("renders rows in the exact order given by data, without local re-sorting", () => {
    const data = [
      { id: 2, name: "Bravo" },
      { id: 1, name: "Alpha" },
    ];
    renderTable({ data, pagination: { total: 2, limit: 10, offset: 0 } });

    const rows = getDataRows();
    expect(within(rows[0]).getByText("Bravo")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Alpha")).toBeInTheDocument();
  });

  it("calls onSortChange with the ascending column name on first click without changing the rendered order", () => {
    const onSortChange = vi.fn();
    const data = [
      { id: 2, name: "Bravo" },
      { id: 1, name: "Alpha" },
    ];
    renderTable({
      data,
      sort: null,
      onSortChange,
      pagination: { total: 2, limit: 10, offset: 0 },
    });

    fireEvent.click(screen.getByRole("button", { name: "Nom" }));

    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("name");
    const rows = getDataRows();
    expect(within(rows[0]).getByText("Bravo")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Alpha")).toBeInTheDocument();
  });

  it("cycles a sorted column from ascending to descending to unsorted", () => {
    const onSortChange = vi.fn();
    const { rerender, props } = renderTable({ sort: "name", onSortChange });

    fireEvent.click(screen.getByRole("button", { name: "Nom" }));
    expect(onSortChange).toHaveBeenNthCalledWith(1, "-name");

    rerender(<DataTable {...props} sort="-name" onSortChange={onSortChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Nom" }));
    expect(onSortChange).toHaveBeenNthCalledWith(2, null);
  });

  it("reflects the current sort via aria-sort on the corresponding header", () => {
    renderTable({ sort: "-name" });
    expect(screen.getByRole("columnheader", { name: "Nom" })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: "ID" })).toHaveAttribute("aria-sort", "none");
  });

  it("pins a column marked meta.sticky: \"right\" to the right edge of the horizontally scrollable table", () => {
    const columnsWithSticky: ColumnDef<Item>[] = [
      ...columns,
      { id: "actions", header: "Actions", meta: { sticky: "right" }, cell: () => "Modifier" },
    ];
    renderTable({
      columns: columnsWithSticky,
      data: [{ id: 1, name: "Alpha" }],
      pagination: { total: 1, limit: 10, offset: 0 },
    });

    expect(screen.getByRole("columnheader", { name: "Actions" })).toHaveClass("sticky", "right-0");
    const actionsCell = screen.getByText("Modifier").closest("td");
    expect(actionsCell).toHaveClass("sticky", "right-0");
  });

  it("omits aria-sort entirely on a column with no meta.sortColumn, rather than setting it to none", () => {
    const columnsWithOneUnsortable: ColumnDef<Item>[] = [
      ...columns,
      { id: "actions", header: "Actions" },
    ];
    renderTable({ columns: columnsWithOneUnsortable, sort: "-name" });
    expect(screen.getByRole("columnheader", { name: "Actions" })).not.toHaveAttribute("aria-sort");
  });

  it("debounces search onChange calls instead of firing on every keystroke", () => {
    vi.useFakeTimers();
    try {
      const onChange = vi.fn();
      renderTable({ search: { value: "", onChange, placeholder: "Rechercher un item" } });

      const input = screen.getByLabelText("Rechercher un item");
      fireEvent.change(input, { target: { value: "a" } });
      fireEvent.change(input, { target: { value: "ab" } });
      fireEvent.change(input, { target: { value: "abc" } });

      expect(onChange).not.toHaveBeenCalled();
      expect(input).toHaveValue("abc");

      vi.advanceTimersByTime(300);

      expect(onChange).toHaveBeenCalledExactlyOnceWith("abc");
    } finally {
      vi.useRealTimers();
    }
  });

  it("still fires the debounced onChange despite unrelated re-renders that give it a new identity each time", () => {
    // Regression: a page resetting pagination alongside the search value
    // (onChange: (v) => { setQuery(v); setOffset(0); }) creates a fresh onChange
    // identity every render -- an idiomatic pattern, not a contrived edge case. If
    // the debounce effect depended on `onChange`, each such re-render would cancel
    // and reschedule the pending timeout, and typing would appear to do nothing.
    vi.useFakeTimers();
    try {
      const calls: string[] = [];
      const { rerender, props } = renderTable({
        search: { value: "", onChange: (next) => calls.push(next) },
      });

      fireEvent.change(screen.getByLabelText("Rechercher"), { target: { value: "a" } });

      for (let i = 0; i < 5; i += 1) {
        vi.advanceTimersByTime(200);
        rerender(
          <DataTable {...props} search={{ value: "", onChange: (next) => calls.push(next) }} />,
        );
      }

      expect(calls).toEqual(["a"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("suspends a pending debounced search once isEditing becomes true, and does not replay it once editing ends", () => {
    // Regression test: an in-flight debounce timer used to keep running even after
    // isEditing flipped to true (e.g. the user clicked "Modifier" on a row right
    // after typing a search), silently loading a new filtered page underneath an
    // edit in progress and potentially dropping the edited row off the page with no
    // way back to it (pagination/sort are frozen by isEditing, but the page content
    // itself wasn't). Silent abandonment on resume is a deliberate, documented
    // choice (see `useDebouncedSearchValue`'s comment) -- the pending search must
    // not fire late either, once editing ends.
    vi.useFakeTimers();
    try {
      const onChange = vi.fn();
      const { rerender, props } = renderTable({ search: { value: "", onChange } });

      fireEvent.change(screen.getByLabelText("Rechercher"), { target: { value: "abc" } });
      vi.advanceTimersByTime(100);

      rerender(<DataTable {...props} search={{ value: "", onChange }} isEditing />);
      vi.advanceTimersByTime(300);
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByLabelText("Rechercher")).toHaveValue("abc");

      rerender(<DataTable {...props} search={{ value: "", onChange }} isEditing={false} />);
      vi.advanceTimersByTime(300);
      expect(onChange).not.toHaveBeenCalled();
      // The abandoned "abc" must not linger in the input forever once editing ends --
      // it was never applied, so the field must resync onto the external value.
      expect(screen.getByLabelText("Rechercher")).toHaveValue("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the pinned row visible regardless of data, search, and pagination state", () => {
    renderTable({
      data: [],
      pinnedRow: <tr><td>Ligne épinglée</td></tr>,
      search: { value: "introuvable", onChange: vi.fn() },
      pagination: { total: 0, limit: 10, offset: 0 },
    });

    expect(screen.getByText("Ligne épinglée")).toBeInTheDocument();
  });

  it("disables search and pagination controls and shows the editing reason while isEditing is true", () => {
    renderTable({
      data: [{ id: 1, name: "Alpha" }],
      search: { value: "", onChange: vi.fn() },
      pagination: { total: 20, limit: 5, offset: 5 },
      isEditing: true,
      editingReason: "Terminez l'édition en cours pour changer de page ou filtrer.",
    });

    expect(screen.getByLabelText("Rechercher")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
    expect(
      screen.getByText("Terminez l'édition en cours pour changer de page ou filtrer."),
    ).toBeInTheDocument();
    // Sort must be frozen too: re-sorting mid-edit can drop the edited row off the
    // page with no way to reach its Enregistrer/Annuler controls again.
    expect(screen.getByRole("button", { name: "Nom" })).toBeDisabled();
  });

  it("calls preventDefault on Enter in the search input, so it can't submit a wrapping form", () => {
    // A caller commonly wraps the whole DataTable (search box included) in a <form>
    // for its own pinned create-row submit button. Per the HTML implicit-submission
    // algorithm, Enter in any single-line text input inside that form submits it --
    // search must not let an unrelated Enter-to-search keystroke trigger that.
    //
    // jsdom does not implement that implicit-submission algorithm at all (verified:
    // a real <form onSubmit> around this exact render still never fires on Enter,
    // fix or no fix), so asserting on a submit handler would pass either way and
    // prove nothing. `fireEvent.keyDown` returns `dispatchEvent`'s own result --
    // `false` iff some handler called `preventDefault()` on the (cancelable)
    // keydown event -- which does exercise the actual code path this component
    // controls, regardless of what jsdom does or doesn't do with it afterwards.
    renderTable({ search: { value: "", onChange: vi.fn() } });

    const notCancelled = fireEvent.keyDown(screen.getByLabelText("Rechercher"), { key: "Enter" });

    expect(notCancelled).toBe(false);
  });

  it("shows a loading state distinct from the empty-data render", () => {
    renderTable({ data: [], isLoading: true });

    expect(screen.getByRole("status", { name: "Chargement des données" })).toBeInTheDocument();
    expect(screen.queryByText("Aucune donnée.")).not.toBeInTheDocument();
  });

  it("freezes the position label and pagination controls while isLoading, even with stale data/pagination left mounted", () => {
    // A caller may keep the previous page's `data`/`pagination` mounted during a
    // background refetch to avoid a flash of empty content; without this, the
    // position label and Prev/Next controls would describe that stale state
    // underneath the loading indicator instead of freezing like isEditing does.
    renderTable({
      data: [{ id: 1, name: "Alpha" }, { id: 2, name: "Bravo" }],
      pagination: { total: 20, limit: 2, offset: 2 },
      isLoading: true,
    });

    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
    expect(screen.queryByText("3 à 4 sur 20")).not.toBeInTheDocument();
  });

  it("shows the default empty state when data is empty and there is no active search", () => {
    renderTable({ data: [] });

    expect(screen.getByText("Aucune donnée.")).toBeInTheDocument();
  });

  it("shows a custom emptyState node when provided", () => {
    renderTable({ data: [], emptyState: <span>Rien à afficher pour le moment</span> });

    expect(screen.getByText("Rien à afficher pour le moment")).toBeInTheDocument();
  });

  it("shows noResultsState instead of emptyState when a search is active and data is empty", () => {
    renderTable({
      data: [],
      search: { value: "zzz", onChange: vi.fn() },
      emptyState: <span>Aucune donnée.</span>,
      noResultsState: <span>Aucun résultat pour &quot;zzz&quot;.</span>,
    });

    expect(screen.getByText('Aucun résultat pour "zzz".')).toBeInTheDocument();
    expect(screen.queryByText("Aucune donnée.")).not.toBeInTheDocument();
  });

  it("disables Next exactly when offset + data.length >= total, not merely when data.length < limit", () => {
    // A short page (data.length < limit) that is NOT the last page: Next must stay enabled.
    const { rerender, props } = renderTable({
      data: [{ id: 1, name: "Alpha" }, { id: 2, name: "Bravo" }, { id: 3, name: "Charlie" }],
      pagination: { total: 10, limit: 5, offset: 0 },
    });
    expect(screen.getByRole("button", { name: "Suivant" })).toBeEnabled();

    // Exactly at the boundary: Next must be disabled even though data.length === limit.
    rerender(
      <DataTable
        {...props}
        data={[
          { id: 8, name: "H" },
          { id: 9, name: "I" },
          { id: 10, name: "J" },
        ]}
        pagination={{ total: 10, limit: 5, offset: 7 }}
      />,
    );
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });

  it("disables Previous only at offset 0", () => {
    const { rerender, props } = renderTable({
      data: [{ id: 1, name: "Alpha" }],
      pagination: { total: 10, limit: 5, offset: 0 },
    });
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();

    rerender(<DataTable {...props} pagination={{ total: 10, limit: 5, offset: 5 }} />);
    expect(screen.getByRole("button", { name: "Précédent" })).toBeEnabled();
  });

  it("calls onPaginationChange with the next offset when Suivant is clicked", () => {
    const onPaginationChange = vi.fn();
    renderTable({
      data: [{ id: 1, name: "Alpha" }],
      pagination: { total: 10, limit: 5, offset: 0 },
      onPaginationChange,
    });

    fireEvent.click(screen.getByRole("button", { name: "Suivant" }));

    expect(onPaginationChange).toHaveBeenCalledExactlyOnceWith({ offset: 5, limit: 5 });
  });

  it("calls onPaginationChange with the previous offset when Précédent is clicked, clamped at zero", () => {
    const onPaginationChange = vi.fn();
    renderTable({
      data: [{ id: 1, name: "Alpha" }],
      pagination: { total: 10, limit: 5, offset: 5 },
      onPaginationChange,
    });

    fireEvent.click(screen.getByRole("button", { name: "Précédent" }));

    expect(onPaginationChange).toHaveBeenCalledExactlyOnceWith({ offset: 0, limit: 5 });
  });

  it("exposes accessible, keyboard-reachable controls", () => {
    renderTable({
      data: [{ id: 1, name: "Alpha" }],
      search: { value: "", onChange: vi.fn(), placeholder: "Rechercher" },
      pagination: { total: 1, limit: 5, offset: 0 },
    });

    const sortButton = screen.getByRole("button", { name: "Nom" });
    expect(sortButton.tagName).toBe("BUTTON");
    expect(screen.getByLabelText("Rechercher")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeInTheDocument();
  });
});

describe("DataTable row click", () => {
  it("calls onRowClick with the row's own data when a data row is clicked", () => {
    const onRowClick = vi.fn();
    const data = [{ id: 1, name: "Alpha" }, { id: 2, name: "Bravo" }];
    renderTable({ data, pagination: { total: 2, limit: 10, offset: 0 }, onRowClick });

    fireEvent.click(screen.getByText("Bravo"));

    expect(onRowClick).toHaveBeenCalledExactlyOnceWith({ id: 2, name: "Bravo" });
  });

  it("adds a cursor-pointer affordance to data rows only when onRowClick is set", () => {
    const data = [{ id: 1, name: "Alpha" }];
    const { rerender, props } = renderTable({ data, pagination: { total: 1, limit: 10, offset: 0 } });

    expect(getDataRows()[0]).not.toHaveClass("cursor-pointer");

    rerender(<DataTable {...props} onRowClick={() => {}} />);
    expect(getDataRows()[0]).toHaveClass("cursor-pointer");
  });

  it("never applies onRowClick to the pinned row", () => {
    const onRowClick = vi.fn();
    renderTable({
      data: [],
      pagination: { total: 0, limit: 10, offset: 0 },
      pinnedRow: <tr><td>Ligne épinglée</td></tr>,
      onRowClick,
    });

    fireEvent.click(screen.getByText("Ligne épinglée"));

    expect(onRowClick).not.toHaveBeenCalled();
  });
});

describe("DataTable without search", () => {
  it("renders with no search input when the search prop is omitted", () => {
    renderTable({ data: [{ id: 1, name: "Alpha" }] });
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });
});
