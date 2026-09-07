import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlanningImportPanel, type PlanningImportPanelProps } from "./planning-import-panel";

afterEach(() => cleanup());

function renderPanel(overrides: Partial<PlanningImportPanelProps> = {}) {
  const props: PlanningImportPanelProps = {
    projectStatusInitialise: true,
    importFile: null,
    importBusy: false,
    onFileChange: vi.fn(),
    onFilesDrop: vi.fn(),
    onPreview: vi.fn(),
    planningExportBusy: false,
    onExportXml: vi.fn(),
    importReview: null,
    onConfirmImport: vi.fn(),
    ...overrides,
  };
  render(<PlanningImportPanel {...props} />);
  return props;
}

function getDropZone() {
  return screen.getByRole("group", { name: "Zone de dépôt du fichier de planning à importer" });
}

describe("PlanningImportPanel", () => {
  it("shows a visual affordance while a file is dragged over the drop zone and clears it on leave", () => {
    renderPanel();
    const zone = getDropZone();

    expect(zone.className).not.toContain("border-primary");

    fireEvent.dragEnter(zone);
    expect(zone.className).toContain("border-primary");

    fireEvent.dragLeave(zone);
    expect(zone.className).not.toContain("border-primary");
  });

  it("keeps the visual affordance while the pointer briefly crosses a child element", () => {
    renderPanel();
    const zone = getDropZone();
    const label = screen.getByText("Importer un planning MS Project (.xml)");
    const previewButton = screen.getByRole("button", { name: "Prévisualiser l'import" });

    fireEvent.dragEnter(zone);
    expect(zone.className).toContain("border-primary");

    fireEvent.dragEnter(label);
    fireEvent.dragLeave(label);
    expect(zone.className).toContain("border-primary");

    fireEvent.dragEnter(previewButton);
    fireEvent.dragLeave(previewButton);
    expect(zone.className).toContain("border-primary");

    fireEvent.dragLeave(zone);
    expect(zone.className).not.toContain("border-primary");
  });

  it("does not throw and keeps the affordance absent when dragLeave fires without a matching dragEnter", () => {
    renderPanel();
    const zone = getDropZone();

    expect(() => {
      fireEvent.dragLeave(zone);
      fireEvent.dragLeave(zone);
    }).not.toThrow();
    expect(zone.className).not.toContain("border-primary");
  });

  it("calls onFilesDrop with the dropped files", () => {
    const props = renderPanel();
    const zone = getDropZone();
    const file = new File(["<Project />"], "planning.xml", { type: "application/xml" });

    fireEvent.drop(zone, { dataTransfer: { files: [file] } });

    expect(props.onFilesDrop).toHaveBeenCalledTimes(1);
    const droppedFiles = (props.onFilesDrop as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(droppedFiles[0]).toBe(file);
  });

  it("keeps the manual file input available and labelled", () => {
    renderPanel();
    expect(screen.getByLabelText("Importer un planning MS Project (.xml)")).toBeInTheDocument();
  });
});
