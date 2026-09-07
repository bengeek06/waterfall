"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import type { Calendar, ResourceRole } from "@/lib/backend";

export type RoleCalendarsTableProps = {
  roles: ResourceRole[];
  // Always the full, unpaginated, active-plus-currently-assigned-inactive calendar
  // reference list -- never sourced from a paginated calendars fetch, regardless of
  // this table's own roles pagination state, so every active calendar (and a role's
  // own inactive one) always shows up in the per-row dropdown.
  calendars: Calendar[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  drafts: Record<number, string>;
  actionBusy: boolean;
  nodeCodeById: Map<number, string>;
  onDraftChange: (roleId: number, calendarId: string) => void;
  onSave: (roleId: number) => void;
};

// Mirrors the backend's `_has_any_working_day` (calendar_schedule.py): a calendar
// only has working capacity if at least one of its weekdays has hours_per_day > 0.
// A calendar with no configured weekday (or every weekday at 0) has no capacity,
// even when flagged `is_default` -- the scheduling cascade falls through to the
// implicit wall-clock (24h/24, 7j/7) fallback in that case instead of using it.
function hasWorkingDay(calendar: Calendar): boolean {
  return (calendar.weekdays ?? []).some((weekday) => Number(weekday.hours_per_day) > 0);
}

function getDefaultOptionLabel(defaultCalendar: Calendar | undefined): string {
  if (!defaultCalendar) return "Aucun calendrier par défaut défini";
  if (hasWorkingDay(defaultCalendar)) return `Calendrier par défaut (${defaultCalendar.code} - ${defaultCalendar.name})`;
  return "Calendrier implicite (24h/24, 7j/7) — le calendrier par défaut configuré n'a aucun jour travaillé";
}

// A stable-identity <select> for one role's calendar assignment. `columns`
// below is memoized so TanStack Table's `flexRender` keeps passing the *same*
// component type across renders (see the comment on `columns`), but that
// alone isn't enough for a value the user is actively picking: the value this
// component should display can't be read fresh from `props.drafts` at render
// time the way `columns`'s own closures read other, less time-sensitive props
// (that ref lags one render behind during the very render pass that just
// received new props -- verified empirically before choosing this design, see
// `CapacityFieldInput` in capacity-table.tsx for the same fix applied there).
// Instead this component owns its selected value as local state, seeded once
// from the draft when the role first appears, and reports every selection
// upward via `onChange` for `props.drafts`/"Enregistrer" to use.
function RoleCalendarSelect(props: {
  role: ResourceRole;
  initialValue: string;
  ariaLabel: string;
  disabled: boolean;
  defaultOptionLabel: string;
  assignedInactiveCalendar: Calendar | undefined;
  activeCalendars: Calendar[];
  onChange: (roleId: number, value: string) => void;
}) {
  const [value, setValue] = useState(props.initialValue);
  return (
    <select
      aria-label={props.ariaLabel}
      className="h-8 rounded-md border border-input bg-background px-2 text-sm"
      value={value}
      disabled={props.disabled}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange(props.role.id, event.target.value);
      }}
    >
      <option value="">{props.defaultOptionLabel}</option>
      {props.assignedInactiveCalendar ? (
        <option value={props.assignedInactiveCalendar.id}>
          {props.assignedInactiveCalendar.code} - {props.assignedInactiveCalendar.name} (inactif)
        </option>
      ) : null}
      {props.activeCalendars.map((calendar) => (
        <option key={calendar.id} value={calendar.id}>
          {calendar.code} - {calendar.name}
        </option>
      ))}
    </select>
  );
}

