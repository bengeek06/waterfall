import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_PLANNING_COLUMN_WIDTHS,
  PLANNING_COLUMN_WIDTHS_STORAGE_KEY,
  PLANNING_MAX_COLUMN_WIDTH,
  PLANNING_MIN_COLUMN_WIDTHS,
  usePlanningColumnWidths,
} from "@/hooks/use-planning-column-widths";

function fireMouseEvent(type: "mousemove" | "mouseup", clientX: number) {
  const event = new MouseEvent(type, { clientX, bubbles: true });
  window.dispatchEvent(event);
}

describe("usePlanningColumnWidths", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns the default widths when localStorage is empty", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    expect(result.current.widths).toEqual(DEFAULT_PLANNING_COLUMN_WIDTHS);
  });

  it("loads persisted widths from localStorage when present and valid", () => {
    // Backed by useSyncExternalStore rather than a synchronous useState initializer: React only
    // calls getServerSnapshot (always DEFAULT_PLANNING_COLUMN_WIDTHS) while hydrating server-
    // rendered markup, and getSnapshot (this localStorage-backed read) on every plain client
    // render, including the very first one in this jsdom-only test -- so this still resolves in a
    // single render here, while a real SSR/hydration pass would render defaults first and only
    // pick up this value in the following client-only render.
    const stored = { ...DEFAULT_PLANNING_COLUMN_WIDTHS, predecessors: 320 };
    window.localStorage.setItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(stored));

    const { result } = renderHook(() => usePlanningColumnWidths());

    expect(result.current.widths.predecessors).toBe(320);
  });

  it("falls back to defaults when localStorage contains invalid JSON", () => {
    window.localStorage.setItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY, "{not-json");

    const { result } = renderHook(() => usePlanningColumnWidths());

    expect(result.current.widths).toEqual(DEFAULT_PLANNING_COLUMN_WIDTHS);
  });

  it("clamps a persisted width below its column's minimum instead of discarding it", () => {
    const stored = { ...DEFAULT_PLANNING_COLUMN_WIDTHS, uid: 1 };
    window.localStorage.setItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(stored));

    const { result } = renderHook(() => usePlanningColumnWidths());

    expect(result.current.widths.uid).toBe(PLANNING_MIN_COLUMN_WIDTHS.uid);
  });

  it("clamps a persisted width above the shared maximum", () => {
    const stored = { ...DEFAULT_PLANNING_COLUMN_WIDTHS, predecessors: 10_000 };
    window.localStorage.setItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(stored));

    const { result } = renderHook(() => usePlanningColumnWidths());

    expect(result.current.widths.predecessors).toBe(PLANNING_MAX_COLUMN_WIDTH);
  });

  it("updates and persists a column's width when dragging its resize handle", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());
    const startWidth = result.current.widths.predecessors;

    act(() => {
      result.current.startResize("predecessors", {
        clientX: 100,
        preventDefault: () => {},
      } as never);
    });
    act(() => {
      fireMouseEvent("mousemove", 160);
    });
    act(() => {
      fireMouseEvent("mouseup", 160);
    });

    expect(result.current.widths.predecessors).toBe(startWidth + 60);

    const persisted = JSON.parse(window.localStorage.getItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY) ?? "{}");
    expect(persisted.predecessors).toBe(startWidth + 60);
  });

  it("clamps the resized width to the column's configured minimum", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    act(() => {
      result.current.startResize("uid", {
        clientX: 100,
        preventDefault: () => {},
      } as never);
    });
    act(() => {
      fireMouseEvent("mousemove", -1000);
    });
    act(() => {
      fireMouseEvent("mouseup", -1000);
    });

    expect(result.current.widths.uid).toBe(PLANNING_MIN_COLUMN_WIDTHS.uid);
  });

  it("clamps the resized width to the shared maximum", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    act(() => {
      result.current.startResize("predecessors", {
        clientX: 100,
        preventDefault: () => {},
      } as never);
    });
    act(() => {
      fireMouseEvent("mousemove", 100_000);
    });
    act(() => {
      fireMouseEvent("mouseup", 100_000);
    });

    expect(result.current.widths.predecessors).toBe(PLANNING_MAX_COLUMN_WIDTH);
  });

  it("adjusts and persists a column's width by a fixed delta via resizeBy", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());
    const startWidth = result.current.widths.name;

    act(() => {
      result.current.resizeBy("name", 10);
    });

    expect(result.current.widths.name).toBe(startWidth + 10);
    const persisted = JSON.parse(window.localStorage.getItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY) ?? "{}");
    expect(persisted.name).toBe(startWidth + 10);
  });

  it("clamps resizeBy to the column's configured minimum instead of going negative", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    act(() => {
      result.current.resizeBy("uid", -1000);
    });

    expect(result.current.widths.uid).toBe(PLANNING_MIN_COLUMN_WIDTHS.uid);
  });

  it("clamps resizeBy to the shared maximum", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    act(() => {
      result.current.resizeBy("predecessors", 10_000);
    });

    expect(result.current.widths.predecessors).toBe(PLANNING_MAX_COLUMN_WIDTH);
  });

  it("gives columns with non-truncatable content (dates, type, the mode selector) a higher minimum than uid/name/predecessors", () => {
    // Regression guard for the shared 60px minimum previously letting e.g. the mode column's w-fit
    // Select trigger paint over the next column when shrunk all the way down.
    expect(PLANNING_MIN_COLUMN_WIDTHS.start).toBeGreaterThan(PLANNING_MIN_COLUMN_WIDTHS.uid);
    expect(PLANNING_MIN_COLUMN_WIDTHS.end).toBeGreaterThan(PLANNING_MIN_COLUMN_WIDTHS.uid);
    expect(PLANNING_MIN_COLUMN_WIDTHS.type).toBeGreaterThan(PLANNING_MIN_COLUMN_WIDTHS.uid);
    expect(PLANNING_MIN_COLUMN_WIDTHS.mode).toBeGreaterThan(PLANNING_MIN_COLUMN_WIDTHS.uid);
  });

  it("keeps every default width within its column's [minimum, maximum] range", () => {
    for (const [key, width] of Object.entries(DEFAULT_PLANNING_COLUMN_WIDTHS)) {
      const min = PLANNING_MIN_COLUMN_WIDTHS[key as keyof typeof PLANNING_MIN_COLUMN_WIDTHS];
      expect(width).toBeGreaterThanOrEqual(min);
      expect(width).toBeLessThanOrEqual(PLANNING_MAX_COLUMN_WIDTH);
    }
  });
});
