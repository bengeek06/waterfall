"use client";

import type { ColumnDef } from "@tanstack/react-table";

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
  const years = [-4, -3, -2, -1, 0].map((offset) => new Date().getFullYear() + offset);
  const lastYear = years.at(-1);

  const columns: ColumnDef<CostCategory>[] = [
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
              <Input
                aria-label={`${category.accounting_code} ${year}`}
                type="number"
                step="0.01"
                min="0"
                value={props.drafts[key] ?? ""}
                onChange={(event) => props.onRateChange(key, event.target.value)}
                placeholder="-"
              />
            </div>
          );
        },
      }),
    ),
  ];

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
