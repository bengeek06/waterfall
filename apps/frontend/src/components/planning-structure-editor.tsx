"use client";

import { Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { PlanningStructureDraftRow } from "@/lib/planning-structure";

export type PlanningStructureGroup = {
  groupId: string;
  postKey: string;
  postName: string;
  lots: { row: PlanningStructureDraftRow }[];
};

export type PlanningStructureEditorProps = {
  structureOpen: boolean;
  isReadOnlyProject: boolean;
  postGroups: PlanningStructureGroup[];
  structureDraft: PlanningStructureDraftRow[];
  structureBusy: boolean;
  structureAction: "save" | "generate" | "skip" | null;
  canSkipStructure: boolean;
  onUpdatePostField: (postKey: string, field: "postKey" | "postName", value: string) => void;
  onUpdateLotField: (rowId: string, field: "lotKey" | "lotName", value: string) => void;
  onUpdateDeliverable: (rowId: string, deliverableIndex: number, value: string) => void;
  onAddDeliverable: (rowId: string) => void;
  onRemoveDeliverable: (rowId: string, deliverableIndex: number) => void;
  onRemoveLot: (rowId: string) => void;
  onAddLotToPost: (postKey: string, postName: string) => void;
  onAddPost: () => void;
  onSave: () => void;
  onGenerate: () => void;
  onSkip: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the "lotissement" (posts/lots/deliverables)
// structure editor card, shown while the project's planning structure hasn't been generated yet.
// Verbatim JSX move -- see page.tsx call site for wiring.
export function PlanningStructureEditor({
  structureOpen,
  isReadOnlyProject,
  postGroups,
  structureDraft,
  structureBusy,
  structureAction,
  canSkipStructure,
  onUpdatePostField,
  onUpdateLotField,
  onUpdateDeliverable,
  onAddDeliverable,
  onRemoveDeliverable,
  onRemoveLot,
  onAddLotToPost,
  onAddPost,
  onSave,
  onGenerate,
  onSkip,
}: PlanningStructureEditorProps) {
  if (!structureOpen || isReadOnlyProject) {
    return null;
  }

  return (
    <Card className="mb-4">
      <CardContent className="pt-6">
        <h2 className="text-lg font-semibold">Lotissement du projet</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Décris la décomposition du projet en postes, lots et livrables. « Enregistrer »
          sauvegarde un brouillon sans quitter cet écran ; « Générer le squelette » crée le
          planning à partir de cette décomposition et t&apos;amène sur sa page.
        </p>
        {postGroups.map((group, postIndex) => (
          <div className="mt-4 rounded-lg border p-4" key={group.groupId}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                aria-label={`Clé poste ${postIndex + 1}`}
                placeholder="Clé poste"
                value={group.postKey}
                onChange={(event) => onUpdatePostField(group.postKey, "postKey", event.target.value)}
              />
              <Input
                aria-label={`Nom poste ${postIndex + 1}`}
                placeholder="Poste"
                value={group.postName}
                onChange={(event) => onUpdatePostField(group.postKey, "postName", event.target.value)}
              />
            </div>

            {group.lots.map(({ row }, lotIndex) => {
              const deliverables = row.deliverables.split(",");
              return (
                <div className="mt-3 grid gap-3 rounded-md border bg-muted/30 p-3" key={row.rowId}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="grid flex-1 gap-3 sm:grid-cols-2">
                      <Input
                        aria-label={`Clé lot ${postIndex + 1}.${lotIndex + 1}`}
                        placeholder="Clé lot"
                        value={row.lotKey}
                        onChange={(event) => onUpdateLotField(row.rowId, "lotKey", event.target.value)}
                      />
                      <Input
                        aria-label={`Nom lot ${postIndex + 1}.${lotIndex + 1}`}
                        placeholder="Lot"
                        value={row.lotName}
                        onChange={(event) => onUpdateLotField(row.rowId, "lotName", event.target.value)}
                      />
                    </div>
                    {structureDraft.length > 1 ? (
                      <Button
                        variant="destructive"
                        size="sm"
                        type="button"
                        aria-label={`Supprimer le lot ${postIndex + 1}.${lotIndex + 1}`}
                        onClick={() => onRemoveLot(row.rowId)}
                      >
                        Supprimer le lot
                      </Button>
                    ) : null}
                  </div>

                  <p className="text-xs font-medium text-muted-foreground">Livrables</p>
                  {deliverables.map((deliverable, deliverableIndex) => (
                    <div className="flex items-center gap-2" key={deliverableIndex}>
                      <Input
                        aria-label={`Livrable ${postIndex + 1}.${lotIndex + 1}.${deliverableIndex + 1}`}
                        placeholder="Nom du livrable"
                        value={deliverable}
                        onChange={(event) => onUpdateDeliverable(row.rowId, deliverableIndex, event.target.value)}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        type="button"
                        aria-label={`Supprimer le livrable ${postIndex + 1}.${lotIndex + 1}.${deliverableIndex + 1}`}
                        onClick={() => onRemoveDeliverable(row.rowId, deliverableIndex)}
                      >
                        Supprimer
                      </Button>
                    </div>
                  ))}
                  <Button variant="outline" size="sm" type="button" className="w-fit" onClick={() => onAddDeliverable(row.rowId)}>
                    Ajouter un livrable
                  </Button>
                </div>
              );
            })}

            <Button
              variant="outline"
              size="sm"
              type="button"
              className="mt-3"
              onClick={() => onAddLotToPost(group.postKey, group.postName)}
            >
              Ajouter un lot
            </Button>
          </div>
        ))}
        <Button variant="outline" size="sm" type="button" className="mt-4 w-fit" onClick={onAddPost}>
          Ajouter un poste
        </Button>

        <div className="mt-6 flex flex-wrap gap-2 border-t pt-4">
          <Button variant="outline" type="button" disabled={structureBusy} onClick={onSave}>
            <Save aria-hidden="true" />
            {structureAction === "save" ? "Enregistrement..." : "Enregistrer"}
          </Button>
          <Button type="button" disabled={structureBusy} onClick={onGenerate}>
            {structureAction === "generate" ? "Génération..." : "Générer le squelette"}
          </Button>
          {canSkipStructure ? (
            <Button type="button" disabled={structureBusy} onClick={onSkip}>
              {structureAction === "skip" ? "Passage en cours..." : "Passer cette étape"}
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
