"use client";

import type { KeyboardEvent, MouseEvent } from "react";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TableCell } from "@/components/ui/table";
import { stopRowKeys } from "@/hooks/use-tree-table-selection";
import { formatCalendarDuration, type ProjectCalendar } from "@/lib/planning-calendar";
import {
  durationInvalidForAutomatic,
  formatDate,
  missingStartAnchorForAutomatic,
  planningModeLabel,
  type ScheduleDraft,
} from "@/lib/planning-schedule";
import type { PlanningRow } from "@/lib/planning-tree";

type ScheduleEditability = {
  editable: boolean;
  startEditable: boolean;
  finishEditable: boolean;
  durationEditable: boolean;
  startConstrainedByPredecessors: boolean;
  startHelpText: string | undefined;
};

// Centralizes every "which cell is editable for this row" branch in one place so the individual
// cell renderers below stay simple prop-in/JSX-out functions.
//
// E14-10 (#336): "is a summary" is no longer a stored flag but the structural fact of having task
// children -- a task carrying only cost lines is still a leaf of the planning and stays editable.
function computeScheduleEditability(row: PlanningRow, readOnly: boolean, hasScheduleUpdate: boolean): ScheduleEditability {
  const editable = !row.hasChildren && !readOnly && hasScheduleUpdate;
  const startEditable = editable && (row.planning.is_milestone || row.planning.is_manual);
  // The client cannot know whether a predecessor link actually resolves to a schedule constraint
  // server-side -- only whether one exists at all. Using "has at least one predecessor" as a proxy
  // is a documented, deliberate over-approximation: worst case a not-yet-constraining link
  // disables the field a little early, which is far preferable to accepting an edit guaranteed to
  // be silently reverted by the server.
  const startConstrainedByPredecessors =
    row.planning.is_milestone && !row.planning.is_manual && row.predecessors.length > 0;
  return {
    editable,
    startEditable,
    finishEditable: editable && !row.planning.is_milestone && row.planning.is_manual,
    durationEditable: editable && !row.planning.is_milestone,
    startConstrainedByPredecessors,
    startHelpText: startConstrainedByPredecessors ? "Date déterminée par les prédécesseurs" : undefined,
  };
}

type ScheduleCellProps = {
  row: PlanningRow;
  draft: ScheduleDraft;
  editability: ScheduleEditability;
  mutationBusy: boolean;
  onUpdateDraft: (field: keyof ScheduleDraft, value: string) => void;
  onCommit: () => void;
  onFieldKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
};

function StartCell({ row, draft, editability, mutationBusy, onUpdateDraft, onCommit, onFieldKeyDown }: ScheduleCellProps) {
  if (!editability.startEditable) {
    return <TableCell role="gridcell">{formatDate(row.planning.start_at)}</TableCell>;
  }
  const label = editability.startHelpText
    ? `Début de ${row.planning.name} (${editability.startHelpText})`
    : `Début de ${row.planning.name}`;
  return (
    <TableCell role="gridcell">
      <Input
        type="date"
        aria-label={label}
        title={editability.startHelpText}
        value={draft.start_at}
        disabled={mutationBusy || editability.startConstrainedByPredecessors}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onUpdateDraft("start_at", event.target.value)}
        onBlur={onCommit}
        onKeyDown={onFieldKeyDown}
      />
    </TableCell>
  );
}

function FinishCell({ row, draft, editability, mutationBusy, onUpdateDraft, onCommit, onFieldKeyDown }: ScheduleCellProps) {
  if (!editability.finishEditable) {
    return <TableCell role="gridcell">{formatDate(row.planning.finish_at)}</TableCell>;
  }
  return (
    <TableCell role="gridcell">
      <Input
        type="date"
        aria-label={`Fin de ${row.planning.name}`}
        value={draft.finish_at}
        disabled={mutationBusy}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onUpdateDraft("finish_at", event.target.value)}
        onBlur={onCommit}
        onKeyDown={onFieldKeyDown}
      />
    </TableCell>
  );
}

type DurationCellProps = ScheduleCellProps & {
  calendar: ProjectCalendar;
  /** Format-parsing error (see lib/planning-calendar.ts) from the last commit attempt on this
   * row's duration field, or null. Business-validation failures (e.g. a 0 duration on an automatic
   * task) are still silently rejected with no message -- only an unrecognized *format* surfaces. */
  durationError: string | null;
};

