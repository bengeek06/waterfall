import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ValuationPanel, type ValuationPanelProps } from "./valuation-panel";
import type { CostCategory } from "@/lib/backend";

afterEach(() => cleanup());

const currentYear = new Date().getFullYear();

const category = (overrides: Partial<CostCategory>): CostCategory =>
  ({
    id: 1,
    cost_type_id: 1,
    accounting_code: "MO-DEV",
    category_code: null,
    name: "Développement",
    is_active: true,
    ...overrides,
  }) as CostCategory;

function panelProps(overrides: Partial<ValuationPanelProps> = {}): ValuationPanelProps {
  return {
    items: [category({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    inflationYear: "2026",
    inflationValue: "2.00",
    currency: "EUR",
    drafts: {},
    busy: false,
    onCurrencyChange: vi.fn(),
    onInflationChange: vi.fn(),
    onRateChange: vi.fn(),
    onSave: vi.fn(),
    ...overrides,
  };
}

function renderPanel(overrides: Partial<ValuationPanelProps> = {}) {
  const props = panelProps(overrides);
  return render(<ValuationPanel {...props} />);
}

describe("ValuationPanel", () => {
  it("renders one column per year plus the accounting-code column, for the current page's items", () => {
    renderPanel();
    expect(screen.getByText("MO-DEV")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(6);
  });

  it("only renders the rows handed to it as the current page (labor-only filtering already happened upstream)", () => {
    renderPanel({ items: [category({ id: 2, accounting_code: "MO-INT" })] });
    expect(screen.getByText("MO-INT")).toBeInTheDocument();
    expect(screen.queryByText("MO-DEV")).not.toBeInTheDocument();
  });

  it("calls onRateChange with the categoryId:year key when a rate cell changes", () => {
    const onRateChange = vi.fn();
    renderPanel({ onRateChange });
    fireEvent.change(screen.getByLabelText(`MO-DEV ${currentYear}`), { target: { value: "45.5" } });
    expect(onRateChange).toHaveBeenCalledExactlyOnceWith(`1:${currentYear}`, "45.5");
  });

  it("delegates sorting on the accounting-code column to the caller", () => {
    const onSortChange = vi.fn();
    renderPanel({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Code comptable" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("accounting_code");
  });

  it("debounces the search box and delegates it to the caller", () => {
    vi.useFakeTimers();
    try {
      const onSearchChange = vi.fn();
      renderPanel({ onSearchChange });
      fireEvent.change(screen.getByLabelText("Rechercher une catégorie"), { target: { value: "MO" } });
      expect(onSearchChange).not.toHaveBeenCalled();
      vi.advanceTimersByTime(300);
      expect(onSearchChange).toHaveBeenCalledExactlyOnceWith("MO");
    } finally {
      vi.useRealTimers();
    }
  });

  it("wires pagination controls to the caller", () => {
    const onPaginationChange = vi.fn();
    renderPanel({ pagination: { total: 40, limit: 20, offset: 0 }, onPaginationChange });
    fireEvent.click(screen.getByRole("button", { name: "Suivant" }));
    expect(onPaginationChange).toHaveBeenCalledExactlyOnceWith({ offset: 20, limit: 20 });
  });

  // Issue #122 (E8-04): the ValuationPanel grid is server-driven for search/sort but
  // its pagination is entirely presentational -- see the long comment atop
  // valuation-panel.tsx for why drafts are conserved across pages (they live in the
  // parent page's `rateDrafts` state, never reset by pagination/search/sort). This
  // test proves the conservation from ValuationPanel's own point of view: swapping
  // `items` (simulating a page change) never drops a draft already present in
  // `drafts`, and navigating back to the original page still shows it.
  it("preserves a draft entered on one page when the visible page changes", () => {
    const pageOneCategory = category({ id: 1, accounting_code: "MO-DEV" });
    const pageTwoCategory = category({ id: 2, accounting_code: "MO-INT", cost_type_id: 1 });
    const drafts = { [`1:${currentYear}`]: "50.00" };

    const { rerender } = renderPanel({
      items: [pageOneCategory],
      pagination: { total: 2, limit: 1, offset: 0 },
      drafts,
    });
    expect(screen.getByLabelText(`MO-DEV ${currentYear}`)).toHaveValue(50);

    // Simulate navigating to the next page: a different category is now visible,
    // but the draft for the previous page's category must still be intact in
    // `drafts` -- ValuationPanel itself never mutates or clears it.
    rerender(
      <ValuationPanel
        {...panelProps({
          items: [pageTwoCategory],
          pagination: { total: 2, limit: 1, offset: 1 },
          drafts,
        })}
      />,
    );
    expect(screen.queryByLabelText(`MO-DEV ${currentYear}`)).not.toBeInTheDocument();
    expect(drafts[`1:${currentYear}`]).toBe("50.00");

    // Navigating back to the original page must still show the preserved draft.
    rerender(
      <ValuationPanel
        {...panelProps({
          items: [pageOneCategory],
          pagination: { total: 2, limit: 1, offset: 0 },
          drafts,
        })}
      />,
    );
    expect(screen.getByLabelText(`MO-DEV ${currentYear}`)).toHaveValue(50);
  });

  it("disables the save button while busy, but not the grid itself", () => {
    renderPanel({ busy: true });
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
    expect(screen.getByLabelText("Rechercher une catégorie")).toBeEnabled();
  });
});
