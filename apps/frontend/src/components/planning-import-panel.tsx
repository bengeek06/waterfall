"use client";

import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ImportCostLoss, ImportDiff, ImportDiffItem } from "@/lib/backend";
import { cn } from "@/lib/utils";

/** Where the last confirmed import landed, as the page resolves it from the revision list. */
export type PlanningImportTarget = {
  revisionId: number;
  /** "V3" -- the version number the user sees, or null when the list could not be refreshed. */
  versionLabel: string | null;
  /** True when the import had to create that revision because the project had none. */
  created: boolean;
};

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
  /** Set once an import has actually been applied; null while none has been in this session. */
  importTarget: PlanningImportTarget | null;
};

const EUROS = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

function formatAmount(amount: string): string {
  const value = Number(amount);
  return Number.isFinite(value) ? EUROS.format(value) : `${amount} €`;
}

/**
 * The project-level, **deduplicated** total of the chiffrage this import would destroy.
 *
 * This is the only summable list the diff carries. The per-item lists attribute the same loss to
 * every vanished task that takes it away -- a cost node condemned by two nested deletions appears
 * in both -- so adding them up would show an amount that is simply false. Hence the split this
 * panel implements: the total at the project level, the names at the item level, never the
 * reverse.
 *
 * A malformed amount is skipped rather than added: `Number("")` is NaN and a single one of them
 * turns the whole total into "NaN €", while the per-line display right below degrades gracefully
 * (see formatAmount). Same guard, same behaviour, on both sides of the panel.
 */
function totalCostLoss(losses: readonly ImportCostLoss[]): string {
  const total = losses.reduce((sum, loss) => {
    const amount = Number(loss.amount);
    return Number.isFinite(amount) ? sum + amount : sum;
  }, 0);
  return EUROS.format(total);
}

function itemsWithCostLosses(diff: ImportDiff): ImportDiffItem[] {
  return diff.items.filter((item) => item.costLosses.length > 0);
}

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
  importTarget,
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
    // Chromium can represent a dropped directory as a zero-byte file-like entry, so a directory
    // named e.g. "planning.xml" would otherwise pass the extension/size checks downstream and be
    // treated as a valid import file. `dataTransfer.files` alone can't tell a directory apart from
    // a real file, so inspect `dataTransfer.items` via the (widely supported, if oddly prefixed)
    // `webkitGetAsEntry()` API and reject the whole drop as unusable if any entry is a directory.
    const items = event.dataTransfer.items;
    const hasDirectoryEntry = items
      ? Array.from(items).some((item) => {
          const entry = typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null;
          return entry?.isDirectory === true;
        })
      : false;
    // Always forward the drop, even an empty FileList: some browsers (e.g. Firefox dropping a
    // directory) report zero files, and a silent no-op here would leave the user without any
    // feedback. Let the page decide how to report an unusable drop (see onImportFilesDrop) --
    // the native input is then synced from its decision (the `importFile` prop) by the effect
    // above, not from this raw, possibly-rejected FileList.
    onFilesDrop(hasDirectoryEntry ? new DataTransfer().files : event.dataTransfer.files);
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
            Le planning de la révision ciblée ne sera remplacé qu&apos;après confirmation explicite.
          </AlertDescription>
          {importReview.diff.identicalSource ? (
            <AlertDescription>La source est identique à la dernière importation.</AlertDescription>
          ) : null}
          {/*
            Règle 3 : une suppression ne doit jamais être silencieuse. Le total dédoublonné est
            affiché ici, au niveau du projet -- c'est le seul montant juste -- et les libellés sont
            nommés item par item juste en dessous, sans montant cumulé.
          */}
          {importReview.diff.costLosses.length ? (
            <AlertDescription>
              <strong>
                Cet import supprimera {importReview.diff.costLosses.length} ligne(s) de chiffrage,
                pour un total de {totalCostLoss(importReview.diff.costLosses)}.
              </strong>
              <ul className="mt-2 list-disc pl-5 text-sm">
                {itemsWithCostLosses(importReview.diff).map((item) => (
                  <li key={`${item.kind}-${item.uid}`}>
                    {item.message}
                    <span className="text-muted-foreground">
                      {" "}
                      — chiffrage emporté :{" "}
                      {item.costLosses.map((loss) => `${loss.label} (${formatAmount(loss.amount)})`).join(", ")}
                    </span>
                  </li>
                ))}
              </ul>
            </AlertDescription>
          ) : null}
          <Button className="mt-3" variant="destructive" type="button" disabled={importBusy} onClick={onConfirmImport}>
            {importBusy ? "Import..." : "Confirmer le remplacement"}
          </Button>
        </Alert>
      ) : null}

      {importTarget ? (
        <Alert className="mb-4">
          <AlertTitle><h2>Import appliqué</h2></AlertTitle>
          {/*
            L'import vise toujours la dernière révision du projet par numéro de version et le client
            ne la choisit pas : sans cette restitution, un utilisateur qui croit alimenter un
            brouillon alors qu'un plus récent existe ne l'apprendrait jamais.
          */}
          <AlertDescription>
            Le fichier a été importé dans la révision {importTarget.versionLabel ?? `#${importTarget.revisionId}`}
            {importTarget.created
              ? ", créée pour l'occasion : le projet n'en avait aucune."
              : ", la plus récente du projet."}
          </AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}
