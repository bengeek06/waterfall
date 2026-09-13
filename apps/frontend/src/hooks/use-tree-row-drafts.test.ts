import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useTreeRowDrafts } from "@/hooks/use-tree-row-drafts";

// Neither a planning schedule draft nor a devis grid draft: the blur-commit motif is tested here
// on its own, independently of any concrete table or payload shape.
type FakeRow = { id: number; label: string };
type FakeDraft = { label: string };

const row: FakeRow = { id: 1, label: "Terrassement" };
const otherRow: FakeRow = { id: 2, label: "Gros oeuvre" };

function renderDrafts(busy = false) {
  return renderHook(() =>
    useTreeRowDrafts<FakeRow, FakeDraft>({
      rowKeyOf: (candidate) => candidate.id,
      defaultDraftFor: (candidate) => ({ label: candidate.label }),
      busy,
    }),
  );
}

describe("useTreeRowDrafts draft state", () => {
  it("falls back to the row's own value until the user types something", () => {
    const { result } = renderDrafts();

    expect(result.current.draftFor(row)).toEqual({ label: "Terrassement" });
    expect(result.current.hasPendingDraft(row)).toBe(false);
  });

  it("keeps one independent draft per row", () => {
    const { result } = renderDrafts();

    act(() => result.current.updateDraftField(row, "label", "Terrassement lot 2"));

    expect(result.current.draftFor(row)).toEqual({ label: "Terrassement lot 2" });
    expect(result.current.draftFor(otherRow)).toEqual({ label: "Gros oeuvre" });
    expect(result.current.hasPendingDraft(otherRow)).toBe(false);
  });

  it("discards a draft on demand and on reset", () => {
    const { result } = renderDrafts();

    act(() => result.current.updateDraftField(row, "label", "Modifié"));
    act(() => result.current.clearDraft(row));
    expect(result.current.hasPendingDraft(row)).toBe(false);

    act(() => result.current.updateDraftField(row, "label", "Encore modifié"));
    act(() => result.current.reset());
    expect(result.current.hasPendingDraft(row)).toBe(false);
    expect(result.current.draftFor(row)).toEqual({ label: "Terrassement" });
  });
});

describe("useTreeRowDrafts commit on blur", () => {
  it("does nothing at all when the user never typed into the row", async () => {
    const persist = vi.fn().mockResolvedValue(true);
    const { result } = renderDrafts();

    await act(async () => result.current.commitDraft(row, persist));

    expect(persist).not.toHaveBeenCalled();
  });

  it("commits the row's current draft and discards it once persisted", async () => {
    const persist = vi.fn().mockResolvedValue(true);
    const { result } = renderDrafts();

    act(() => result.current.updateDraftField(row, "label", "Terrassement lot 2"));
    await act(async () => result.current.commitDraft(row, persist));

    expect(persist).toHaveBeenCalledWith({ label: "Terrassement lot 2" });
    expect(result.current.hasPendingDraft(row)).toBe(false);
  });

  it("keeps what the user typed when the commit is refused, instead of reverting silently", async () => {
    const persist = vi.fn().mockResolvedValue(false);
    const { result } = renderDrafts();

    act(() => result.current.updateDraftField(row, "label", "Valeur refusée"));
    await act(async () => result.current.commitDraft(row, persist));

    expect(persist).toHaveBeenCalledTimes(1);
    expect(result.current.hasPendingDraft(row)).toBe(true);
    expect(result.current.draftFor(row)).toEqual({ label: "Valeur refusée" });
  });

  it("never commits while a mutation is already in flight", async () => {
    const persist = vi.fn().mockResolvedValue(true);
    const { result } = renderDrafts(true);

    act(() => result.current.updateDraftField(row, "label", "Terrassement lot 2"));
    await act(async () => result.current.commitDraft(row, persist));

    expect(persist).not.toHaveBeenCalled();
    expect(result.current.hasPendingDraft(row)).toBe(true);
  });

  it("accepts a synchronous persist callback", async () => {
    const { result } = renderDrafts();

    act(() => result.current.updateDraftField(row, "label", "Terrassement lot 2"));
    await act(async () => result.current.commitDraft(row, () => true));

    expect(result.current.hasPendingDraft(row)).toBe(false);
  });
});

describe("useTreeRowDrafts onFieldKeyDown", () => {
  function keyEvent(key: string) {
    const blur = vi.fn();
    const event = {
      key,
      stopPropagation: vi.fn(),
      preventDefault: vi.fn(),
      currentTarget: { blur },
    };
    return { event, blur };
  }

  it("blurs the field on Enter, so the field's own onBlur is what commits", () => {
    const { result } = renderDrafts();
    const { event, blur } = keyEvent("Enter");

    act(() => result.current.onFieldKeyDown(event as never));

    expect(blur).toHaveBeenCalledTimes(1);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
  });

  it("never lets a keystroke inside a field reach the row's navigation shortcuts", () => {
    const { result } = renderDrafts();
    const { event, blur } = keyEvent("ArrowDown");

    act(() => result.current.onFieldKeyDown(event as never));

    expect(event.stopPropagation).toHaveBeenCalledTimes(1);
    expect(blur).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});
