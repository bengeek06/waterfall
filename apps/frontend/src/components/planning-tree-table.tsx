"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { PlanningTaskScheduleUpdate, Task } from "@/lib/backend";
import {
  computeIndentCommand,
  computeOutdentCommand,
  computeReorderCommand,
  type PlanningMoveCommand,
} from "@/lib/planning-tree";

type PlanningTreeRow = Task & { depth: number; hasChildren: boolean };

// MS Project standard predecessor link type codes (see wf_planning_link_snapshot check constraint).
const LINK_TYPE_LABELS: Record<number, string> = { 0: "FF", 1: "FS", 2: "SF", 3: "SS" };

function buildVisibleRows(tasks: Task[], collapsedUids: Set<number>): PlanningTreeRow[] {
  const knownUids = new Set(tasks.map((task) => task.uid));
  const childrenByParent = new Map<number | null, Task[]>();
  for (const task of tasks) {
    const parentKey = task.parent_uid !== null && task.parent_uid !== undefined && knownUids.has(task.parent_uid)
      ? task.parent_uid
      : null;
    const siblings = childrenByParent.get(parentKey) ?? [];
    siblings.push(task);
    childrenByParent.set(parentKey, siblings);
  }
  // The backend orders unpositioned tasks last; mirror that instead of treating null as position 0.
  for (const siblings of childrenByParent.values()) {
    siblings.sort((a, b) => (a.position ?? Number.POSITIVE_INFINITY) - (b.position ?? Number.POSITIVE_INFINITY));
  }

  const rows: PlanningTreeRow[] = [];
  function walk(parentUid: number | null, depth: number) {
    for (const task of childrenByParent.get(parentUid) ?? []) {
      const hasChildren = (childrenByParent.get(task.uid) ?? []).length > 0;
      rows.push({ ...task, depth, hasChildren });
      if (hasChildren && !collapsedUids.has(task.uid)) {
        walk(task.uid, depth + 1);
      }
    }
  }
  walk(null, 0);
  return rows;
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  // Read-only counterpart of toDateTimeInputValue's UTC convention (see below): parse the
  // naive-UTC backend value as UTC, then format in UTC too, so this display never disagrees
  // with the editable fields or shifts across a midnight boundary for a non-UTC viewer.
  return new Date(asUtcIsoString(value)).toLocaleDateString("fr-FR", { timeZone: "UTC" });
}

function formatDurationMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) {
    return "-";
  }
  if (minutes === 0) {
    return "0";
  }
  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  if (hours === 0) {
    return `${remainderMinutes}min`;
  }
  if (remainderMinutes === 0) {
    return `${hours}h`;
  }
  return `${hours}h${remainderMinutes}min`;
}

// The backend stores/returns naive-UTC datetimes (no offset, e.g. "2026-01-09T08:00:00"). A
// string with no trailing "Z"/numeric offset is otherwise interpreted by `new Date(...)` as
// *local* time (standard JS behaviour), which silently shifts every value by the browser's UTC
// offset for any non-UTC user. Force it to be read as UTC by appending "Z" when no offset is
// already present.
function asUtcIsoString(value: string): string {
  return /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
}

// Timezone convention (deliberate, keep toDateTimeInputValue/fromDateTimeInputValue symmetric):
// this field always displays and edits the value's *UTC* components, not the browser's local
// time. A native `datetime-local` input has no timezone concept of its own, so "local time" here
// would actually mean "the browser's local time", which has no clean, lossless round-trip back to
// the naive-UTC value the backend expects without extra local<->UTC conversion. Treating the
// component's yyyy-MM-ddTHH:mm:ss as UTC end-to-end is simpler and fully reversible in every
// browser timezone; it trades away a "shows my local time" UX nicety in favour of never corrupting
// dates.
//
// Seconds are included (not just minutes) because a manual task's start_at/finish_at can carry a
// non-zero seconds component derived from a predecessor link's lag_tenth_minute (stored at a
// 6-second resolution). commitScheduleEdit always resends all three schedule fields on any single
// field edit (e.g. editing only the duration), so dropping seconds here would silently truncate an
// untouched start_at/finish_at on every commit. `step="1"` on the corresponding <Input
// type="datetime-local"> is required for the browser to surface/accept this seconds component.
function toDateTimeInputValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(asUtcIsoString(value));
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
}

