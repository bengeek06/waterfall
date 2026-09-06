import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type MouseEvent as ReactMouseEvent,
} from "react";

export type PlanningColumnKey =
  | "uid"
  | "name"
  | "type"
  | "start"
  | "end"
  | "duration"
  | "mode"
  | "predecessors";

export type PlanningColumnWidths = Record<PlanningColumnKey, number>;

export const PLANNING_COLUMN_ORDER: PlanningColumnKey[] = [
  "uid",
  "name",
  "type",
  "start",
  "end",
  "duration",
  "mode",
  "predecessors",
];

export const PLANNING_COLUMN_WIDTHS_STORAGE_KEY = "waterfall:planning-tree-table:column-widths";

// Per-column floor, not a single shared constant: a couple of columns host content that cannot
// truncate/wrap cleanly (see Table's `whitespace-nowrap` default on TableCell) -- start/end show a
// fixed-format date, type shows a short but non-abbreviatable label, and mode hosts a `w-fit`
// Select trigger -- so their minimum must stay wide enough to avoid painting over the next column.
// Predecessors can shrink further than those because it truncates/wraps its content instead. Name
// also truncates its text, but its floor still ends up the highest of all: unlike the others, it
// has to additionally budget for a non-shrinking chevron plus tree indentation ahead of that text
// (see the dedicated comment below), which the shallower columns don't carry.
//
// `mode`'s floor is measured, not guessed, because its intrinsic content (the "sm" SelectTrigger
// in ui/select.tsx, `w-fit whitespace-nowrap`) cannot shrink below its own content width: 16px
// TableCell padding (p-2) + 2px trigger border + 18px trigger padding (pl-2.5 + pr-2) + 6px
// value/icon gap (gap-1.5) + 16px chevron icon (size-4) + ~78px for its longest option's label,
// "Automatique", at text-sm ≈ 136px, rounded up for safety.
//
// `name`'s floor also has to be measured rather than guessed, even though its text itself truncates
// cleanly: the cell also hosts a `shrink-0` expand/collapse chevron (`size-6` = 24px) plus a
// `gap-1` (4px) before that text, and the row's tree indentation (`row.depth * 1.25rem` = depth *
// 20px) sits in front of both. None of the chevron, the gap, or the indentation can shrink, so if
// the column narrows below their combined width the chevron itself gets clipped by the cell's
// `overflow-hidden` -- not just the text -- making the expand/collapse control invisible/unusable
// for deeply nested rows. Budget: 16px TableCell padding (p-2) + 24px chevron + 4px gap = 44px,
// plus indentation headroom up to a typical nesting depth of 4 (one level past the
// Lot > Sous-lot > Tâche > Sous-tâche example that originally exposed this) = 4 * 20px = 80px,
// plus a 40px margin so a few characters of the truncated name plus an ellipsis remain visible
// even at the floor. Total: 44 + 80 + 40 = 164.
//
// This floor is comfortable through that depth-4 example, not a hard guarantee for arbitrary
// nesting: the tree builder allows deeper nesting (a real MS Project import can exceed depth 4),
// and the row's indentation itself is intentionally left uncapped (see PlanningTreeTable's Name
// cell, `row.depth * 1.25rem`) so the visual nesting cue always reflects the actual hierarchy
// rather than flattening past some arbitrary depth. A tree nested deep enough can therefore still
// push the chevron/text past what this floor budgets for at the column's minimum width -- the
// expected fix at that point is for the user to widen the Name column with its resize handle
// (the very capability this hook exists to provide), not a lower ceiling on how deep the
// indentation is allowed to visually represent.

export const PLANNING_MIN_COLUMN_WIDTHS: PlanningColumnWidths = {
  uid: 60,
  name: 164,
  type: 90,
  start: 100,
  end: 100,
  duration: 80,
  mode: 140,
  predecessors: 90,
};

// Single shared ceiling: unlike the per-column minimum, every column's default width comfortably
// fits under one generous maximum, and there is no equivalent overflow risk on the wide end that
// would call for a narrower, column-specific cap.
export const PLANNING_MAX_COLUMN_WIDTH = 480;

export const DEFAULT_PLANNING_COLUMN_WIDTHS: PlanningColumnWidths = {
  uid: 64,
  name: 220,
  type: 96,
  start: 112,
  end: 112,
  duration: 88,
  mode: 150,
  predecessors: 240,
};

function clampColumnWidth(column: PlanningColumnKey, width: number): number {
  return Math.min(PLANNING_MAX_COLUMN_WIDTH, Math.max(PLANNING_MIN_COLUMN_WIDTHS[column], width));
}

