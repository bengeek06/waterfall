import { useMemo, useState } from "react";

import type { RevisionPredecessorWrite } from "@/lib/backend";
import { createLinkRowDraft, linkRowToPredecessorWrite, type LinkRowDraft } from "@/lib/planning-links";
import type { PlanningRow } from "@/lib/planning-tree";

type UsePlanningTaskLinksParams = {
  rows: PlanningRow[];
  onEditLinks?: (payload: { nodeId: number; predecessors: RevisionPredecessorWrite[] }) => Promise<void>;
};

// Every row must reference a predecessor before submitting; returns the first validation error
// found, or null when every row is valid.
function validateLinkRows(rows: LinkRowDraft[]): string | null {
  if (rows.some((row) => row.predecessorNodeId === null)) {
    return "Sélectionnez une tâche prédécesseure pour chaque ligne.";
  }
  const seen = new Set<string>();
  for (const row of rows) {
    const dedupeKey = `${row.predecessorNodeId}-${row.linkType}`;
    if (seen.has(dedupeKey)) {
      return "Deux lignes ne peuvent pas référencer la même tâche prédécesseure avec le même type de lien.";
    }
    seen.add(dedupeKey);
  }
  return null;
}

// Converts already-validated draft rows into the write payload, or returns an error message if a
// row's lag is out of the backend's representable range. Assumes validateLinkRows already passed.
function buildPredecessorsPayload(rows: LinkRowDraft[]): RevisionPredecessorWrite[] | string {
  const predecessors: RevisionPredecessorWrite[] = [];
  for (const row of rows) {
    const written = linkRowToPredecessorWrite(row);
    // Checked after scaling, not on the typed value alone: a finite input large enough (e.g.
    // 1e308) overflows to Infinity once multiplied by 10, which JSON.stringify would then silently
    // turn into null instead of the entered value. The bounds mirror the backend's
    // lag_tenth_minute range (a PostgreSQL Integer column), so an out-of-range value is rejected
    // here instead of via an avoidable failed request.
    if (
      !written ||
      !Number.isFinite(written.lag_tenth_minute) ||
      (written.lag_tenth_minute ?? 0) < -2_147_483_648 ||
      (written.lag_tenth_minute ?? 0) > 2_147_483_647
    ) {
      return "Le décalage doit être un nombre de minutes valide.";
    }
    predecessors.push(written);
  }
  return predecessors;
}

// Extracted from PlanningTreeTable (E4-12 / #152): the predecessor-links dialog's state (which row
// is being edited, its draft rows) and submit flow. Owns its own reset() called from
// PlanningTreeTable's render-phase revision-change block -- see that component for why this must
// stay a synchronous render-body reset, not a useEffect.
//
// E14-10 (#336): a link designates a **node**, never an uid, and replacing a node's predecessors
// is a PUT of the whole list -- an empty list erases them, and is the only way to.
export function usePlanningTaskLinks({ rows, onEditLinks }: UsePlanningTaskLinksParams) {
  const [editingNodeId, setEditingNodeId] = useState<number | null>(null);
  const [linkRows, setLinkRows] = useState<LinkRowDraft[]>([]);
  const [linkFormError, setLinkFormError] = useState<string | null>(null);
  const [linkFormBusy, setLinkFormBusy] = useState(false);

  const editingRow = useMemo(
    () => (editingNodeId !== null ? (rows.find((row) => row.node_id === editingNodeId) ?? null) : null),
    [rows, editingNodeId],
  );
  const linkCandidateRows = useMemo(
    () => rows.filter((row) => row.node_id !== editingNodeId),
    [rows, editingNodeId],
  );

  function openLinksDialog(row: PlanningRow) {
    setEditingNodeId(row.node_id);
    setLinkRows(row.predecessors.map((link) => createLinkRowDraft(link)));
    setLinkFormError(null);
  }

  function closeLinksDialog() {
    setEditingNodeId(null);
    setLinkRows([]);
    setLinkFormError(null);
  }

  function addLinkRow() {
    setLinkRows((current) => [...current, createLinkRowDraft()]);
  }

  function removeLinkRow(rowId: string) {
    setLinkRows((current) => current.filter((row) => row.rowId !== rowId));
  }

  function updateLinkRow(rowId: string, patch: Partial<LinkRowDraft>) {
    setLinkRows((current) => current.map((row) => (row.rowId === rowId ? { ...row, ...patch } : row)));
  }

  async function submitLinks() {
    if (editingNodeId === null || !onEditLinks) {
      return;
    }
    const validationError = validateLinkRows(linkRows);
    if (validationError) {
      setLinkFormError(validationError);
      return;
    }
    const built = buildPredecessorsPayload(linkRows);
    if (typeof built === "string") {
      setLinkFormError(built);
      return;
    }
    setLinkFormError(null);
    setLinkFormBusy(true);
    try {
      await onEditLinks({ nodeId: editingNodeId, predecessors: built });
      closeLinksDialog();
    } catch (cause) {
      setLinkFormError(cause instanceof Error ? cause.message : "Impossible de mettre à jour les prédécesseurs.");
    } finally {
      setLinkFormBusy(false);
    }
  }

  function reset() {
    setEditingNodeId(null);
    setLinkRows([]);
    setLinkFormError(null);
    setLinkFormBusy(false);
  }

  return {
    editingRow,
    linkCandidateRows,
    linkRows,
    linkFormError,
    linkFormBusy,
    openLinksDialog,
    closeLinksDialog,
    addLinkRow,
    removeLinkRow,
    updateLinkRow,
    submitLinks,
    reset,
  };
}
