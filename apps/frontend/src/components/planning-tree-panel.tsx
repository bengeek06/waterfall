"use client";

import { useMemo } from "react";

import { PlanningTreeTable } from "@/components/planning-tree-table";
import { ReadOnlyGantt } from "@/components/read-only-gantt";
import type { RevisionPredecessorWrite, RevisionTree } from "@/lib/backend";
import type { CreateTaskCommand } from "@/hooks/use-planning-create-task-dialog";
import type { SchedulePayload } from "@/hooks/use-planning-schedule-drafts";
import type { ProjectCalendar } from "@/lib/planning-calendar";
import { buildPlanningRows, type PlanningMoveMode } from "@/lib/planning-tree";
import { rowNumberByNodeId } from "@/lib/revision-tree";

export type PlanningTreePanelProps = {
  treeBusy: boolean;
  /** True while the list of revisions is being read: there is nothing to conclude from it yet. */
  revisionsBusy: boolean;
  /** Whether the project holds at least one revision, as the freshly-read list reports it. */
  hasRevisions: boolean;
  /** True when the page is already showing an error banner, so the panel keeps quiet about it. */
  hasError: boolean;
  tree: RevisionTree | null;
  isReadOnlyProject: boolean;
  hasConflict: boolean;
  mutationBusy: boolean;
  /** The owning project's working calendar -- see PlanningTreeTableProps.calendar. */
  calendar: ProjectCalendar;
  onMove: (mode: PlanningMoveMode, nodeIds: number[]) => void;
  onScheduleUpdate: (nodeId: number, payload: SchedulePayload) => Promise<boolean>;
  onEditLinks: (payload: { nodeId: number; predecessors: RevisionPredecessorWrite[] }) => Promise<void>;
  onCreateTask: (command: CreateTaskCommand) => void;
  onDeleteNodes: (nodeIds: number[]) => void;
};

/**
 * A revision is editable only while it is a draft (INV-03: a validated or superseded revision
 * refuses every write, with the same code on both facets), the project is not read-only, and no
 * unresolved lock conflict is pending.
 */
export function isPlanningTreeReadOnly(
  isReadOnlyProject: boolean,
  hasConflict: boolean,
  tree: RevisionTree | null,
): boolean {
  return isReadOnlyProject || hasConflict || (tree ? tree.status !== "draft" : false);
}

// Extracted from ProjectDetailsPage (E4-11 / #151): the busy/empty states plus the read-only Gantt
// and the editable tree table for the currently-displayed revision.
export function PlanningTreePanel({
  treeBusy,
  revisionsBusy,
  hasRevisions,
  hasError,
  tree,
  isReadOnlyProject,
  hasConflict,
  mutationBusy,
  calendar,
  onMove,
  onScheduleUpdate,
  onEditLinks,
  onCreateTask,
  onDeleteNodes,
}: PlanningTreePanelProps) {
  // Memoised on `tree`, not recomputed per render: `rows` is the input of useTreeTableSelection,
  // whose four useMemo all list it as a dependency. A new array on every render invalidates the
  // lot -- and ProjectDetailsPage re-renders on every keystroke in the project-name field, which
  // would rebuild the whole table per character typed.
  const rows = useMemo(() => (tree ? buildPlanningRows(tree.nodes) : []), [tree]);
  const rowNumbers = useMemo(() => (tree ? rowNumberByNodeId(tree.nodes) : new Map<number, number>()), [tree]);
  // Nothing is empty until both reads have answered: on the very first render the list has not
  // been requested yet, and saying "no revision, import one" over a network round-trip -- or,
  // worse, over a list that failed to load -- invites the user to fix the wrong problem.
  const showEmptyState = !revisionsBusy && !treeBusy && !hasError && !hasRevisions;
  return (
    <>
      {/* Only the tree read is announced here: while the *list* is loading, the header above
          already says so, and two live regions repeating it would be announced twice. */}
      {treeBusy ? (
        <p className="text-sm text-muted-foreground" role="status">
          Chargement de la révision...
        </p>
      ) : null}
      {showEmptyState ? (
        <p className="py-6 text-sm text-muted-foreground">
          Aucune révision à afficher. Importe un planning MS Project pour en créer une.
        </p>
      ) : null}
      {rows.length ? <ReadOnlyGantt rows={rows} /> : null}
      {tree ? (
        <PlanningTreeTable
          rows={rows}
          treeNodes={tree.nodes}
          rowNumberByNodeId={rowNumbers}
          revisionKey={tree.revision_id}
          calendar={calendar}
          readOnly={isPlanningTreeReadOnly(isReadOnlyProject, hasConflict, tree)}
          onMove={onMove}
          onScheduleUpdate={onScheduleUpdate}
          onEditLinks={onEditLinks}
          onCreateTask={onCreateTask}
          onDeleteNodes={onDeleteNodes}
          mutationBusy={mutationBusy}
        />
      ) : null}
    </>
  );
}
