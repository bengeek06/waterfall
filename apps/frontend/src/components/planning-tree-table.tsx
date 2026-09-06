"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlanningCascadeDeleteDialog } from "@/components/planning-cascade-delete-dialog";
import { PlanningCreateTaskDialog } from "@/components/planning-create-task-dialog";
import { PlanningScheduleCells } from "@/components/planning-schedule-cells";
import { PlanningTaskLinksDialog } from "@/components/planning-task-links-dialog";
import { PlanningTreeToolbar } from "@/components/planning-tree-toolbar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  PLANNING_COLUMN_ORDER,
  PLANNING_MAX_COLUMN_WIDTH,
  PLANNING_MIN_COLUMN_WIDTHS,
  usePlanningColumnWidths,
  type PlanningColumnKey,
} from "@/hooks/use-planning-column-widths";
import { usePlanningCreateTaskDialog } from "@/hooks/use-planning-create-task-dialog";
import { usePlanningDeleteSelection } from "@/hooks/use-planning-delete-selection";
import { usePlanningScheduleDrafts } from "@/hooks/use-planning-schedule-drafts";
import { usePlanningTaskLinks } from "@/hooks/use-planning-task-links";
import { usePlanningTreeSelection } from "@/hooks/use-planning-tree-selection";
import type { PlanningTaskScheduleUpdate, Task, TaskLinkWrite } from "@/lib/backend";
import { predecessorsLabel } from "@/lib/planning-links";
import {
  computeIndentCommand,
  computeOutdentCommand,
  computeReorderCommand,
  type PlanningMoveCommand,
} from "@/lib/planning-tree";
import { cn } from "@/lib/utils";

const COLUMN_HEADERS: ReadonlyArray<{ key: PlanningColumnKey; label: string }> = [
  { key: "uid", label: "UID" },
  { key: "name", label: "Nom" },
  { key: "type", label: "Type" },
  { key: "start", label: "Début" },
  { key: "end", label: "Fin" },
  { key: "duration", label: "Durée" },
  { key: "mode", label: "Mode" },
  { key: "predecessors", label: "Prédécesseurs" },
];

// Fixed step for keyboard-driven resizing (ArrowLeft/ArrowRight), mirroring the granularity of a
// small mouse drag.
const COLUMN_RESIZE_KEYBOARD_STEP = 10;

function ColumnResizeHandle({
  column,
  label,
  width,
  min,
  onResizeStart,
  onResizeBy,
}: {
  column: PlanningColumnKey;
  label: string;
  width: number;
  min: number;
  onResizeStart: (column: PlanningColumnKey, event: MouseEvent<HTMLSpanElement>) => void;
  onResizeBy: (column: PlanningColumnKey, delta: number) => void;
}) {
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={`Redimensionner la colonne ${label}`}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={PLANNING_MAX_COLUMN_WIDTH}
      tabIndex={0}
      data-testid={`resize-handle-${column}`}
      // `group` + a wider (w-3 = 12px) hit area than what's visually painted (the inner bar below
      // stays w-1 = 4px, flush against the column boundary via justify-end): a plain 4px strip is
      // only discoverable by accidentally hovering exactly on the column boundary, and is a fiddly
      // mouse/touch target. The outer box stays entirely inside the TableHead's own bounds (right-0,
      // extending leftward into the current column, never past its right edge), so none of it is
      // clipped by the parent's `overflow-hidden` (needed so the handle never visually spills into
      // the next header).
      className="group absolute right-0 top-0 z-10 flex h-full w-3 cursor-col-resize items-center justify-end select-none outline-none"
      onMouseDown={(event) => onResizeStart(column, event)}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          onResizeBy(column, -COLUMN_RESIZE_KEYBOARD_STEP);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          onResizeBy(column, COLUMN_RESIZE_KEYBOARD_STEP);
        }
      }}
    >
      {/*
        Visible handle bar, separate from the interactive span above: `hover:bg-border` gives
        sighted mouse users a discoverable affordance instead of an invisible strip.
        `group-focus-visible:bg-primary` is a background-color change rather than an
        `outline`/`ring` utility on the handle itself, because that would be clipped by the parent
        TableHead's `overflow-hidden` if it extended outside the handle's own box -- a background
        change painted inside the bar's own bounds stays visible under that clipping, so keyboard
        focus is never silently invisible.
      */}
      <span
        aria-hidden="true"
        className="h-full w-1 rounded-full bg-transparent transition-colors group-hover:bg-border group-focus-visible:bg-primary"
      />
    </span>
  );
}

