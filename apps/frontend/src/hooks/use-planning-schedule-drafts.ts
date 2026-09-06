import { useState, type KeyboardEvent } from "react";

import type { PlanningTaskScheduleUpdate } from "@/lib/backend";
import { formatCalendarDurationForEditing, parseCalendarDuration, type ProjectCalendar } from "@/lib/planning-calendar";
import { combineDateWithExistingTime, toDateInputValue, type ScheduleDraft } from "@/lib/planning-schedule";
import type { PlanningTreeRow } from "@/lib/planning-tree";

type SchedulePayload = Omit<PlanningTaskScheduleUpdate, "expected_revision">;

// A duration-field commit can now fail for a reason the user needs to actually see and fix (an
// unrecognized format, e.g. "3jj") in addition to the pre-existing, silent business-validation
// abort (see buildAutomaticPayload's null return) -- this discriminates the two so
// commitScheduleEdit can react differently: surface the former, stay silent for the latter.
type ScheduleCommitResult = SchedulePayload | { error: string } | null;

type UsePlanningScheduleDraftsParams = {
  onScheduleUpdate?: (taskUid: number, payload: SchedulePayload) => Promise<boolean>;
  mutationBusy: boolean;
  calendar: ProjectCalendar;
};

// A milestone only exposes its start date: duration and finish are always forced by the server,
// so omitting them here avoids conflicting with a stale finish_at/duration. Returns null when the
// draft's start date cannot be committed (see the comment at its call site in commitScheduleEdit).
function buildMilestonePayload(row: PlanningTreeRow, draft: ScheduleDraft): SchedulePayload | null {
  const startAt = combineDateWithExistingTime(draft.start_at, row.start_at);
  if (startAt === null) {
    return null;
  }
  return { is_manual: Boolean(row.is_manual), start_at: startAt };
}

// Intentional: `is_manual: null/undefined` (e.g. a task imported without an explicit mode) is
// treated the same as `false` here, so the first edit on such a task -- regardless of which field
// the user touched -- assigns it "automatique". This is a deliberate product decision, not an
// oversight; do not "fix" it into a three-way branch.
//
// duration_minutes parsing: the format is validated by parseCalendarDuration (unit
// suffixes/raw minutes, see lib/planning-calendar.ts) before any business-rule validation; an
// unrecognized format is reported back as { error } so the caller can surface it, distinct from
// the historical, silent null returned for a business-invalid value.
function buildManualPayload(row: PlanningTreeRow, draft: ScheduleDraft, calendar: ProjectCalendar): ScheduleCommitResult {
  if (draft.duration_minutes === "") {
    return {
      is_manual: true,
      start_at: combineDateWithExistingTime(draft.start_at, row.start_at),
      finish_at: combineDateWithExistingTime(draft.finish_at, row.finish_at),
      duration_minutes: null,
    };
  }
  const parsedDuration = parseCalendarDuration(draft.duration_minutes, calendar);
  if ("error" in parsedDuration) {
    return { error: parsedDuration.error };
  }
  return {
    is_manual: true,
    start_at: combineDateWithExistingTime(draft.start_at, row.start_at),
    finish_at: combineDateWithExistingTime(draft.finish_at, row.finish_at),
    duration_minutes: parsedDuration.minutes,
  };
}

// Automatic, non-milestone tasks only allow editing the duration; start/finish are always
// recomputed by the server from the calendar and predecessors. Returns null when
// _apply_automatic_schedule would reject the duration (null/zero/negative) with a 400 -- this
// business-rule check happens only *after* a successful format parse, per the same split as
// buildManualPayload above.
function buildAutomaticPayload(draft: ScheduleDraft, calendar: ProjectCalendar): ScheduleCommitResult {
  if (draft.duration_minutes === "") {
    return null;
  }
  const parsedDuration = parseCalendarDuration(draft.duration_minutes, calendar);
  if ("error" in parsedDuration) {
    return { error: parsedDuration.error };
  }
  if (parsedDuration.minutes <= 0) {
    return null;
  }
  return { is_manual: false, duration_minutes: parsedDuration.minutes };
}

