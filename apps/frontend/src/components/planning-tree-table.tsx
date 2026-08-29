"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Task } from "@/lib/backend";

type PlanningTreeRow = Task & { depth: number; hasChildren: boolean };

// MS Project standard predecessor link type codes (see wf_planning_link_snapshot check constraint).
const LINK_TYPE_LABELS: Record<number, string> = { 0: "FF", 1: "FS", 2: "SF", 3: "SS" };

function buildVisibleRows(tasks: Task[], collapsedUids: Set<number>): PlanningTreeRow[] {
  const knownUids = new Set(tasks.map((task) => task.uid));
  const childrenByParent = new Map<number | null, Task[]>();
  for (const task of tasks) {
    const parentKey = task.parent_uid !== null && task.parent_uid !== undefined && knownUids.has(task.parent_uid)
      ? task.parent_uid
      : null;
    const siblings = childrenByParent.get(parentKey) ?? [];
    siblings.push(task);
    childrenByParent.set(parentKey, siblings);
  }
  // The backend orders unpositioned tasks last; mirror that instead of treating null as position 0.
  for (const siblings of childrenByParent.values()) {
    siblings.sort((a, b) => (a.position ?? Number.POSITIVE_INFINITY) - (b.position ?? Number.POSITIVE_INFINITY));
  }

  const rows: PlanningTreeRow[] = [];
  function walk(parentUid: number | null, depth: number) {
    for (const task of childrenByParent.get(parentUid) ?? []) {
      const hasChildren = (childrenByParent.get(task.uid) ?? []).length > 0;
      rows.push({ ...task, depth, hasChildren });
      if (hasChildren && !collapsedUids.has(task.uid)) {
        walk(task.uid, depth + 1);
      }
    }
  }
  walk(null, 0);
  return rows;
}

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleDateString("fr-FR") : "-";
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

// TaskRead does not expose duration_minutes; derive a display-only duration from the scheduled dates.
function formatDuration(startAt: string | null | undefined, finishAt: string | null | undefined): string {
  if (!startAt || !finishAt) {
    return "-";
  }
  const start = new Date(startAt).getTime();
  const finish = new Date(finishAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(finish) || finish < start) {
    return "-";
  }
  const days = Math.max(Math.round((finish - start) / MS_PER_DAY), 0);
  return `${days} j`;
}

function taskTypeLabel(task: Task): string {
  if (task.is_milestone) {
    return "Jalon";
  }
  return task.is_summary ? "Résumé" : "Tâche";
}

function taskModeLabel(task: Task): string {
  if (task.is_manual === null || task.is_manual === undefined) {
    return "-";
  }
  return task.is_manual ? "Manuel" : "Automatique";
}

function predecessorsLabel(task: Task): string {
  if (!task.predecessor_links?.length) {
    return "-";
  }
  return task.predecessor_links
    .map((link) => {
      const type = LINK_TYPE_LABELS[link.link_type] ?? String(link.link_type);
      const lagMinutes = link.lag_tenth_minute ? link.lag_tenth_minute / 10 : 0;
      const lagSign = lagMinutes > 0 ? "+" : "";
      const lag = lagMinutes ? ` ${lagSign}${lagMinutes}min` : "";
      return `${link.predecessor_uid} (${type}${lag})`;
    })
    .join(", ");
}

type PlanningTreeTableProps = Readonly<{
  tasks: Task[];
  /** Any value identifying the loaded planning version; changing it resets local expand/selection state. */
  versionKey: number | string | null;
  readOnly?: boolean;
}>;

export function PlanningTreeTable({ tasks, versionKey, readOnly = false }: PlanningTreeTableProps) {
  const [collapsedUids, setCollapsedUids] = useState<Set<number>>(new Set());
  const [selectedUids, setSelectedUids] = useState<Set<number>>(new Set());
  const [focusedUid, setFocusedUid] = useState<number | null>(null);
  const [renderedVersionKey, setRenderedVersionKey] = useState(versionKey);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  // A different planning version must never reuse another version's expand/selection state.
  if (versionKey !== renderedVersionKey) {
    setRenderedVersionKey(versionKey);
    setCollapsedUids(new Set());
    setSelectedUids(new Set());
    setFocusedUid(null);
  }

  const rows = useMemo(() => buildVisibleRows(tasks, collapsedUids), [tasks, collapsedUids]);
  const rowIndexByUid = useMemo(() => new Map(rows.map((row, index) => [row.uid, index])), [rows]);

  useEffect(() => {
    if (focusedUid !== null) {
      rowRefs.current.get(focusedUid)?.focus();
    }
  }, [focusedUid]);

  const readOnlyNotice = readOnly ? (
    <p className="mt-2 text-xs text-muted-foreground">Version validée ou projet en lecture seule : édition désactivée.</p>
  ) : null;

  if (!tasks.length) {
    return (
      <>
        <p className="py-6 text-sm text-muted-foreground">Le planning ne contient aucune tâche.</p>
        {readOnlyNotice}
      </>
    );
  }

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

  function selectRow(row: PlanningTreeRow, event: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) {
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

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Planning</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>UID</TableHead>
              <TableHead>Nom</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Début</TableHead>
              <TableHead>Fin</TableHead>
              <TableHead>Durée</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead>Prédécesseurs</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const collapsed = collapsedUids.has(row.uid);
              const selected = selectedUids.has(row.uid);
              const isFocusable = focusedUid === row.uid || (focusedUid === null && row.uid === rows[0]?.uid);
              return (
                <TableRow
                  key={row.uid}
                  ref={(element) => {
                    if (element) {
                      rowRefs.current.set(row.uid, element);
                    } else {
                      rowRefs.current.delete(row.uid);
                    }
                  }}
                  data-state={selected ? "selected" : undefined}
                  aria-selected={selected}
                  tabIndex={isFocusable ? 0 : -1}
                  className="cursor-pointer outline-none"
                  onClick={(event) => selectRow(row, event)}
                  onFocus={() => setFocusedUid(row.uid)}
                  onKeyDown={(event) => onRowKeyDown(event, row)}
                >
                  <TableCell>{row.id_display ?? row.uid}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1" style={{ paddingLeft: `${row.depth * 1.25}rem` }}>
                      {row.hasChildren ? (
                        <button
                          type="button"
                          aria-label={collapsed ? `Déplier ${row.name}` : `Replier ${row.name}`}
                          className="flex size-6 items-center justify-center"
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleCollapsed(row.uid);
                          }}
                        >
                          {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
                        </button>
                      ) : (
                        <span className="size-6" />
                      )}
                      {row.is_milestone ? "◆ " : ""}
                      {row.name}
                    </div>
                  </TableCell>
                  <TableCell>{taskTypeLabel(row)}</TableCell>
                  <TableCell>{formatDate(row.start_at)}</TableCell>
                  <TableCell>{formatDate(row.finish_at)}</TableCell>
                  <TableCell>{formatDuration(row.start_at, row.finish_at)}</TableCell>
                  <TableCell>{taskModeLabel(row)}</TableCell>
                  <TableCell>{predecessorsLabel(row)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {readOnlyNotice}
      </CardContent>
    </Card>
  );
}