// Renders a task's name, interactive only when it is actually visually truncated: an ordinary,
// non-truncated name stays a plain <span>, with no tab stop or button semantics, so keyboard/
// screen-reader users navigating a large planning (including the supported 1000-row case) never
// have to traverse a per-row control that does nothing beyond announcing the name they'd already
// hear. Only once the text is truncated does it become a focusable Tooltip trigger, which is the
// only way to reach the full name without a mouse hover in that case.
function TaskNameLabel({ name, width, isMilestone }: { name: string; width: number; isMilestone: boolean }) {
  const textRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  // Re-checked whenever the name text or the Name column's own width changes -- either can flip
  // whether the text actually overflows its box. `width` (usePlanningColumnWidths' committed value
  // for the "name" column) also updates while a resize drag is in progress, not just once it ends:
  // the hook commits at most one width per animation frame during a drag (see its own rAF-
  // coalescing comment), so this re-measures at that same, already-throttled cadence rather than on
  // every raw mousemove.
  useEffect(() => {
    const element = textRef.current;
    if (!element) {
      return;
    }
    setIsTruncated(element.scrollWidth > element.clientWidth);
  }, [name, width]);

  const label = (
    <>
      {isMilestone ? "◆ " : ""}
      {name}
    </>
  );

  if (!isTruncated) {
    return (
      <span ref={textRef} className="min-w-0 truncate text-left">
        {label}
      </span>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger
        ref={textRef}
        type="button"
        className="min-w-0 truncate text-left"
        onClick={(event: MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
        onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => event.stopPropagation()}
      >
        {label}
      </TooltipTrigger>
      <TooltipContent>{name}</TooltipContent>
    </Tooltip>
  );
}

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

  const columnWidths = usePlanningColumnWidths();
  // Table renders `w-full`, which under table-fixed layout redistributes any surplus between the
  // container and this sum across the columns -- making rendered widths drift from the persisted
  // ones and coupling a resize on one column to its neighbors. Pinning the table's own width to
  // exactly this sum (see the inline style below) keeps each handle in sole control of its column;
  // the existing overflow-x-auto wrapper still takes over and scrolls once this exceeds the
  // viewport.
  const totalColumnWidth = useMemo(
    () => PLANNING_COLUMN_ORDER.reduce((total, key) => total + columnWidths.widths[key], 0),
    [columnWidths.widths],
  );
  const selection = usePlanningTreeSelection(tasks);
  const scheduleDrafts = usePlanningScheduleDrafts({ onScheduleUpdate, mutationBusy });
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
          <Table className="table-fixed w-auto" style={{ width: totalColumnWidth }}>
            <colgroup>
              {COLUMN_HEADERS.map(({ key }) => (
                <col key={key} style={{ width: `${columnWidths.widths[key]}px` }} />
              ))}
            </colgroup>
            <TableHeader>
              <TableRow>
                {COLUMN_HEADERS.map(({ key, label }) => (
                  <TableHead
                    key={key}
                    className={cn(
                      "relative overflow-hidden",
                      key === "predecessors" && "whitespace-normal break-words align-top",
                    )}
                  >
                    {label}
                    <ColumnResizeHandle
                      column={key}
                      label={label}
                      width={columnWidths.widths[key]}
                      min={PLANNING_MIN_COLUMN_WIDTHS[key]}
                      onResizeStart={columnWidths.startResize}
                      onResizeBy={columnWidths.resizeBy}
                    />
                  </TableHead>
                ))}
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
                    <TableCell className="overflow-hidden">
                      <div
                        className="flex min-w-0 items-center gap-1"
                        // Deliberately uncapped: the tree builder allows arbitrary nesting depth (a
                        // real MS Project import can exceed a handful of levels), and the visual
                        // indentation must keep reflecting the actual hierarchy rather than flattening
                        // past some arbitrary depth. PLANNING_MIN_COLUMN_WIDTHS.name (in
                        // use-planning-column-widths.ts) only comfortably budgets indentation headroom
                        // up to a typical depth of 4 -- a tree nested deeper than that may need the
                        // Name column widened via its resize handle to keep the chevron/text fully
                        // visible, which is expected, not a bug.
                        style={{ paddingLeft: `${row.depth * 1.25}rem` }}
                      >
                        {row.hasChildren ? (
                          <button
                            type="button"
                            aria-label={collapsed ? `Déplier ${row.name}` : `Replier ${row.name}`}
                            className="flex size-6 shrink-0 items-center justify-center"
                            onClick={(event) => {
                              event.stopPropagation();
                              selection.toggleCollapsed(row.uid);
                            }}
                          >
                            {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
                          </button>
                        ) : (
                          <span className="size-6 shrink-0" />
                        )}
                        <TaskNameLabel
                          name={row.name}
                          width={columnWidths.widths.name}
                          isMilestone={row.is_milestone}
                        />
                      </div>
                    </TableCell>
                    <TableCell>{taskTypeLabel(row)}</TableCell>
                    <PlanningScheduleCells
                      row={row}
                      draft={scheduleDrafts.scheduleDraftFor(row)}
                      readOnly={readOnly}
                      hasScheduleUpdate={Boolean(onScheduleUpdate)}
                      mutationBusy={mutationBusy}
                      tasksByUid={tasksByUid}
                      onUpdateDraft={(field, value) => scheduleDrafts.updateScheduleDraft(row, field, value)}
                      onCommit={() => void scheduleDrafts.commitScheduleEdit(row)}
                      onCommitModeChange={(isManual) => void scheduleDrafts.commitModeChange(row, isManual)}
                      onFieldKeyDown={scheduleDrafts.onScheduleFieldKeyDown}
                    />
                    <TableCell className="whitespace-normal break-words align-top">
                      <div className="flex items-center gap-2">
                        <span>{predecessorsLabel(row)}</span>
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
