import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { Task } from "@/lib/backend";
import { buildVisibleRows, type PlanningTreeRow } from "@/lib/planning-tree";

type RowSelectEvent = { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean };

// Extracted from PlanningTreeTable (E4-12 / #152): row visibility (collapse/expand), single/
// multi-selection and keyboard navigation (arrows, Enter, Space) over the flattened tree. Owns
// its own reset() called from PlanningTreeTable's render-phase versionKey-change block -- see
// that component for why this must stay a synchronous render-body reset, not a useEffect.
export function usePlanningTreeSelection(tasks: Task[]) {
  const [collapsedUids, setCollapsedUids] = useState<Set<number>>(new Set());
  const [selectedUids, setSelectedUids] = useState<Set<number>>(new Set());
  const [focusedUid, setFocusedUid] = useState<number | null>(null);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  const rows = useMemo(() => buildVisibleRows(tasks, collapsedUids), [tasks, collapsedUids]);
  const rowIndexByUid = useMemo(() => new Map(rows.map((row, index) => [row.uid, index])), [rows]);

  useEffect(() => {
    if (focusedUid === null) {
      return;
    }
    const rowElement = rowRefs.current.get(focusedUid);
    // Do not steal focus back to the row when it is already inside one of its inline edit controls.
    if (rowElement && !rowElement.contains(document.activeElement)) {
      rowElement.focus();
    }
  }, [focusedUid]);

  function toggleCollapsed(uid: number) {
    setCollapsedUids((current) => {
      const next = new Set(current);
      if (next.has(uid)) {
        next.delete(uid);
      } else {
        next.add(uid);
      }
      return next;
    });
  }

  function selectRow(row: PlanningTreeRow, event: RowSelectEvent) {
    setSelectedUids((current) => {
      if (event.shiftKey && focusedUid !== null && rowIndexByUid.has(focusedUid)) {
        const start = Math.min(rowIndexByUid.get(focusedUid)!, rowIndexByUid.get(row.uid)!);
        const end = Math.max(rowIndexByUid.get(focusedUid)!, rowIndexByUid.get(row.uid)!);
        return new Set(rows.slice(start, end + 1).map((candidate) => candidate.uid));
      }
      if (event.ctrlKey || event.metaKey) {
        const next = new Set(current);
        if (next.has(row.uid)) {
          next.delete(row.uid);
        } else {
          next.add(row.uid);
        }
        return next;
      }
      return new Set([row.uid]);
    });
    setFocusedUid(row.uid);
  }

  function focusSibling(row: PlanningTreeRow, offset: number) {
    const index = rowIndexByUid.get(row.uid) ?? 0;
    const sibling = rows[index + offset];
    if (sibling) {
      setFocusedUid(sibling.uid);
    }
  }

  function expandOrFocusChild(row: PlanningTreeRow) {
    if (!row.hasChildren) {
      return;
    }
    if (collapsedUids.has(row.uid)) {
      toggleCollapsed(row.uid);
    } else {
      focusSibling(row, 1);
    }
  }

  function collapseOrFocusParent(row: PlanningTreeRow) {
    if (row.hasChildren && !collapsedUids.has(row.uid)) {
      toggleCollapsed(row.uid);
    } else if (row.parent_uid !== null && row.parent_uid !== undefined) {
      setFocusedUid(row.parent_uid);
    }
  }

  const rowKeyHandlers: Record<string, (row: PlanningTreeRow) => void> = {
    ArrowDown: (row) => focusSibling(row, 1),
    ArrowUp: (row) => focusSibling(row, -1),
    ArrowRight: expandOrFocusChild,
    ArrowLeft: collapseOrFocusParent,
    Enter: (row) => selectRow(row, { ctrlKey: false, metaKey: false, shiftKey: false }),
    " ": (row) => selectRow(row, { ctrlKey: true, metaKey: false, shiftKey: false }),
  };

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: PlanningTreeRow) {
    const handler = rowKeyHandlers[event.key];
    if (!handler) {
      return;
    }
    event.preventDefault();
    handler(row);
  }

  function clearSelection() {
    setSelectedUids(new Set());
  }

  function reset() {
    setCollapsedUids(new Set());
    setSelectedUids(new Set());
    setFocusedUid(null);
  }

  return {
    rows,
    rowRefs,
    collapsedUids,
    selectedUids,
    focusedUid,
    setFocusedUid,
    toggleCollapsed,
    selectRow,
    onRowKeyDown,
    clearSelection,
    reset,
  };
}
