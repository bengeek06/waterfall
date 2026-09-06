import type { Task } from "./backend";

// Pure, presentation-agnostic schedule formatting/parsing helpers extracted from
// planning-tree-table.tsx (E4-12 / #152): shared by the tree table's own row rendering, the
// use-planning-schedule-drafts hook and the planning-schedule-cells component, none of which
// should duplicate this logic or the naive-UTC/date-only conventions documented below.

export type ScheduleDraft = {
  start_at: string;
  finish_at: string;
  duration_minutes: string;
};

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  // Read-only counterpart of toDateInputValue's UTC convention (see below): parse the
  // naive-UTC backend value as UTC, then format in UTC too, so this display never disagrees
  // with the editable fields or shifts across a midnight boundary for a non-UTC viewer.
  return new Date(asUtcIsoString(value)).toLocaleDateString("fr-FR", { timeZone: "UTC" });
}

// The backend stores/returns naive-UTC datetimes (no offset, e.g. "2026-01-09T08:00:00"). A
// string with no trailing "Z"/numeric offset is otherwise interpreted by `new Date(...)` as
// *local* time (standard JS behaviour), which silently shifts every value by the browser's UTC
// offset for any non-UTC user. Force it to be read as UTC by appending "Z" when no offset is
// already present.
export function asUtcIsoString(value: string): string {
  return /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
}

// Timezone convention (deliberate, keep toDateInputValue/combineDateWithExistingTime symmetric):
// this field always displays and edits the value's *UTC* date component, not the browser's local
// time. A native `date` input has no timezone concept of its own, so "local time" here would
// actually mean "the browser's local time", which has no clean, lossless round-trip back to the
// naive-UTC value the backend expects without extra local<->UTC conversion. Treating the
// component's yyyy-MM-dd as a UTC calendar date end-to-end is simpler and fully reversible in
// every browser timezone; it trades away a "shows my local date" UX nicety in favour of never
// corrupting dates.
export function toDateInputValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(asUtcIsoString(value));
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

const DATE_INPUT_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

// The date input only ever exposes the calendar date, not the time of day: a manual task's
// start_at/finish_at can carry a non-zero, non-minute-aligned time component derived from a
// predecessor link's lag_tenth_minute (stored at a 6-second resolution), and commitScheduleEdit
// always resends all three schedule fields on any single field edit (e.g. editing only the
// duration). Discarding that time component here instead of preserving it would silently reset an
// untouched start_at/finish_at to midnight on every commit, so the new date is combined with the
// time-of-day already stored on `existingValue` (the row's current, pre-edit value) rather than
// zeroing it out. A task that never had a time component (fresh manual entry) simply defaults to
// midnight UTC.
export function combineDateWithExistingTime(
  dateOnly: string,
  existingValue: string | null | undefined,
): string | null {
  if (!dateOnly) {
    return null;
  }
  const match = DATE_INPUT_PATTERN.exec(dateOnly);
  if (!match) {
    return null;
  }
  const [year, month, day] = match.slice(1).map(Number);
  let hour = 0;
  let minute = 0;
  let second = 0;
  if (existingValue) {
    const existing = new Date(asUtcIsoString(existingValue));
    if (!Number.isNaN(existing.getTime())) {
      hour = existing.getUTCHours();
      minute = existing.getUTCMinutes();
      second = existing.getUTCSeconds();
    }
  }
  // Symmetric with toDateInputValue: the field's yyyy-MM-dd components are a UTC calendar date, so
  // they must be combined with the preserved time-of-day via Date.UTC directly, not through
  // `new Date(...)`, which would reinterpret them as local time and reintroduce the same
  // corruption this convention exists to avoid.
  const date = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

export function taskModeLabel(task: Task): string {
  if (task.is_manual === null || task.is_manual === undefined) {
    return "-";
  }
  return task.is_manual ? "Manuel" : "Automatique";
}

// Shared with the direct duration-edit guard in commitScheduleEdit: _apply_automatic_schedule
// rejects a null/zero/negative duration with a 400, so both the "switch to automatic" affordance
// and the direct edit must treat 0/negative the same as missing.
export function durationInvalidForAutomatic(task: Task): boolean {
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
// sufficient -- see LINK_TYPE_LABELS (lib/planning-links.ts) for the code mapping.
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
export function missingStartAnchorForAutomatic(task: Task, tasksByUid: Map<number, Task>): boolean {
  if (task.start_at) {
    return false;
  }
  return !task.predecessor_links?.some((link) => predecessorResolvesStartAnchor(link, tasksByUid));
}
