"use client";

import type { PlanningRow } from "@/lib/planning-tree";

const MIN_SPAN_MS = 24 * 60 * 60 * 1000;

function toTimestamp(value: string | null | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Visualisation Gantt en lecture seule : le planning reste piloté par MS Project,
 * cette vue ne fait que projeter les dates déjà importées.
 */
export function ReadOnlyGantt({ rows }: Readonly<{ rows: PlanningRow[] }>) {
  const scheduled = rows.filter((row) => row.planning.start_at && row.planning.finish_at);
  if (!scheduled.length) {
    return null;
  }

  const starts = scheduled
    .map((row) => toTimestamp(row.planning.start_at))
    .filter((value): value is number => value !== null);
  const finishes = scheduled
    .map((row) => toTimestamp(row.planning.finish_at))
    .filter((value): value is number => value !== null);
  const rangeStart = Math.min(...starts);
  const rangeEnd = Math.max(...finishes);
  const span = Math.max(rangeEnd - rangeStart, MIN_SPAN_MS);

  return (
    <section className="mt-6 border-t pt-4" aria-label="Planning en lecture seule">
      <h3 className="mb-3 text-sm font-medium text-muted-foreground">Vue Gantt (lecture seule)</h3>
      <div className="grid gap-2">
        {scheduled.map((row) => {
          const start = toTimestamp(row.planning.start_at) ?? rangeStart;
          const finish = toTimestamp(row.planning.finish_at) ?? start;
          const offsetPct = ((start - rangeStart) / span) * 100;
          const widthPct = Math.max(((finish - start) / span) * 100, 0.6);
          return (
            <div key={row.node_id} className="grid grid-cols-[minmax(7.5rem,13.75rem)_1fr] items-center gap-3">
              <span className="truncate text-sm" title={row.planning.name}>
                {row.planning.name}
              </span>
              <div className="relative h-3.5 rounded-full bg-muted">
                <div
                  className={`absolute h-full rounded-full ${row.planning.is_milestone ? "bg-destructive" : "bg-primary"}`}
                  style={{ left: `${offsetPct}%`, width: `${widthPct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
