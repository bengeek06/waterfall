import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EstimateTab, type EstimateTabProps } from "./estimate-tab";

const estimate = { id: 1, version_number: 1, status: "validated" } as never;

function renderTab(overrides: Partial<EstimateTabProps> = {}) {
  const props: EstimateTabProps = {
    active: true,
    estimates: [estimate],
    selectedEstimateId: 1,
    onSelectEstimate: vi.fn(),
    isReadOnlyProject: false,
    onNewDraft: vi.fn(),
    exportBusy: false,
    onExport: vi.fn(),
    canEditEstimate: false,
    estimateBusy: false,
    onOpenValidation: vi.fn(),
    validationWarnings: [],
    onDismissValidationWarnings: vi.fn(),
    estimateTaskRowCount: 0,
    costLines: [],
    costCategories: [],
    costLineDraft: { categoryId: "", label: "", quantity: "1", unitCost: "0", plannedDate: "" },
    onCategoryChange: vi.fn(),
    onLabelChange: vi.fn(),
    onQuantityChange: vi.fn(),
    onUnitCostChange: vi.fn(),
    onPlannedDateChange: vi.fn(),
    onAddCostLine: vi.fn(),
    editingLineId: null,
    editingLineDraft: { label: "", quantity: "", unitCost: "", plannedDate: "" },
    onEditLabelChange: vi.fn(),
    onEditQuantityChange: vi.fn(),
    onEditUnitCostChange: vi.fn(),
    onEditPlannedDateChange: vi.fn(),
    onStartEditCostLine: vi.fn(),
    onSaveCostLine: vi.fn(),
    onRequestDeleteCostLine: vi.fn(),
    selectedCostLineIds: new Set(),
    onSelectedCostLineIdsChange: vi.fn(),
    projectCostCodes: [],
    bulkCostCodeId: "",
    onBulkCostCodeIdChange: vi.fn(),
    bulkAssignBusy: false,
    onBulkAssignCostCode: vi.fn(),
    ...overrides,
  };
  return render(<EstimateTab {...props} />);
}

// #65 (E6-04): non-blocking warning banner listing real planning tasks that have neither a
// role assignment nor a cost line, returned by the validate endpoint's `warnings` field.
describe("EstimateTab validation warnings banner", () => {
  afterEach(() => cleanup());

  it("does not render a warnings banner when the last validation found nothing to warn about", () => {
    renderTab({ validationWarnings: [] });

    expect(screen.queryByText(/sans affectation de rôle/)).not.toBeInTheDocument();
  });

  it("lists every task returned by the last validation's warnings", () => {
    renderTab({
      validationWarnings: [
        { task_uid: 12, task_name: "Terrassement lot 3" },
        { task_uid: 15, task_name: "Coulage dalle" },
      ],
    });

    expect(screen.getByText(/sans affectation de rôle/)).toBeInTheDocument();
    expect(screen.getByText("Terrassement lot 3")).toBeInTheDocument();
    expect(screen.getByText("Coulage dalle")).toBeInTheDocument();
  });

  it("acknowledges/closes the banner via the dismiss action without touching validation itself", () => {
    const onDismissValidationWarnings = vi.fn();
    renderTab({
      validationWarnings: [{ task_uid: 12, task_name: "Terrassement lot 3" }],
      onDismissValidationWarnings,
    });

    fireEvent.click(screen.getByRole("button", { name: "Fermer" }));

    expect(onDismissValidationWarnings).toHaveBeenCalledTimes(1);
  });
});
