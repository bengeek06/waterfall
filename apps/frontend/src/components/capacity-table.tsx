"use client";

import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import type { ResourceRole } from "@/lib/backend";

type CapacityDraft = { personCount: string; availableHours: string };

export type CapacityTableProps = {
  items: ResourceRole[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  drafts: Record<number, CapacityDraft>;
  actionBusy: boolean;
  nodeCodeById: Map<number, string>;
  onDraftChange: (roleId: number, draft: CapacityDraft) => void;
  onSave: (roleId: number) => void;
};

export function CapacityTable(props: CapacityTableProps) {
  function draftFor(role: ResourceRole): CapacityDraft {
    return props.drafts[role.id] ?? { personCount: "0.00", availableHours: "0.00" };
  }

  function labelFor(role: ResourceRole): string {
    const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?";
    return `${role.name} — ${nodeCode} (#${role.id})`;
  }

  const columns: ColumnDef<ResourceRole>[] = [
    {
      accessorKey: "name",
      header: "Rôle",
      meta: { sortColumn: "name" },
      cell: ({ row }) => labelFor(row.original),
    },
    {
      id: "personCount",
      header: "Nombre de personnes",
      cell: ({ row }) => {
        const role = row.original;
        const draft = draftFor(role);
        return (
          <Input
            type="number"
            min="0"
            step="0.01"
            aria-label={`Nombre de personnes pour ${labelFor(role)}`}
            value={draft.personCount}
            onChange={(event) => props.onDraftChange(role.id, { ...draft, personCount: event.target.value })}
          />
        );
      },
    },
    {
      id: "availableHours",
      header: "Heures disponibles",
      cell: ({ row }) => {
        const role = row.original;
        const draft = draftFor(role);
        return (
          <Input
            type="number"
            min="0"
            step="0.01"
            aria-label={`Heures disponibles pour ${labelFor(role)}`}
            value={draft.availableHours}
            onChange={(event) => props.onDraftChange(role.id, { ...draft, availableHours: event.target.value })}
          />
        );
      },
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => {
        const role = row.original;
        return (
          <Button size="sm" type="button" disabled={props.actionBusy} onClick={() => props.onSave(role.id)}>
            Enregistrer
          </Button>
        );
      },
    },
  ];

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Capacités</CardTitle></CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          data={props.items}
          getRowId={(role) => String(role.id)}
          pagination={props.pagination}
          onPaginationChange={props.onPaginationChange}
          sort={props.sort}
          onSortChange={props.onSortChange}
          // Server-side, this only matches ResourceRole.name -- searching by the node
          // code or id also shown in the label below (e.g. "IT" or "#42") returns
          // nothing. Matching those too would need a backend join, out of scope here.
          search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un rôle" }}
          isLoading={props.isLoading}
        />
      </CardContent>
    </Card>
  );
}
