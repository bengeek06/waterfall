import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BulkCostCodeAssignmentBar, type BulkCostCodeAssignmentBarProps } from "./bulk-cost-code-assignment-bar";

const costCodes = [
  { id: 10, code: "1.1", name: "Terrassement" },
  { id: 11, code: "1.2", name: "Fondations" },
] as never;

function renderBar(overrides: Partial<BulkCostCodeAssignmentBarProps> = {}) {
  const props: BulkCostCodeAssignmentBarProps = {
    selectedCount: 2,
    projectCostCodes: costCodes,
    bulkCostCodeId: "",
    onBulkCostCodeIdChange: vi.fn(),
    bulkAssignBusy: false,
    onAssign: vi.fn(),
    ...overrides,
  };
  return render(<BulkCostCodeAssignmentBar {...props} />);
}

describe("BulkCostCodeAssignmentBar", () => {
  afterEach(() => cleanup());

  it("renders nothing when no line is selected", () => {
    const { container } = renderBar({ selectedCount: 0 });

    expect(container).toBeEmptyDOMElement();
  });

  it("lists the project's cost codes as flat options, matching roles-panel.tsx's picker", () => {
    renderBar();

    expect(screen.getByRole("option", { name: "1.1 - Terrassement" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1.2 - Fondations" })).toBeInTheDocument();
  });

  it("disables 'Affecter' until a cost code is chosen", () => {
    renderBar({ bulkCostCodeId: "" });

    expect(screen.getByRole("button", { name: "Affecter" })).toBeDisabled();
  });

  it("enables 'Affecter' once a cost code is chosen, and calls onAssign when clicked", () => {
    const onAssign = vi.fn();
    renderBar({ bulkCostCodeId: "10", onAssign });

    const assignButton = screen.getByRole("button", { name: "Affecter" });
    expect(assignButton).not.toBeDisabled();

    fireEvent.click(assignButton);

    expect(onAssign).toHaveBeenCalled();
  });

  it("disables 'Affecter' while a bulk assignment is in flight", () => {
    renderBar({ bulkCostCodeId: "10", bulkAssignBusy: true });

    expect(screen.getByRole("button", { name: "Affecter" })).toBeDisabled();
  });

  it("reports the selected cost code back to the caller", () => {
    const onBulkCostCodeIdChange = vi.fn();
    renderBar({ onBulkCostCodeIdChange });

    fireEvent.change(screen.getByLabelText("Code d'imputation"), { target: { value: "11" } });

    expect(onBulkCostCodeIdChange).toHaveBeenCalledWith("11");
  });
});
