import { useState } from "react";

import { filterVisibleEstimateGridRows, type EstimateGridTreeRow } from "@/lib/estimate-grid-tree";

type RowSelectEvent = { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean };

// E12-10/#292: collapse/expand and row selection over the devis grid tree -- modeled after
// usePlanningTreeSelection, deliberately smaller: only cost-line/role-assignment ("grid node")
// rows can ever enter `selectedUids` (a task row click is a no-op for selection purposes, see
// selectRow below), since the move toolbar this selection feeds (EstimateGridTreeTable's
// Indenter/Désindenter/Monter/Descendre) never reorders tasks -- see lib/estimate-grid-move.ts's
// own doc comment. Full keyboard arrow-navigation (ArrowUp/Down/Left/Right) is intentionally not
// reimplemented here: not required by this issue's own acceptance criteria, unlike
// PlanningTreeTable's richer, pre-existing keyboard support.
export function useEstimateGridSelection(rows: EstimateGridTreeRow[]) {
  const [collapsedUids, setCollapsedUids] = useState<Set<number>>(new Set());
  const [selectedUids, setSelectedUids] = useState<Set<number>>(new Set());
  const [focusedUid, setFocusedUid] = useState<number | null>(null);

  const visibleRows = filterVisibleEstimateGridRows(rows, collapsedUids);
  const selectableRows = visibleRows.filter((row) => row.kind !== "task" && row.uid != null);
  const selectableIndexByUid = new Map(selectableRows.map((row, index) => [row.uid as number, index]));

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

  function selectRow(row: EstimateGridTreeRow, event: RowSelectEvent) {
    if (row.kind === "task" || row.uid == null) {
      return;
    }
    const uid = row.uid;
    setSelectedUids((current) => {
      if (event.shiftKey && focusedUid !== null && selectableIndexByUid.has(focusedUid)) {
        const start = Math.min(selectableIndexByUid.get(focusedUid)!, selectableIndexByUid.get(uid)!);
        const end = Math.max(selectableIndexByUid.get(focusedUid)!, selectableIndexByUid.get(uid)!);
        return new Set(selectableRows.slice(start, end + 1).map((candidate) => candidate.uid as number));
      }
      if (event.ctrlKey || event.metaKey) {
        const next = new Set(current);
        if (next.has(uid)) {
          next.delete(uid);
        } else {
          next.add(uid);
        }
        return next;
      }
      return new Set([uid]);
    });
    setFocusedUid(uid);
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
    visibleRows,
    collapsedUids,
    selectedUids,
    focusedUid,
    toggleCollapsed,
    selectRow,
    clearSelection,
    reset,
  };
}
