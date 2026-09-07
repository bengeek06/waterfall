"use client";

import type { KeyboardEvent, MouseEvent } from "react";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TableCell } from "@/components/ui/table";
import type { Task } from "@/lib/backend";
import { formatCalendarDuration, type ProjectCalendar } from "@/lib/planning-calendar";
import {
  durationInvalidForAutomatic,
  formatDate,
  missingStartAnchorForAutomatic,
  taskModeLabel,
  type ScheduleDraft,
} from "@/lib/planning-schedule";
import type { PlanningTreeRow } from "@/lib/planning-tree";

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
function computeScheduleEditability(row: PlanningTreeRow, readOnly: boolean, hasScheduleUpdate: boolean): ScheduleEditability {
  const editable = !row.is_summary && !readOnly && hasScheduleUpdate;
  const startEditable = editable && Boolean(row.is_milestone || row.is_manual);
  // The client cannot know whether a predecessor link actually resolves to a schedule
  // constraint server-side (`_apply_automatic_milestone_schedule` only ignores payload.start_at
  // once `_resolve_predecessor_constraints` yields at least one value, which additionally
  // requires the predecessor to itself already have a start_at/finish_at) -- only whether a
  // predecessor link exists at all. Using "has at least one predecessor link" as a proxy is a
  // documented, deliberate over-approximation: worst case a not-yet-constraining link disables
  // the field a little early, which is far preferable to accepting an edit guaranteed to be
  // silently reverted by the server.
  const startConstrainedByPredecessors = row.is_milestone && !row.is_manual && Boolean(row.predecessor_links?.length);
  return {
    editable,
    startEditable,
    finishEditable: editable && !row.is_milestone && Boolean(row.is_manual),
    durationEditable: editable && !row.is_milestone,
    startConstrainedByPredecessors,
    startHelpText: startConstrainedByPredecessors ? "Date déterminée par les prédécesseurs" : undefined,
  };
}

type StartCellProps = {
  row: PlanningTreeRow;
  draft: ScheduleDraft;
  editability: ScheduleEditability;
  mutationBusy: boolean;
  onUpdateDraft: (field: keyof ScheduleDraft, value: string) => void;
  onCommit: () => void;
  onFieldKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
};