function DurationCell({
  row,
  draft,
  editability,
  mutationBusy,
  calendar,
  durationError,
  onUpdateDraft,
  onCommit,
  onFieldKeyDown,
}: DurationCellProps) {
  if (!editability.durationEditable) {
    return <TableCell role="gridcell">{formatCalendarDuration(row.planning.duration_minutes, calendar)}</TableCell>;
  }
  const errorId = `duration-error-${row.node_id}`;
  return (
    <TableCell role="gridcell">
      <Input
        // A plain number input cannot accept the MS-Project-like unit suffixes ("3j", "1sm2j",
        // ...) this field accepts alongside raw minutes -- see lib/planning-calendar.ts.
        type="text"
        aria-label={`Durée de ${row.planning.name}`}
        aria-invalid={durationError ? true : undefined}
        aria-describedby={durationError ? errorId : undefined}
        value={draft.duration_minutes}
        disabled={mutationBusy}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onUpdateDraft("duration_minutes", event.target.value)}
        onBlur={onCommit}
        onKeyDown={onFieldKeyDown}
      />
      {durationError ? (
        <p id={errorId} role="alert" className="mt-1 text-xs text-destructive">
          {durationError}
        </p>
      ) : null}
    </TableCell>
  );
}

type ModeCellProps = {
  row: PlanningRow;
  editability: ScheduleEditability;
  mutationBusy: boolean;
  rowsByNodeId: Map<number, PlanningRow>;
  onCommitModeChange: (isManual: boolean) => void;
};

function ModeCell({ row, editability, mutationBusy, rowsByNodeId, onCommitModeChange }: ModeCellProps) {
  if (!editability.editable) {
    return <TableCell role="gridcell">{planningModeLabel(row.planning)}</TableCell>;
  }
  // A milestone's duration is always forced to 0 server-side, so it can always switch to
  // automatic. A non-milestone task with no duration, or a zero/negative one (a valid state for a
  // manual task), would be rejected by the server, so disable the option rather than let the user
  // hit a guaranteed 400. Separately, automatic scheduling needs either a stored start_at or at
  // least one predecessor resolving to a start anchor -- without either, disable it too.
  const automaticDisabled =
    (!row.planning.is_milestone && durationInvalidForAutomatic(row.planning)) ||
    missingStartAnchorForAutomatic(row, rowsByNodeId);
  return (
    <TableCell role="gridcell">
      <Select
        value={row.planning.is_manual ? "manual" : "auto"}
        onValueChange={(value) => onCommitModeChange(value === "manual")}
        disabled={mutationBusy}
      >
        <SelectTrigger
          aria-label={`Mode de ${row.planning.name}`}
          size="sm"
          onClick={(event: MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
          {...stopRowKeys}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="manual">Manuel</SelectItem>
          <SelectItem value="auto" disabled={automaticDisabled}>
            Automatique
          </SelectItem>
        </SelectContent>
      </Select>
    </TableCell>
  );
}

export type PlanningScheduleCellsProps = Readonly<{
  row: PlanningRow;
  draft: ScheduleDraft;
  readOnly: boolean;
  hasScheduleUpdate: boolean;
  mutationBusy: boolean;
  calendar: ProjectCalendar;
  durationError: string | null;
  rowsByNodeId: Map<number, PlanningRow>;
  onUpdateDraft: (field: keyof ScheduleDraft, value: string) => void;
  onCommit: () => void;
  onCommitModeChange: (isManual: boolean) => void;
  onFieldKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
}>;

// Extracted from PlanningTreeTable's former renderScheduleCells (E4-12 / #152): the four
// start/finish/duration/mode cells of one planning row, each an editable input or a read-only
// formatted value depending on the row's milestone/manual/automatic state (see
// computeScheduleEditability above). Every cell carries `role="gridcell"` explicitly, the table
// itself being a `treegrid` (#380).
export function PlanningScheduleCells({
  row,
  draft,
  readOnly,
  hasScheduleUpdate,
  mutationBusy,
  calendar,
  durationError,
  rowsByNodeId,
  onUpdateDraft,
  onCommit,
  onCommitModeChange,
  onFieldKeyDown,
}: PlanningScheduleCellsProps) {
  const editability = computeScheduleEditability(row, readOnly, hasScheduleUpdate);
  const shared = { row, draft, editability, mutationBusy, onUpdateDraft, onCommit, onFieldKeyDown };
  return (
    <>
      <StartCell {...shared} />
      <FinishCell {...shared} />
      <DurationCell {...shared} calendar={calendar} durationError={durationError} />
      <ModeCell
        row={row}
        editability={editability}
        mutationBusy={mutationBusy}
        rowsByNodeId={rowsByNodeId}
        onCommitModeChange={onCommitModeChange}
      />
    </>
  );
}
