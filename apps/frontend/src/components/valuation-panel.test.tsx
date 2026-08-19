import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ValuationPanel } from "./valuation-panel";

describe("ValuationPanel", () => {
  it("shows five years and only labor categories", () => {
    render(<ValuationPanel categories={[{ id: 1, cost_type_id: 1, accounting_code: "MO-DEV", category_code: null, name: "Développement", is_active: true } as never, { id: 2, cost_type_id: 2, accounting_code: "FO-CABLE", category_code: null, name: "Câbles", is_active: true } as never]} costTypes={[{ id: 1, code: "MO", name: "Main d'œuvre", kind: "labor" } as never, { id: 2, code: "FO", name: "Fournitures", kind: "supply" } as never]} inflationYear="2026" inflationValue="2.00" currency="EUR" drafts={{}} busy={false} onCurrencyChange={vi.fn()} onInflationChange={vi.fn()} onRateChange={vi.fn()} onSave={vi.fn()} />);
    expect(screen.getByText("MO-DEV")).toBeInTheDocument();
    expect(screen.queryByText("FO-CABLE")).not.toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(6);
  });
});