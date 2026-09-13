import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportCostLoss, ImportDiff, ImportDiffItem } from "@/lib/backend";
import { PlanningImportPanel, type PlanningImportPanelProps } from "./planning-import-panel";

afterEach(() => cleanup());

function buildProps(overrides: Partial<PlanningImportPanelProps> = {}): PlanningImportPanelProps {
  return {
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
    importTarget: null,
    ...overrides,
  };
}

function renderPanel(overrides: Partial<PlanningImportPanelProps> = {}) {
  const props = buildProps(overrides);
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

  it("still forwards an empty dropped file list instead of silently ignoring the drop", () => {
    const props = renderPanel();
    const zone = getDropZone();

    fireEvent.drop(zone, { dataTransfer: { files: [] } });

    expect(props.onFilesDrop).toHaveBeenCalledTimes(1);
    const droppedFiles = (props.onFilesDrop as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(droppedFiles.length).toBe(0);
  });

  // Regression coverage for the round-2 Copilot review on #132: Chromium can expose a dropped
  // directory as a zero-byte file-like entry that carries whatever name the directory has (e.g.
  // "dossier.xml"), which would otherwise pass the extension/size checks downstream and be
  // treated as a valid import. `webkitGetAsEntry()` is the only way to tell the entry is really a
  // directory, so the drop must be rejected (forwarded as an empty FileList) before it ever
  // reaches the page's file-based validation.
  it("rejects a dropped directory disguised as a .xml file via webkitGetAsEntry", () => {
    const originalDataTransfer = (globalThis as { DataTransfer?: unknown }).DataTransfer;
    class FakeDataTransfer {
      private readonly collected: File[] = [];
      items = {
        add: (file: File) => {
          this.collected.push(file);
        },
      };
      get files() {
        return this.collected as unknown as FileList;
      }
    }
    (globalThis as { DataTransfer?: unknown }).DataTransfer = FakeDataTransfer;

    try {
      const props = renderPanel();
      const zone = getDropZone();
      const disguisedDirectoryFile = new File([], "dossier.xml", { type: "application/xml" });

      fireEvent.drop(zone, {
        dataTransfer: {
          files: [disguisedDirectoryFile],
          items: [{ webkitGetAsEntry: () => ({ isDirectory: true }) }],
        },
      });

      expect(props.onFilesDrop).toHaveBeenCalledTimes(1);
      const droppedFiles = (props.onFilesDrop as ReturnType<typeof vi.fn>).mock.calls[0][0];
      expect(droppedFiles.length).toBe(0);
    } finally {
      (globalThis as { DataTransfer?: unknown }).DataTransfer = originalDataTransfer;
    }
  });

  it("shows no file selected by default and reflects the importFile prop when set", () => {
    renderPanel();
    expect(screen.getByText("Aucun fichier sélectionné.")).toBeInTheDocument();

    const file = new File(["<Project />"], "planning.xml", { type: "application/xml" });
    cleanup();
    renderPanel({ importFile: file });
    expect(screen.getByText("Fichier sélectionné : planning.xml")).toBeInTheDocument();
    expect(screen.queryByText("Aucun fichier sélectionné.")).not.toBeInTheDocument();
  });

  // Regression coverage for #132: the native file input must follow the `importFile` prop (the
  // page's accept/reject decision), never the raw FileList a drop happened to carry. jsdom doesn't
  // implement `DataTransfer` at all, and its native `HTMLInputElement.files` setter rejects
  // anything that isn't a real, browser-constructed FileList -- both throw under test, which used
  // to silently mask the bug (the `catch` branch always ran, never the `try`). Stubbing both lets
  // the component's actual try-path run so these tests can fail against the old, buggy code.
  describe("native file input sync with the importFile prop", () => {
    let filesValue: FileList | undefined;
    let originalFilesDescriptor: PropertyDescriptor | undefined;
    let originalDataTransfer: unknown;

    beforeEach(() => {
      filesValue = undefined;
      originalFilesDescriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files");
      Object.defineProperty(HTMLInputElement.prototype, "files", {
        configurable: true,
        get() {
          return filesValue;
        },
        set(value: FileList) {
          filesValue = value;
        },
      });

      originalDataTransfer = (globalThis as { DataTransfer?: unknown }).DataTransfer;
      class FakeDataTransfer {
        private readonly collected: File[] = [];
        items = {
          add: (file: File) => {
            this.collected.push(file);
          },
        };
        get files() {
          return this.collected as unknown as FileList;
        }
      }
      (globalThis as { DataTransfer?: unknown }).DataTransfer = FakeDataTransfer;
    });

    afterEach(() => {
      if (originalFilesDescriptor) {
        Object.defineProperty(HTMLInputElement.prototype, "files", originalFilesDescriptor);
      }
      (globalThis as { DataTransfer?: unknown }).DataTransfer = originalDataTransfer;
    });

    function getNativeInput() {
      return screen.getByLabelText("Importer un planning MS Project (.xml)") as HTMLInputElement;
    }

    it("reflects the accepted file on the native input", () => {
      const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
      renderPanel({ importFile: fileA });

      expect(getNativeInput().files?.[0]).toBe(fileA);
    });

    it("clears the native input once a previously accepted file is rejected (importFile goes back to null)", () => {
      const fileA = new File(["<Project />"], "a.xml", { type: "application/xml" });
      const props = buildProps({ importFile: fileA });
      const { rerender } = render(<PlanningImportPanel {...props} />);
      expect(getNativeInput().files?.[0]).toBe(fileA);

      // Simulates the page rejecting a subsequent drop/selection (wrong type, several files, ...)
      // by resetting `importFile` to null -- exactly what happens after `onImportFilesDrop` bails
      // out with an error, without ever touching the native input directly.
      rerender(<PlanningImportPanel {...props} importFile={null} />);

      expect(getNativeInput().value).toBe("");
    });

    it("reflects a newly accepted file on the native input (importFile from null to a file)", () => {
      const props = buildProps({ importFile: null });
      const { rerender } = render(<PlanningImportPanel {...props} />);

      const fileB = new File(["<Project />"], "b.xml", { type: "application/xml" });
      rerender(<PlanningImportPanel {...props} importFile={fileB} />);

      expect(getNativeInput().files?.[0]).toBe(fileB);
    });

    it("does not sync the native input from a raw drop directly, only from the resulting importFile prop", () => {
      // `onFilesDrop` is a plain vi.fn() here, exactly like a page that hasn't yet decided whether
      // to accept the drop: the panel must never assume the drop is accepted and must leave the
      // native input alone until it's told to via a new `importFile` value.
      renderPanel({ importFile: null });
      const zone = screen.getByRole("group", { name: "Zone de dépôt du fichier de planning à importer" });
      const wrongTypeFile = new File(["not xml"], "planning.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });

      fireEvent.drop(zone, { dataTransfer: { files: [wrongTypeFile] } });

      expect(getNativeInput().files).toBeUndefined();
    });
  });
});

// -------------------------------------------------------------------------------------------
// Règle 3's safeguard (#332): a deletion is never silent, and the two forms the contract carries
// are not interchangeable -- the deduplicated total at the project level, the labels per item.
// -------------------------------------------------------------------------------------------

function costLoss(overrides: Partial<ImportCostLoss> & { label: string; amount: string }): ImportCostLoss {
  return { nodeId: 1, workItemId: 1, nature: "labor", bearingTaskName: null, ...overrides };
}

function diffItem(overrides: Partial<ImportDiffItem> & { uid: number }): ImportDiffItem {
  return {
    kind: "removed",
    message: `Tâche ${overrides.uid} supprimée`,
    fields: [],
    costLosses: [],
    ...overrides,
  };
}

function diffWithLosses(): ImportDiff {
  const study = costLoss({ nodeId: 10, label: "Étude", amount: "1000.00" });
  const build = costLoss({ nodeId: 11, label: "Réalisation", amount: "500.00" });
  return {
    batchId: 7,
    sourceSha256: null,
    identicalSource: false,
    items: [
      // The parent's item carries *both* losses, the child's carries one of them: the same node is
      // attributed to every vanished task that takes it away.
      diffItem({ uid: 1, message: "Tâche 1 (Poste) supprimée", costLosses: [study, build] }),
      diffItem({ uid: 2, message: "Tâche 2 (Lot) supprimée", costLosses: [build] }),
    ],
    // The deduplicated total: 1000 + 500, not 1000 + 500 + 500.
    costLosses: [study, build],
  };
}

describe("PlanningImportPanel cost losses", () => {
  it("shows the deduplicated project-level total, not the sum of the per-item lists", () => {
    renderPanel({ importReview: { batchId: 7, diff: diffWithLosses() } });

    expect(screen.getByText(/2 ligne\(s\) de chiffrage/)).toBeInTheDocument();
    // 1 500 €, and never 2 000 € -- the per-item lists are not summable.
    expect(screen.getByText(/1\s*500,00/)).toBeInTheDocument();
    expect(screen.queryByText(/2\s*000,00/)).not.toBeInTheDocument();
  });

  it("names the chiffrage each vanished task takes away, item by item", () => {
    renderPanel({ importReview: { batchId: 7, diff: diffWithLosses() } });

    const firstItem = screen.getByText(/Tâche 1 \(Poste\) supprimée/);
    expect(firstItem.textContent).toContain("Étude");
    expect(firstItem.textContent).toContain("Réalisation");
    const secondItem = screen.getByText(/Tâche 2 \(Lot\) supprimée/);
    expect(secondItem.textContent).toContain("Réalisation");
  });

  it("says nothing about chiffrage when the import destroys none", () => {
    renderPanel({
      importReview: {
        batchId: 7,
        diff: { batchId: 7, sourceSha256: null, identicalSource: false, items: [], costLosses: [] },
      },
    });

    expect(screen.queryByText(/ligne\(s\) de chiffrage/)).not.toBeInTheDocument();
  });
});

describe("PlanningImportPanel import target", () => {
  it("says which revision the file landed in", () => {
    renderPanel({ importTarget: { revisionId: 12, versionLabel: "V3", created: false } });

    expect(screen.getByText(/importé dans la révision V3/)).toBeInTheDocument();
    expect(screen.getByText(/la plus récente du projet/)).toBeInTheDocument();
  });

  it("says when a revision had to be created for the file", () => {
    renderPanel({ importTarget: { revisionId: 12, versionLabel: "V1", created: true } });

    expect(screen.getByText(/créée pour l'occasion/)).toBeInTheDocument();
  });

  it("falls back on the revision id when the version number could not be resolved", () => {
    renderPanel({ importTarget: { revisionId: 12, versionLabel: null, created: false } });

    expect(screen.getByText(/importé dans la révision #12/)).toBeInTheDocument();
  });
});
