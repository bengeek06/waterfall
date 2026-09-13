import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type MouseEvent as ReactMouseEvent,
} from "react";

// E14-09 (#335) / resolves #316: user-resizable, locally persisted column widths for a tree table,
// extracted from use-planning-column-widths.ts so it is no longer a planning-only capability --
// #316 listed resizable columns, alongside keyboard navigation, as the visible divergence between
// the two tables. This hook carries the mechanism; a table supplies its own column set, floors and
// defaults through the config below (see use-planning-column-widths.ts for the planning preset).

export type TreeColumnWidthsConfig<TKey extends string> = {
  /** localStorage key. Must be unique per table: the persisted shape is the column set itself. */
  storageKey: string;
  order: readonly TKey[];
  defaults: Readonly<Record<TKey, number>>;
  /**
   * Per-column floor rather than a single shared one: a column whose content cannot truncate or
   * wrap (a fixed-format date, a `w-fit` Select trigger, a non-shrinking expand chevron plus tree
   * indentation) needs a wider minimum than one that simply ellipsizes.
   */
  minWidths: Readonly<Record<TKey, number>>;
  /**
   * Single shared ceiling: unlike the floor, there is no per-column overflow risk on the wide end
   * that would call for a column-specific cap.
   */
  maxWidth: number;
};

function clampColumnWidth<TKey extends string>(config: TreeColumnWidthsConfig<TKey>, column: TKey, width: number): number {
  return Math.min(config.maxWidth, Math.max(config.minWidths[column], width));
}

function readStoredColumnWidths<TKey extends string>(config: TreeColumnWidthsConfig<TKey>): Record<TKey, number> {
  if (typeof window === "undefined") {
    return config.defaults;
  }
  try {
    const raw = window.localStorage.getItem(config.storageKey);
    if (!raw) {
      return config.defaults;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return config.defaults;
    }
    const next: Record<TKey, number> = { ...config.defaults };
    for (const key of config.order) {
      const value = (parsed as Record<string, unknown>)[key];
      if (typeof value === "number" && Number.isFinite(value)) {
        next[key] = clampColumnWidth(config, key, value);
      }
    }
    return next;
  } catch {
    return config.defaults;
  }
}

function persistColumnWidths<TKey extends string>(config: TreeColumnWidthsConfig<TKey>, widths: Record<TKey, number>) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(config.storageKey, JSON.stringify(widths));
  } catch {
    // Ignore persistence failures (storage disabled/full): resizing still works for the session.
  }
}

type DragState<TKey extends string> = { column: TKey; startX: number; startWidth: number };

type ColumnWidthsListener = () => void;

