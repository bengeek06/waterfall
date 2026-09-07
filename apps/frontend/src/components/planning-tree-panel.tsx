"use client";

import { PlanningTreeTable } from "@/components/planning-tree-table";
import { ReadOnlyGantt } from "@/components/read-only-gantt";
import type { Planning, PlanningDetail, PlanningTaskScheduleUpdate, TaskLinkWrite } from "@/lib/backend";
import type { ProjectCalendar } from "@/lib/planning-calendar";
import type { PlanningMoveCommand } from "@/lib/planning-tree";

export type PlanningTreePanelProps = {
  planningDetailBusy: boolean;
  planningDetail: PlanningDetail | null;
  selectedPlanning: Planning | null;
  isReadOnlyProject: boolean;
  selectedPlanningHasConflict: boolean;
  planningMutationBusy: boolean;
  /** The owning project's working calendar -- see PlanningTreeTableProps.calendar. */
  calendar: ProjectCalendar;
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

// A planning still under construction (its own draft not yet validated) is only editable while
// it stays the selected draft with no pending revision conflict -- mirrors the guard duplicated
// across every planning mutation handler in ProjectDetailsPage (see selectPlanning et al.).
function isPlanningTreeReadOnly(
  isReadOnlyProject: boolean,
  selectedPlanningHasConflict: boolean,
  selectedPlanning: Planning | null,
): boolean {
  return isReadOnlyProject || selectedPlanningHasConflict || (selectedPlanning ? selectedPlanning.status !== "draft" : false);
}

// Extracted from ProjectDetailsPage (E4-11 / #151): the busy/empty states plus the read-only
// Gantt and the editable tree table for the currently-selected planning version. Verbatim JSX
// move -- see page.tsx call site for wiring.
export function PlanningTreePanel({
  planningDetailBusy,
  planningDetail,
  selectedPlanning,
  isReadOnlyProject,
  selectedPlanningHasConflict,
  planningMutationBusy,
  calendar,
  onMove,
  onScheduleUpdate,
  onEditLinks,
  onCreateTask,
  onDeleteTasks,
}: PlanningTreePanelProps) {
  return (
    <>
      {planningDetailBusy ? <p className="text-sm text-muted-foreground" role="status">Chargement du planning...</p> : null}
      {!planningDetailBusy && !planningDetail ? <p className="py-6 text-sm text-muted-foreground">Aucun planning sélectionné.</p> : null}
      {planningDetail?.tasks.length ? <ReadOnlyGantt tasks={planningDetail.tasks} /> : null}
      {planningDetail ? (
        <PlanningTreeTable
          tasks={planningDetail.tasks}
          versionKey={selectedPlanning?.id ?? null}
          calendar={calendar}
          readOnly={isPlanningTreeReadOnly(isReadOnlyProject, selectedPlanningHasConflict, selectedPlanning)}
          onMove={onMove}
          onScheduleUpdate={onScheduleUpdate}
          onEditLinks={onEditLinks}
          onCreateTask={onCreateTask}
          onDeleteTasks={onDeleteTasks}
          mutationBusy={planningMutationBusy}
        />
      ) : null}
    </>
  );
}
