import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EstimateMilestoneTemplateDialog,
  type EstimateMilestoneTemplateDialogProps,
} from "./estimate-milestone-template-dialog";

function renderDialog(overrides: Partial<EstimateMilestoneTemplateDialogProps> = {}) {
  const props: EstimateMilestoneTemplateDialogProps = {
    open: true,
    costLineLabel: "Fourniture ascenseur",
    template: "fourniture",
    intermediateMilestonesCount: "0",
    lagMinutes: "0",
    busy: false,
    error: null,
    requiresPlanningDraft: false,
    onTemplateChange: vi.fn(),
    onIntermediateMilestonesCountChange: vi.fn(),
    onLagMinutesChange: vi.fn(),
    onClose: vi.fn(),
    onSubmit: vi.fn(),
    onReopenStructure: vi.fn(),
    ...overrides,
  };
  return render(<EstimateMilestoneTemplateDialog {...props} />);
}

describe("EstimateMilestoneTemplateDialog", () => {
  afterEach(() => cleanup());

  it("shows the targeted cost line's label", () => {
    renderDialog({ costLineLabel: "Fourniture ascenseur" });

    expect(screen.getByText(/Fourniture ascenseur/)).toBeInTheDocument();
  });

  it("hides the intermediate-milestones-count field for the fourniture template", () => {
    renderDialog({ template: "fourniture" });

    expect(screen.queryByLabelText("Nombre de jalons intermédiaires")).not.toBeInTheDocument();
  });

  it("shows the intermediate-milestones-count field for the sous_traitance template", () => {
    renderDialog({ template: "sous_traitance" });

    expect(screen.getByLabelText("Nombre de jalons intermédiaires")).toBeInTheDocument();
  });

  it("reports a template change", () => {
    const onTemplateChange = vi.fn();
    renderDialog({ onTemplateChange });

    fireEvent.change(screen.getByLabelText("Gabarit de jalons"), { target: { value: "sous_traitance" } });

    expect(onTemplateChange).toHaveBeenCalledWith("sous_traitance");
  });

  it("reports a lag change", () => {
    const onLagMinutesChange = vi.fn();
    renderDialog({ onLagMinutesChange });

    fireEvent.change(screen.getByLabelText("Délai entre jalons, en minutes"), { target: { value: "120" } });

    expect(onLagMinutesChange).toHaveBeenCalledWith("120");
  });

  it("calls onSubmit when 'Appliquer' is clicked", () => {
    const onSubmit = vi.fn();
    renderDialog({ onSubmit });

    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("shows the error message and offers a reopen-structure action only when requiresPlanningDraft is set", () => {
    const onReopenStructure = vi.fn();
    renderDialog({
      error: "Le planning affiché n'est plus un brouillon.",
      requiresPlanningDraft: true,
      onReopenStructure,
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Le planning affiché n'est plus un brouillon.");
    fireEvent.click(screen.getByRole("button", { name: "Rouvrir la structure" }));
    expect(onReopenStructure).toHaveBeenCalledTimes(1);
  });

  it("does not offer the reopen-structure action for a generic error", () => {
    renderDialog({ error: "Une erreur est survenue.", requiresPlanningDraft: false });

    expect(screen.queryByRole("button", { name: "Rouvrir la structure" })).not.toBeInTheDocument();
  });
});