function readStoredColumnWidths(): PlanningColumnWidths {
  if (typeof window === "undefined") {
    return DEFAULT_PLANNING_COLUMN_WIDTHS;
  }
  try {
    const raw = window.localStorage.getItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_PLANNING_COLUMN_WIDTHS;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return DEFAULT_PLANNING_COLUMN_WIDTHS;
    }
    const next = { ...DEFAULT_PLANNING_COLUMN_WIDTHS };
    for (const key of PLANNING_COLUMN_ORDER) {
      const value = (parsed as Record<string, unknown>)[key];
      if (typeof value === "number" && Number.isFinite(value)) {
        next[key] = clampColumnWidth(key, value);
      }
    }
    return next;
  } catch {
    return DEFAULT_PLANNING_COLUMN_WIDTHS;
  }
}

function persistColumnWidths(widths: PlanningColumnWidths) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(PLANNING_COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(widths));
  } catch {
    // Ignore persistence failures (storage disabled/full): resizing still works for the session.
  }
}

type DragState = { column: PlanningColumnKey; startX: number; startWidth: number };

type ColumnWidthsListener = () => void;

// A tiny store, one instance per hook call rather than a module-level singleton (see the lazy
// useState below): useSyncExternalStore is the sanctioned way to reconcile a value that differs
// between the server (no localStorage, so DEFAULT_PLANNING_COLUMN_WIDTHS) and the client's first
// render (the persisted value, if any) without a hydration mismatch on the <col> widths -- React
// itself swaps getServerSnapshot for getSnapshot across the hydration boundary. A useEffect that
// calls the useState setter to load the persisted value after mount would also fix the mismatch,
// but is exactly the "setState synchronously in an effect" anti-pattern the react-hooks lint rule
// flags for this "sync with an external system on mount" use case.
function createColumnWidthsStore() {
  let snapshot: PlanningColumnWidths | null = null;
  const listeners = new Set<ColumnWidthsListener>();

  function getSnapshot(): PlanningColumnWidths {
    snapshot ??= readStoredColumnWidths();
    return snapshot;
  }

  function getServerSnapshot(): PlanningColumnWidths {
    return DEFAULT_PLANNING_COLUMN_WIDTHS;
  }

  function setSnapshot(next: PlanningColumnWidths) {
    snapshot = next;
    listeners.forEach((listener) => listener());
  }

  function subscribe(listener: ColumnWidthsListener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return { getSnapshot, getServerSnapshot, setSnapshot, subscribe };
}

// Column widths are a persistent UI preference, independent of the loaded planning data: unlike
// usePlanningTreeSelection's versionKey-driven reset, nothing here should react to the tasks/
// version changing, so this hook is never wired into PlanningTreeTable's synchronous reset block.
export function usePlanningColumnWidths() {
  const [store] = useState(createColumnWidthsStore);
  const widths = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
  const dragStateRef = useRef<DragState | null>(null);

  // Raw "mousemove" fires far more often than the display can repaint (well past 60fps on some
  // systems), and every store.setSnapshot re-renders the whole PlanningTreeTable (all visible rows)
  // via useSyncExternalStore. Coalescing to one store update per animation frame keeps the drag
  // O(rows × frames) instead of O(rows × mouse events) without changing the final width: the latest
  // computed width for the in-progress drag is buffered here and only committed to the store from
  // the scheduled rAF callback (or flushed immediately by stopResize/unmount, see below), so the
  // gesture never applies a value older than the pointer's current position.
  const rafIdRef = useRef<number | null>(null);
  const pendingWidthRef = useRef<{ column: PlanningColumnKey; width: number } | null>(null);

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
      const nextWidth = clampColumnWidth(drag.column, drag.startWidth + delta);
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
    persistColumnWidths(store.getSnapshot());
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
      // A drag can still be active when this hook unmounts (e.g. navigating away from the
      // planning page mid-resize, before the window's own "mouseup" ever fires): without this,
      // the pending width computed by the last buffered mousemove -- or even an already-applied
      // one -- would be silently discarded instead of persisted, contradicting the flush-on-
      // unmount behavior the rest of this hook relies on. Mirror stopResize via the same
      // commitDrag helper in that case; otherwise just cancel whatever frame (if any) is still
      // pending.
      if (dragStateRef.current !== null) {
        commitDrag();
      } else if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, [handleMouseMove, stopResize, commitDrag]);

  const startResize = useCallback(
    (column: PlanningColumnKey, event: ReactMouseEvent<HTMLElement>) => {
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
    (column: PlanningColumnKey, delta: number) => {
      const current = store.getSnapshot();
      const nextWidth = clampColumnWidth(column, current[column] + delta);
      const next = { ...current, [column]: nextWidth };
      store.setSnapshot(next);
      persistColumnWidths(next);
    },
    [store],
  );

  return { widths, startResize, resizeBy };
}
