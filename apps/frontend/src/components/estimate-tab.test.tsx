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
    estimateTaskRows: [],
    costLines: [],
    costCategories: [],
    allCostCategories: [],
    costLineDraft: { categoryId: "", label: "", quantity: "1", unitCost: "0", plannedDate: "", taskId: "" },
    onCategoryChange: vi.fn(),
    onLabelChange: vi.fn(),
    onQuantityChange: vi.fn(),
    onUnitCostChange: vi.fn(),
    onPlannedDateChange: vi.fn(),
    onTaskIdChange: vi.fn(),
    onAddCostLine: vi.fn(),
    editingLineId: null,
    editingLineDraft: { label: "", quantity: "", unitCost: "", plannedDate: "", taskId: "" },
    onEditLabelChange: vi.fn(),
    onEditQuantityChange: vi.fn(),
    onEditUnitCostChange: vi.fn(),
    onEditPlannedDateChange: vi.fn(),
    onEditTaskIdChange: vi.fn(),
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
    taskDialogOpen: false,
    taskDraftName: "",
    taskDraftIsMilestone: false,
    taskDraftParentUid: "",
    parentTaskOptions: [],
    taskCreateBusy: false,
    taskCreateError: null,
    taskCreateRequiresPlanningDraft: false,
    onOpenCreateTaskDialog: vi.fn(),
    onCloseCreateTaskDialog: vi.fn(),
    onTaskDraftNameChange: vi.fn(),
    onTaskDraftIsMilestoneChange: vi.fn(),
    onTaskDraftParentUidChange: vi.fn(),
    onSubmitCreateTask: vi.fn(),
    onReopenStructure: vi.fn(),
    milestoneDialogOpen: false,
    milestoneLineId: null,
    milestoneTemplate: "fourniture",
    milestoneIntermediateCount: "0",
    milestoneLagMinutes: "0",
    milestoneBusy: false,
    milestoneError: null,
    milestoneRequiresPlanningDraft: false,
    onOpenMilestoneDialog: vi.fn(),
    onCloseMilestoneDialog: vi.fn(),
    onMilestoneTemplateChange: vi.fn(),
    onMilestoneIntermediateCountChange: vi.fn(),
    onMilestoneLagMinutesChange: vi.fn(),
    onSubmitMilestoneTemplate: vi.fn(),
    onReopenStructureForMilestone: vi.fn(),
    estimateRoleAssignments: [],
    resourceNodes: [],
    resourceRoles: [],
    costRates: [],
    editingRoleAssignmentId: null,
    editingRoleAssignmentDraft: { quantity: "", hours: "" },
    onEditRoleAssignmentQuantityChange: vi.fn(),
    onEditRoleAssignmentHoursChange: vi.fn(),
    onStartEditRoleAssignment: vi.fn(),
    onSaveRoleAssignment: vi.fn(),
    onRequestDeleteRoleAssignment: vi.fn(),
    roleAssignmentDialogOpen: false,
    roleAssignmentNodeId: "",
    onRoleAssignmentNodeIdChange: vi.fn(),
    roleAssignmentRoles: [],
    roleAssignmentRolesLoading: false,
    roleAssignmentRoleId: "",
    onRoleAssignmentRoleIdChange: vi.fn(),
    roleAssignmentTaskId: "",
    onRoleAssignmentTaskIdChange: vi.fn(),
    roleAssignmentQuantity: "1",
    onRoleAssignmentQuantityChange: vi.fn(),
    roleAssignmentHours: "0",
    onRoleAssignmentHoursChange: vi.fn(),
    roleAssignmentCostCodeId: "",
    onRoleAssignmentCostCodeIdChange: vi.fn(),
    roleAssignmentComment: "",
    onRoleAssignmentCommentChange: vi.fn(),
    roleAssignmentBusy: false,
    roleAssignmentError: null,
    onOpenRoleAssignmentDialog: vi.fn(),
    onCloseRoleAssignmentDialog: vi.fn(),
    onSubmitRoleAssignment: vi.fn(),
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

// Haute review finding on #68: parentTaskOptions (planningDetail.tasks) is the source this tab
// resolves milestoneTaskIds from before handing it to CostLinesTable -- see estimate-tab.tsx's
// own doc comment on that computation.
describe("EstimateTab milestone-template gating (E6-07 review finding)", () => {
  afterEach(() => cleanup());

  it("disables the milestone-template action for a cost line attached to a milestone task", () => {
    renderTab({
      canEditEstimate: true,
      costLines: [
        { id: 1, accounting_code: "6011", label: "Livraison lot 3", quantity: "1", unit_cost: "0", purchase_cost: "0", task_id: 42 },
      ] as never,
      parentTaskOptions: [{ id: 42, is_milestone: true }] as never,
    });

    expect(screen.getByRole("button", { name: "Gabarit de jalons" })).toBeDisabled();
  });

  it("keeps the milestone-template action enabled for a cost line attached to a non-milestone task", () => {
    renderTab({
      canEditEstimate: true,
      costLines: [
        { id: 1, accounting_code: "6011", label: "Fourniture lot 2", quantity: "1", unit_cost: "0", purchase_cost: "0", task_id: 7 },
      ] as never,
      parentTaskOptions: [{ id: 42, is_milestone: true }] as never,
    });

    expect(screen.getByRole("button", { name: "Gabarit de jalons" })).not.toBeDisabled();
  });
});

// Basse review finding #5 (E12-06/#278): "Ajouter une ligne MO" sits in the same
// `canEditEstimate ?` block as "Ajouter une tâche au planning", so it's correct by
// construction -- these tests just make that explicit instead of leaving it unasserted.
describe("EstimateTab 'Ajouter une ligne MO' visibility (E12-06)", () => {
  afterEach(() => cleanup());

  it("opens the role-assignment dialog when clicked, with canEditEstimate: true", () => {
    const onOpenRoleAssignmentDialog = vi.fn();
    renderTab({ canEditEstimate: true, onOpenRoleAssignmentDialog });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter une ligne MO" }));

    expect(onOpenRoleAssignmentDialog).toHaveBeenCalledTimes(1);
  });

  it("is absent when canEditEstimate is false", () => {
    renderTab({ canEditEstimate: false });

    expect(screen.queryByRole("button", { name: "Ajouter une ligne MO" })).not.toBeInTheDocument();
  });
});
