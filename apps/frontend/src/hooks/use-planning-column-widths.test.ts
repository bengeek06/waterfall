import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_PLANNING_COLUMN_WIDTHS,
  PLANNING_COLUMN_WIDTHS_STORAGE_KEY,
  PLANNING_MIN_COLUMN_WIDTH,
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

  it("clamps the resized width to the configured minimum", () => {
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

    expect(result.current.widths.uid).toBe(PLANNING_MIN_COLUMN_WIDTH);
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

  it("clamps resizeBy to the configured minimum instead of going negative", () => {
    const { result } = renderHook(() => usePlanningColumnWidths());

    act(() => {
      result.current.resizeBy("uid", -1000);
    });

    expect(result.current.widths.uid).toBe(PLANNING_MIN_COLUMN_WIDTH);
  });
});
