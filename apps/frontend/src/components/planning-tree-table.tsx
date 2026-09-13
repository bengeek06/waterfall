"use client";

import { useEffect, useMemo, useRef, useState, type MouseEvent, type Ref } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlanningCreateTaskDialog } from "@/components/planning-create-task-dialog";
import { PlanningDeleteDialog } from "@/components/planning-delete-dialog";
import { PlanningScheduleCells } from "@/components/planning-schedule-cells";
import { PlanningTaskLinksDialog } from "@/components/planning-task-links-dialog";
import { PlanningTreeToolbar } from "@/components/planning-tree-toolbar";
import { TreeTableColumnResizeHandle } from "@/components/tree-table-column-resize-handle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  PLANNING_COLUMN_ORDER,
  PLANNING_MAX_COLUMN_WIDTH,
  PLANNING_MIN_COLUMN_WIDTHS,
  usePlanningColumnWidths,
  type PlanningColumnKey,
} from "@/hooks/use-planning-column-widths";
import { usePlanningCreateTaskDialog, type CreateTaskCommand } from "@/hooks/use-planning-create-task-dialog";
import { usePlanningScheduleDrafts, type SchedulePayload } from "@/hooks/use-planning-schedule-drafts";
import { usePlanningTaskLinks } from "@/hooks/use-planning-task-links";
import { stopRowKeys, useTreeTableSelection } from "@/hooks/use-tree-table-selection";
import type { RevisionNode, RevisionPredecessorWrite } from "@/lib/backend";
import { DEFAULT_PROJECT_CALENDAR, type ProjectCalendar } from "@/lib/planning-calendar";
import { predecessorsLabel } from "@/lib/planning-links";
import {
  EXPLAINED_MOVE_REFUSALS,
  planningMoveAvailability,
  normalizeSelectionToRoots,
  type PlanningMoveMode,
  type PlanningRow,
} from "@/lib/planning-tree";
import { revisionNodeRowIdentity, siblingRanks } from "@/lib/revision-tree";
import { cn } from "@/lib/utils";

const COLUMN_HEADERS: ReadonlyArray<{ key: PlanningColumnKey; label: string }> = [
  { key: "uid", label: "ID" },
  { key: "name", label: "Nom" },
  { key: "type", label: "Type" },
  { key: "start", label: "Début" },
  { key: "end", label: "Fin" },
  { key: "duration", label: "Durée" },
  { key: "mode", label: "Mode" },
  { key: "predecessors", label: "Prédécesseurs" },
];

