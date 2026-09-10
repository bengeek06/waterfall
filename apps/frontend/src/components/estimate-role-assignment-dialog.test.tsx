import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EstimateRoleAssignmentDialog,
  type EstimateRoleAssignmentDialogProps,
} from "./estimate-role-assignment-dialog";

function renderDialog(overrides: Partial<EstimateRoleAssignmentDialogProps> = {}) {
  const props: EstimateRoleAssignmentDialogProps = {
    open: true,
    resourceNodes: [{ id: 1, code: "A", name: "Direction", parent_id: null }] as never,
    nodeId: "",
    onNodeIdChange: vi.fn(),
    roles: [],
    rolesLoading: false,
    roleId: "",
    onRoleIdChange: vi.fn(),
    estimateTaskRows: [
      { id: 1, estimate_id: 1, task_id: 42, parent_task_id: null, position: 1, task_name: "Terrassement", outline_number: "1", outline_level: 0, is_milestone: false },
    ] as never,
    taskId: "",
    onTaskIdChange: vi.fn(),
    quantity: "1",
    onQuantityChange: vi.fn(),
    hours: "0",
    onHoursChange: vi.fn(),
    projectCostCodes: [],
    costCodeId: "",
    onCostCodeIdChange: vi.fn(),
    comment: "",
    onCommentChange: vi.fn(),
    busy: false,
    error: null,
    onClose: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides,
  };
  return render(<EstimateRoleAssignmentDialog {...props} />);
}

describe("EstimateRoleAssignmentDialog", () => {
  afterEach(() => cleanup());

  it("disables the role selector until a node is chosen", () => {
    renderDialog({ nodeId: "" });

    expect(screen.getByLabelText("Rôle")).toBeDisabled();
  });

  it("enables the role selector once a node is chosen and lists the roles provided by the caller", () => {
    renderDialog({
      nodeId: "1",
      roles: [{ id: 5, name: "Développeur", node_id: 1, cost_category_id: 1, calendar_id: null, is_active: true }] as never,
    });

    expect(screen.getByLabelText("Rôle")).not.toBeDisabled();
    expect(screen.getByRole("option", { name: "Développeur" })).toBeInTheDocument();
  });

  it("reports a node change so the caller can load that node's roles", () => {
    const onNodeIdChange = vi.fn();
    renderDialog({ onNodeIdChange });

    fireEvent.change(screen.getByLabelText("Nœud organisationnel"), { target: { value: "1" } });

    expect(onNodeIdChange).toHaveBeenCalledWith("1");
  });

  it("only offers attachable tasks (task_id set) in the task selector", () => {
    renderDialog({
      estimateTaskRows: [
        { id: 1, estimate_id: 1, task_id: 42, parent_task_id: null, position: 1, task_name: "Terrassement", outline_number: "1", outline_level: 0, is_milestone: false },
        { id: 2, estimate_id: 1, task_id: null, parent_task_id: null, position: 2, task_name: "Sans jumeau", outline_number: "2", outline_level: 0, is_milestone: false },
      ] as never,
    });

    expect(screen.getByRole("option", { name: "Terrassement" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Sans jumeau" })).not.toBeInTheDocument();
  });

  it("submits via the Ajouter button", () => {
    const onSubmit = vi.fn();
    renderDialog({ onSubmit });

    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));

    expect(onSubmit).toHaveBeenCalled();
  });

  it("closes via Annuler", () => {
    const onClose = vi.fn();
    renderDialog({ onClose });

    fireEvent.click(screen.getByRole("button", { name: "Annuler" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("shows an error message when provided", () => {
    renderDialog({ error: "Couverture de taux incomplète pour cette tâche déjà datée." });

    expect(screen.getByRole("alert")).toHaveTextContent("Couverture de taux incomplète");
  });

  it("offers the project's cost codes as an optional cost-code selector", () => {
    renderDialog({
      projectCostCodes: [{ id: 10, code: "1.1", name: "Terrassement" }] as never,
    });

    expect(screen.getByRole("option", { name: "1.1 - Terrassement" })).toBeInTheDocument();
  });
});
