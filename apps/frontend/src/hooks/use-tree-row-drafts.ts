import { useState, type KeyboardEvent } from "react";

// E14-09 (#335) / resolves #316: the "local draft per row, committed on blur, turned into an API
// call" motif both the planning table (use-planning-schedule-drafts.ts) and the devis grid
// (use-estimate-grid-drafts.ts) used to implement separately.
//
// What is shared is the *bookkeeping*, not the payload: which rows currently hold an uncommitted
// value, what a never-edited row falls back to, when a draft may be discarded, and the Enter =
// blur = commit convention. Building the actual request body -- and deciding what makes it
// invalid -- stays in the per-table hook, which passes it as the `persist` callback below.

export type TreeRowDraftsOptions<TRow, TDraft> = {
  /** Stable per-row draft key. It must not depend on the draft's own content. */
  rowKeyOf: (row: TRow) => string | number;
  /** Value shown for a row the user has never typed into, derived from the row's stored data. */
  defaultDraftFor: (row: TRow) => TDraft;
  /** While true, a mutation is already in flight and every commit is a no-op. */
  busy?: boolean;
};

export function useTreeRowDrafts<TRow, TDraft extends object>({
  rowKeyOf,
  defaultDraftFor,
  busy = false,
}: TreeRowDraftsOptions<TRow, TDraft>) {
  const [drafts, setDrafts] = useState<Record<string, TDraft>>({});

  function keyOf(row: TRow): string {
    return String(rowKeyOf(row));
  }

  function draftFor(row: TRow): TDraft {
    return drafts[keyOf(row)] ?? defaultDraftFor(row);
  }

  function updateDraftField<TField extends keyof TDraft>(row: TRow, field: TField, value: TDraft[TField]) {
    const key = keyOf(row);
    setDrafts((current) => ({ ...current, [key]: { ...(current[key] ?? defaultDraftFor(row)), [field]: value } }));
  }

  function clearDraft(row: TRow) {
    const key = keyOf(row);
    setDrafts((current) => {
      if (!(key in current)) {
        return current;
      }
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  /**
   * No draft entry means the user never actually typed into this row's fields (e.g. just tabbed
   * through on focus/blur): nothing changed, so nothing should be committed.
   */
  function hasPendingDraft(row: TRow): boolean {
    return keyOf(row) in drafts;
  }

  /**
   * Runs `persist` for a row that actually holds a draft, and discards that draft only once
   * `persist` reports success.
   *
   * Keeping the draft on failure is deliberate and load-bearing: discarding it would make
   * `draftFor(row)` fall back to `defaultDraftFor(row)`, i.e. the stale pre-edit values, silently
   * replacing what the user typed with something that was never saved. `persist` returns `false`
   * both for "the request failed" and for "this draft is not worth/able to be sent" -- it is the
   * per-table hook's job to tell those apart and to surface a message if there is one.
   */
  async function commitDraft(row: TRow, persist: (draft: TDraft) => Promise<boolean> | boolean) {
    if (busy || !hasPendingDraft(row)) {
      return;
    }
    if (await persist(draftFor(row))) {
      clearDraft(row);
    }
  }

  /**
   * Enter validates and blurs the field, which triggers the very same commit a plain blur does --
   * committing here as well would fire two identical requests in the same tick, since the `busy`
   * guard has not re-rendered yet at that point. Also stops the keystroke from bubbling up to the
   * row's own selection/navigation shortcuts.
   */
  function onFieldKeyDown(event: KeyboardEvent<HTMLElement>) {
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
    }
  }

  function reset() {
    setDrafts({});
  }

  return { draftFor, updateDraftField, clearDraft, hasPendingDraft, commitDraft, onFieldKeyDown, reset };
}
