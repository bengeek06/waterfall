"use client";

import type { FormEventHandler } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CostCategory, CostType, ResourceNode, ResourceRole } from "@/lib/backend";

export type RolesPanelProps = {
  selectedNode: ResourceNode | null;
  items: ResourceRole[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  nodes: ResourceNode[];
  categories: CostCategory[];
  costTypes: CostType[];
  roleName: string;
  roleNodeId: string;
  roleCategoryId: string;
  actionBusy: boolean;
  categoryNames: Map<number, string | null>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onNameChange: (value: string) => void;
  onNodeChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
};

export function RolesPanel(props: RolesPanelProps) {
  const laborCategories = props.categories.filter((category) => category.is_active && props.costTypes.some((type) => type.id === category.cost_type_id && type.kind === "labor"));

  // Unlike CostTypesTable, the create form here is kept as its own `<form>` above
  // the DataTable rather than folded into a `pinnedRow`: its three fields (name,
  // node, accounting category) don't map onto the list's two display columns
  // (name, accounting category) -- there is no "node" column to anchor a pinned
  // node <select> to, since every row already belongs to the single node named in
  // the card's own heading. The node dropdown here also deliberately lets a user
  // create a role under a *different* node than the one currently displayed (it
  // additionally drives the organization-tree selection itself, see the page's
  // `onNodeChange` wiring) -- a use case a row pinned inside this node-scoped
  // table would misrepresent as "adding to the currently listed node".
  const columns: ColumnDef<ResourceRole>[] = [
    {
      accessorKey: "name",
      header: "Nom",
      meta: { sortColumn: "name" },
      cell: ({ row }) => `${row.original.name} (#${row.original.id})`,
    },
    {
      id: "category",
      // `categoryNames` (page.tsx) maps a category id to its *name*, not its
      // accounting code -- this header must match what's actually displayed.
      header: "Catégorie",
      cell: ({ row }) => <Badge variant="outline">{props.categoryNames.get(row.original.cost_category_id) ?? "?"}</Badge>,
    },
  ];

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Rôles {props.selectedNode ? `de ${props.selectedNode.name}` : ""}</CardTitle></CardHeader>
      <CardContent className="grid gap-6">
        <form onSubmit={props.onSubmit} className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2"><Label htmlFor="role-name">Nom</Label><Input id="role-name" value={props.roleName} onChange={(event) => props.onNameChange(event.target.value)} required /></div>
          <div className="grid gap-2"><Label htmlFor="role-node">Nœud</Label><select id="role-node" className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={props.roleNodeId} onChange={(event) => props.onNodeChange(event.target.value)} required><option value="">Sélectionner</option>{props.nodes.map((node) => <option key={node.id} value={node.id}>{node.code} - {node.name}</option>)}</select></div>
          <div className="grid gap-2"><Label htmlFor="role-category">Code comptable</Label><select id="role-category" className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={props.roleCategoryId} onChange={(event) => props.onCategoryChange(event.target.value)} required><option value="">Sélectionner</option>{laborCategories.map((category) => <option key={category.id} value={category.id}>{category.accounting_code} - {category.name}</option>)}</select></div>
          <Button className="sm:col-span-2 sm:w-fit" disabled={props.actionBusy} type="submit">Ajouter</Button>
        </form>
        <DataTable
          columns={columns}
          data={props.items}
          getRowId={(item) => String(item.id)}
          pagination={props.pagination}
          onPaginationChange={props.onPaginationChange}
          sort={props.sort}
          onSortChange={props.onSortChange}
          search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un rôle" }}
          isLoading={props.isLoading}
          emptyState={props.selectedNode ? "Aucun rôle pour ce nœud." : "Sélectionnez un nœud pour voir ses rôles."}
          // `DataTable` prefers `noResultsState` over `emptyState` whenever a
          // search is active. Clearing the selected node (e.g. deleting it)
          // doesn't clear the search box, so without this the "no node
          // selected" prompt above would be silently replaced by the generic
          // "no search results" message while a query is still typed in.
          noResultsState={props.selectedNode ? undefined : "Sélectionnez un nœud pour voir ses rôles."}
        />
      </CardContent>
    </Card>
  );
}
