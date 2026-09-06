"use client";

import type { FormEventHandler } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { TableCell, TableRow } from "@/components/ui/table";
import type { CostType } from "@/lib/backend";

export type CostTypesTableProps = {
  items: CostType[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  code: string;
  name: string;
  kind: CostType["kind"];
  draft: string;
  editingId: number | null;
  busy: boolean;
  labels: Record<CostType["kind"], string>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onCodeChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onKindChange: (value: CostType["kind"]) => void;
  onStartEdit: (item: CostType) => void;
  onDraftChange: (value: string) => void;
  onSave: (item: CostType) => void;
  onCancel: () => void;
  onToggle: (item: CostType) => void;
};

export function CostTypesTable(props: CostTypesTableProps) {
  const columns: ColumnDef<CostType>[] = [
    {
      accessorKey: "code",
      header: "Code",
      meta: { sortColumn: "code" },
      cell: ({ row }) => <span className="font-medium">{row.original.code}</span>,
    },
    {
      accessorKey: "name",
      header: "Nom",
      meta: { sortColumn: "name" },
      cell: ({ row }) => {
        const item = row.original;
        return props.editingId === item.id ? (
          <Input
            aria-label={`Nom de ${item.code}`}
            value={props.draft}
            onChange={(event) => props.onDraftChange(event.target.value)}
          />
        ) : (
          item.name
        );
      },
    },
    {
      id: "kind",
      header: "Comportement",
      cell: ({ row }) => props.labels[row.original.kind],
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
        <Input
          aria-label="Code du nouveau type"
          value={props.code}
          onChange={(event) => props.onCodeChange(event.target.value)}
          required
        />
      </TableCell>
      <TableCell>
        <Input
          aria-label="Nom du nouveau type"
          value={props.name}
          onChange={(event) => props.onNameChange(event.target.value)}
          required
        />
      </TableCell>
      <TableCell>
        <select
          aria-label="Comportement du nouveau type"
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm"
          value={props.kind}
          onChange={(event) => props.onKindChange(event.target.value as CostType["kind"])}
        >
          <option value="labor">{props.labels.labor}</option>
          <option value="supply">{props.labels.supply}</option>
          <option value="other">{props.labels.other}</option>
        </select>
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
        <CardTitle>Types de coût</CardTitle>
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
            search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un type de coût" }}
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
