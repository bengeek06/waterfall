"use client";

import { useMemo, useState, type MouseEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlanningCascadeDeleteDialog } from "@/components/planning-cascade-delete-dialog";
import { PlanningCreateTaskDialog } from "@/components/planning-create-task-dialog";
import { PlanningScheduleCells } from "@/components/planning-schedule-cells";
import { PlanningTaskLinksDialog } from "@/components/planning-task-links-dialog";
import { PlanningTreeToolbar } from "@/components/planning-tree-toolbar";
import { usePlanningCreateTaskDialog } from "@/hooks/use-planning-create-task-dialog";
import { usePlanningDeleteSelection } from "@/hooks/use-planning-delete-selection";
import { usePlanningScheduleDrafts } from "@/hooks/use-planning-schedule-drafts";
import { usePlanningTaskLinks } from "@/hooks/use-planning-task-links";
import { usePlanningTreeSelection } from "@/hooks/use-planning-tree-selection";
import type { PlanningTaskScheduleUpdate, Task, TaskLinkWrite } from "@/lib/backend";
import { DEFAULT_PROJECT_CALENDAR, type ProjectCalendar } from "@/lib/planning-calendar";
import { predecessorsLabel } from "@/lib/planning-links";
import {
  computeIndentCommand,
  computeOutdentCommand,
  computeReorderCommand,
  type PlanningMoveCommand,
} from "@/lib/planning-tree";

function taskTypeLabel(task: Task): string {
  if (task.is_milestone) {
    return "Jalon";
  }
  return task.is_summary ? "Résumé" : "Tâche";
}

// Only meaningful when exactly one row is selected: with zero or several rows selected there is
// no single unambiguous "relative to this task" position, so the create dialog only offers the
// root-level default in that case (see PlanningCreateTaskDialog's position <select>).
function getSingleSelectedTask(selectedUids: Set<number>, tasksByUid: Map<number, Task>): Task | null {
  if (selectedUids.size !== 1) {
    return null;
  }
  return tasksByUid.get([...selectedUids][0]) ?? null;
}

type PlanningTreeTableProps = Readonly<{
  tasks: Task[];
  /** Any value identifying the loaded planning version; changing it resets local expand/selection state. */
  versionKey: number | string | null;
  /**
   * The owning project's working calendar, used to format/parse the Duration cell and the
   * Prédécesseurs column's lag in MS-Project-like units (day/week/month) instead of raw minutes.
   * Optional (defaulting to DEFAULT_PROJECT_CALENDAR) so call sites that don't care about this
   * formatting -- most of this component's own tests -- don't need to thread it through, mirroring
   * readOnly/mutationBusy's own optional-with-default pattern below.
   */
  calendar?: ProjectCalendar;
  readOnly?: boolean;
  onMove?: (command: PlanningMoveCommand) => void;
  onScheduleUpdate?: (
    taskUid: number,
    payload: Omit<PlanningTaskScheduleUpdate, "expected_revision">,
  ) => Promise<boolean>;
  /** Replaces the full predecessor link list of one task; rejects with a user-facing message on failure. */
  onEditLinks?: (payload: { taskUid: number; links: TaskLinkWrite[] }) => Promise<void>;
  /** Creates a single new task at an explicit position; errors are reported by the parent's own error state. */
  onCreateTask?: (command: {
    name: string;
    isMilestone: boolean;
    targetParentUid?: number;
    insertAfterUid?: number;
  }) => void;
  /**
   * Deletes the given task uids. Must reject on failure -- including the
   * CASCADE_CONFIRMATION_REQUIRED conflict, which this component itself turns into a follow-up
   * confirmation dialog (see use-planning-delete-selection) -- so it can tell "needs confirmation"
   * apart from "resolved".
   *
   * `versionKey` is the identity of the planning version the deletion was requested against
   * (captured from this component's own `versionKey` prop at the moment the request was made,
   * not re-read at call time). The caller must re-check it against whatever planning version is
   * currently displayed before sending any request: task uids are reused across a planning's
   * versions, so a cascade confirmation retried after the displayed version changed could
   * otherwise delete the wrong version's tasks. Errors are reported by the parent's own error
   * state, mirroring onCreateTask.
   */
  onDeleteTasks?: (
    taskUids: number[],
    confirmCascade: boolean,
    versionKey: number | string | null,
  ) => Promise<void>;
  mutationBusy?: boolean;
}>;

