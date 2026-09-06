import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";

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

export const PLANNING_MIN_COLUMN_WIDTH = 60;

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
      if (typeof value === "number" && Number.isFinite(value) && value >= PLANNING_MIN_COLUMN_WIDTH) {
        next[key] = value;
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

// Column widths are a persistent UI preference, independent of the loaded planning data: unlike
// usePlanningTreeSelection's versionKey-driven reset, nothing here should react to the tasks/
// version changing, so this hook is never wired into PlanningTreeTable's synchronous reset block.
export function usePlanningColumnWidths() {
  const [widths, setWidths] = useState<PlanningColumnWidths>(() => readStoredColumnWidths());
  const dragStateRef = useRef<DragState | null>(null);

  const handleMouseMove = useCallback((event: MouseEvent) => {
    const drag = dragStateRef.current;
    if (!drag) {
      return;
    }
    const delta = event.clientX - drag.startX;
    const nextWidth = Math.max(PLANNING_MIN_COLUMN_WIDTH, drag.startWidth + delta);
    setWidths((current) => ({ ...current, [drag.column]: nextWidth }));
  }, []);

  const stopResize = useCallback(() => {
    dragStateRef.current = null;
    window.removeEventListener("mousemove", handleMouseMove);
    setWidths((current) => {
      persistColumnWidths(current);
      return current;
    });
  }, [handleMouseMove]);

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopResize);
    };
  }, [handleMouseMove, stopResize]);

  const startResize = useCallback(
    (column: PlanningColumnKey, event: ReactMouseEvent<HTMLElement>) => {
      event.preventDefault();
      dragStateRef.current = { column, startX: event.clientX, startWidth: widths[column] };
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", stopResize, { once: true });
    },
    [widths, handleMouseMove, stopResize],
  );

  // Discrete keyboard adjustment (e.g. ArrowLeft/ArrowRight on the resize handle), as opposed to
  // the continuous mouse drag above. Each call is a complete, self-contained resize -- unlike
  // startResize/handleMouseMove/stopResize, there is no separate "end of gesture" event to persist
  // on, so this persists immediately after every adjustment.
  const resizeBy = useCallback((column: PlanningColumnKey, delta: number) => {
    setWidths((current) => {
      const nextWidth = Math.max(PLANNING_MIN_COLUMN_WIDTH, current[column] + delta);
      const next = { ...current, [column]: nextWidth };
      persistColumnWidths(next);
      return next;
    });
  }, []);

  return { widths, startResize, resizeBy };
}
