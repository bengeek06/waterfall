"use client";

import type { EstimateAggregates } from "@/lib/backend";

export type AnalyticsTabProps = {
  active: boolean;
  selectedEstimateId: number | null;
  aggregates: EstimateAggregates | null;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): composes the "Analytique" tab (aggregate
// summary cards + per-category distribution bars). Gates its own visibility via the `active`
// prop, matching PlanningTab/EstimateTab. Verbatim JSX move -- see page.tsx call site for wiring.
export function AnalyticsTab({ active, selectedEstimateId, aggregates }: AnalyticsTabProps) {
  if (!active) {
    return null;
  }

  return (
    <div className="grid gap-4">
      <h2>Analytique</h2>
      {!selectedEstimateId ? <p className="text-sm text-muted-foreground">Sélectionne un devis dans l&apos;onglet Devis.</p> : null}
      {selectedEstimateId && !aggregates ? <p className="text-sm text-muted-foreground">Chargement des agrégats...</p> : null}
      {aggregates ? (
        <div className="grid gap-4">
          <div className="flex flex-wrap gap-3">
            <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
              <strong>{Number(aggregates.total_labor_cost).toFixed(2)}</strong>
              <span>Total MO</span>
            </div>
            <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
              <strong>{Number(aggregates.total_purchase_cost).toFixed(2)}</strong>
              <span>Total Achat</span>
            </div>
            <div className="grid min-w-37.5 w-fit gap-0.5 rounded-lg border bg-muted/40 px-4 py-3">
              <strong>{Number(aggregates.total_unburdened_cost).toFixed(2)}</strong>
              <span>PRU non chargé</span>
            </div>
          </div>

          <div className="pt-2">
            <h3 className="mb-3 text-sm font-medium text-muted-foreground">Répartition par catégorie</h3>
            {Object.keys(aggregates.by_category).length === 0 ? (
              <p className="text-sm text-muted-foreground">Aucun montant à répartir pour ce devis.</p>
            ) : (
              (() => {
                const entries = Object.entries(aggregates.by_category);
                const max = Math.max(...entries.map(([, amount]) => Number(amount)), 1);
                return (
                  <div className="grid gap-2">
                    {entries.map(([category, amount]) => (
                      <div className="grid grid-cols-[minmax(7.5rem,13.75rem)_1fr_auto] items-center gap-3" key={category}>
                        <span className="truncate text-sm">{category}</span>
                        <div className="relative h-3.5 rounded-full bg-muted">
                          <div
                            className="absolute h-full rounded-full bg-primary"
                            style={{ width: `${(Number(amount) / max) * 100}%` }}
                          />
                        </div>
                        <span className="text-sm text-muted-foreground">{Number(amount).toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                );
              })()
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
