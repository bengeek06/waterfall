"use client";

import type { FormEventHandler } from "react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
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

// A stable-identity input for the "Nom" field of one cost type's edit row.
// `columns` in `CostTypesTable` below is memoized (deps: `editingId`/`busy`/
// `labels`, not `draft`) so TanStack Table's `flexRender` keeps passing the
// *same* component type across renders while the user types -- otherwise (a
// fresh `cell` closure on every keystroke, since it closed over `draft`)
// React would unmount/remount the input after every character, dropping
// focus (same bug class found in the EPIC E8 migrations built on this table
// as their reference implementation -- #121/#123/#124/#125). Since the memo
// doesn't depend on `draft`, the value displayed while typing can't be read
// fresh from it either -- this component owns its value as local state
// instead, seeded once when the row enters edit mode (which *is* a memo
// dependency, via `editingId`, so the seed is always the value at that
// transition), reporting every keystroke upward via `onChange` for
// `draft`/"Enregistrer" to use.
function CostTypeNameField(props: { ariaLabel: string; initialValue: string; onChange: (value: string) => void }) {
  const [value, setValue] = useState(props.initialValue);
  return (
    <Input
      aria-label={props.ariaLabel}
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange(event.target.value);
      }}
    />
  );
}

export function CostTypesTable(props: CostTypesTableProps) {
  // Kept fresh on every render via `useLayoutEffect` (React forbids writing to
  // a ref during render, `react-hooks/refs`) rather than read directly, so the
  // cell renderers below -- built once per `columns` memoization, not every
  // render -- can still reach the *current* mutation callbacks at the moment
  // they're actually invoked (an event handler firing always runs after the
  // most recent commit's layout effect has already flushed, so there's no
  // staleness risk there, unlike reading the ref for a value used in the
  // render output itself -- see `CostTypeNameField` for that case).
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  // Memoized so cell renderers keep a stable identity across renders -- see
  // `CostTypeNameField`'s comment for why. Deliberately excludes `props.draft`
  // (changes per keystroke) from the dependency array; includes
  // `editingId`/`busy`/`labels` since those govern which mode each cell
  // renders in, whether an action is disabled, or the "Comportement" column's
  // lookup, and change far less often (only on explicit user actions, not per
  // keystroke -- `labels` in particular is a module-level constant in
  // `resources/page.tsx`, never recreated at all).
  const columns = useMemo<ColumnDef<CostType>[]>(
    () => [
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
            <CostTypeNameField
              ariaLabel={`Nom de ${item.code}`}
              initialValue={props.draft}
              onChange={(value) => propsRef.current.onDraftChange(value)}
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
                    <Button size="sm" type="button" disabled={props.busy} onClick={() => propsRef.current.onSave(item)}>
                      Enregistrer
                    </Button>
                    <Button size="sm" variant="outline" type="button" onClick={() => propsRef.current.onCancel()}>
                      Annuler
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="outline" type="button" onClick={() => propsRef.current.onStartEdit(item)}>
                    Modifier
                  </Button>
                )
              ) : null}
              <Button size="sm" variant="outline" type="button" disabled={props.busy} onClick={() => propsRef.current.onToggle(item)}>
                {item.is_active ? "Désactiver" : "Réactiver"}
              </Button>
            </div>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.editingId, props.busy, props.labels],
  );

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
