"use client";

import type { FormEventHandler } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { TableCell, TableRow } from "@/components/ui/table";
import type { CostCategory, CostType } from "@/lib/backend";

export type CostCategoriesTableProps = {
  items: CostCategory[];
  types: CostType[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  typeId: string;
  accountingCode: string;
  categoryCode: string;
  name: string;
  draft: { code: string; name: string; accountingCode: string };
  editingId: number | null;
  busy: boolean;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onTypeChange: (value: string) => void;
  onAccountingCodeChange: (value: string) => void;
  onCategoryCodeChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onStartEdit: (item: CostCategory) => void;
  onDraftChange: (field: "code" | "name" | "accountingCode", value: string) => void;
  onSave: (item: CostCategory) => void;
  onCancel: () => void;
  onToggle: (item: CostCategory) => void;
};

export function CostCategoriesTable(props: CostCategoriesTableProps) {
  const columns: ColumnDef<CostCategory>[] = [
    {
      id: "type",
      header: "Type",
      cell: ({ row }) => props.types.find((type) => type.id === row.original.cost_type_id)?.name ?? "?",
    },
    {
      accessorKey: "accounting_code",
      header: "Code comptable",
      meta: { sortColumn: "accounting_code" },
      cell: ({ row }) => {
        const item = row.original;
        return props.editingId === item.id ? (
          <Input
            aria-label={`Code comptable de ${item.accounting_code}`}
            value={props.draft.code}
            onChange={(event) => props.onDraftChange("code", event.target.value)}
          />
        ) : (
          <span className="font-medium">{item.accounting_code}</span>
        );
      },
    },
    {
      accessorKey: "category_code",
      header: "Catégorie comptable",
      meta: { sortColumn: "category_code" },
      cell: ({ row }) => {
        const item = row.original;
        return props.editingId === item.id ? (
          <Input
            aria-label={`Catégorie comptable de ${item.accounting_code}`}
            value={props.draft.accountingCode}
            onChange={(event) => props.onDraftChange("accountingCode", event.target.value)}
          />
        ) : (
          (item.category_code ?? "Sans catégorie")
        );
      },
    },
    {
      accessorKey: "name",
      header: "Nom",
      meta: { sortColumn: "name" },
      cell: ({ row }) => {
        const item = row.original;
        return props.editingId === item.id ? (
          <Input
            aria-label={`Nom de ${item.accounting_code}`}
            value={props.draft.name}
            onChange={(event) => props.onDraftChange("name", event.target.value)}
          />
        ) : (
          item.name
        );
      },
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => {
        const item = row.original;
        const editing = props.editingId === item.id;
        return (
          <div className="flex justify-end gap-2">
            {item.is_active ? (
              editing ? (
                <>
                  <Button size="sm" type="button" disabled={props.busy} onClick={() => props.onSave(item)}>
                    Enregistrer
                  </Button>
                  <Button size="sm" variant="outline" type="button" onClick={props.onCancel}>
                    Annuler
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="outline" type="button" onClick={() => props.onStartEdit(item)}>
                  Modifier
                </Button>
              )
            ) : null}
            <Button size="sm" variant="outline" type="button" disabled={props.busy} onClick={() => props.onToggle(item)}>
              {item.is_active ? "Désactiver" : "Réactiver"}
            </Button>
          </div>
        );
      },
    },
  ];

  const pinnedRow = (
    <TableRow>
      <TableCell>
        <select
          aria-label="Type de la nouvelle catégorie"
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm"
          value={props.typeId}
          onChange={(event) => props.onTypeChange(event.target.value)}
          required
        >
          <option value="">Sélectionner</option>
          {props.types
            .filter((type) => type.is_active)
            .map((type) => (
              <option key={type.id} value={type.id}>
                {type.code} - {type.name}
              </option>
            ))}
        </select>
      </TableCell>
      <TableCell>
        <Input
          aria-label="Code comptable de la nouvelle catégorie"
          value={props.accountingCode}
          onChange={(event) => props.onAccountingCodeChange(event.target.value)}
          required
        />
      </TableCell>
      <TableCell>
        <Input
          aria-label="Catégorie comptable de la nouvelle catégorie"
          value={props.categoryCode}
          onChange={(event) => props.onCategoryCodeChange(event.target.value)}
        />
      </TableCell>
      <TableCell>
        <Input
          aria-label="Nom de la nouvelle catégorie"
          value={props.name}
          onChange={(event) => props.onNameChange(event.target.value)}
          required
        />
      </TableCell>
      <TableCell className="text-right">
        <Button size="sm" disabled={props.busy} type="submit">
          Ajouter
        </Button>
      </TableCell>
    </TableRow>
  );

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Catégories de coût</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={props.onSubmit}>
          <DataTable
            columns={columns}
            data={props.items}
            getRowId={(item) => String(item.id)}
            pagination={props.pagination}
            onPaginationChange={props.onPaginationChange}
            sort={props.sort}
            onSortChange={props.onSortChange}
            search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher une catégorie de coût" }}
            pinnedRow={pinnedRow}
            getRowClassName={(item) => (item.is_active ? undefined : "opacity-55")}
            isEditing={props.editingId !== null}
            editingReason="Terminez l'édition en cours pour changer de page ou filtrer."
            isLoading={props.isLoading}
          />
        </form>
      </CardContent>
    </Card>
  );
}
