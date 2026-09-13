"use client";

import { PlanningConflictBanner } from "@/components/planning-conflict-banner";
import { PlanningImportPanel, type PlanningImportTarget } from "@/components/planning-import-panel";
import { PlanningStructureEditor, type PlanningStructureGroup } from "@/components/planning-structure-editor";
import { PlanningTreePanel } from "@/components/planning-tree-panel";
import { PlanningVersionControls, revisionLabel } from "@/components/planning-version-controls";
import type { CreateTaskCommand } from "@/hooks/use-planning-create-task-dialog";
import type { SchedulePayload } from "@/hooks/use-planning-schedule-drafts";
import type { RevisionLockConflict } from "@/hooks/use-revision-planning";
import type { ImportDiff, Project, Revision, RevisionPredecessorWrite, RevisionTree } from "@/lib/backend";
import { DEFAULT_PROJECT_CALENDAR, type ProjectCalendar } from "@/lib/planning-calendar";
import type { PlanningStructureDraftRow } from "@/lib/planning-structure";
import type { PlanningMoveMode } from "@/lib/planning-tree";
import type { ChangeEvent } from "react";

export type PlanningTabProps = {
  active: boolean;
  project: Project | null;
  isReadOnlyProject: boolean;

  // Import
  importFile: File | null;
  importBusy: boolean;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onFilesDrop: (files: FileList) => void;
  onPreviewImport: () => void;
  planningExportBusy: boolean;
  onExportXml: () => void;
  importReview: { batchId: number; diff: ImportDiff } | null;
  onConfirmImport: () => void;
  importTarget: PlanningImportTarget | null;

  // Structure editor
  structureOpen: boolean;
  postGroups: PlanningStructureGroup[];
  structureDraft: PlanningStructureDraftRow[];
  structureBusy: boolean;
  structureAction: "save" | "generate" | "skip" | "reopen" | null;
  onUpdatePostField: (postKey: string, field: "postKey" | "postName", value: string) => void;
  onUpdateLotField: (rowId: string, field: "lotKey" | "lotName", value: string) => void;
  onUpdateDeliverable: (rowId: string, deliverableIndex: number, value: string) => void;
  onAddDeliverable: (rowId: string) => void;
  onRemoveDeliverable: (rowId: string, deliverableIndex: number) => void;
  onRemoveLot: (rowId: string) => void;
  onAddLotToPost: (postKey: string, postName: string) => void;
  onAddPost: () => void;
  onSaveStructure: () => void;
  onGenerateStructure: () => void;
  onSkipStructure: () => void;

  // Revision controls
  revisions: Revision[];
  selectedRevision: Revision | null;
  selectedRevisionId: number | null;
  referenceRevisionId: number | null;
  revisionsBusy: boolean;
  onSelectRevision: (revisionId: number) => void;
  onCreateDraft: () => void;
  onValidateRevision: () => void;
  onReopenStructure: () => void;
  planningMutationBusy: boolean;
  /** Post-command feedback (a draft was created, a validation froze N lines, a deletion took chiffrage away). */
  revisionFeedback: string | null;

  // Conflict banner
  conflict: RevisionLockConflict | null;
  onReloadConflict: () => void;
  /** True when the page is already showing an error banner -- see PlanningTreePanel.hasError. */
  hasError: boolean;

  // Tree panel
  treeBusy: boolean;
  tree: RevisionTree | null;
  onMove: (mode: PlanningMoveMode, nodeIds: number[]) => void;
  onScheduleUpdate: (nodeId: number, payload: SchedulePayload) => Promise<boolean>;
  onEditLinks: (payload: { nodeId: number; predecessors: RevisionPredecessorWrite[] }) => Promise<void>;
  onCreateTask: (command: CreateTaskCommand) => void;
  onDeleteNodes: (nodeIds: number[]) => void;
};

// A skeleton can only be generated once, from a project that hasn't already got a displayed or
// reference planning -- mirrors the "Passer cette étape" button's original inline condition.
function canSkipPlanningStructure(project: Project | null): boolean {
  return (
    project?.status === "cree" &&
    project?.displayed_planning_id == null &&
    project?.planning_reference_id == null
  );
}

// Re-opening the structure editor is only offered once a planning skeleton already exists (the
// project is past "cree") and the project itself isn't read-only.
function canReopenPlanningStructure(project: Project | null, isReadOnlyProject: boolean): boolean {
  return !isReadOnlyProject && project?.status !== "cree";
}

/**
 * What the header says under "Révision affichée".
 *
 * "Aucune révision pour ce projet." is a *conclusion*, and it is only reachable once the list has
 * actually answered: asserted while the read is still in flight -- or after it failed -- it tells
 * the user the project is empty when it may be nothing of the sort.
 */
function revisionSubtitle(
  selectedRevision: Revision | null,
  revisionsBusy: boolean,
  hasError: boolean,
): string {
  if (selectedRevision) {
    return `${revisionLabel(selectedRevision)} - planning et devis d'une même révision`;
  }
  if (revisionsBusy) {
    return "Chargement des révisions...";
  }
  if (hasError) {
    return "Les révisions du projet n'ont pas pu être chargées.";
  }
  return "Aucune révision pour ce projet.";
}

