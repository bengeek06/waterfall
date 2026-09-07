"use client";

import { PlanningConflictBanner } from "@/components/planning-conflict-banner";
import { PlanningImportPanel } from "@/components/planning-import-panel";
import { PlanningStructureEditor, type PlanningStructureGroup } from "@/components/planning-structure-editor";
import { PlanningTreePanel } from "@/components/planning-tree-panel";
import { PlanningVersionControls } from "@/components/planning-version-controls";
import type { PlanningRevisionConflict } from "@/hooks/use-planning-detail";
import type {
  ImportDiff,
  Planning,
  PlanningDetail,
  PlanningTaskScheduleUpdate,
  Project,
  TaskLinkWrite,
} from "@/lib/backend";
import type { PlanningStructureDraftRow } from "@/lib/planning-structure";
import type { PlanningMoveCommand } from "@/lib/planning-tree";
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

  // Structure editor
  structureOpen: boolean;
  postGroups: PlanningStructureGroup[];
  structureDraft: PlanningStructureDraftRow[];
  structureBusy: boolean;
  structureAction: "save" | "generate" | "skip" | null;
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

  // Version controls
  plannings: Planning[];
  selectedPlanningId: number | null;
  planningBusy: boolean;
  onSelectPlanning: (planningId: number) => void;
  selectedPlanning: Planning | null;
  selectedPlanningHasConflict: boolean;
  onValidatePlanning: () => void;
  onSetReference: () => void;
  onReopenStructure: () => void;
  planningMutationBusy: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;

  // Conflict banner
  conflict: PlanningRevisionConflict | null;
  onReloadConflict: () => void;

  // Tree panel
  planningDetailBusy: boolean;
  planningDetail: PlanningDetail | null;
  onMove: (command: PlanningMoveCommand) => void;
  onScheduleUpdate: (
    taskUid: number,
    payload: Omit<PlanningTaskScheduleUpdate, "expected_revision">,
  ) => Promise<boolean>;
  onEditLinks: (payload: { taskUid: number; links: TaskLinkWrite[] }) => Promise<void>;
  onCreateTask: (command: {
    name: string;
    isMilestone: boolean;
    targetParentUid?: number;
    insertAfterUid?: number;
  }) => void;
  onDeleteTasks: (
    taskUids: number[],
    confirmCascade: boolean,
    versionKey: number | string | null,
  ) => Promise<void>;
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
  plannings,
  selectedPlanningId,
  planningBusy,
  onSelectPlanning,
  selectedPlanning,
  selectedPlanningHasConflict,
  onValidatePlanning,
  onSetReference,
  onReopenStructure,
  planningMutationBusy,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  conflict,
  onReloadConflict,
  planningDetailBusy,
  planningDetail,
  onMove,
  onScheduleUpdate,
  onEditLinks,
  onCreateTask,
  onDeleteTasks,
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
              <h2>Planning affiché</h2>
              <p className="text-sm text-muted-foreground">
                {selectedPlanning
                  ? `Version ${selectedPlanning.version_number} - ${selectedPlanning.status}`
                  : "Aucune version de planning."}
              </p>
            </div>
            <PlanningVersionControls
              plannings={plannings}
              selectedPlanningId={selectedPlanningId}
              planningBusy={planningBusy}
              onSelectPlanning={onSelectPlanning}
              selectedPlanning={selectedPlanning}
              isReadOnlyProject={isReadOnlyProject}
              selectedPlanningHasConflict={selectedPlanningHasConflict}
              onValidate={onValidatePlanning}
              projectPlanningReferenceId={project?.planning_reference_id}
              onSetReference={onSetReference}
              showReopenStructure={canReopenPlanningStructure(project, isReadOnlyProject)}
              onReopenStructure={onReopenStructure}
              planningMutationBusy={planningMutationBusy}
              canUndo={canUndo}
              canRedo={canRedo}
              onUndo={onUndo}
              onRedo={onRedo}
            />
          </div>
          <PlanningConflictBanner
            conflict={conflict}
            planningId={selectedPlanning?.id ?? null}
            onReload={onReloadConflict}
          />
          <PlanningTreePanel
            planningDetailBusy={planningDetailBusy}
            planningDetail={planningDetail}
            selectedPlanning={selectedPlanning}
            isReadOnlyProject={isReadOnlyProject}
            selectedPlanningHasConflict={selectedPlanningHasConflict}
            planningMutationBusy={planningMutationBusy}
            onMove={onMove}
            onScheduleUpdate={onScheduleUpdate}
            onEditLinks={onEditLinks}
            onCreateTask={onCreateTask}
            onDeleteTasks={onDeleteTasks}
          />
        </div>
      ) : null}
    </>
  );
}
