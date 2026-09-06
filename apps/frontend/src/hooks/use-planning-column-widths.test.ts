import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_PLANNING_COLUMN_WIDTHS,
  PLANNING_COLUMN_WIDTHS_STORAGE_KEY,
  PLANNING_MAX_COLUMN_WIDTH,
  PLANNING_MIN_COLUMN_WIDTHS,
  usePlanningColumnWidths,
} from "@/hooks/use-planning-column-widths";

// `buttons` defaults to 1 (primary button held), matching every native "mousemove" fired mid-drag
// by a real browser: handleMouseMove now reads `event.buttons` to detect a mouseup that happened
// outside the window (see the dedicated describe block below), so tests simulating an ongoing drag
// must set it, or every such mousemove would look like the button was already released.
function fireMouseEvent(type: "mousemove" | "mouseup", clientX: number, buttons = 1) {
  const event = new MouseEvent(type, { clientX, bubbles: true, buttons });
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
        button: 0,
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

  it("ignores a non-primary mouse button and does not start a drag", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());
    const startWidth = result.current.widths.predecessors;
    const preventDefault = () => {
      throw new Error("preventDefault should not be called for a non-primary button");
    };

    act(() => {
      // button: 2 is the right button, button: 1 is the middle button -- neither should start a
      // resize drag or suppress the browser's native handling (context menu, autoscroll, ...).
      result.current.startResize("predecessors", { clientX: 100, button: 2, preventDefault } as never);
    });
    act(() => {
      fireMouseEvent("mousemove", 220);
    });
    act(() => {
      fireMouseEvent("mouseup", 220);
    });

    expect(result.current.widths.predecessors).toBe(startWidth);
  });

  it("clamps the resized width to the column's configured minimum", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    act(() => {
      result.current.startResize("uid", {
        clientX: 100,
        button: 0,
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
        button: 0,
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

  describe("mouseup outside the window", () => {
    // A drag only ever completes via this window's own "mouseup" listener. If the user releases
    // the primary button while the pointer is outside the browser window/tab (or even outside the
    // page content, over a devtools panel, etc.), that "mouseup" never reaches us: without checking
    // `event.buttons`, dragStateRef and the "mousemove" listener would stay alive, and moving the
    // pointer back over the page would resume resizing with no button held anymore.
    it("stops resizing as soon as a mousemove reports the primary button is no longer pressed", () => {
      const { result } = renderHook(() => usePlanningColumnWidths());
      const startWidth = result.current.widths.predecessors;

      act(() => {
        result.current.startResize("predecessors", {
          clientX: 100,
          button: 0,
          preventDefault: () => {},
        } as never);
      });
      // The button is released off-window; the browser never delivers a "mouseup" here, but the
      // next "mousemove" the page does receive (e.g. once the pointer re-enters it) reports
      // buttons: 0.
      act(() => {
        fireMouseEvent("mousemove", 130, 0);
      });

      // The drag ended exactly where it was frozen (delta of 30 from the missed-mouseup move is
      // never applied), not wherever the pointer happened to be when the button was actually
      // released.
      expect(result.current.widths.predecessors).toBe(startWidth);

      // A later, unrelated mousemove with the button reported held again must not resume the
      // now-finished drag.
      act(() => {
        fireMouseEvent("mousemove", 400, 1);
      });
      expect(result.current.widths.predecessors).toBe(startWidth);

      // The frozen width was also persisted, exactly like a normal in-window mouseup would.
      const persisted = JSON.parse(window.localStorage.getItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY) ?? "{}");
      expect(persisted.predecessors).toBe(startWidth);
    });
  });

  describe("drag re-render coalescing", () => {
    // Every raw "mousemove" used to call store.setSnapshot directly, re-rendering the whole
    // PlanningTreeTable (every visible row) once per browser mousemove event -- easily far more
    // than 60 times a second on some systems. handleMouseMove now only buffers the computed width
    // and schedules a single requestAnimationFrame per frame to apply it, so a burst of moves within
    // the same frame must not schedule more than one.
    it("schedules a single animation frame for a burst of mousemove events in the same tick", () => {
      const rafSpy = vi.spyOn(window, "requestAnimationFrame");
      const { result } = renderHook(() => usePlanningColumnWidths());

      act(() => {
        result.current.startResize("predecessors", {
          clientX: 100,
          button: 0,
          preventDefault: () => {},
        } as never);
      });
      act(() => {
        fireMouseEvent("mousemove", 120);
        fireMouseEvent("mousemove", 140);
        fireMouseEvent("mousemove", 160);
      });

      expect(rafSpy).toHaveBeenCalledTimes(1);

      rafSpy.mockRestore();
    });

    it("still resolves to the exact cursor position at mouseup, not a stale coalesced value", () => {
      const { result } = renderHook(() => usePlanningColumnWidths());
      const startWidth = result.current.widths.predecessors;

      act(() => {
        result.current.startResize("predecessors", {
          clientX: 100,
          button: 0,
          preventDefault: () => {},
        } as never);
      });
      // A burst of moves, none of which have necessarily been flushed to the store yet (the
      // scheduled animation frame may not have run within this same synchronous tick).
      act(() => {
        fireMouseEvent("mousemove", 120);
        fireMouseEvent("mousemove", 140);
        fireMouseEvent("mousemove", 160);
      });
      act(() => {
        fireMouseEvent("mouseup", 160);
      });

      // stopResize flushes whatever the last pending mousemove computed before persisting, so the
      // final width matches the pointer's last reported position exactly, even though the
      // per-mousemove store updates were coalesced away.
      expect(result.current.widths.predecessors).toBe(startWidth + 60);
      const persisted = JSON.parse(window.localStorage.getItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY) ?? "{}");
      expect(persisted.predecessors).toBe(startWidth + 60);
    });

    it("cancels a still-pending animation frame on unmount", () => {
      const cancelSpy = vi.spyOn(window, "cancelAnimationFrame");
      const { result, unmount } = renderHook(() => usePlanningColumnWidths());

      act(() => {
        result.current.startResize("predecessors", {
          clientX: 100,
          button: 0,
          preventDefault: () => {},
        } as never);
      });
      act(() => {
        fireMouseEvent("mousemove", 160);
      });

      unmount();

      expect(cancelSpy).toHaveBeenCalled();

      cancelSpy.mockRestore();
    });
  });
});
