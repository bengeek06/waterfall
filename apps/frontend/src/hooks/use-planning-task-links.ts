import { useMemo, useState } from "react";

import type { Task, TaskLinkWrite } from "@/lib/backend";
import { createLinkRowDraft, type LinkRowDraft } from "@/lib/planning-links";
import type { PlanningTreeRow } from "@/lib/planning-tree";

type UsePlanningTaskLinksParams = {
  tasks: Task[];
  onEditLinks?: (payload: { taskUid: number; links: TaskLinkWrite[] }) => Promise<void>;
};

// Every row must reference a predecessor before submitting; returns the first validation error
// found, or null when every row is valid.
function validateLinkRows(rows: LinkRowDraft[]): string | null {
  if (rows.some((row) => row.predecessorUid === null)) {
    return "Sélectionnez une tâche prédécesseure pour chaque ligne.";
  }
  const seen = new Set<string>();
  for (const row of rows) {
    const dedupeKey = `${row.predecessorUid}-${row.linkType}`;
    if (seen.has(dedupeKey)) {
      return "Deux lignes ne peuvent pas référencer la même tâche prédécesseure avec le même type de lien.";
    }
    seen.add(dedupeKey);
  }
  return null;
}

// Converts already-validated draft rows into the write payload, or returns an error message if a
// row's lag is out of the backend's representable range. Assumes validateLinkRows already passed.
function buildLinksPayload(rows: LinkRowDraft[]): TaskLinkWrite[] | string {
  const links: TaskLinkWrite[] = [];
  for (const row of rows) {
    const trimmedLag = row.lagMinutes.trim();
    const lagMinutesValue = trimmedLag === "" ? 0 : Number(trimmedLag);
    // Checked after scaling, not on lagMinutesValue alone: a finite input large enough
    // (e.g. 1e308) overflows to Infinity once multiplied by 10, which JSON.stringify
    // would then silently turn into null instead of the entered value. The upper/lower
    // bounds mirror the backend's lag_tenth_minute range (a PostgreSQL Integer column),
    // so an out-of-range value is rejected here instead of via an avoidable failed request.
    const lagTenthMinute = Math.round(lagMinutesValue * 10);
    if (!Number.isFinite(lagTenthMinute) || lagTenthMinute < -2_147_483_648 || lagTenthMinute > 2_147_483_647) {
      return "Le décalage doit être un nombre de minutes valide.";
    }
    links.push({
      predecessor_uid: row.predecessorUid as number,
      link_type: row.linkType,
      lag_tenth_minute: lagTenthMinute,
      // Preserve the row's existing lag_format rather than overwriting it: this dialog
      // only edits predecessor/type/lag value, never the lag's working-time/elapsed unit.
      lag_format: row.lagFormat,
    });
  }
  return links;
}

// Extracted from PlanningTreeTable (E4-12 / #152): the predecessor-links dialog's state (which
// task is being edited, its draft rows) and submit flow. Owns its own reset() called from
// PlanningTreeTable's render-phase versionKey-change block -- see that component for why this
// must stay a synchronous render-body reset, not a useEffect.
export function usePlanningTaskLinks({ tasks, onEditLinks }: UsePlanningTaskLinksParams) {
  const [editingTaskUid, setEditingTaskUid] = useState<number | null>(null);
  const [linkRows, setLinkRows] = useState<LinkRowDraft[]>([]);
  const [linkFormError, setLinkFormError] = useState<string | null>(null);
  const [linkFormBusy, setLinkFormBusy] = useState(false);

  const editingTask = useMemo(
    () => (editingTaskUid !== null ? (tasks.find((task) => task.uid === editingTaskUid) ?? null) : null),
    [tasks, editingTaskUid],
  );
  const linkCandidateTasks = useMemo(
    () => tasks.filter((task) => task.uid !== editingTaskUid),
    [tasks, editingTaskUid],
  );

  function openLinksDialog(row: PlanningTreeRow) {
    setEditingTaskUid(row.uid);
    setLinkRows((row.predecessor_links ?? []).map((link) => createLinkRowDraft(link)));
    setLinkFormError(null);
  }

  function closeLinksDialog() {
    setEditingTaskUid(null);
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
    if (editingTaskUid === null || !onEditLinks) {
      return;
    }
    const validationError = validateLinkRows(linkRows);
    if (validationError) {
      setLinkFormError(validationError);
      return;
    }
    const built = buildLinksPayload(linkRows);
    if (typeof built === "string") {
      setLinkFormError(built);
      return;
    }
    setLinkFormError(null);
    setLinkFormBusy(true);
    try {
      await onEditLinks({ taskUid: editingTaskUid, links: built });
      closeLinksDialog();
    } catch (cause) {
      setLinkFormError(cause instanceof Error ? cause.message : "Impossible de mettre à jour les prédécesseurs.");
    } finally {
      setLinkFormBusy(false);
    }
  }

  function reset() {
    setEditingTaskUid(null);
    setLinkRows([]);
    setLinkFormError(null);
    setLinkFormBusy(false);
  }

  return {
    editingTask,
    linkCandidateTasks,
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
