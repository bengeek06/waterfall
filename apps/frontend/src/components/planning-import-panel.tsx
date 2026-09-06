"use client";

import type { ChangeEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ImportDiff } from "@/lib/backend";

export type PlanningImportPanelProps = {
  projectStatusInitialise: boolean;
  importFile: File | null;
  importBusy: boolean;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
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
  onPreview,
  planningExportBusy,
  onExportXml,
  importReview,
  onConfirmImport,
}: PlanningImportPanelProps) {
  return (
    <>
      {projectStatusInitialise ? (
        <Card className="mb-4">
          <CardContent className="flex flex-wrap items-end justify-between gap-4 pt-6">
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid gap-2">
                <Label htmlFor="planning-import-file">Importer un planning MS Project (.xml)</Label>
                <Input
                  id="planning-import-file"
                  type="file"
                  accept=".xml,application/xml,text/xml"
                  onChange={onFileChange}
                />
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
