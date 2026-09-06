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
// Name and predecessors can shrink further because they truncate/wrap their content instead.
export const PLANNING_MIN_COLUMN_WIDTHS: PlanningColumnWidths = {
  uid: 60,
  name: 100,
  type: 90,
  start: 100,
  end: 100,
  duration: 80,
  mode: 90,
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
  mode: 96,
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

  const handleMouseMove = useCallback(
    (event: MouseEvent) => {
      const drag = dragStateRef.current;
      if (!drag) {
        return;
      }
      const delta = event.clientX - drag.startX;
      const nextWidth = clampColumnWidth(drag.column, drag.startWidth + delta);
      store.setSnapshot({ ...store.getSnapshot(), [drag.column]: nextWidth });
    },
    [store],
  );

  const stopResize = useCallback(() => {
    dragStateRef.current = null;
    window.removeEventListener("mousemove", handleMouseMove);
    persistColumnWidths(store.getSnapshot());
  }, [handleMouseMove, store]);

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopResize);
    };
  }, [handleMouseMove, stopResize]);

  const startResize = useCallback(
    (column: PlanningColumnKey, event: ReactMouseEvent<HTMLElement>) => {
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
