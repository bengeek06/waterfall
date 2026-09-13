import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useTreeColumnWidths, type TreeColumnWidthsConfig } from "@/hooks/use-tree-column-widths";

// A column set that is neither the planning table's nor the devis grid's: the point here is that
// the resizing mechanism is genuinely table-agnostic. The planning preset's own, far more detailed
// drag/persistence suite lives in use-planning-column-widths.test.ts and exercises the very same
// hook through usePlanningColumnWidths.
type FakeColumn = "label" | "amount";

const config: TreeColumnWidthsConfig<FakeColumn> = {
  storageKey: "waterfall:test:tree-column-widths",
  order: ["label", "amount"],
  defaults: { label: 200, amount: 100 },
  minWidths: { label: 120, amount: 60 },
  maxWidth: 400,
};

describe("useTreeColumnWidths", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it("returns the caller's own defaults when nothing is persisted", () => {
    const { result } = renderHook(() => useTreeColumnWidths(config));

    expect(result.current.widths).toEqual(config.defaults);
  });

  it("persists a keyboard resize under the caller's own storage key", () => {
    const { result } = renderHook(() => useTreeColumnWidths(config));

    act(() => result.current.resizeBy("amount", 25));

    expect(result.current.widths.amount).toBe(125);
    expect(JSON.parse(window.localStorage.getItem(config.storageKey) ?? "{}")).toEqual({ label: 200, amount: 125 });
  });

  it("clamps to the caller's own per-column floor and shared ceiling", () => {
    const { result } = renderHook(() => useTreeColumnWidths(config));

    act(() => result.current.resizeBy("amount", -1000));
    expect(result.current.widths.amount).toBe(config.minWidths.amount);

    act(() => result.current.resizeBy("label", 1000));
    expect(result.current.widths.label).toBe(config.maxWidth);
  });

  it("reloads a persisted width, clamping a stored value that is out of range", () => {
    window.localStorage.setItem(config.storageKey, JSON.stringify({ label: 10, amount: 150 }));

    const { result } = renderHook(() => useTreeColumnWidths(config));

    expect(result.current.widths).toEqual({ label: config.minWidths.label, amount: 150 });
  });

  // E14-09/#335 round-2 B4: the drag's window listeners are installed by an effect whose deps
  // include the callbacks built from `config`. A caller passing a freshly built object on every
  // render -- the natural thing to write, and what a second table wiring itself onto this hook is
  // likely to do -- used to re-run that effect mid-drag and tear the listeners down after the
  // first frame. The config is now read through a ref, so its identity is not reactive at all.
  it("survives a caller that rebuilds its config object on every render, mid-drag", () => {
    const { result, rerender } = renderHook(() => useTreeColumnWidths({ ...config }));
    const startWidth = result.current.widths.label;

    act(() => result.current.startResize("label", { clientX: 100, button: 0, preventDefault: () => {} } as never));
    // A re-render with a brand-new (but equal) config object, in the middle of the gesture.
    rerender();
    act(() => window.dispatchEvent(new MouseEvent("mousemove", { clientX: 150, bubbles: true, buttons: 1 })));
    act(() => window.dispatchEvent(new MouseEvent("mouseup", { clientX: 150, bubbles: true, buttons: 1 })));

    expect(result.current.widths.label).toBe(startWidth + 50);
  });
});