// A tiny store, one instance per hook call rather than a module-level singleton (see the lazy
// useState below): useSyncExternalStore is the sanctioned way to reconcile a value that differs
// between the server (no localStorage, so the config's defaults) and the client's first render
// (the persisted value, if any) without a hydration mismatch on the <col> widths -- React itself
// swaps getServerSnapshot for getSnapshot across the hydration boundary. A useEffect that calls
// the useState setter to load the persisted value after mount would also fix the mismatch, but is
// exactly the "setState synchronously in an effect" anti-pattern the react-hooks lint rule flags
// for this "sync with an external system on mount" use case.
function createColumnWidthsStore<TKey extends string>(config: TreeColumnWidthsConfig<TKey>) {
  let snapshot: Record<TKey, number> | null = null;
  const listeners = new Set<ColumnWidthsListener>();

  function getSnapshot(): Record<TKey, number> {
    snapshot ??= readStoredColumnWidths(config);
    return snapshot;
  }

  function getServerSnapshot(): Record<TKey, number> {
    return config.defaults;
  }

  function setSnapshot(next: Record<TKey, number>) {
    snapshot = next;
    listeners.forEach((listener) => listener());
  }

  function subscribe(listener: ColumnWidthsListener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return { getSnapshot, getServerSnapshot, setSnapshot, subscribe };
}

// Column widths are a persistent UI preference, independent of the loaded data: unlike
// useTreeTableSelection's versionKey-driven reset, nothing here should react to the rows/version
// changing, so this hook is never wired into a table's synchronous reset block.
export function useTreeColumnWidths<TKey extends string>(config: TreeColumnWidthsConfig<TKey>) {
  const [store] = useState(() => createColumnWidthsStore(config));
  const widths = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
  const dragStateRef = useRef<DragState<TKey> | null>(null);

  // `config` is read through a ref by every callback below instead of being captured directly, so
  // that none of their identities -- and therefore none of the effects depending on them -- is
  // reactive to it. A caller building its config inline (a perfectly ordinary thing to do, and
  // what a second table wiring itself onto this hook is likely to write first) would otherwise
  // hand a new object every render, re-running the listener-teardown effect below on each one and
  // aborting an in-progress drag right after its first frame. Making that impossible beats
  // documenting "pass a stable object" and hoping the next caller reads it.
  const configRef = useRef(config);
  useEffect(() => {
    configRef.current = config;
  }, [config]);

  // Raw "mousemove" fires far more often than the display can repaint (well past 60fps on some
  // systems), and every store.setSnapshot re-renders the whole table (all visible rows) via
  // useSyncExternalStore. Coalescing to one store update per animation frame keeps the drag
  // O(rows × frames) instead of O(rows × mouse events) without changing the final width: the latest
  // computed width for the in-progress drag is buffered here and only committed to the store from
  // the scheduled rAF callback (or flushed immediately by stopResize/unmount, see below), so the
  // gesture never applies a value older than the pointer's current position.
  const rafIdRef = useRef<number | null>(null);
  const pendingWidthRef = useRef<{ column: TKey; width: number } | null>(null);

  // "Latest ref" for stopResize, populated by the effect below: handleMouseMove needs to call
  // stopResize (see the "button released outside the window" branch below), and stopResize needs to
  // remove the exact handleMouseMove listener it was registered with, which would otherwise be a
  // circular dependency between the two useCallbacks. The ref breaks the cycle without either
  // callback needing the other in its dependency array. It is kept in sync via a `useEffect` rather
  // than a plain write in the render body: mutating a ref's `.current` during render itself is
  // exactly what the react-hooks lint rule (and eventually the React Compiler) flags as unsafe,
  // even though this particular ref is never read during render.
  const stopResizeRef = useRef<() => void>(() => {});

  const handleMouseMove = useCallback(
    (event: MouseEvent) => {
      const drag = dragStateRef.current;
      if (!drag) {
        return;
      }
      // A drag only ever ends via this window's own "mouseup" listener (see startResize below). If
      // the primary button is released while the pointer is outside the browser window/tab, that
      // "mouseup" never reaches us, so dragStateRef and the listener stay alive; moving the pointer
      // back over the page would then resume resizing with no button pressed. `event.buttons` is
      // the live snapshot of which buttons are held *during this move event*, independent of what
      // started the drag, so checking it here reliably detects that the primary button (bit 0) is
      // no longer down and ends the drag as soon as the first mousemove after the missed mouseup
      // arrives, instead of leaving the column "stuck" resizing.
      if ((event.buttons & 1) === 0) {
        stopResizeRef.current();
        return;
      }
      const delta = event.clientX - drag.startX;
      const nextWidth = clampColumnWidth(configRef.current, drag.column, drag.startWidth + delta);
      pendingWidthRef.current = { column: drag.column, width: nextWidth };
      rafIdRef.current ??= requestAnimationFrame(() => {
        rafIdRef.current = null;
        const pending = pendingWidthRef.current;
        if (!pending) {
          return;
        }
        pendingWidthRef.current = null;
        store.setSnapshot({ ...store.getSnapshot(), [pending.column]: pending.width });
      });
    },
    [store],
  );

  // Applies whatever width the still-pending (not yet rAF-flushed) mousemove computed, then cancels
  // the scheduled frame so it can't re-apply a now-stale value afterwards. Used both to end a drag
  // "on time" (stopResize) and to avoid leaking a pending frame past unmount.
  const flushPendingWidth = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    const pending = pendingWidthRef.current;
    if (!pending) {
      return;
    }
    pendingWidthRef.current = null;
    store.setSnapshot({ ...store.getSnapshot(), [pending.column]: pending.width });
  }, [store]);

  // Shared by stopResize and the unmount cleanup below: both need to end an active drag the same
  // way -- flush whatever width the last buffered mousemove computed, then persist the store's
  // current snapshot -- so this is factored out once instead of duplicated between the two.
  const commitDrag = useCallback(() => {
    dragStateRef.current = null;
    flushPendingWidth();
    persistColumnWidths(configRef.current, store.getSnapshot());
  }, [flushPendingWidth, store]);

  const stopResize = useCallback(() => {
    window.removeEventListener("mousemove", handleMouseMove);
    commitDrag();
  }, [handleMouseMove, commitDrag]);

  useEffect(() => {
    stopResizeRef.current = stopResize;
  }, [stopResize]);

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopResize);
      // A drag can still be active when this hook unmounts (e.g. navigating away from the page
      // mid-resize, before the window's own "mouseup" ever fires): without this, the pending width
      // computed by the last buffered mousemove -- or even an already-applied one -- would be
      // silently discarded instead of persisted, contradicting the flush-on-unmount behavior the
      // rest of this hook relies on. Mirror stopResize via the same commitDrag helper in that case;
      // otherwise just cancel whatever frame (if any) is still pending.
      if (dragStateRef.current !== null) {
        commitDrag();
      } else if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, [handleMouseMove, stopResize, commitDrag]);

  const startResize = useCallback(
    (column: TKey, event: ReactMouseEvent<HTMLElement>) => {
      // Ignore right-/middle-button presses: only the primary (left) button should start a drag,
      // otherwise preventDefault below would suppress the browser's native context menu/paste
      // behavior for a gesture that was never meant to resize anything.
      if (event.button !== 0) {
        return;
      }
      event.preventDefault();
      dragStateRef.current = { column, startX: event.clientX, startWidth: store.getSnapshot()[column] };
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", stopResize, { once: true });
    },
    [store, handleMouseMove, stopResize],
  );

  // Discrete keyboard adjustment (e.g. ArrowLeft/ArrowRight on the resize handle), as opposed to
  // the continuous mouse drag above. Each call is a complete, self-contained resize -- unlike
  // startResize/handleMouseMove/stopResize, there is no separate "end of gesture" event to persist
  // on, so this persists immediately after every adjustment.
  const resizeBy = useCallback(
    (column: TKey, delta: number) => {
      const current = store.getSnapshot();
      const nextWidth = clampColumnWidth(configRef.current, column, current[column] + delta);
      const next = { ...current, [column]: nextWidth };
      store.setSnapshot(next);
      persistColumnWidths(configRef.current, next);
    },
    [store],
  );

  return { widths, startResize, resizeBy };
}
