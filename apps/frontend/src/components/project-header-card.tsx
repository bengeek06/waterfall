"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Project } from "@/lib/backend";

export type ProjectInfoDraft = { name: string; shortDescription: string };

export type ProjectHeaderCardProps = {
  project: Project | null;
  projectId: number;
  editingProjectInfo: boolean;
  projectInfoDraft: ProjectInfoDraft;
  projectInfoBusy: boolean;
  isReadOnlyProject: boolean;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the top header card, either displaying the
// project's name/code/description or an inline edit form for them. Verbatim JSX move -- see
// page.tsx call site for wiring.
export function ProjectHeaderCard({
  project,
  projectId,
  editingProjectInfo,
  projectInfoDraft,
  projectInfoBusy,
  isReadOnlyProject,
  onNameChange,
  onDescriptionChange,
  onStartEdit,
  onCancelEdit,
  onSave,
}: ProjectHeaderCardProps) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {editingProjectInfo ? (
            <div className="grid max-w-2xl gap-4">
              <div className="grid gap-2">
                <Label htmlFor="project-info-name">Nom du projet</Label>
                <Input
                  id="project-info-name"
                  value={projectInfoDraft.name}
                  onChange={(event) => onNameChange(event.target.value)}
                  maxLength={255}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="project-info-description">Description courte</Label>
                <Textarea
                  id="project-info-description"
                  rows={2}
                  value={projectInfoDraft.shortDescription}
                  onChange={(event) => onDescriptionChange(event.target.value)}
                  maxLength={500}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" disabled={projectInfoBusy} onClick={onSave}>
                  Sauver
                </Button>
                <Button variant="outline" type="button" onClick={onCancelEdit}>
                  Annuler
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold">{project?.name ?? `Projet #${projectId}`}</h1>
                {project?.code ? <Badge variant="outline">{project.code}</Badge> : null}
              </div>
              <p className="mt-1 text-sm text-muted-foreground italic">
                {project?.short_description ?? "Pilotage du planning et des versions de devis."}
              </p>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!editingProjectInfo && !isReadOnlyProject ? (
            <Button variant="outline" type="button" onClick={onStartEdit}>
              Modifier
            </Button>
          ) : null}
          <Button variant="outline" nativeButton={false} render={<Link href="/projects" />}>Retour projets</Button>
        </div>
      </CardContent>
    </Card>
  );
}