export function RoleCalendarsTable(props: RoleCalendarsTableProps) {
  // See `CapacityFieldInput`'s comment (capacity-table.tsx) and the comment on
  // `columns` below for why callbacks are read through this ref instead of
  // being closed over directly: it keeps `columns`'s identity stable (safe
  // here because callbacks are only invoked from event handlers, which run
  // after the most recent commit's `useLayoutEffect` has already flushed).
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  // Memoized (not a plain `.filter()`/derivation on every render): both values
  // are dependencies of the memoized `columns` below, and a fresh array/string
  // identity every render -- even one with the same *contents* -- would defeat
  // that memoization just as surely as depending on `props.drafts` directly.
  const activeCalendars = useMemo(
    () => props.calendars.filter((calendar) => calendar.is_active),
    [props.calendars],
  );
  const defaultOptionLabel = useMemo(
    () => getDefaultOptionLabel(activeCalendars.find((calendar) => calendar.is_default)),
    [activeCalendars],
  );

  function labelFor(role: ResourceRole): string {
    const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?";
    return `${role.name} — ${nodeCode} (#${role.id})`;
  }

  function assignedInactiveCalendarFor(role: ResourceRole): Calendar | undefined {
    if (role.calendar_id == null || activeCalendars.some((calendar) => calendar.id === role.calendar_id)) return undefined;
    return props.calendars.find((calendar) => calendar.id === role.calendar_id);
  }

  // `columns` is memoized so its cell renderers (in particular
  // `RoleCalendarSelect`) keep a stable identity across renders -- otherwise,
  // since `flexRender` passes each cell renderer to React as a component
  // *type*, rebuilding this array inline on every render (as this component
  // used to) gives every cell a new identity whenever `drafts` changes, which
  // happens on every selection; React then unmounts the previous `<select>`
  // DOM node and mounts a new one, dropping keyboard focus after every pick.
  //
  // Depends on `activeCalendars`/`defaultOptionLabel` (derived from
  // `props.calendars`, which changes rarely, not per-selection) so the
  // dropdown's own option list stays correct; deliberately does not depend on
  // `props.drafts` (per-selection) or the callback props (unstable identity
  // from the parent on every render) -- see `propsRef`'s comment above.
  const columns = useMemo<ColumnDef<ResourceRole>[]>(
    () => [
      {
        id: "role",
        header: "Rôle",
        meta: { sortColumn: "name" },
        cell: ({ row }) => labelFor(row.original),
      },
      {
        id: "calendar",
        header: "Calendrier",
        cell: ({ row }) => {
          const role = row.original;
          // Reads the *live* drafts via `propsRef`, not the `draftFor` closed over
          // when this memoized cell function was created: `initialValue` only
          // seeds `RoleCalendarSelect`'s local state once, at mount, but a row
          // remounts whenever its role leaves and re-enters the current page
          // (pagination/sort/search) -- reading the stale snapshot from
          // `columns`'s own creation-time render would revert an unsaved draft
          // made in the meantime back to whatever it was when `columns` was last
          // rebuilt.
          const liveDrafts = propsRef.current.drafts;
          const initialValue = liveDrafts[role.id] ?? (role.calendar_id ? String(role.calendar_id) : "");
          return (
            <RoleCalendarSelect
              role={role}
              initialValue={initialValue}
              ariaLabel={`Calendrier de ${labelFor(role)}`}
              disabled={propsRef.current.actionBusy}
              defaultOptionLabel={defaultOptionLabel}
              assignedInactiveCalendar={assignedInactiveCalendarFor(role)}
              activeCalendars={activeCalendars}
              onChange={(roleId, value) => propsRef.current.onDraftChange(roleId, value)}
            />
          );
        },
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => (
          <Button
            size="sm"
            type="button"
            disabled={propsRef.current.actionBusy}
            onClick={() => propsRef.current.onSave(row.original.id)}
          >
            Enregistrer
          </Button>
        ),
      },
    ],
    // Depends on `props.nodeCodeById` too (not just the calendar reference
    // list): unlike `props.drafts`, it changes only when the organization
    // tree's nodes change (e.g. a node rename on the "Nœud" tab) -- a rare
    // event, not a per-keystroke one -- so including it here doesn't reproduce
    // the focus-loss bug `columns`'s memoization exists to prevent, and it must
    // be included: `labelFor`'s displayed node code would otherwise go stale
    // after a rename, since nothing else in this array would change to force
    // `columns` (and the `labelFor` closure it captured) to rebuild.
    // `assignedInactiveCalendarFor` is recreated every render but only used
    // inside the memoized cell closures for a lookup that doesn't need to be
    // render-fresh. The calendar select's initial value is read from
    // `propsRef.current.drafts` directly (see that cell's own comment), not
    // from a closed-over helper.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeCalendars, defaultOptionLabel, props.nodeCodeById],
  );

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Calendriers des rôles</CardTitle></CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          data={props.roles}
          getRowId={(role) => String(role.id)}
          pagination={props.pagination}
          onPaginationChange={props.onPaginationChange}
          sort={props.sort}
          onSortChange={props.onSortChange}
          search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un rôle" }}
          isLoading={props.isLoading}
        />
      </CardContent>
    </Card>
  );
}
