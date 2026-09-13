import { useState } from "react";

import { useTreeRowDrafts } from "@/hooks/use-tree-row-drafts";
import type { RevisionPlanFacetUpdateInput } from "@/lib/backend";
import { formatCalendarDurationForEditing, parseCalendarDuration, type ProjectCalendar } from "@/lib/planning-calendar";
import { combineDateWithExistingTime, toDateInputValue, type ScheduleDraft } from "@/lib/planning-schedule";
import type { PlanningRow } from "@/lib/planning-tree";

/** What a commit sends: the planning facet's schedule fields, without the lock counter the caller adds. */
export type SchedulePayload = Omit<RevisionPlanFacetUpdateInput, "expected_lock_version">;

// A duration-field commit can fail for a reason the user needs to actually see and fix (an
// unrecognized format, e.g. "3jj") in addition to the silent business-validation abort (see
// buildAutomaticPayload's null return) -- this discriminates the two so commitScheduleEdit can
// react differently: surface the former, stay silent for the latter.
type ScheduleCommitResult = SchedulePayload | { error: string } | null;

type UsePlanningScheduleDraftsParams = {
  onScheduleUpdate?: (nodeId: number, payload: SchedulePayload) => Promise<boolean>;
  mutationBusy: boolean;
  calendar: ProjectCalendar;
};

// A milestone only exposes its start date: duration and finish are always forced by the server,
// so omitting them here avoids conflicting with a stale finish_at/duration. Returns null when the
// draft's start date cannot be committed (see the comment at its call site in commitScheduleEdit).
function buildMilestonePayload(row: PlanningRow, draft: ScheduleDraft): SchedulePayload | null {
  const startAt = combineDateWithExistingTime(draft.start_at, row.planning.start_at);
  if (startAt === null) {
    return null;
  }
  return { is_manual: row.planning.is_manual, start_at: startAt };
}

// duration_minutes parsing: the format is validated by parseCalendarDuration (unit suffixes/raw
// minutes, see lib/planning-calendar.ts) before any business-rule validation; an unrecognized
// format is reported back as { error } so the caller can surface it, distinct from the historical,
// silent null returned for a business-invalid value.
function buildManualPayload(row: PlanningRow, draft: ScheduleDraft, calendar: ProjectCalendar): ScheduleCommitResult {
  if (draft.duration_minutes === "") {
    return {
      is_manual: true,
      start_at: combineDateWithExistingTime(draft.start_at, row.planning.start_at),
      finish_at: combineDateWithExistingTime(draft.finish_at, row.planning.finish_at),
      duration_minutes: null,
    };
  }
  const parsedDuration = parseCalendarDuration(draft.duration_minutes, calendar);
  if ("error" in parsedDuration) {
    return { error: parsedDuration.error };
  }
  return {
    is_manual: true,
    start_at: combineDateWithExistingTime(draft.start_at, row.planning.start_at),
    finish_at: combineDateWithExistingTime(draft.finish_at, row.planning.finish_at),
    duration_minutes: parsedDuration.minutes,
  };
}