// Seconds are captured as an optional group: toDateTimeInputValue always emits them, but a
// `type="datetime-local"` field's seconds granularity ultimately depends on the host browser
// honouring `step="1"` (and jsdom's own value-sanitization in tests never keeps them at all), so
// this stays defensive and treats a missing seconds group as :00 rather than rejecting the value.
const DATETIME_INPUT_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

function fromDateTimeInputValue(value: string): string | null {
  if (!value) {
    return null;
  }
  // Symmetric with toDateTimeInputValue: the field's yyyy-MM-ddTHH:mm[:ss] components are UTC, so
  // they must be parsed as UTC directly (Date.UTC), not through `new Date(value)`, which would
  // reinterpret them as local time and reintroduce the same corruption this is fixing.
  const match = DATETIME_INPUT_PATTERN.exec(value);
  if (!match) {
    return null;
  }
  const [year, month, day, hour, minute, second] = match.slice(1).map((part) => (part === undefined ? 0 : Number(part)));
  const date = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

function taskTypeLabel(task: Task): string {
  if (task.is_milestone) {
    return "Jalon";
  }
  return task.is_summary ? "Résumé" : "Tâche";
}

function taskModeLabel(task: Task): string {
  if (task.is_manual === null || task.is_manual === undefined) {
    return "-";
  }
  return task.is_manual ? "Manuel" : "Automatique";
}

// Shared with the direct duration-edit guard in commitScheduleEdit: _apply_automatic_schedule
// rejects a null/zero/negative duration with a 400, so both the "switch to automatic" affordance
// and the direct edit must treat 0/negative the same as missing.
function durationInvalidForAutomatic(task: Task): boolean {
  return (
    task.duration_minutes === null ||
    task.duration_minutes === undefined ||
    task.duration_minutes <= 0
  );
}

type PredecessorLink = NonNullable<Task["predecessor_links"]>[number];

// A predecessor link only actually resolves to a start anchor server-side
// (_resolve_predecessor_constraints) if the predecessor itself already carries the date the link
// type depends on: FS/FF (link_type 1/0) derive from the predecessor's finish_at, SS/SF
// (link_type 3/2) derive from the predecessor's start_at. Both columns are nullable (e.g. the
// predecessor can itself be an unanchored automatic task), so "a link exists" alone is not
// sufficient -- see LINK_TYPE_LABELS above for the code mapping.
function predecessorResolvesStartAnchor(link: PredecessorLink, tasksByUid: Map<number, Task>): boolean {
  const predecessor = tasksByUid.get(link.predecessor_uid);
  if (!predecessor) {
    return false;
  }
  if (link.link_type === 1 || link.link_type === 0) {
    return Boolean(predecessor.finish_at);
  }
  return Boolean(predecessor.start_at);
}

// _apply_automatic_schedule/_apply_automatic_milestone_schedule both require either a stored
// start_at or at least one predecessor link that resolves to a start anchor (see
// predecessorResolvesStartAnchor) to derive one; without either, the server rejects the automatic
// scheduling with a 400 regardless of the task being a milestone or not.
function missingStartAnchorForAutomatic(task: Task, tasksByUid: Map<number, Task>): boolean {
  if (task.start_at) {
    return false;
  }
  return !task.predecessor_links?.some((link) => predecessorResolvesStartAnchor(link, tasksByUid));
}

function predecessorsLabel(task: Task): string {
  if (!task.predecessor_links?.length) {
    return "-";
  }
  return task.predecessor_links
    .map((link) => {
      const type = LINK_TYPE_LABELS[link.link_type] ?? String(link.link_type);
      const lagMinutes = link.lag_tenth_minute ? link.lag_tenth_minute / 10 : 0;
      const lagSign = lagMinutes > 0 ? "+" : "";
      const lag = lagMinutes ? ` ${lagSign}${lagMinutes}min` : "";
      return `${link.predecessor_uid} (${type}${lag})`;
    })
    .join(", ");
}

type ScheduleDraft = {
  start_at: string;
  finish_at: string;
  duration_minutes: string;
};

type PlanningTreeTableProps = Readonly<{
  tasks: Task[];
  /** Any value identifying the loaded planning version; changing it resets local expand/selection state. */
  versionKey: number | string | null;
  readOnly?: boolean;
  onMove?: (command: PlanningMoveCommand) => void;
  onScheduleUpdate?: (taskUid: number, payload: PlanningTaskScheduleUpdate) => Promise<boolean>;
  mutationBusy?: boolean;
}>;

export function PlanningTreeTable({
  tasks,
  versionKey,
  readOnly = false,
  onMove,
  onScheduleUpdate,
  mutationBusy = false,
}: PlanningTreeTableProps) {
  const [collapsedUids, setCollapsedUids] = useState<Set<number>>(new Set());
  const [selectedUids, setSelectedUids] = useState<Set<number>>(new Set());
  const [focusedUid, setFocusedUid] = useState<number | null>(null);
  const [renderedVersionKey, setRenderedVersionKey] = useState(versionKey);
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<number, ScheduleDraft>>({});
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  // A different planning version must never reuse another version's expand/selection state.
  if (versionKey !== renderedVersionKey) {
    setRenderedVersionKey(versionKey);
    setCollapsedUids(new Set());
    setSelectedUids(new Set());
    setFocusedUid(null);
    setScheduleDrafts({});
  }

  const rows = useMemo(() => buildVisibleRows(tasks, collapsedUids), [tasks, collapsedUids]);
  const rowIndexByUid = useMemo(() => new Map(rows.map((row, index) => [row.uid, index])), [rows]);
  // Full-planning lookup (unlike rowIndexByUid, not limited to currently-visible rows): a
  // predecessor referenced by a collapsed/off-screen task must still resolve correctly.
  const tasksByUid = useMemo(() => new Map(tasks.map((task) => [task.uid, task])), [tasks]);

  useEffect(() => {
    if (focusedUid === null) {
      return;
    }
    const rowElement = rowRefs.current.get(focusedUid);
    // Do not steal focus back to the row when it is already inside one of its inline edit controls.
    if (rowElement && !rowElement.contains(document.activeElement)) {
      rowElement.focus();
    }
  }, [focusedUid]);

  const readOnlyNotice = readOnly ? (
    <p className="mt-2 text-xs text-muted-foreground">Version validée ou projet en lecture seule : édition désactivée.</p>
  ) : null;

  if (!tasks.length) {
    return (
      <>
        <p className="py-6 text-sm text-muted-foreground">Le planning ne contient aucune tâche.</p>
        {readOnlyNotice}
      </>
    );
  }

  function toggleCollapsed(uid: number) {
    setCollapsedUids((current) => {
      const next = new Set(current);
      if (next.has(uid)) {
        next.delete(uid);
      } else {
        next.add(uid);
      }
      return next;
    });
  }

  function selectRow(row: PlanningTreeRow, event: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) {
    setSelectedUids((current) => {
      if (event.shiftKey && focusedUid !== null && rowIndexByUid.has(focusedUid)) {
        const start = Math.min(rowIndexByUid.get(focusedUid)!, rowIndexByUid.get(row.uid)!);
        const end = Math.max(rowIndexByUid.get(focusedUid)!, rowIndexByUid.get(row.uid)!);
        return new Set(rows.slice(start, end + 1).map((candidate) => candidate.uid));
      }
      if (event.ctrlKey || event.metaKey) {
        const next = new Set(current);
        if (next.has(row.uid)) {
          next.delete(row.uid);
        } else {
          next.add(row.uid);
        }
        return next;
      }
      return new Set([row.uid]);
    });
    setFocusedUid(row.uid);
  }

  function focusSibling(row: PlanningTreeRow, offset: number) {
    const index = rowIndexByUid.get(row.uid) ?? 0;
    const sibling = rows[index + offset];
    if (sibling) {
      setFocusedUid(sibling.uid);
    }
  }

  function expandOrFocusChild(row: PlanningTreeRow) {
    if (!row.hasChildren) {
      return;
    }
    if (collapsedUids.has(row.uid)) {
      toggleCollapsed(row.uid);
    } else {
      focusSibling(row, 1);
    }
  }

  function collapseOrFocusParent(row: PlanningTreeRow) {
    if (row.hasChildren && !collapsedUids.has(row.uid)) {
      toggleCollapsed(row.uid);
    } else if (row.parent_uid !== null && row.parent_uid !== undefined) {
      setFocusedUid(row.parent_uid);
    }
  }

  const rowKeyHandlers: Record<string, (row: PlanningTreeRow) => void> = {
    ArrowDown: (row) => focusSibling(row, 1),
    ArrowUp: (row) => focusSibling(row, -1),
    ArrowRight: expandOrFocusChild,
    ArrowLeft: collapseOrFocusParent,
    Enter: (row) => selectRow(row, { ctrlKey: false, metaKey: false, shiftKey: false }),
    " ": (row) => selectRow(row, { ctrlKey: true, metaKey: false, shiftKey: false }),
  };

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: PlanningTreeRow) {
    const handler = rowKeyHandlers[event.key];
    if (!handler) {
      return;
    }
    event.preventDefault();
    handler(row);
  }

  function defaultScheduleDraft(row: PlanningTreeRow): ScheduleDraft {
    return {
      start_at: toDateTimeInputValue(row.start_at),
      finish_at: toDateTimeInputValue(row.finish_at),
      duration_minutes: row.duration_minutes === null || row.duration_minutes === undefined ? "" : String(row.duration_minutes),
    };
  }

  function scheduleDraftFor(row: PlanningTreeRow): ScheduleDraft {
    return scheduleDrafts[row.uid] ?? defaultScheduleDraft(row);
  }

  function updateScheduleDraft(row: PlanningTreeRow, field: keyof ScheduleDraft, value: string) {
    setScheduleDrafts((current) => ({
      ...current,
      [row.uid]: { ...(current[row.uid] ?? defaultScheduleDraft(row)), [field]: value },
    }));
  }

  function clearScheduleDraft(uid: number) {
    setScheduleDrafts((current) => {
      if (!(uid in current)) {
        return current;
      }
      const next = { ...current };
      delete next[uid];
      return next;
    });
  }

  async function commitScheduleEdit(row: PlanningTreeRow) {
    if (!onScheduleUpdate || mutationBusy) {
      return;
    }
    // No draft entry means the user never actually typed into one of this row's fields (e.g. just
    // tabbed through on focus/blur): nothing changed, so nothing should be committed.
    if (!(row.uid in scheduleDrafts)) {
      return;
    }
    const draft = scheduleDraftFor(row);
    let payload: PlanningTaskScheduleUpdate;
    if (row.is_milestone) {
      // A milestone only exposes its start date: duration and finish are always forced by the
      // server, so omitting them here avoids conflicting with a stale finish_at/duration.
      const startAt = fromDateTimeInputValue(draft.start_at);
      // The milestone schedule payload has no way to distinguish "field omitted" from "field
      // explicitly cleared": both _apply_manual_milestone_schedule and
      // _apply_automatic_milestone_schedule treat a null start_at as "not provided" and silently
      // fall back to the already-stored value. Sending a cleared field would therefore succeed
      // (200) but change nothing, then bounce the input back to its old value with no feedback.
      // Bail out before the request instead, the same way the automatic-duration guard below
      // does; the draft is intentionally left in place (not cleared) so the empty value stays
      // visible to correct rather than silently reverting.
      if (startAt === null) {
        return;
      }
      payload = { is_manual: Boolean(row.is_manual), start_at: startAt };
    } else if (row.is_manual) {
      // Intentional: `is_manual: null/undefined` (e.g. a task imported without an explicit mode)
      // is treated the same as `false` here, so the first edit on such a task — regardless of
      // which field the user touched — assigns it "automatique". This is a deliberate product
      // decision, not an oversight; do not "fix" it into a three-way branch.
      payload = {
        is_manual: true,
        start_at: fromDateTimeInputValue(draft.start_at),
        finish_at: fromDateTimeInputValue(draft.finish_at),
        duration_minutes: draft.duration_minutes === "" ? null : Number(draft.duration_minutes),
      };
    } else {
      // Automatic, non-milestone tasks only allow editing the duration; start/finish are always
      // recomputed by the server from the calendar and predecessors.
      const durationMinutes = draft.duration_minutes === "" ? null : Number(draft.duration_minutes);
      // _apply_automatic_schedule rejects a null/zero/negative duration with a 400. Bail out
      // before the request instead of sending one guaranteed to fail; the draft is intentionally
      // left in place (not cleared) so the user's in-progress, still-invalid value stays visible
      // to correct rather than silently reverting to the last committed value. Mirrors the same
      // guard already applied when switching a task into automatic mode (see the "Automatique"
      // SelectItem's `disabled` condition below), just covering the direct-edit path too.
      if (durationMinutes === null || durationMinutes <= 0) {
        return;
      }
      payload = { is_manual: false, duration_minutes: durationMinutes };
    }
    // Only discard the draft once the update is confirmed persisted server-side: clearing it
    // beforehand (or on failure) would make scheduleDraftFor(row) fall back to defaultScheduleDraft,
    // which reflects the stale, pre-edit `row` values -- silently reverting the user's input to a
    // value that was never actually saved, with no way to recover it. On failure the draft is left
    // in place so the user still sees what they typed and can retry or correct it.
    const succeeded = await onScheduleUpdate(row.uid, payload);
    if (succeeded) {
      clearScheduleDraft(row.uid);
    }
  }

  async function commitModeChange(row: PlanningTreeRow, isManual: boolean) {
    if (!onScheduleUpdate || mutationBusy) {
      return;
    }
    const payload: PlanningTaskScheduleUpdate = row.is_milestone
      ? { is_manual: isManual, start_at: row.start_at ?? null }
      : {
          is_manual: isManual,
          start_at: row.start_at ?? null,
          finish_at: row.finish_at ?? null,
          duration_minutes: row.duration_minutes ?? null,
        };
    // The mode change itself has no draft of its own to reconcile (unlike commitScheduleEdit):
    // the Select is driven directly by row.is_manual, so on failure it simply re-renders with the
    // same (unchanged) value once the parent's data reload reflects the rejected request -- no
    // stale-draft/lost-input risk from *this* request to guard against. However, a *previous*
    // schedule-field edit on this same row may have failed and left its draft in place
    // (deliberately, so the user's invalid/unsaved input stays visible -- see commitScheduleEdit).
    // If this mode change then succeeds, the server returns fresh start/finish/duration values,
    // but scheduleDraftFor(row) would keep serving that stale leftover draft instead. Clear it on
    // success so the fields reflect the row's new, server-confirmed values.
    const succeeded = await onScheduleUpdate(row.uid, payload);
    if (succeeded) {
      clearScheduleDraft(row.uid);
    }
  }

  function onScheduleFieldKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // Editing a field must never bubble up to the row's own navigation shortcuts (arrows, space...).
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      // Blurring alone triggers the field's onBlur handler, which already commits the edit;
      // calling commitScheduleEdit here too would fire two identical PATCH requests in the
      // same tick, since the mutationBusy guard has not re-rendered yet at that point.
      event.currentTarget.blur();
    }
  }

  function renderScheduleCells(row: PlanningTreeRow) {
    const editable = !row.is_summary && !readOnly && Boolean(onScheduleUpdate);
    const draft = scheduleDraftFor(row);
    const startEditable = editable && (row.is_milestone || row.is_manual);
    // The client cannot know whether a predecessor link actually resolves to a schedule
    // constraint server-side (`_apply_automatic_milestone_schedule` only ignores payload.start_at
    // once `_resolve_predecessor_constraints` yields at least one value, which additionally
    // requires the predecessor to itself already have a start_at/finish_at) -- only whether a
    // predecessor link exists at all. Using "has at least one predecessor link" as a proxy is a
    // documented, deliberate over-approximation: worst case a not-yet-constraining link disables
    // the field a little early, which is far preferable to accepting an edit guaranteed to be
    // silently reverted by the server.
    const startConstrainedByPredecessors =
      row.is_milestone && !row.is_manual && Boolean(row.predecessor_links?.length);
    const startHelpText = startConstrainedByPredecessors
      ? "Date déterminée par les prédécesseurs"
      : undefined;
    const finishEditable = editable && !row.is_milestone && row.is_manual;
    const durationEditable = editable && !row.is_milestone;
    return (
      <>
        <TableCell>
          {startEditable ? (
            <Input
              type="datetime-local"
              step="1"
              aria-label={startHelpText ? `Début de ${row.name} (${startHelpText})` : `Début de ${row.name}`}
              title={startHelpText}
              value={draft.start_at}
              disabled={mutationBusy || startConstrainedByPredecessors}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => updateScheduleDraft(row, "start_at", event.target.value)}
              onBlur={() => void commitScheduleEdit(row)}
              onKeyDown={onScheduleFieldKeyDown}
            />
          ) : (
            formatDate(row.start_at)
          )}
        </TableCell>
        <TableCell>
          {finishEditable ? (
            <Input
              type="datetime-local"
              step="1"
              aria-label={`Fin de ${row.name}`}
              value={draft.finish_at}
              disabled={mutationBusy}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => updateScheduleDraft(row, "finish_at", event.target.value)}
              onBlur={() => void commitScheduleEdit(row)}
              onKeyDown={onScheduleFieldKeyDown}
            />
          ) : (
            formatDate(row.finish_at)
          )}
        </TableCell>
        <TableCell>
          {durationEditable ? (
            <Input
              type="number"
              // An automatic non-milestone task requires a strictly positive duration server-side
              // (_apply_automatic_schedule rejects null/0/negative with a 400); a manual task's
              // duration is always accepted, including 0/null. `min` is a browser hint only
              // (commitScheduleEdit below is the real guard against a doomed request).
              min={row.is_manual ? 0 : 1}
              step={1}
              aria-label={`Durée de ${row.name}`}
              value={draft.duration_minutes}
              disabled={mutationBusy}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => updateScheduleDraft(row, "duration_minutes", event.target.value)}
              onBlur={() => void commitScheduleEdit(row)}
              onKeyDown={onScheduleFieldKeyDown}
            />
          ) : (
            formatDurationMinutes(row.duration_minutes)
          )}
        </TableCell>
        <TableCell>
          {editable ? (
            <Select
              value={row.is_manual ? "manual" : "auto"}
              onValueChange={(value) => void commitModeChange(row, value === "manual")}
              disabled={mutationBusy}
            >
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
                {/* A milestone's duration is always forced to 0 server-side, so it can always switch
                    to automatic. A non-milestone task with no duration, or a zero/negative one
                    (a valid state for a manual task), would be rejected by the server
                    (_apply_automatic_schedule requires a strictly positive duration), so disable
                    the option rather than let the user hit a guaranteed 400. Separately, both
                    _apply_automatic_schedule and _apply_automatic_milestone_schedule need either a
                    stored start_at or at least one predecessor link to derive a start anchor
                    (milestone or not) — without either, disable the option too. */}
                <SelectItem
                  value="auto"
                  disabled={
                    (!row.is_milestone && durationInvalidForAutomatic(row)) ||
                    missingStartAnchorForAutomatic(row, tasksByUid)
                  }
                >
                  Automatique
                </SelectItem>
              </SelectContent>
            </Select>
          ) : (
            taskModeLabel(row)
          )}
        </TableCell>
      </>
    );
  }

  const indentCommand = computeIndentCommand(tasks, selectedUids);
  const outdentCommand = computeOutdentCommand(tasks, selectedUids);
  const moveUpCommand = computeReorderCommand(tasks, selectedUids, "up");
  const moveDownCommand = computeReorderCommand(tasks, selectedUids, "down");

  function dispatchMove(command: PlanningMoveCommand | null) {
    if (command) {
      onMove?.(command);
    }
  }

  const actionsToolbar = !readOnly && onMove ? (
    <div className="mb-3 flex flex-wrap gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!indentCommand || mutationBusy}
        onClick={() => dispatchMove(indentCommand)}
      >
        Indenter
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!outdentCommand || mutationBusy}
        onClick={() => dispatchMove(outdentCommand)}
      >
        Désindenter
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!moveUpCommand || mutationBusy}
        onClick={() => dispatchMove(moveUpCommand)}
      >
        Monter
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!moveDownCommand || mutationBusy}
        onClick={() => dispatchMove(moveDownCommand)}
      >
        Descendre
      </Button>
    </div>
  ) : null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Planning</CardTitle>
      </CardHeader>
      <CardContent>
        {actionsToolbar}
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
            {rows.map((row) => {
              const collapsed = collapsedUids.has(row.uid);
              const selected = selectedUids.has(row.uid);
              const isFocusable = focusedUid === row.uid || (focusedUid === null && row.uid === rows[0]?.uid);
              return (
                <TableRow
                  key={row.uid}
                  ref={(element) => {
                    if (element) {
                      rowRefs.current.set(row.uid, element);
                    } else {
                      rowRefs.current.delete(row.uid);
                    }
                  }}
                  data-state={selected ? "selected" : undefined}
                  aria-selected={selected}
                  tabIndex={isFocusable ? 0 : -1}
                  className="cursor-pointer outline-none"
                  onClick={(event) => selectRow(row, event)}
                  onFocus={() => setFocusedUid(row.uid)}
                  onKeyDown={(event) => onRowKeyDown(event, row)}
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
                            toggleCollapsed(row.uid);
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
                  {renderScheduleCells(row)}
                  <TableCell>{predecessorsLabel(row)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {readOnlyNotice}
      </CardContent>
    </Card>
  );
}
