"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CostCategory } from "@/lib/backend";

export type ValuationPanelProps = {
  // Already restricted to "labor"-kind categories and sliced to the current page --
  // see `getValuationCategoryPage` in `resources/page.tsx`.
  items: CostCategory[];
  // Computed once in the parent page (not recomputed here) and shared with
  // `saveAllValuation`'s save loop, so the displayed year columns and the years
  // actually persisted on "Enregistrer" can never drift apart -- see the comment
  // on `valuationYears` in `resources/page.tsx`.
  years: number[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  inflationYear: string;
  inflationValue: string;
  currency: string;
  drafts: Record<string, string>;
  busy: boolean;
  onCurrencyChange: (value: string) => void;
  onInflationChange: (value: string) => void;
  onRateChange: (key: string, value: string) => void;
  onSave: () => void;
};

// A stable-identity input for one category/year rate cell. `columns` below is
// memoized with an empty dependency array so TanStack Table's `flexRender`
// keeps passing the *same* component type across renders -- otherwise (a
// fresh `cell` closure on every keystroke, since it closed over `props.drafts`)
// React would unmount/remount the input after every character typed, dropping
// focus (same bug class found in the parallel EPIC E8 migrations #123/#124).
// Since the memo doesn't depend on `drafts`, the value displayed while typing
// can't be read fresh from it either -- this component owns its value as
// local state instead, seeded once when the row/year cell first appears (e.g.
// on initial load or a page change), reporting every keystroke upward via
// `onChange` for `drafts`/"Enregistrer" to use. Cross-page persistence of a
// draft (this panel's whole reason for keeping `drafts` in the parent, per the
// comment on `ValuationPanel`) is unaffected: navigating away and back
// remounts this cell (a different row/page), correctly re-seeding from
// `drafts`, which already reflects whatever was typed before navigating away.
function ValuationRateInput(props: { ariaLabel: string; initialValue: string; onChange: (value: string) => void }) {
  const [value, setValue] = useState(props.initialValue);
  return (
    <Input
      aria-label={props.ariaLabel}
      type="number"
      step="0.01"
      min="0"
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange(event.target.value);
      }}
      placeholder="-"
    />
  );
}

// Comportement retenu pour les brouillons (issue #122, EPIC E8) : ILS SONT
// CONSERVÉS entre deux pages, tris ou recherches -- jamais réinitialisés par un
// changement de page/tri/filtre. `drafts` (l'état `rateDrafts` de la page
// parente) est une map plate "categoryId:year" -> valeur saisie, tenue
// indépendamment de la page actuellement affichée par le DataTable ci-dessous :
// changer de page ne fait que changer quelles lignes sont rendues, jamais le
// contenu de cette map. Symétriquement, `onSave` (`saveAllValuation` dans
// `resources/page.tsx`) parcourt la liste complète des catégories de main
// d'œuvre (pas seulement `items`, la page actuellement visible) : l'enregistrement
// groupé porte donc toujours sur l'ensemble des brouillons saisis, y compris ceux
// d'une page qui n'est plus affichée au moment du clic sur "Enregistrer".
//
// La recherche/le tri/la pagination de cette grille sont calculés côté client
// (voir `getValuationCategoryPage` dans `resources/page.tsx`) plutôt que délégués
// au serveur : `/resources/categories` ne fournit aucun filtre par type de coût
// (main d'œuvre / fourniture / autre), alors que cette grille ne doit jamais
// afficher que des catégories de type "main d'œuvre". Post-filtrer une page
// renvoyée par le serveur casserait la pagination -- des pages entières
// pourraient apparaître vides dès qu'elles ne contiennent, côté serveur, que des
// catégories d'un autre type, ce qui arrive réellement sur le jeu de données de
// seed (catégories "Fournitures/Frais/ST/UO" mêlées aux catégories "MO"). La
// liste complète des catégories est de toute façon déjà chargée sans pagination
// ailleurs sur cette page (voir le commentaire sur `costTypes`/`categories` dans
// `resources/page.tsx`), donc appliquer recherche/tri/pagination en mémoire sur
// cette liste ne coûte aucun aller-retour réseau supplémentaire.
export function ValuationPanel(props: ValuationPanelProps) {
  const years = props.years;
  const lastYear = years.at(-1);

  // Callbacks are forwarded through this ref (safe -- only invoked from event
  // handlers, which run after the most recent commit's `useLayoutEffect` has
  // already flushed), so `columns` below doesn't need `onRateChange` (recreated
  // every render by the parent) as a dependency.
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  // Memoized (empty deps) so cell renderers keep a stable identity across
  // renders -- see `ValuationRateInput`'s comment for why. `years` is now a
  // stable-identity array computed once by the parent page (`valuationYears`
  // in `resources/page.tsx`, itself in a mount-only `useState` initializer),
  // so capturing it here at mount is equivalent to reading it fresh on every
  // render -- it never changes for the component's lifetime.
  const columns = useMemo<ColumnDef<CostCategory>[]>(
    () => [
      {
        accessorKey: "accounting_code",
        header: "Code comptable",
        meta: { sortColumn: "accounting_code" },
        cell: ({ row }) => <span className="font-medium">{row.original.accounting_code}</span>,
      },
      ...years.map(
        (year): ColumnDef<CostCategory> => ({
          id: `year-${year}`,
          header: () => <span className={year === lastYear ? "font-medium" : undefined}>{year}</span>,
          cell: ({ row }) => {
            const category = row.original;
            const key = `${category.id}:${year}`;
            return (
              <div className={year === lastYear ? "-mx-2 rounded bg-muted px-2 py-1" : undefined}>
                <ValuationRateInput
                  ariaLabel={`${category.accounting_code} ${year}`}
                  initialValue={propsRef.current.drafts[key] ?? ""}
                  onChange={(value) => propsRef.current.onRateChange(key, value)}
                />
              </div>
            );
          },
        }),
      ),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Valorisation</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="display-currency">Devise</Label>
            <select
              id="display-currency"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={props.currency}
              onChange={(event) => props.onCurrencyChange(event.target.value)}
            >
              <option value="EUR">EUR</option>
              <option value="USD">Dollar</option>
            </select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inflation-value">Inflation ({props.inflationYear})</Label>
            <div className="flex items-center gap-2">
              <Input
                id="inflation-value"
                type="number"
                min="-100"
                step="0.01"
                value={props.inflationValue}
                onChange={(event) => props.onInflationChange(event.target.value)}
                placeholder="Pourcentage"
              />
              <span className="text-sm text-muted-foreground">%</span>
            </div>
          </div>
        </div>
        <DataTable
          columns={columns}
          data={props.items}
          getRowId={(item) => String(item.id)}
          pagination={props.pagination}
          onPaginationChange={props.onPaginationChange}
          sort={props.sort}
          onSortChange={props.onSortChange}
          search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher une catégorie" }}
          emptyState="Aucune catégorie de main d'œuvre."
        />
        <div className="flex justify-end">
          <Button type="button" disabled={props.busy} onClick={props.onSave}>
            Enregistrer
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