// Automatic, non-milestone tasks only allow editing the duration; start/finish are always
// recomputed by the server from the calendar and predecessors. Returns null when the automatic
// scheduler would reject the duration (null/zero/negative) with a 400 -- this business-rule check
// happens only *after* a successful format parse, per the same split as buildManualPayload above.
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
// a planning-facet update once the user blurs/Enters a field, or switches a row's manual/automatic
// mode. Owns its own reset() called from PlanningTreeTable's render-phase revision-change block --
// see that component for why this must stay a synchronous render-body reset, not a useEffect.
//
// E14-09 (#335): the draft bookkeeping itself comes from the shared useTreeRowDrafts. E14-10
// (#336): what a row carries is now a **planning facet** hung on a revision node, keyed by
// node_id, and what a commit sends is a PATCH on that facet. The milestone/manual/automatic rules
// below did not change.
export function usePlanningScheduleDrafts({ onScheduleUpdate, mutationBusy, calendar }: UsePlanningScheduleDraftsParams) {
  // Per-row format-parsing error message for the duration field (see ScheduleCommitResult above).
  // Kept alongside the row drafts (one entry per row, same lifecycle) rather than a single shared
  // value, so an error on one row never leaks onto another's cell.
  const [durationErrors, setDurationErrors] = useState<Record<number, string>>({});

  // The default (never-yet-edited) value is shown formatted per the project's calendar (e.g. "1j"
  // rather than "480"), for symmetry with what the field also accepts as input -- but only when
  // that formatting round-trips losslessly back to the same duration_minutes (see
  // formatCalendarDurationForEditing's own doc comment): a lossy compound value instead falls back
  // to the plain minute count, so the field never silently misrepresents a task's stored duration.
  function defaultScheduleDraft(row: PlanningRow): ScheduleDraft {
    return {
      start_at: toDateInputValue(row.planning.start_at),
      finish_at: toDateInputValue(row.planning.finish_at),
      duration_minutes:
        row.planning.duration_minutes === null
          ? ""
          : formatCalendarDurationForEditing(row.planning.duration_minutes, calendar),
    };
  }

  const drafts = useTreeRowDrafts<PlanningRow, ScheduleDraft>({
    rowKeyOf: (row) => row.node_id,
    defaultDraftFor: defaultScheduleDraft,
    busy: mutationBusy,
  });

  function scheduleDraftFor(row: PlanningRow): ScheduleDraft {
    return drafts.draftFor(row);
  }

  function durationErrorFor(row: PlanningRow): string | null {
    return durationErrors[row.node_id] ?? null;
  }

  function clearDurationError(nodeId: number) {
    setDurationErrors((current) => {
      if (!(nodeId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[nodeId];
      return next;
    });
  }

  function updateScheduleDraft(row: PlanningRow, field: keyof ScheduleDraft, value: string) {
    drafts.updateDraftField(row, field, value);
    // Any further edit implicitly retracts the previous attempt's format error -- the next commit
    // will re-validate and re-report it if it's still invalid.
    if (field === "duration_minutes") {
      clearDurationError(row.node_id);
    }
  }

  function clearScheduleDraft(row: PlanningRow) {
    drafts.clearDraft(row);
    // A stale format-parsing error from a previous failed attempt on this row must not survive
    // once the draft itself is discarded (e.g. after a successful commitModeChange): otherwise the
    // now-reset, valid field would still display the old error message next to it.
    clearDurationError(row.node_id);
  }

  async function commitScheduleEdit(row: PlanningRow) {
    if (!onScheduleUpdate) {
      return;
    }
    // commitDraft owns the "mutation already in flight" and "this row holds no draft at all"
    // guards, and discards the draft only when the callback below reports success -- returning
    // false keeps the user's in-progress value visible instead of silently reverting it.
    await drafts.commitDraft(row, async (draft) => {
      const result: ScheduleCommitResult = row.planning.is_milestone
        ? buildMilestonePayload(row, draft)
        : row.planning.is_manual
          ? buildManualPayload(row, draft, calendar)
          : buildAutomaticPayload(draft, calendar);
      // Bail out before the request instead of sending one guaranteed to fail or to be a no-op
      // (see buildMilestonePayload/buildAutomaticPayload above).
      if (result === null) {
        return false;
      }
      if ("error" in result) {
        // Unlike the business-validation null above, an unrecognized *format* is actionable by the
        // user -- surface it via durationErrorFor so the cell can render it next to the field.
        setDurationErrors((current) => ({ ...current, [row.node_id]: result.error }));
        return false;
      }
      clearDurationError(row.node_id);
      return onScheduleUpdate(row.node_id, result);
    });
  }

  async function commitModeChange(row: PlanningRow, isManual: boolean) {
    if (!onScheduleUpdate || mutationBusy) {
      return;
    }
    const payload: SchedulePayload = row.planning.is_milestone
      ? { is_manual: isManual, start_at: row.planning.start_at }
      : {
          is_manual: isManual,
          start_at: row.planning.start_at,
          finish_at: row.planning.finish_at,
          duration_minutes: row.planning.duration_minutes,
        };
    // The mode change itself has no draft of its own to reconcile (unlike commitScheduleEdit): the
    // Select is driven directly by the facet. However a *previous* schedule-field edit on this row
    // may have failed and left its draft in place (deliberately, so the user's unsaved input stays
    // visible). If this mode change then succeeds, the server returns fresh start/finish/duration
    // values, but scheduleDraftFor(row) would keep serving that stale leftover draft instead.
    const succeeded = await onScheduleUpdate(row.node_id, payload);
    if (succeeded) {
      clearScheduleDraft(row);
    }
  }

  function reset() {
    drafts.reset();
    setDurationErrors({});
  }

  return {
    scheduleDraftFor,
    durationErrorFor,
    updateScheduleDraft,
    commitScheduleEdit,
    commitModeChange,
    // Editing a field must never bubble up to the row's own navigation shortcuts (arrows, space...),
    // and Enter must blur rather than commit a second time -- both come from the shared hook.
    onScheduleFieldKeyDown: drafts.onFieldKeyDown,
    reset,
  };
}
