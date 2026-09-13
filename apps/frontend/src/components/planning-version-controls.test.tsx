import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Revision } from "@/lib/backend";
import { PlanningVersionControls, type PlanningVersionControlsProps } from "./planning-version-controls";

afterEach(() => cleanup());

function revision(overrides: Partial<Revision> = {}): Revision {
  return {
    revision_id: 7,
    project_id: 1,
    version_number: 1,
    kind: "initial",
    status: "draft",
    lock_version: 0,
    note: null,
    created_at: "2026-09-01T08:00:00Z",
    validated_at: null,
    ...overrides,
  };
}

function renderControls(overrides: Partial<PlanningVersionControlsProps> = {}) {
  const props: PlanningVersionControlsProps = {
    revisions: [revision()],
    selectedRevisionId: 7,
    selectedRevision: revision(),
    referenceRevisionId: null,
    revisionsBusy: false,
    mutationBusy: false,
    isReadOnlyProject: false,
    hasConflict: false,
    onSelectRevision: vi.fn(),
    onCreateDraft: vi.fn(),
    onValidate: vi.fn(),
    showReopenStructure: false,
    onReopenStructure: vi.fn(),
    ...overrides,
  };
  render(<PlanningVersionControls {...props} />);
  return props;
}

describe("PlanningVersionControls", () => {
  it("offers validation and draft creation on a draft revision", () => {
    const props = renderControls();

    fireEvent.click(screen.getByRole("button", { name: "Valider la révision" }));
    fireEvent.click(screen.getByRole("button", { name: "Créer un brouillon" }));

    expect(props.onValidate).toHaveBeenCalled();
    expect(props.onCreateDraft).toHaveBeenCalled();
  });

  it("offers to open a draft from a validated revision, and never to validate it again", () => {
    renderControls({
      revisions: [revision({ status: "validated" })],
      selectedRevision: revision({ status: "validated" }),
    });

    expect(screen.queryByRole("button", { name: "Valider la révision" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Créer un brouillon" })).toBeInTheDocument();
  });

  it("disables every write command on a read-only project", () => {
    renderControls({ isReadOnlyProject: true });

    expect(screen.getByRole("button", { name: "Valider la révision" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Créer un brouillon" })).toBeDisabled();
  });

  it("disables every write command while a lock conflict is unresolved", () => {
    renderControls({ hasConflict: true });

    expect(screen.getByRole("button", { name: "Valider la révision" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Créer un brouillon" })).toBeDisabled();
  });

  it("labels each revision by version and status in the selector", () => {
    renderControls({
      revisions: [revision({ revision_id: 7, version_number: 1, status: "validated" }), revision({ revision_id: 8, version_number: 2 })],
    });

    const selector = screen.getByRole("combobox", { name: "Révision affichée" });
    expect(within(selector).getByText("V1 (validée)")).toBeInTheDocument();
    expect(within(selector).getByText("V2 (brouillon)")).toBeInTheDocument();
  });

  it("selects another revision from the selector", () => {
    const props = renderControls({
      revisions: [revision({ revision_id: 7 }), revision({ revision_id: 8, version_number: 2 })],
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Révision affichée" }), { target: { value: "8" } });

    expect(props.onSelectRevision).toHaveBeenCalledWith(8);
  });

  it("shows the history with each revision's status, nature and dates, and marks the reference", () => {
    renderControls({
      revisions: [
        revision({ revision_id: 7, version_number: 1, status: "validated", validated_at: "2026-09-02T09:00:00Z" }),
        revision({ revision_id: 8, version_number: 2, kind: "forecast_remaining" }),
      ],
      referenceRevisionId: 7,
    });

    fireEvent.click(screen.getByRole("button", { name: "Historique" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("V1 (référence)")).toBeInTheDocument();
    expect(within(dialog).getByText("reste à engager")).toBeInTheDocument();
    expect(within(dialog).getAllByText("validée").length).toBeGreaterThan(0);
  });

  it("displays a revision picked from the history and closes it", () => {
    const props = renderControls({
      revisions: [revision({ revision_id: 7 }), revision({ revision_id: 8, version_number: 2 })],
    });

    fireEvent.click(screen.getByRole("button", { name: "Historique" }));
    fireEvent.click(screen.getByRole("button", { name: "Afficher la révision V2" }));

    expect(props.onSelectRevision).toHaveBeenCalledWith(8);
  });

  it("offers nothing at all when the project has no revision yet", () => {
    renderControls({ revisions: [], selectedRevision: null, selectedRevisionId: null });

    expect(screen.queryByRole("combobox", { name: "Révision affichée" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Créer un brouillon" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Historique" })).not.toBeInTheDocument();
  });
});
