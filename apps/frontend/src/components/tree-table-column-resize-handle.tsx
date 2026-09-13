"use client";

import type { MouseEvent } from "react";

// Fixed step for keyboard-driven resizing (ArrowLeft/ArrowRight), mirroring the granularity of a
// small mouse drag.
export const COLUMN_RESIZE_KEYBOARD_STEP = 10;

export type TreeTableColumnResizeHandleProps<TKey extends string> = {
  column: TKey;
  /** Column header label, used to build the handle's accessible name. */
  label: string;
  width: number;
  min: number;
  max: number;
  onResizeStart: (column: TKey, event: MouseEvent<HTMLSpanElement>) => void;
  onResizeBy: (column: TKey, delta: number) => void;
};

// E14-09 (#335) / resolves #316: the resize grip that goes with useTreeColumnWidths, extracted
// from planning-tree-table.tsx so any tree table can mount it on its own header cells (the host
// TableHead must be `relative overflow-hidden`). Presentational only -- it owns no width state.
export function TreeTableColumnResizeHandle<TKey extends string>({
  column,
  label,
  width,
  min,
  max,
  onResizeStart,
  onResizeBy,
}: TreeTableColumnResizeHandleProps<TKey>) {
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={`Redimensionner la colonne ${label}`}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      data-testid={`resize-handle-${column}`}
      // `group` + a wider (w-3 = 12px) hit area than what's visually painted (the inner bar below
      // stays w-1 = 4px, flush against the column boundary via justify-end): a plain 4px strip is
      // only discoverable by accidentally hovering exactly on the column boundary, and is a fiddly
      // mouse/touch target. The outer box stays entirely inside the TableHead's own bounds (right-0,
      // extending leftward into the current column, never past its right edge), so none of it is
      // clipped by the parent's `overflow-hidden` (needed so the handle never visually spills into
      // the next header).
      className="group absolute right-0 top-0 z-10 flex h-full w-3 cursor-col-resize items-center justify-end select-none outline-none"
      onMouseDown={(event) => onResizeStart(column, event)}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          onResizeBy(column, -COLUMN_RESIZE_KEYBOARD_STEP);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          onResizeBy(column, COLUMN_RESIZE_KEYBOARD_STEP);
        }
      }}
    >
      {/*
        Visible handle bar, separate from the interactive span above: `hover:bg-border` gives
        sighted mouse users a discoverable affordance instead of an invisible strip.
        `group-focus-visible:bg-primary` is a background-color change rather than an
        `outline`/`ring` utility on the handle itself, because that would be clipped by the parent
        TableHead's `overflow-hidden` if it extended outside the handle's own box -- a background
        change painted inside the bar's own bounds stays visible under that clipping, so keyboard
        focus is never silently invisible.
      */}
      <span
        aria-hidden="true"
        className="h-full w-1 rounded-full bg-transparent transition-colors group-hover:bg-border group-focus-visible:bg-primary"
      />
    </span>
  );
}