function StartCell({ row, draft, editability, mutationBusy, onUpdateDraft, onCommit, onFieldKeyDown }: StartCellProps) {
  if (!editability.startEditable) {
    return <TableCell>{formatDate(row.start_at)}</TableCell>;
  }
  const label = editability.startHelpText ? `Début de ${row.name} (${editability.startHelpText})` : `Début de ${row.name}`;
  return (
    <TableCell>
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

type FinishCellProps = {
  row: PlanningTreeRow;
  draft: ScheduleDraft;
  editability: ScheduleEditability;
  mutationBusy: boolean;
  onUpdateDraft: (field: keyof ScheduleDraft, value: string) => void;
  onCommit: () => void;
  onFieldKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
};

function FinishCell({ row, draft, editability, mutationBusy, onUpdateDraft, onCommit, onFieldKeyDown }: FinishCellProps) {
  if (!editability.finishEditable) {
    return <TableCell>{formatDate(row.finish_at)}</TableCell>;
  }
  return (
    <TableCell>
      <Input
        type="date"
        aria-label={`Fin de ${row.name}`}
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

type DurationCellProps = {
  row: PlanningTreeRow;
  draft: ScheduleDraft;
  editability: ScheduleEditability;
  mutationBusy: boolean;
  calendar: ProjectCalendar;
  /** Format-parsing error (see lib/planning-calendar.ts) from the last commit attempt on this row's
   * duration field, or null. Business-validation failures (e.g. a 0 duration on an automatic task)
   * are still silently rejected with no message, unchanged from before #142 -- only an unrecognized
   * *format* surfaces here. */
  durationError: string | null;
  onUpdateDraft: (field: keyof ScheduleDraft, value: string) => void;
  onCommit: () => void;
  onFieldKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
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
    return <TableCell>{formatCalendarDuration(row.duration_minutes, calendar)}</TableCell>;
  }
  const errorId = `duration-error-${row.uid}`;
  return (
    <TableCell>
      <Input
        // A plain number input cannot accept the MS-Project-like unit suffixes ("3j", "1sm2j",
        // ...) this field now accepts alongside raw minutes -- see lib/planning-calendar.ts.
        // `min`/`step` are dropped along with it: commitScheduleEdit (via buildManualPayload /
        // buildAutomaticPayload) remains the real guard against a doomed or malformed request.
        type="text"
        aria-label={`Durée de ${row.name}`}
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
  row: PlanningTreeRow;
  editability: ScheduleEditability;
  mutationBusy: boolean;
  tasksByUid: Map<number, Task>;
  onCommitModeChange: (isManual: boolean) => void;
};

function ModeCell({ row, editability, mutationBusy, tasksByUid, onCommitModeChange }: ModeCellProps) {
  if (!editability.editable) {
    return <TableCell>{taskModeLabel(row)}</TableCell>;
  }
  // A milestone's duration is always forced to 0 server-side, so it can always switch to
  // automatic. A non-milestone task with no duration, or a zero/negative one (a valid state for a
  // manual task), would be rejected by the server (_apply_automatic_schedule requires a strictly
  // positive duration), so disable the option rather than let the user hit a guaranteed 400.
  // Separately, both _apply_automatic_schedule and _apply_automatic_milestone_schedule need
  // either a stored start_at or at least one predecessor link to derive a start anchor (milestone
  // or not) — without either, disable the option too.
  const automaticDisabled =
    (!row.is_milestone && durationInvalidForAutomatic(row)) || missingStartAnchorForAutomatic(row, tasksByUid);
  return (
    <TableCell>
      <Select value={row.is_manual ? "manual" : "auto"} onValueChange={(value) => onCommitModeChange(value === "manual")} disabled={mutationBusy}>
        <SelectTrigger
          aria-label={`Mode de ${row.name}`}
          size="sm"
          onClick={(event: MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
          onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => event.stopPropagation()}
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
  row: PlanningTreeRow;
  draft: ScheduleDraft;
  readOnly: boolean;
  hasScheduleUpdate: boolean;
  mutationBusy: boolean;
  calendar: ProjectCalendar;
  durationError: string | null;
  tasksByUid: Map<number, Task>;
  onUpdateDraft: (field: keyof ScheduleDraft, value: string) => void;
  onCommit: () => void;
  onCommitModeChange: (isManual: boolean) => void;
  onFieldKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
}>;

// Extracted from PlanningTreeTable's former renderScheduleCells (E4-12 / #152): the four
// start/finish/duration/mode <TableCell>s of one planning row, each an editable input or a
// read-only formatted value depending on the row's milestone/manual/automatic state (see
// computeScheduleEditability above).
export function PlanningScheduleCells({
  row,
  draft,
  readOnly,
  hasScheduleUpdate,
  mutationBusy,
  calendar,
  durationError,
  tasksByUid,
  onUpdateDraft,
  onCommit,
  onCommitModeChange,
  onFieldKeyDown,
}: PlanningScheduleCellsProps) {
  const editability = computeScheduleEditability(row, readOnly, hasScheduleUpdate);
  return (
    <>
      <StartCell row={row} draft={draft} editability={editability} mutationBusy={mutationBusy} onUpdateDraft={onUpdateDraft} onCommit={onCommit} onFieldKeyDown={onFieldKeyDown} />
      <FinishCell row={row} draft={draft} editability={editability} mutationBusy={mutationBusy} onUpdateDraft={onUpdateDraft} onCommit={onCommit} onFieldKeyDown={onFieldKeyDown} />
      <DurationCell row={row} draft={draft} editability={editability} mutationBusy={mutationBusy} calendar={calendar} durationError={durationError} onUpdateDraft={onUpdateDraft} onCommit={onCommit} onFieldKeyDown={onFieldKeyDown} />
      <ModeCell row={row} editability={editability} mutationBusy={mutationBusy} tasksByUid={tasksByUid} onCommitModeChange={onCommitModeChange} />
    </>
  );
}