// Renders a task's name, interactive only when it is actually visually truncated: an ordinary,
// non-truncated name stays a plain <span>, with no tab stop or button semantics, so keyboard/
// screen-reader users navigating a large planning (including the supported 1000-row case) never
// have to traverse a per-row control that does nothing beyond announcing the name they'd already
// hear. Only once the text is truncated does it become a focusable Tooltip trigger, which is the
// only way to reach the full name without a mouse hover in that case.
function TaskNameLabel({ name, width, isMilestone }: Readonly<{ name: string; width: number; isMilestone: boolean }>) {
  // Typed as the common base rather than HTMLSpanElement | HTMLButtonElement because the same ref
  // is attached to either a plain <span> (untruncated case) or the Tooltip's <button> trigger
  // (truncated case) -- only scrollWidth/clientWidth are read from it, both HTMLElement members.
  const textRef = useRef<HTMLElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  // Re-checked whenever the name text or the Name column's own width changes -- either can flip
  // whether the text actually overflows its box.
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
      <span ref={textRef as Ref<HTMLSpanElement>} className="min-w-0 truncate text-left">
        {label}
      </span>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger
        ref={textRef as Ref<HTMLButtonElement>}
        type="button"
        className="min-w-0 truncate text-left"
        onClick={(event: MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
        {...stopRowKeys}
      >
        {label}
      </TooltipTrigger>
      <TooltipContent>{name}</TooltipContent>
    </Tooltip>
  );
}

// A task with task children is a summary line: the revision model carries no `is_summary` column,
// because the tree already says it (and a task carrying only cost lines is not one).
function planningRowTypeLabel(row: PlanningRow): string {
  if (row.planning.is_milestone) {
    return "Jalon";
  }
  return row.hasChildren ? "Résumé" : "Tâche";
}

function rowLabel(row: PlanningRow): string {
  return `${row.row_number} - ${row.planning.name}`;
}

// Only meaningful when exactly one row is selected: with zero or several rows selected there is no
// single unambiguous "relative to this task" position, so the create dialog only offers the
// root-level default in that case (see PlanningCreateTaskDialog's position <select>).
function getSingleSelectedRow(selectedIds: Set<number>, rowsByNodeId: Map<number, PlanningRow>): PlanningRow | null {
  if (selectedIds.size !== 1) {
    return null;
  }
  return rowsByNodeId.get([...selectedIds][0]) ?? null;
}

export type PlanningTreeTableProps = Readonly<{
  /** Task rows of the displayed revision, depth-first, as lib/planning-tree.ts builds them. */
  rows: PlanningRow[];
  /**
   * The revision's **complete** node list -- cost nodes included, hence not `rows` above.
   *
   * It is what the move commands decide on: the backend ranks a node among *all* its siblings
   * (`children_of()`, INV-05), so a task sitting after a cost line is not at the rank the task
   * rows alone suggest. See planningMoveAvailability's contract.
   */
  treeNodes: readonly RevisionNode[];
  /** node_id -> row_number over the **whole** tree, for the Prédécesseurs column. */
  rowNumberByNodeId: Map<number, number>;
  /** Identity of the displayed revision; changing it resets local expand/selection/draft state. */
  revisionKey: number | null;
  /**
   * The owning project's working calendar, used to format/parse the Duration cell and the
   * Prédécesseurs column's lag in MS-Project-like units (day/week/month) instead of raw minutes.
   */
  calendar?: ProjectCalendar;
  readOnly?: boolean;
  /**
   * Asks for one of the four sibling-level moves. The destination is **not** passed: `POST
   * .../nodes/move` computes it from the mode (and the outdent semantics of #344 are its own, not
   * this table's). Node ids are passed raw -- the backend normalises the selection to its roots.
   */
  onMove?: (mode: PlanningMoveMode, nodeIds: number[]) => void;
  onScheduleUpdate?: (nodeId: number, payload: SchedulePayload) => Promise<boolean>;
  /** Replaces the whole predecessor list of one node; rejects with a user-facing message on failure. */
  onEditLinks?: (payload: { nodeId: number; predecessors: RevisionPredecessorWrite[] }) => Promise<void>;
  /** Creates a single task at an explicit position; errors are reported by the parent's own state. */
  onCreateTask?: (command: CreateTaskCommand) => void;
  /**
   * Deletes the given nodes, their subtree and both facets of each (INV-02) -- the confirmation is
   * asked here, before the call, since the backend's cascade is unconditional. Errors and the list
   * of chiffrage the deletion took away are reported by the parent's own state.
   */
  onDeleteNodes?: (nodeIds: number[]) => void;
  mutationBusy?: boolean;
}>;

export function PlanningTreeTable({
  rows,
  treeNodes,
  rowNumberByNodeId,
  revisionKey,
  calendar = DEFAULT_PROJECT_CALENDAR,
  readOnly = false,
  onMove,
  onScheduleUpdate,
  onEditLinks,
  onCreateTask,
  onDeleteNodes,
  mutationBusy = false,
}: PlanningTreeTableProps) {
  const [renderedRevisionKey, setRenderedRevisionKey] = useState(revisionKey);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Whole-tree lookup (unlike selection.visibleRows, not limited to currently-visible rows): a
  // predecessor referenced by a collapsed/off-screen row must still resolve correctly.
  const rowsByNodeId = useMemo(() => new Map(rows.map((row) => [row.node_id, row])), [rows]);

  const columnWidths = usePlanningColumnWidths();
  // Table renders `w-full`, which under table-fixed layout redistributes any surplus between the
  // container and this sum across the columns -- making rendered widths drift from the persisted
  // ones and coupling a resize on one column to its neighbors. Pinning the table's own width to
  // exactly this sum keeps each handle in sole control of its column; the existing overflow-x-auto
  // wrapper still takes over and scrolls once this exceeds the viewport.
  const totalColumnWidth = useMemo(
    () => PLANNING_COLUMN_ORDER.reduce((total, key) => total + columnWidths.widths[key], 0),
    [columnWidths.widths],
  );
  const selection = useTreeTableSelection(rows, revisionNodeRowIdentity);
  const scheduleDrafts = usePlanningScheduleDrafts({ onScheduleUpdate, mutationBusy, calendar });
  const taskLinks = usePlanningTaskLinks({ rows, onEditLinks });
  const singleSelectedRow = getSingleSelectedRow(selection.selectedUids, rowsByNodeId);
  const createTaskDialog = usePlanningCreateTaskDialog({ onCreateTask, singleSelectedRow });

  // A different revision must never reuse another revision's expand/selection state. This is a
  // deliberate synchronous render-body write (not a useEffect): it must reset every hook's local
  // state within the same render as the revisionKey prop change, so no frame is ever painted with
  // the previous revision's selection/drafts/dialogs applied to the newly loaded rows.
  if (revisionKey !== renderedRevisionKey) {
    setRenderedRevisionKey(revisionKey);
    taskLinks.reset();
    selection.reset();
    scheduleDrafts.reset();
    createTaskDialog.reset();
    setDeleteDialogOpen(false);
  }

  const moveAvailability = {
    indent: planningMoveAvailability(treeNodes, selection.selectedUids, "indent"),
    outdent: planningMoveAvailability(treeNodes, selection.selectedUids, "outdent"),
    up: planningMoveAvailability(treeNodes, selection.selectedUids, "up"),
    down: planningMoveAvailability(treeNodes, selection.selectedUids, "down"),
  };
  // INV-27 (#343) and INV-14 are explained rather than merely greyed out: "this row is already
  // the first of its level" is self-evident from the table, whereas "this jalon cannot be
  // outdented" comes from a flag carried by another row -- and "the previous sibling is a cost
  // line" from a row this table does not even render. A user who is not told would keep clicking
  // a dead button. Announced politely (role="status") so a screen-reader user learns it too,
  // instead of only seeing a disabled control.
  const moveNotice =
    [moveAvailability.indent, moveAvailability.outdent].find(
      (availability) => availability.refusal !== null && EXPLAINED_MOVE_REFUSALS.has(availability.refusal),
    )?.reason ?? null;

  const selectedRootIds = normalizeSelectionToRoots(treeNodes, selection.selectedUids).map(
    (node) => node.node_id,
  );
  const selectedLabels = [...selection.selectedUids]
    .map((nodeId) => rowsByNodeId.get(nodeId))
    .filter((row): row is PlanningRow => row !== undefined)
    .map(rowLabel);

  function dispatchMove(mode: PlanningMoveMode) {
    if (planningMoveAvailability(treeNodes, selection.selectedUids, mode).enabled) {
      onMove?.(mode, [...selection.selectedUids]);
    }
  }

  function confirmDelete() {
    onDeleteNodes?.(selectedRootIds);
    setDeleteDialogOpen(false);
    selection.clearSelection();
  }

  // aria-posinset/aria-setsize, which a flattened DOM gives assistive technology no way to work
  // out on its own (#380). Both are computed over the **rendered** rows, deliberately unlike the
  // move commands above: the stored `position` ranks a node among all its siblings, cost lines
  // included, so pairing it with a count of task rows would announce "3 of 2" as soon as a cost
  // node sits between two tasks.
  const rankByNodeId = useMemo(() => siblingRanks(rows), [rows]);

  const readOnlyNotice = readOnly ? (
    <p className="mt-2 text-xs text-muted-foreground">
      Révision validée ou projet en lecture seule : édition désactivée. Crée un brouillon pour
      modifier ce planning.
    </p>
  ) : null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Planning</CardTitle>
      </CardHeader>
      <CardContent>
        <PlanningTreeToolbar
          visible={!readOnly}
          showMoveActions={Boolean(onMove)}
          indentDisabled={!moveAvailability.indent.enabled || mutationBusy}
          outdentDisabled={!moveAvailability.outdent.enabled || mutationBusy}
          moveUpDisabled={!moveAvailability.up.enabled || mutationBusy}
          moveDownDisabled={!moveAvailability.down.enabled || mutationBusy}
          onIndent={() => dispatchMove("indent")}
          onOutdent={() => dispatchMove("outdent")}
          onMoveUp={() => dispatchMove("up")}
          onMoveDown={() => dispatchMove("down")}
          notice={moveNotice}
          showCreateAction={Boolean(onCreateTask)}
          createDisabled={mutationBusy}
          onCreateTask={createTaskDialog.openCreateTaskDialog}
          showDeleteAction={Boolean(onDeleteNodes)}
          deleteDisabled={selection.selectedUids.size === 0 || mutationBusy}
          onDeleteSelection={() => setDeleteDialogOpen(true)}
        />
        {selection.visibleRows.length === 0 ? (
          <p className="py-6 text-sm text-muted-foreground">Cette révision ne contient aucune tâche.</p>
        ) : (
          <Table
            // #380: the interaction model this table has always implemented -- rows that fold,
            // unfold, take focus and enter a selection -- is a treegrid, and now says so. Without
            // these roles a screen-reader user hears a plain table and is told neither the level of
            // a row nor whether it can be unfolded.
            role="treegrid"
            aria-label="Planning de la révision"
            aria-multiselectable="true"
            className="table-fixed w-auto"
            style={{ width: totalColumnWidth }}
          >
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
                    <TreeTableColumnResizeHandle
                      column={key}
                      label={label}
                      width={columnWidths.widths[key]}
                      min={PLANNING_MIN_COLUMN_WIDTHS[key]}
                      max={PLANNING_MAX_COLUMN_WIDTH}
                      onResizeStart={columnWidths.startResize}
                      onResizeBy={columnWidths.resizeBy}
                    />
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {selection.visibleRows.map((row) => {
                const collapsed = selection.collapsedUids.has(row.node_id);
                const selected = selection.selectedUids.has(row.node_id);
                const isFocusable = selection.focusableUid === row.node_id;
                return (
                  <TableRow
                    key={row.node_id}
                    ref={(element) => selection.registerRow(row, element)}
                    role="row"
                    data-state={selected ? "selected" : undefined}
                    aria-selected={selected}
                    aria-level={row.level}
                    aria-posinset={rankByNodeId.get(row.node_id)?.position ?? 1}
                    aria-setsize={rankByNodeId.get(row.node_id)?.total ?? 1}
                    aria-expanded={row.hasChildren ? !collapsed : undefined}
                    tabIndex={isFocusable ? 0 : -1}
                    // The focus ring is an `outline` and not the `ring-3` the design system uses
                    // elsewhere: a box-shadow on a `display: table-row` element is unreliable across
                    // browsers, where an outline is drawn around the whole row. Replacing the bare
                    // `outline-none` this row used to carry is the other half of #380 -- a focused
                    // row that shows nothing fails WCAG 2.4.7 no matter how correct its roles are.
                    className="cursor-pointer outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
                    onClick={(event) => selection.selectRow(row, event)}
                    onFocus={() => selection.setFocusedUid(row.node_id)}
                    onKeyDown={(event) => selection.onRowKeyDown(event, row)}
                  >
                    <TableCell role="gridcell">{row.row_number}</TableCell>
                    <TableCell role="gridcell" className="overflow-hidden">
                      <div
                        className="flex min-w-0 items-center gap-1"
                        // Deliberately uncapped: the tree allows arbitrary nesting depth (a real
                        // MS Project import can exceed a handful of levels), and the visual
                        // indentation must keep reflecting the actual hierarchy. `level` is 1-based
                        // (roots at 1), hence the -1.
                        style={{ paddingLeft: `${(row.level - 1) * 1.25}rem` }}
                      >
                        {row.hasChildren ? (
                          <button
                            type="button"
                            aria-label={
                              collapsed ? `Déplier ${row.planning.name}` : `Replier ${row.planning.name}`
                            }
                            className="flex size-6 shrink-0 items-center justify-center rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                            {...stopRowKeys}
                            onClick={(event) => {
                              event.stopPropagation();
                              selection.toggleCollapsed(row.node_id);
                            }}
                          >
                            {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
                          </button>
                        ) : (
                          <span className="size-6 shrink-0" />
                        )}
                        <TaskNameLabel
                          name={row.planning.name}
                          width={columnWidths.widths.name}
                          isMilestone={row.planning.is_milestone}
                        />
                      </div>
                    </TableCell>
                    <TableCell role="gridcell">{planningRowTypeLabel(row)}</TableCell>
                    <PlanningScheduleCells
                      row={row}
                      draft={scheduleDrafts.scheduleDraftFor(row)}
                      readOnly={readOnly}
                      hasScheduleUpdate={Boolean(onScheduleUpdate)}
                      mutationBusy={mutationBusy}
                      calendar={calendar}
                      durationError={scheduleDrafts.durationErrorFor(row)}
                      rowsByNodeId={rowsByNodeId}
                      onUpdateDraft={(field, value) => scheduleDrafts.updateScheduleDraft(row, field, value)}
                      onCommit={() => void scheduleDrafts.commitScheduleEdit(row)}
                      onCommitModeChange={(isManual) => void scheduleDrafts.commitModeChange(row, isManual)}
                      onFieldKeyDown={scheduleDrafts.onScheduleFieldKeyDown}
                    />
                    <TableCell role="gridcell" className="whitespace-normal break-words align-top">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0">
                          {predecessorsLabel(row.predecessors, calendar, rowNumberByNodeId)}
                        </span>
                        {!readOnly && onEditLinks ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="shrink-0"
                            disabled={mutationBusy}
                            aria-label={`Éditer les prédécesseurs de ${row.planning.name}`}
                            {...stopRowKeys}
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
        editingRow={taskLinks.editingRow}
        linkCandidateRows={taskLinks.linkCandidateRows}
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
        singleSelectedRow={singleSelectedRow}
        mutationBusy={mutationBusy}
        onNameChange={createTaskDialog.setCreateTaskName}
        onMilestoneChange={createTaskDialog.setCreateTaskIsMilestone}
        onPositionModeChange={createTaskDialog.setCreatePositionMode}
        onClose={createTaskDialog.closeCreateTaskDialog}
        onSubmit={createTaskDialog.submitCreateTask}
      />
      <PlanningDeleteDialog
        open={deleteDialogOpen}
        rowLabels={selectedLabels}
        busy={mutationBusy}
        onCancel={() => setDeleteDialogOpen(false)}
        onConfirm={confirmDelete}
      />
    </Card>
  );
}
