"use client";

import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ImportDiff } from "@/lib/backend";
import { cn } from "@/lib/utils";

export type PlanningImportPanelProps = {
  projectStatusInitialise: boolean;
  importFile: File | null;
  importBusy: boolean;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onFilesDrop: (files: FileList) => void;
  onPreview: () => void;
  planningExportBusy: boolean;
  onExportXml: () => void;
  importReview: { batchId: number; diff: ImportDiff } | null;
  onConfirmImport: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the MS Project import card (file input +
// preview + XML export) and its "replacement to confirm" review banner. The two blocks are
// gated independently, exactly as in the original inline JSX. Verbatim JSX move -- see page.tsx
// call site for wiring.
export function PlanningImportPanel({
  projectStatusInitialise,
  importFile,
  importBusy,
  onFileChange,
  onFilesDrop,
  onPreview,
  planningExportBusy,
  onExportXml,
  importReview,
  onConfirmImport,
}: PlanningImportPanelProps) {
  // dragenter/dragleave bubble up from the label/input/button children of the drop zone, so a
  // naive boolean toggled directly by those events would flicker off every time the pointer
  // crosses a child element. A depth counter absorbs that bubbling: it only reaches zero once the
  // pointer has actually left every nested element, at which point the visual affordance clears.
  const [dragDepth, setDragDepth] = useState(0);
  const isDraggingOver = dragDepth > 0;
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Keep the native input in sync with `importFile`, the single source of truth for what was
  // actually accepted -- not with whatever raw FileList a drop happened to carry. `importFile` is
  // set by the page after it has decided whether a drop/selection is usable (right type, single
  // file, ...), so this effect covers both the manual-picker and drag-and-drop paths without
  // duplicating that decision here.
  useEffect(() => {
    const nativeInput = fileInputRef.current;
    if (!nativeInput) {
      return;
    }
    if (importFile) {
      try {
        const transfer = new DataTransfer();
        transfer.items.add(importFile);
        nativeInput.files = transfer.files;
      } catch {
        // Best-effort only: the canonical, always-accurate visible/announced state is the
        // paragraph below driven directly by `importFile`, not this native input's own display.
      }
    } else {
      nativeInput.value = "";
    }
  }, [importFile]);

  function onDropZoneDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragDepth((depth) => depth + 1);
  }

  function onDropZoneDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
  }

  function onDropZoneDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragDepth((depth) => Math.max(0, depth - 1));
  }

  function onDropZoneDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragDepth(0);
    // Always forward the drop, even an empty FileList: some browsers (e.g. Firefox dropping a
    // directory) report zero files, and a silent no-op here would leave the user without any
    // feedback. Let the page decide how to report an unusable drop (see onImportFilesDrop) --
    // the native input is then synced from its decision (the `importFile` prop) by the effect
    // above, not from this raw, possibly-rejected FileList.
    onFilesDrop(event.dataTransfer.files);
  }

  return (
    <>
      {projectStatusInitialise ? (
        <Card className="mb-4">
          <CardContent className="flex flex-wrap items-end justify-between gap-4 pt-6">
            <div
              role="group"
              aria-label="Zone de dépôt du fichier de planning à importer"
              onDragEnter={onDropZoneDragEnter}
              onDragOver={onDropZoneDragOver}
              onDragLeave={onDropZoneDragLeave}
              onDrop={onDropZoneDrop}
              className={cn(
                "flex flex-wrap items-end gap-3 rounded-lg border-2 border-dashed border-transparent p-2 transition-colors",
                isDraggingOver && "border-primary bg-muted/50",
              )}
            >
              <div className="grid gap-2">
                <Label htmlFor="planning-import-file">Importer un planning MS Project (.xml)</Label>
                <p className="text-sm text-muted-foreground">
                  Glissez-déposez un fichier XML ici, ou choisissez-le ci-dessous.
                </p>
                <Input
                  ref={fileInputRef}
                  id="planning-import-file"
                  type="file"
                  accept=".xml,application/xml,text/xml"
                  onChange={onFileChange}
                />
                <p className="text-sm" aria-live="polite">
                  {importFile ? `Fichier sélectionné : ${importFile.name}` : "Aucun fichier sélectionné."}
                </p>
              </div>
              <Button type="button" disabled={!importFile || importBusy} onClick={onPreview}>
                {importBusy ? "Prévisualisation..." : "Prévisualiser l'import"}
              </Button>
            </div>
            <Button variant="outline" type="button" disabled={planningExportBusy} onClick={onExportXml}>
              {planningExportBusy ? "Export..." : "Export XML"}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {importReview ? (
        <Alert className="mb-4">
          <AlertTitle><h2>Remplacement à confirmer</h2></AlertTitle>
          <AlertDescription>
            Cette prévisualisation contient {importReview.diff.items.length} changement(s).
            Le planning actuel ne sera remplacé qu&apos;après confirmation explicite.
          </AlertDescription>
          {importReview.diff.identicalSource ? (
            <AlertDescription>La source est identique à la dernière importation.</AlertDescription>
          ) : null}
          <Button className="mt-3" variant="destructive" type="button" disabled={importBusy} onClick={onConfirmImport}>
            {importBusy ? "Import..." : "Confirmer le remplacement"}
          </Button>
        </Alert>
      ) : null}
    </>
  );
}
