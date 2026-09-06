"use client";

import type { ColumnDef } from "@tanstack/react-table";

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

export function RoleCalendarsTable(props: RoleCalendarsTableProps) {
  const activeCalendars = props.calendars.filter((calendar) => calendar.is_active);
  const defaultCalendar = activeCalendars.find((calendar) => calendar.is_default);
  const defaultOptionLabel = getDefaultOptionLabel(defaultCalendar);

  const columns: ColumnDef<ResourceRole>[] = [
    {
      id: "role",
      header: "Rôle",
      meta: { sortColumn: "name" },
      cell: ({ row }) => {
        const role = row.original;
        const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?";
        return `${role.name} — ${nodeCode} (#${role.id})`;
      },
    },
    {
      id: "calendar",
      header: "Calendrier",
      cell: ({ row }) => {
        const role = row.original;
        const draft = props.drafts[role.id] ?? (role.calendar_id ? String(role.calendar_id) : "");
        const assignedInactiveCalendar = role.calendar_id != null && !activeCalendars.some((calendar) => calendar.id === role.calendar_id)
          ? props.calendars.find((calendar) => calendar.id === role.calendar_id)
          : undefined;
        const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?";
        const roleLabel = `${role.name} — ${nodeCode} (#${role.id})`;
        return (
          <select
            aria-label={`Calendrier de ${roleLabel}`}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            value={draft}
            disabled={props.actionBusy}
            onChange={(event) => props.onDraftChange(role.id, event.target.value)}
          >
            <option value="">{defaultOptionLabel}</option>
            {assignedInactiveCalendar ? (
              <option value={assignedInactiveCalendar.id}>{assignedInactiveCalendar.code} - {assignedInactiveCalendar.name} (inactif)</option>
            ) : null}
            {activeCalendars.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.code} - {calendar.name}</option>)}
          </select>
        );
      },
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <Button size="sm" type="button" disabled={props.actionBusy} onClick={() => props.onSave(row.original.id)}>
          Enregistrer
        </Button>
      ),
    },
  ];

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