export function PlanningTreeTable({
  tasks,
  versionKey,
  calendar = DEFAULT_PROJECT_CALENDAR,
  readOnly = false,
  onMove,
  onScheduleUpdate,
  onEditLinks,
  onCreateTask,
  onDeleteTasks,
  mutationBusy = false,
}: PlanningTreeTableProps) {
  const [renderedVersionKey, setRenderedVersionKey] = useState(versionKey);

  // Full-planning lookup (unlike selection.rows, not limited to currently-visible rows): a
  // predecessor referenced by a collapsed/off-screen task must still resolve correctly.
  const tasksByUid = useMemo(() => new Map(tasks.map((task) => [task.uid, task])), [tasks]);

  const selection = usePlanningTreeSelection(tasks);
  const scheduleDrafts = usePlanningScheduleDrafts({ onScheduleUpdate, mutationBusy, calendar });
  const taskLinks = usePlanningTaskLinks({ tasks, onEditLinks });
  const singleSelectedTask = getSingleSelectedTask(selection.selectedUids, tasksByUid);
  const createTaskDialog = usePlanningCreateTaskDialog({ onCreateTask, singleSelectedTask });
  const deleteSelection = usePlanningDeleteSelection({
    tasks,
    versionKey,
    selectedUids: selection.selectedUids,
    mutationBusy,
    onDeleteTasks,
    onSelectionCleared: selection.clearSelection,
  });

  // A different planning version must never reuse another version's expand/selection state. This
  // is a deliberate synchronous render-body write (not a useEffect): it must reset every hook's
  // local state within the same render as the versionKey prop change, so no frame is ever painted
  // with the previous version's selection/drafts/dialogs applied to the newly loaded tasks.
  if (versionKey !== renderedVersionKey) {
    setRenderedVersionKey(versionKey);
    taskLinks.reset();
    selection.reset();
    scheduleDrafts.reset();
    createTaskDialog.reset();
    deleteSelection.reset();
  }

  const readOnlyNotice = readOnly ? (
    <p className="mt-2 text-xs text-muted-foreground">Version validée ou projet en lecture seule : édition désactivée.</p>
  ) : null;

  const indentCommand = computeIndentCommand(tasks, selection.selectedUids);
  const outdentCommand = computeOutdentCommand(tasks, selection.selectedUids);
  const moveUpCommand = computeReorderCommand(tasks, selection.selectedUids, "up");
  const moveDownCommand = computeReorderCommand(tasks, selection.selectedUids, "down");

  function dispatchMove(command: PlanningMoveCommand | null) {
    if (command) {
      onMove?.(command);
    }
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Planning</CardTitle>
      </CardHeader>
      <CardContent>
        <PlanningTreeToolbar
          visible={!readOnly}
          showMoveActions={Boolean(onMove)}
          indentDisabled={!indentCommand || mutationBusy}
          outdentDisabled={!outdentCommand || mutationBusy}
          moveUpDisabled={!moveUpCommand || mutationBusy}
          moveDownDisabled={!moveDownCommand || mutationBusy}
          onIndent={() => dispatchMove(indentCommand)}
          onOutdent={() => dispatchMove(outdentCommand)}
          onMoveUp={() => dispatchMove(moveUpCommand)}
          onMoveDown={() => dispatchMove(moveDownCommand)}
          showCreateAction={Boolean(onCreateTask)}
          createDisabled={mutationBusy}
          onCreateTask={createTaskDialog.openCreateTaskDialog}
          showDeleteAction={Boolean(onDeleteTasks)}
          deleteDisabled={selection.selectedUids.size === 0 || mutationBusy}
          onDeleteSelection={() => void deleteSelection.requestDeleteSelection()}
        />
        {selection.rows.length === 0 ? (
          <p className="py-6 text-sm text-muted-foreground">Le planning ne contient aucune tâche.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>UID</TableHead>
                <TableHead>Nom</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Début</TableHead>
                <TableHead>Fin</TableHead>
                <TableHead>Durée</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead>Prédécesseurs</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {selection.rows.map((row) => {
                const collapsed = selection.collapsedUids.has(row.uid);
                const selected = selection.selectedUids.has(row.uid);
                const isFocusable =
                  selection.focusedUid === row.uid ||
                  (selection.focusedUid === null && row.uid === selection.rows[0]?.uid);
                return (
                  <TableRow
                    key={row.uid}
                    ref={(element) => {
                      if (element) {
                        selection.rowRefs.current.set(row.uid, element);
                      } else {
                        selection.rowRefs.current.delete(row.uid);
                      }
                    }}
                    data-state={selected ? "selected" : undefined}
                    aria-selected={selected}
                    tabIndex={isFocusable ? 0 : -1}
                    className="cursor-pointer outline-none"
                    onClick={(event) => selection.selectRow(row, event)}
                    onFocus={() => selection.setFocusedUid(row.uid)}
                    onKeyDown={(event) => selection.onRowKeyDown(event, row)}
                  >
                    <TableCell>{row.id_display ?? row.uid}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1" style={{ paddingLeft: `${row.depth * 1.25}rem` }}>
                        {row.hasChildren ? (
                          <button
                            type="button"
                            aria-label={collapsed ? `Déplier ${row.name}` : `Replier ${row.name}`}
                            className="flex size-6 items-center justify-center"
                            onClick={(event) => {
                              event.stopPropagation();
                              selection.toggleCollapsed(row.uid);
                            }}
                          >
                            {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
                          </button>
                        ) : (
                          <span className="size-6" />
                        )}
                        {row.is_milestone ? "◆ " : ""}
                        {row.name}
                      </div>
                    </TableCell>
                    <TableCell>{taskTypeLabel(row)}</TableCell>
                    <PlanningScheduleCells
                      row={row}
                      draft={scheduleDrafts.scheduleDraftFor(row)}
                      readOnly={readOnly}
                      hasScheduleUpdate={Boolean(onScheduleUpdate)}
                      mutationBusy={mutationBusy}
                      calendar={calendar}
                      durationError={scheduleDrafts.durationErrorFor(row)}
                      tasksByUid={tasksByUid}
                      onUpdateDraft={(field, value) => scheduleDrafts.updateScheduleDraft(row, field, value)}
                      onCommit={() => void scheduleDrafts.commitScheduleEdit(row)}
                      onCommitModeChange={(isManual) => void scheduleDrafts.commitModeChange(row, isManual)}
                      onFieldKeyDown={scheduleDrafts.onScheduleFieldKeyDown}
                    />
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span>{predecessorsLabel(row, calendar)}</span>
                        {!readOnly && onEditLinks ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={mutationBusy}
                            aria-label={`Éditer les prédécesseurs de ${row.name}`}
                            onClick={(event: MouseEvent<HTMLButtonElement>) => {
                              event.stopPropagation();
                              taskLinks.openLinksDialog(row);
                            }}
                          >
                            Éditer
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {readOnlyNotice}
      </CardContent>
      <PlanningTaskLinksDialog
        editingTask={taskLinks.editingTask}
        linkCandidateTasks={taskLinks.linkCandidateTasks}
        linkRows={taskLinks.linkRows}
        linkFormError={taskLinks.linkFormError}
        linkFormBusy={taskLinks.linkFormBusy}
        mutationBusy={mutationBusy}
        onClose={taskLinks.closeLinksDialog}
        onAddRow={taskLinks.addLinkRow}
        onRemoveRow={taskLinks.removeLinkRow}
        onUpdateRow={taskLinks.updateLinkRow}
        onSubmit={() => void taskLinks.submitLinks()}
      />
      <PlanningCreateTaskDialog
        open={createTaskDialog.createDialogOpen}
        name={createTaskDialog.createTaskName}
        isMilestone={createTaskDialog.createTaskIsMilestone}
        positionMode={createTaskDialog.createPositionMode}
        error={createTaskDialog.createTaskError}
        singleSelectedTask={singleSelectedTask}
        mutationBusy={mutationBusy}
        onNameChange={createTaskDialog.setCreateTaskName}
        onMilestoneChange={createTaskDialog.setCreateTaskIsMilestone}
        onPositionModeChange={createTaskDialog.setCreatePositionMode}
        onClose={createTaskDialog.closeCreateTaskDialog}
        onSubmit={createTaskDialog.submitCreateTask}
      />
      <PlanningCascadeDeleteDialog
        open={deleteSelection.cascadeConflict !== null}
        description={deleteSelection.cascadeDescription}
        busy={deleteSelection.cascadeBusy}
        onCancel={deleteSelection.reset}
        onConfirm={() => void deleteSelection.confirmCascadeDelete()}
      />
    </Card>
  );
}