// Falls back to DEFAULT_PROJECT_CALENDAR while the project hasn't loaded yet (e.g. first render):
// PlanningTreePanel/PlanningTreeTable/predecessorsLabel all require a concrete calendar to format
// durations/lags, and there is no meaningful project-specific value to derive one from before
// `project` itself is available.
function projectCalendar(project: Project | null): ProjectCalendar {
  if (!project) {
    return DEFAULT_PROJECT_CALENDAR;
  }
  return {
    minutes_per_day: project.minutes_per_day,
    minutes_per_week: project.minutes_per_week,
    days_per_month: project.days_per_month,
  };
}

// Extracted from ProjectDetailsPage (E4-11 / #151): composes the whole "Planning" tab (import,
// structure editor, version controls, conflict banner, tree panel). Gates its own visibility via
// the `active` prop instead of a ternary at the call site, so page.tsx's own JSX stays a flat,
// unconditional list of tab components. Verbatim JSX move -- see page.tsx call site for wiring.
export function PlanningTab({
  active,
  project,
  isReadOnlyProject,
  importFile,
  importBusy,
  onFileChange,
  onFilesDrop,
  onPreviewImport,
  planningExportBusy,
  onExportXml,
  importReview,
  onConfirmImport,
  importTarget,
  structureOpen,
  postGroups,
  structureDraft,
  structureBusy,
  structureAction,
  onUpdatePostField,
  onUpdateLotField,
  onUpdateDeliverable,
  onAddDeliverable,
  onRemoveDeliverable,
  onRemoveLot,
  onAddLotToPost,
  onAddPost,
  onSaveStructure,
  onGenerateStructure,
  onSkipStructure,
  revisions,
  selectedRevision,
  selectedRevisionId,
  referenceRevisionId,
  revisionsBusy,
  onSelectRevision,
  onCreateDraft,
  onValidateRevision,
  onReopenStructure,
  planningMutationBusy,
  revisionFeedback,
  conflict,
  onReloadConflict,
  hasError,
  treeBusy,
  tree,
  onMove,
  onScheduleUpdate,
  onEditLinks,
  onCreateTask,
  onDeleteNodes,
}: PlanningTabProps) {
  if (!active) {
    return null;
  }

  return (
    <>
      <PlanningImportPanel
        projectStatusInitialise={project?.status === "initialise"}
        importFile={importFile}
        importBusy={importBusy}
        onFileChange={onFileChange}
        onFilesDrop={onFilesDrop}
        onPreview={onPreviewImport}
        planningExportBusy={planningExportBusy}
        onExportXml={onExportXml}
        importReview={importReview}
        onConfirmImport={onConfirmImport}
        importTarget={importTarget}
      />

      <PlanningStructureEditor
        structureOpen={structureOpen}
        isReadOnlyProject={isReadOnlyProject}
        postGroups={postGroups}
        structureDraft={structureDraft}
        structureBusy={structureBusy}
        structureAction={structureAction}
        canSkipStructure={canSkipPlanningStructure(project)}
        onUpdatePostField={onUpdatePostField}
        onUpdateLotField={onUpdateLotField}
        onUpdateDeliverable={onUpdateDeliverable}
        onAddDeliverable={onAddDeliverable}
        onRemoveDeliverable={onRemoveDeliverable}
        onRemoveLot={onRemoveLot}
        onAddLotToPost={onAddLotToPost}
        onAddPost={onAddPost}
        onSave={onSaveStructure}
        onGenerate={onGenerateStructure}
        onSkip={onSkipStructure}
      />

      {!structureOpen ? (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2>Révision affichée</h2>
              <p className="text-sm text-muted-foreground">
                {revisionSubtitle(selectedRevision, revisionsBusy, hasError)}
              </p>
            </div>
            <PlanningVersionControls
              revisions={revisions}
              selectedRevisionId={selectedRevisionId}
              selectedRevision={selectedRevision}
              referenceRevisionId={referenceRevisionId}
              revisionsBusy={revisionsBusy}
              mutationBusy={planningMutationBusy}
              isReadOnlyProject={isReadOnlyProject}
              hasConflict={conflict !== null}
              onSelectRevision={onSelectRevision}
              onCreateDraft={onCreateDraft}
              onValidate={onValidateRevision}
              showReopenStructure={canReopenPlanningStructure(project, isReadOnlyProject)}
              onReopenStructure={onReopenStructure}
            />
          </div>
          {revisionFeedback ? (
            <p role="status" className="text-sm text-muted-foreground">
              {revisionFeedback}
            </p>
          ) : null}
          <PlanningConflictBanner conflict={conflict} onReload={onReloadConflict} />
          <PlanningTreePanel
            treeBusy={treeBusy}
            revisionsBusy={revisionsBusy}
            hasRevisions={revisions.length > 0}
            hasError={hasError}
            tree={tree}
            isReadOnlyProject={isReadOnlyProject}
            hasConflict={conflict !== null}
            mutationBusy={planningMutationBusy}
            calendar={projectCalendar(project)}
            onMove={onMove}
            onScheduleUpdate={onScheduleUpdate}
            onEditLinks={onEditLinks}
            onCreateTask={onCreateTask}
            onDeleteNodes={onDeleteNodes}
          />
        </div>
      ) : null}
    </>
  );
}
