"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import type { ResourceRole } from "@/lib/backend";

type CapacityDraft = { personCount: string; availableHours: string };
type CapacityField = keyof CapacityDraft;

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

const defaultDraft: CapacityDraft = { personCount: "0.00", availableHours: "0.00" };

// A stable-identity input for one capacity field of one role. `columns` below
// is memoized so TanStack Table's `flexRender` keeps passing the *same*
// component type across renders (see the comment on `columns`), but that
// alone isn't enough for a field the user is actively typing into: the value
// this component should display can't be read fresh from `props.drafts` at
// render time (see `propsRef`'s comment -- that ref lags one render behind
// during the very render pass that just received new props). Instead this
// component owns its displayed value as local state, seeded once from the
// draft when the role first appears (a role only (re)mounts this component
// when it enters/re-enters view, e.g. on the initial load or a page change,
// at which point there's no unsynced ref to worry about), and reports every
// keystroke upward via `onChange` for `props.drafts`/"Enregistrer" to use.
function CapacityFieldInput(props: {
  role: ResourceRole;
  field: CapacityField;
  initialValue: string;
  ariaLabel: string;
  onChange: (roleId: number, field: CapacityField, value: string) => void;
}) {
  const [value, setValue] = useState(props.initialValue);
  return (
    <Input
      type="number"
      min="0"
      step="0.01"
      aria-label={props.ariaLabel}
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange(props.role.id, props.field, event.target.value);
      }}
    />
  );
}

export function CapacityTable(props: CapacityTableProps) {
  // `columns` below is memoized so its cell renderers keep a stable identity
  // across renders. TanStack Table's `flexRender` passes each cell renderer to
  // React as a component *type*, and an inline arrow function rebuilt on every
  // render (e.g. because it closes over `props.drafts`, which changes on every
  // keystroke) gets a new identity each time -- React then treats it as a
  // different component and unmounts the previous DOM node, which drops input
  // focus after every character typed.
  //
  // Callback props (`onDraftChange`/`onSave`) are read through `propsRef`
  // rather than closed over directly, so `columns`'s own identity doesn't
  // depend on them (they're recreated on every parent render). This is safe
  // specifically because they're only ever invoked from event handlers, which
  // run strictly after the most recent commit's `useLayoutEffect` has already
  // flushed -- unlike a value read straight into the render output (see
  // `CapacityFieldInput` above), a callback invoked later doesn't care that
  // this ref lags one render behind *during* a render pass.
  const propsRef = useRef(props);
  // React forbids writing to a ref during render (`react-hooks/refs`), so the
  // sync happens in `useLayoutEffect` rather than the render body -- and
  // `useLayoutEffect` rather than `useEffect`, so it runs synchronously in the
  // commit phase before the browser can paint or process the next keystroke.
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  function draftFor(role: ResourceRole): CapacityDraft {
    return props.drafts[role.id] ?? defaultDraft;
  }

  function labelFor(role: ResourceRole): string {
    const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?";
    return `${role.name} — ${nodeCode} (#${role.id})`;
  }

  function handleFieldChange(roleId: number, field: CapacityField, value: string) {
    const current = propsRef.current.drafts[roleId] ?? defaultDraft;
    propsRef.current.onDraftChange(roleId, { ...current, [field]: value });
  }

  const columns = useMemo<ColumnDef<ResourceRole>[]>(
    () => [
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
          return (
            <CapacityFieldInput
              role={role}
              field="personCount"
              initialValue={draftFor(role).personCount}
              ariaLabel={`Nombre de personnes pour ${labelFor(role)}`}
              onChange={handleFieldChange}
            />
          );
        },
      },
      {
        id: "availableHours",
        header: "Heures disponibles",
        cell: ({ row }) => {
          const role = row.original;
          return (
            <CapacityFieldInput
              role={role}
              field="availableHours"
              initialValue={draftFor(role).availableHours}
              ariaLabel={`Heures disponibles pour ${labelFor(role)}`}
              onChange={handleFieldChange}
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
            <Button
              size="sm"
              type="button"
              disabled={propsRef.current.actionBusy}
              onClick={() => propsRef.current.onSave(role.id)}
            >
              Enregistrer
            </Button>
          );
        },
      },
    ],
    // Intentionally empty: see the comment above `propsRef`. `labelFor`,
    // `draftFor` and `handleFieldChange` are recreated every render but are
    // only used inside the memoized cell closures below as the *initial* seed
    // for `CapacityFieldInput` (only read once, at mount, per role) or as
    // stable-enough-for-event-handlers indirection through `propsRef` -- none
    // of them need to be dependencies for `columns` itself to stay correct.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

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
