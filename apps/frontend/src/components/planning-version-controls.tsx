"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Revision } from "@/lib/backend";

const REVISION_STATUS_LABELS: Readonly<Record<Revision["status"], string>> = {
  draft: "brouillon",
  validated: "validée",
  superseded: "remplacée",
};

const REVISION_KIND_LABELS: Readonly<Record<Revision["kind"], string>> = {
  initial: "initiale",
  contract_reference: "référence contractuelle",
  forecast_remaining: "reste à engager",
};

/** "V3 (brouillon)", the one label the selector and the history table both use. */
export function revisionLabel(revision: Revision): string {
  return `V${revision.version_number} (${REVISION_STATUS_LABELS[revision.status]})`;
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString("fr-FR");
}

export type PlanningVersionControlsProps = Readonly<{
  revisions: Revision[];
  selectedRevisionId: number | null;
  selectedRevision: Revision | null;
  referenceRevisionId: number | null;
  revisionsBusy: boolean;
  mutationBusy: boolean;
  isReadOnlyProject: boolean;
  hasConflict: boolean;
  onSelectRevision: (revisionId: number) => void;
  onCreateDraft: () => void;
  onValidate: () => void;
  showReopenStructure: boolean;
  onReopenStructure: () => void;
}>;

// E14-10 (#336): what the planning version controls became once a "version de planning" is a
// **revision**. Three commands, matching the lifecycle the responsable produit stated:
//
// * *créer un brouillon* -- `POST .../copy`, offered whatever the source's status. From a
//   validated revision it is the only way to change anything (INV-03); from a draft it opens a
//   second variant. It is deliberately **not** labelled "nouvelle version du planning": the copy
//   carries the devis too, because they are one document;
// * *valider* -- offered on a draft only, and irreversible;
// * *consulter l'historique* -- the list of revisions with their status and their dates, which is
//   also where one is picked to be displayed.
//
// Undo/redo is gone rather than ported: it was built on `PUT .../tasks/restore`, an endpoint that
// replaced a planning's whole task/link set with a snapshot the client had kept, and E14-05 (#331)
// removed it. The revision model has no equivalent -- see the closing report of #336.
export function PlanningVersionControls({
  revisions,
  selectedRevisionId,
  selectedRevision,
  referenceRevisionId,
  revisionsBusy,
  mutationBusy,
  isReadOnlyProject,
  hasConflict,
  onSelectRevision,
  onCreateDraft,
  onValidate,
  showReopenStructure,
  onReopenStructure,
}: PlanningVersionControlsProps) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const busy = revisionsBusy || mutationBusy;
  const isDraft = selectedRevision?.status === "draft";

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/*
        The wrapping <label> is the control's accessible name. An aria-label on the <select> on
        top of it would win and leave the visible text purely decorative, so there is exactly one.
      */}
      {revisions.length ? (
        <label className="grid gap-1 text-xs text-muted-foreground">
          Révision affichée
          <select
            className="h-8 min-w-24 rounded-md border border-input bg-background px-2 text-sm text-foreground"
            value={selectedRevisionId ?? ""}
            disabled={busy}
            onChange={(event) => onSelectRevision(Number(event.target.value))}
          >
            {revisions.map((revision) => (
              <option key={revision.revision_id} value={revision.revision_id}>
                {revisionLabel(revision)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {isDraft ? (
        <Button
          variant="outline"
          type="button"
          disabled={busy || isReadOnlyProject || hasConflict}
          onClick={onValidate}
        >
          Valider la révision
        </Button>
      ) : null}
      {selectedRevision ? (
        <Button
          variant="outline"
          type="button"
          disabled={busy || isReadOnlyProject || hasConflict}
          onClick={onCreateDraft}
        >
          Créer un brouillon
        </Button>
      ) : null}
      {revisions.length ? (
        <Button variant="outline" type="button" onClick={() => setHistoryOpen(true)}>
          Historique
        </Button>
      ) : null}
      {showReopenStructure ? (
        <Button
          variant="outline"
          type="button"
          disabled={busy || isReadOnlyProject}
          onClick={onReopenStructure}
        >
          Rouvrir la structure
        </Button>
      ) : null}

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Historique des révisions</DialogTitle>
            <DialogDescription>
              Chaque révision porte l&apos;arbre du projet une seule fois, avec sa planification et
              son chiffrage. Sélectionne-en une pour l&apos;afficher.
            </DialogDescription>
          </DialogHeader>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Version</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Nature</TableHead>
                <TableHead>Créée le</TableHead>
                <TableHead>Validée le</TableHead>
                <TableHead>
                  <span className="sr-only">Afficher</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {revisions.map((revision) => (
                <TableRow key={revision.revision_id}>
                  <TableCell>
                    V{revision.version_number}
                    {revision.revision_id === referenceRevisionId ? " (référence)" : ""}
                  </TableCell>
                  <TableCell>{REVISION_STATUS_LABELS[revision.status]}</TableCell>
                  <TableCell>{REVISION_KIND_LABELS[revision.kind]}</TableCell>
                  <TableCell>{formatDateTime(revision.created_at)}</TableCell>
                  <TableCell>{formatDateTime(revision.validated_at)}</TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={busy || revision.revision_id === selectedRevisionId}
                      aria-label={`Afficher la révision V${revision.version_number}`}
                      onClick={() => {
                        onSelectRevision(revision.revision_id);
                        setHistoryOpen(false);
                      }}
                    >
                      Afficher
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setHistoryOpen(false)}>
              Fermer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
