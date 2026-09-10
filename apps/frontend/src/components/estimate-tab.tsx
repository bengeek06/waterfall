"use client";

import { Alert, AlertAction, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { BulkCostCodeAssignmentBar } from "@/components/bulk-cost-code-assignment-bar";
import { CostLineForm, type CostLineDraft } from "@/components/cost-line-form";
import { EstimateCreateTaskDialog } from "@/components/estimate-create-task-dialog";
import { EstimateGridTreeTable } from "@/components/estimate-grid-tree-table";
import {
  EstimateMilestoneTemplateDialog,
  type MilestoneTemplateValue,
} from "@/components/estimate-milestone-template-dialog";
import { EstimateRoleAssignmentDialog } from "@/components/estimate-role-assignment-dialog";
import { EstimateVersionControls } from "@/components/estimate-version-controls";
import type {
  CostCategory,
  CostRate,
  EstimateCostLine,
  EstimateRoleAssignment,
  EstimateTaskRow,
  EstimateValidationWarning,
  ProjectCostCode,
  ProjectEstimate,
  ResourceNode,
  ResourceRole,
  Task,
} from "@/lib/backend";
import type { EstimateGridMoveCommand } from "@/lib/estimate-grid-move";

export type EstimateTabProps = {
  active: boolean;
  estimates: ProjectEstimate[];
  selectedEstimateId: number | null;
  onSelectEstimate: (estimateId: number) => void;
  isReadOnlyProject: boolean;
  onNewDraft: () => void;
  exportBusy: boolean;
  onExport: () => void;
  canEditEstimate: boolean;
  estimateBusy: boolean;
  onOpenValidation: () => void;
  validationWarnings: EstimateValidationWarning[];
  onDismissValidationWarnings: () => void;
  // E12-04/#276: the full task-row list backs both the "tâches snapshotées" count (derived below
  // via `.length`, kept as a small computation rather than a separate `estimateTaskRowCount`
  // prop, so callers can't let the two drift out of sync) and the Devis grid's task hierarchy.
  estimateTaskRows: EstimateTaskRow[];
  costLines: EstimateCostLine[];
  costCategories: CostCategory[];
  // E12-05/#277: the full (including inactive) cost-category referential, threaded straight
  // through to EstimateGridTreeTable for its "Type" column's category-name resolution -- see
  // that prop's own doc comment on why it's a separate list from `costCategories` above (that one
  // stays active-only, since it feeds CostLineForm's create-line `<select>` and the grid's own
  // "Type" `<select>` for an existing non-MO row).
  allCostCategories: CostCategory[];
  costLineDraft: CostLineDraft;
  onCategoryChange: (value: string) => void;
  onLabelChange: (value: string) => void;
  onQuantityChange: (value: string) => void;
  onUnitCostChange: (value: string) => void;
  onPlannedDateChange: (value: string) => void;
  onTaskIdChange: (value: string) => void;
  onAddCostLine: () => void;
  mutationBusy: boolean;
  onMoveGridSelection: (command: EstimateGridMoveCommand) => void;
  onRenameTask: (taskUid: number, name: string) => Promise<boolean>;
  onUpdateCostLine: (
    lineId: number,
    payload: { label?: string; quantity?: number; unit_cost?: number; cost_category_id?: number },
  ) => Promise<boolean>;
  onUpdateRoleAssignment: (id: number, payload: { quantity?: number; hours?: number }) => Promise<boolean>;
  onRequestDeleteCostLine: (line: EstimateCostLine) => void;
  selectedCostLineIds: Set<number>;
  onSelectedCostLineIdsChange: (next: Set<number>) => void;
  projectCostCodes: ProjectCostCode[];
  bulkCostCodeId: string;
  onBulkCostCodeIdChange: (value: string) => void;
  bulkAssignBusy: boolean;
  onBulkAssignCostCode: () => void;
  // E6-06/#67: "add a task to the planning" dialog, launched from this tab.
  taskDialogOpen: boolean;
  taskDraftName: string;
  taskDraftIsMilestone: boolean;
  taskDraftParentUid: string;
  parentTaskOptions: Task[];
  taskCreateBusy: boolean;
  taskCreateError: string | null;
  taskCreateRequiresPlanningDraft: boolean;
  onOpenCreateTaskDialog: () => void;
  onCloseCreateTaskDialog: () => void;
  onTaskDraftNameChange: (value: string) => void;
  onTaskDraftIsMilestoneChange: (value: boolean) => void;
  onTaskDraftParentUidChange: (value: string) => void;
  onSubmitCreateTask: () => void;
  onReopenStructure: () => void;
  // E6-07/#68: "apply a milestone template" dialog, launched from a single cost line row.
  milestoneDialogOpen: boolean;
  milestoneLineId: number | null;
  milestoneTemplate: MilestoneTemplateValue;
  milestoneIntermediateCount: string;
  milestoneLagMinutes: string;
  milestoneBusy: boolean;
  milestoneError: string | null;
  milestoneRequiresPlanningDraft: boolean;
  onOpenMilestoneDialog: (line: EstimateCostLine) => void;
  onCloseMilestoneDialog: () => void;
  onMilestoneTemplateChange: (value: MilestoneTemplateValue) => void;
  onMilestoneIntermediateCountChange: (value: string) => void;
  onMilestoneLagMinutesChange: (value: string) => void;
  onSubmitMilestoneTemplate: () => void;
  onReopenStructureForMilestone: () => void;
  // E12-06/#278: role-assignment ("MO") referentials, threaded straight through to
  // EstimateGridTreeTable's own Dept/Rôle/Taux horaire/PRU column resolution -- see that
  // component's own prop doc comments.
  estimateRoleAssignments: EstimateRoleAssignment[];
  resourceNodes: ResourceNode[];
  resourceRoles: ResourceRole[];
  costRates: CostRate[];
  onRequestDeleteRoleAssignment: (assignment: EstimateRoleAssignment) => void;
  // "Ajouter une ligne MO" dialog (create-only -- editing an existing row's Qté/Heures happens
  // inline in the grid instead, see EstimateGridTreeTable's onUpdateRoleAssignment).
  roleAssignmentDialogOpen: boolean;
  roleAssignmentDept1Id: string;
  onRoleAssignmentDept1IdChange: (value: string) => void;
  roleAssignmentDept2Id: string;
  onRoleAssignmentDept2IdChange: (value: string) => void;
  roleAssignmentRoles: ResourceRole[];
  roleAssignmentRolesLoading: boolean;
  roleAssignmentRoleId: string;
  onRoleAssignmentRoleIdChange: (value: string) => void;
  roleAssignmentTaskId: string;
  onRoleAssignmentTaskIdChange: (value: string) => void;
  roleAssignmentQuantity: string;
  onRoleAssignmentQuantityChange: (value: string) => void;
  roleAssignmentHours: string;
  onRoleAssignmentHoursChange: (value: string) => void;
  roleAssignmentCostCodeId: string;
  onRoleAssignmentCostCodeIdChange: (value: string) => void;
  roleAssignmentComment: string;
  onRoleAssignmentCommentChange: (value: string) => void;
  roleAssignmentBusy: boolean;
  roleAssignmentError: string | null;
  onOpenRoleAssignmentDialog: () => void;
  // E12-11/#293: same dialog, launched from a labor row's right-click context menu instead of
  // the toolbar button above -- see EstimateGridTreeTable's own onAddRoleAssignmentForRow prop
  // doc comment.
  onOpenRoleAssignmentDialogForRow: (assignment: EstimateRoleAssignment) => void;
  onCloseRoleAssignmentDialog: () => void;
  onSubmitRoleAssignment: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): composes the whole "Devis" tab (version
// controls, cost-line form, cost lines table). Gates its own visibility via the `active` prop
// instead of a ternary at the call site, matching PlanningTab. Verbatim JSX move -- see page.tsx
// call site for wiring.
export function EstimateTab({
  active,
  estimates,
  selectedEstimateId,
  onSelectEstimate,
  isReadOnlyProject,
  onNewDraft,
  exportBusy,
  onExport,
  canEditEstimate,
  estimateBusy,
  onOpenValidation,
  validationWarnings,
  onDismissValidationWarnings,
  estimateTaskRows,
  costLines,
  costCategories,
  allCostCategories,
  costLineDraft,
  onCategoryChange,
  onLabelChange,
  onQuantityChange,
  onUnitCostChange,
  onPlannedDateChange,
  onTaskIdChange,
  onAddCostLine,
  mutationBusy,
  onMoveGridSelection,
  onRenameTask,
  onUpdateCostLine,
  onUpdateRoleAssignment,
  onRequestDeleteCostLine,
  selectedCostLineIds,
  onSelectedCostLineIdsChange,
  projectCostCodes,
  bulkCostCodeId,
  onBulkCostCodeIdChange,
  bulkAssignBusy,
  onBulkAssignCostCode,
  taskDialogOpen,
  taskDraftName,
  taskDraftIsMilestone,
  taskDraftParentUid,
  parentTaskOptions,
  taskCreateBusy,
  taskCreateError,
  taskCreateRequiresPlanningDraft,
  onOpenCreateTaskDialog,
  onCloseCreateTaskDialog,
  onTaskDraftNameChange,
  onTaskDraftIsMilestoneChange,
  onTaskDraftParentUidChange,
  onSubmitCreateTask,
  onReopenStructure,
  milestoneDialogOpen,
  milestoneLineId,
  milestoneTemplate,
  milestoneIntermediateCount,
  milestoneLagMinutes,
  milestoneBusy,
  milestoneError,
  milestoneRequiresPlanningDraft,
  onOpenMilestoneDialog,
  onCloseMilestoneDialog,
  onMilestoneTemplateChange,
  onMilestoneIntermediateCountChange,
  onMilestoneLagMinutesChange,
  onSubmitMilestoneTemplate,
  onReopenStructureForMilestone,
  estimateRoleAssignments,
  resourceNodes,
  resourceRoles,
  costRates,
  onRequestDeleteRoleAssignment,
  roleAssignmentDialogOpen,
  roleAssignmentDept1Id,
  onRoleAssignmentDept1IdChange,
  roleAssignmentDept2Id,
  onRoleAssignmentDept2IdChange,
  roleAssignmentRoles,
  roleAssignmentRolesLoading,
  roleAssignmentRoleId,
  onRoleAssignmentRoleIdChange,
  roleAssignmentTaskId,
  onRoleAssignmentTaskIdChange,
  roleAssignmentQuantity,
  onRoleAssignmentQuantityChange,
  roleAssignmentHours,
  onRoleAssignmentHoursChange,
  roleAssignmentCostCodeId,
  onRoleAssignmentCostCodeIdChange,
  roleAssignmentComment,
  onRoleAssignmentCommentChange,
  roleAssignmentBusy,
  roleAssignmentError,
  onOpenRoleAssignmentDialog,
  onOpenRoleAssignmentDialogForRow,
  onCloseRoleAssignmentDialog,
  onSubmitRoleAssignment,
}: EstimateTabProps) {
  if (!active) {
    return null;
  }

  // Resolved here (rather than threaded as its own prop) since costLines is already available
  // and is the single source of truth for a cost line's current label -- avoids the dialog ever
  // showing a stale label if the line was edited after the dialog was opened.
  const milestoneCostLine = costLines.find((line) => line.id === milestoneLineId) ?? null;

  // Haute review finding on #68: a cost line whose `task_id` points at a milestone task can never
  // accept the milestone-template action -- `create_planning_task` unconditionally rejects
  // attaching children to a milestone with a 409 (see EstimateGridTreeTable's milestoneTaskIds
  // prop doc comment) -- so it's resolved here from the same `parentTaskOptions` (`Task[]`,
  // `planningDetail.tasks`) this tab already threads to EstimateCreateTaskDialog, mirroring that
  // dialog's own `.filter((task) => !task.is_milestone)` parent-task guard.
  const milestoneTaskIds = new Set(
    parentTaskOptions.filter((task) => task.is_milestone).map((task) => task.id),
  );

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2>Versions de devis</h2>
          <p className="text-sm text-muted-foreground">
            {canEditEstimate ? "Le brouillon sélectionné est éditable." : "Cette version n'est plus modifiable."}
          </p>
        </div>
        <EstimateVersionControls
          estimates={estimates}
          selectedEstimateId={selectedEstimateId}
          onSelectEstimate={onSelectEstimate}
          isReadOnlyProject={isReadOnlyProject}
          onNewDraft={onNewDraft}
          exportBusy={exportBusy}
          onExport={onExport}
          canEditEstimate={canEditEstimate}
          estimateBusy={estimateBusy}
          onOpenValidation={onOpenValidation}
        />
      </div>

      {validationWarnings.length ? (
        <Alert>
          <AlertAction>
            <Button size="sm" variant="outline" onClick={onDismissValidationWarnings}>
              Fermer
            </Button>
          </AlertAction>
          <AlertDescription>
            <p>
              Devis validé -- {validationWarnings.length} tâche
              {validationWarnings.length > 1 ? "s" : ""} sans affectation de rôle ni ligne de coût :
            </p>
            <ul className="mt-1 list-disc pl-4">
              {validationWarnings.map((warning) => (
                <li key={warning.task_uid}>{warning.task_name}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {!estimates.length ? <p className="py-6 text-sm text-muted-foreground">Aucune version de devis.</p> : null}

      {estimates.length ? (
        <div className="grid gap-4">
          <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
            <strong>{estimateTaskRows.length}</strong>
            <span>tâches snapshotées</span>
          </div>
          <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
            <strong>{costLines.length}</strong>
            <span>lignes de coût</span>
          </div>

          {canEditEstimate ? (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" disabled={estimateBusy} onClick={onOpenCreateTaskDialog}>
                Ajouter une tâche au planning
              </Button>
              <Button type="button" variant="outline" disabled={estimateBusy} onClick={onOpenRoleAssignmentDialog}>
                Ajouter une ligne MO
              </Button>
            </div>
          ) : null}

          {canEditEstimate ? (
            <CostLineForm
              costCategories={costCategories}
              estimateTaskRows={estimateTaskRows}
              costLineDraft={costLineDraft}
              onCategoryChange={onCategoryChange}
              onLabelChange={onLabelChange}
              onQuantityChange={onQuantityChange}
              onUnitCostChange={onUnitCostChange}
              onPlannedDateChange={onPlannedDateChange}
              onTaskIdChange={onTaskIdChange}
              estimateBusy={estimateBusy}
              onAdd={onAddCostLine}
            />
          ) : null}

          {canEditEstimate ? (
            <BulkCostCodeAssignmentBar
              selectedCount={selectedCostLineIds.size}
              projectCostCodes={projectCostCodes}
              bulkCostCodeId={bulkCostCodeId}
              onBulkCostCodeIdChange={onBulkCostCodeIdChange}
              bulkAssignBusy={bulkAssignBusy}
              onAssign={onBulkAssignCostCode}
            />
          ) : null}

          <EstimateGridTreeTable
            taskRows={estimateTaskRows}
            costLines={costLines}
            roleAssignments={estimateRoleAssignments}
            versionKey={selectedEstimateId}
            canEditEstimate={canEditEstimate}
            mutationBusy={mutationBusy}
            costCategories={costCategories}
            allCostCategories={allCostCategories}
            resourceNodes={resourceNodes}
            resourceRoles={resourceRoles}
            costRates={costRates}
            planningTasks={parentTaskOptions}
            onMove={onMoveGridSelection}
            onRenameTask={onRenameTask}
            onUpdateCostLine={onUpdateCostLine}
            onUpdateRoleAssignment={onUpdateRoleAssignment}
            selectedCostLineIds={selectedCostLineIds}
            onSelectedCostLineIdsChange={onSelectedCostLineIdsChange}
            bulkAssignBusy={bulkAssignBusy}
            onOpenMilestoneDialog={onOpenMilestoneDialog}
            milestoneTaskIds={milestoneTaskIds}
            onRequestDeleteCostLine={onRequestDeleteCostLine}
            onRequestDeleteRoleAssignment={onRequestDeleteRoleAssignment}
            onAddRoleAssignmentForRow={onOpenRoleAssignmentDialogForRow}
          />
        </div>
      ) : null}

      <EstimateCreateTaskDialog
        open={taskDialogOpen}
        name={taskDraftName}
        isMilestone={taskDraftIsMilestone}
        parentTaskUid={taskDraftParentUid}
        parentTaskOptions={parentTaskOptions}
        busy={taskCreateBusy}
        error={taskCreateError}
        requiresPlanningDraft={taskCreateRequiresPlanningDraft}
        onNameChange={onTaskDraftNameChange}
        onMilestoneChange={onTaskDraftIsMilestoneChange}
        onParentTaskUidChange={onTaskDraftParentUidChange}
        onClose={onCloseCreateTaskDialog}
        onSubmit={onSubmitCreateTask}
        onReopenStructure={onReopenStructure}
      />

      <EstimateMilestoneTemplateDialog
        open={milestoneDialogOpen}
        costLineLabel={milestoneCostLine?.label ?? ""}
        template={milestoneTemplate}
        intermediateMilestonesCount={milestoneIntermediateCount}
        lagMinutes={milestoneLagMinutes}
        busy={milestoneBusy}
        error={milestoneError}
        requiresPlanningDraft={milestoneRequiresPlanningDraft}
        onTemplateChange={onMilestoneTemplateChange}
        onIntermediateMilestonesCountChange={onMilestoneIntermediateCountChange}
        onLagMinutesChange={onMilestoneLagMinutesChange}
        onClose={onCloseMilestoneDialog}
        onSubmit={onSubmitMilestoneTemplate}
        onReopenStructure={onReopenStructureForMilestone}
      />

      <EstimateRoleAssignmentDialog
        open={roleAssignmentDialogOpen}
        resourceNodes={resourceNodes}
        dept1Id={roleAssignmentDept1Id}
        onDept1IdChange={onRoleAssignmentDept1IdChange}
        dept2Id={roleAssignmentDept2Id}
        onDept2IdChange={onRoleAssignmentDept2IdChange}
        roles={roleAssignmentRoles}
        rolesLoading={roleAssignmentRolesLoading}
        roleId={roleAssignmentRoleId}
        onRoleIdChange={onRoleAssignmentRoleIdChange}
        estimateTaskRows={estimateTaskRows}
        taskId={roleAssignmentTaskId}
        onTaskIdChange={onRoleAssignmentTaskIdChange}
        quantity={roleAssignmentQuantity}
        onQuantityChange={onRoleAssignmentQuantityChange}
        hours={roleAssignmentHours}
        onHoursChange={onRoleAssignmentHoursChange}
        projectCostCodes={projectCostCodes}
        costCodeId={roleAssignmentCostCodeId}
        onCostCodeIdChange={onRoleAssignmentCostCodeIdChange}
        comment={roleAssignmentComment}
        onCommentChange={onRoleAssignmentCommentChange}
        busy={roleAssignmentBusy}
        error={roleAssignmentError}
        onClose={onCloseRoleAssignmentDialog}
        onSubmit={onSubmitRoleAssignment}
      />
    </div>
  );
}