// Extracted from PlanningTreeTable (E4-12 / #152): the inline schedule-field draft state (one
// local, uncommitted start/finish/duration per row) and the commit logic that turns a draft into
// a PlanningTaskScheduleUpdate payload once the user blurs/Enters a field, or switches a row's
// manual/automatic mode. Owns its own reset() called from PlanningTreeTable's render-phase
// versionKey-change block -- see that component for why this must stay a synchronous render-body
// reset, not a useEffect.
export function usePlanningScheduleDrafts({ onScheduleUpdate, mutationBusy, calendar }: UsePlanningScheduleDraftsParams) {
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<number, ScheduleDraft>>({});
  // Per-row format-parsing error message for the duration field (see ScheduleCommitResult above).
  // Kept alongside scheduleDrafts (one entry per row, same lifecycle) rather than a single shared
  // value, so an error on one row never leaks onto another's cell.
  const [durationErrors, setDurationErrors] = useState<Record<number, string>>({});

  // The default (never-yet-edited) value is shown formatted per the project's calendar (e.g. "1j"
  // rather than "480"), for symmetry with what the field now also accepts as input -- but only
  // when that formatting round-trips losslessly back to the same duration_minutes (see
  // formatCalendarDurationForEditing's own doc comment): a lossy compound value instead falls back
  // to the plain minute count, so the field never silently misrepresents a task's stored duration.
  function defaultScheduleDraft(row: PlanningTreeRow): ScheduleDraft {
    return {
      start_at: toDateInputValue(row.start_at),
      finish_at: toDateInputValue(row.finish_at),
      duration_minutes:
        row.duration_minutes === null || row.duration_minutes === undefined
          ? ""
          : formatCalendarDurationForEditing(row.duration_minutes, calendar),
    };
  }

  function scheduleDraftFor(row: PlanningTreeRow): ScheduleDraft {
    return scheduleDrafts[row.uid] ?? defaultScheduleDraft(row);
  }

  function durationErrorFor(row: PlanningTreeRow): string | null {
    return durationErrors[row.uid] ?? null;
  }

  function clearDurationError(uid: number) {
    setDurationErrors((current) => {
      if (!(uid in current)) {
        return current;
      }
      const next = { ...current };
      delete next[uid];
      return next;
    });
  }

  function updateScheduleDraft(row: PlanningTreeRow, field: keyof ScheduleDraft, value: string) {
    setScheduleDrafts((current) => ({
      ...current,
      [row.uid]: { ...(current[row.uid] ?? defaultScheduleDraft(row)), [field]: value },
    }));
    // Any further edit implicitly retracts the previous attempt's format error -- the next commit
    // will re-validate and re-report it if it's still invalid.
    if (field === "duration_minutes") {
      clearDurationError(row.uid);
    }
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
    const result: ScheduleCommitResult = row.is_milestone
      ? buildMilestonePayload(row, draft)
      : row.is_manual
        ? buildManualPayload(row, draft, calendar)
        : buildAutomaticPayload(draft, calendar);
    // Bail out before the request instead of sending one guaranteed to fail or to be a no-op (see
    // buildMilestonePayload/buildAutomaticPayload above); the draft is intentionally left in place
    // (not cleared) so the user's in-progress, still-invalid value stays visible to correct rather
    // than silently reverting to the last committed value.
    if (result === null) {
      return;
    }
    if ("error" in result) {
      // Unlike the business-validation null above, an unrecognized *format* is actionable by the
      // user -- surface it via durationErrorFor so the cell can render it next to the field.
      setDurationErrors((current) => ({ ...current, [row.uid]: result.error }));
      return;
    }
    clearDurationError(row.uid);
    // Only discard the draft once the update is confirmed persisted server-side: clearing it
    // beforehand (or on failure) would make scheduleDraftFor(row) fall back to defaultScheduleDraft,
    // which reflects the stale, pre-edit `row` values -- silently reverting the user's input to a
    // value that was never actually saved, with no way to recover it. On failure the draft is left
    // in place so the user still sees what they typed and can retry or correct it.
    const succeeded = await onScheduleUpdate(row.uid, result);
    if (succeeded) {
      clearScheduleDraft(row.uid);
    }
  }

  async function commitModeChange(row: PlanningTreeRow, isManual: boolean) {
    if (!onScheduleUpdate || mutationBusy) {
      return;
    }
    const payload: SchedulePayload = row.is_milestone
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

  function reset() {
    setScheduleDrafts({});
    setDurationErrors({});
  }

  return {
    scheduleDraftFor,
    durationErrorFor,
    updateScheduleDraft,
    commitScheduleEdit,
    commitModeChange,
    onScheduleFieldKeyDown,
    reset,
  };
}
