"use client";

import type { FormEventHandler } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { TableCell, TableRow } from "@/components/ui/table";
import type { Calendar } from "@/lib/backend";

export type WeekdayDraft = { day_type: number; hours_per_day: string };

export const WEEKDAY_ORDER: { dayType: number; label: string }[] = [
  { dayType: 2, label: "Lun" },
  { dayType: 3, label: "Mar" },
  { dayType: 4, label: "Mer" },
  { dayType: 5, label: "Jeu" },
  { dayType: 6, label: "Ven" },
  { dayType: 7, label: "Sam" },
  { dayType: 1, label: "Dim" },
];

export function defaultWeekdays(): WeekdayDraft[] {
  return WEEKDAY_ORDER.map(({ dayType }) => ({
    day_type: dayType,
    hours_per_day: dayType >= 2 && dayType <= 6 ? "7.00" : "0.00",
  }));
}

export type CalendarDraft = { code: string; name: string; weeksPerYear: string; weekdays: WeekdayDraft[] };

export type CalendarsTableProps = {
  items: Calendar[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  code: string;
  name: string;
  weeksPerYear: string;
  weekdays: WeekdayDraft[];
  draft: CalendarDraft;
  editingId: number | null;
  busy: boolean;
  calendarIdsInUseByActiveRoles: Set<number>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onCodeChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onWeeksPerYearChange: (value: string) => void;
  onWeekdayChange: (dayType: number, value: string) => void;
  onStartEdit: (item: Calendar) => void;
  onDraftChange: (field: "code" | "name" | "weeksPerYear", value: string) => void;
  onDraftWeekdayChange: (dayType: number, value: string) => void;
  onSave: (item: Calendar) => void;
  onCancel: () => void;
  onToggle: (item: Calendar) => void;
  onSetDefault: (item: Calendar) => void;
};

function renderCodeCell(item: Calendar, props: CalendarsTableProps) {
  if (props.editingId === item.id) {
    return (
      <Input
        aria-label={`Code de ${item.code}`}
        value={props.draft.code}
        onChange={(event) => props.onDraftChange("code", event.target.value)}
      />
    );
  }
  return (
    <span className="font-medium flex items-center gap-2">
      {item.code}
      {item.is_default ? <Badge variant="secondary">Par défaut</Badge> : null}
    </span>
  );
}

function renderNameCell(item: Calendar, props: CalendarsTableProps) {
  if (props.editingId === item.id) {
    return (
      <Input
        aria-label={`Nom de ${item.code}`}
        value={props.draft.name}
        onChange={(event) => props.onDraftChange("name", event.target.value)}
      />
    );
  }
  return item.name;
}

function renderWeeksPerYearCell(item: Calendar, props: CalendarsTableProps) {
  if (props.editingId === item.id) {
    return (
      <Input
        aria-label={`Semaines par an de ${item.code}`}
        type="number"
        min="1"
        max="53"
        value={props.draft.weeksPerYear}
        onChange={(event) => props.onDraftChange("weeksPerYear", event.target.value)}
      />
    );
  }
  return item.weeks_per_year;
}

function renderWeekdayCell(item: Calendar, dayType: number, label: string, props: CalendarsTableProps) {
  if (props.editingId === item.id) {
    const value = props.draft.weekdays.find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0.00";
    return (
      <Input
        aria-label={`Heures du ${label} de ${item.code}`}
        type="number"
        min="0"
        max="24"
        step="0.25"
        className="w-16"
        value={value}
        onChange={(event) => props.onDraftWeekdayChange(dayType, event.target.value)}
      />
    );
  }
  return (item.weekdays ?? []).find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0";
}

// The three disable rules and their accompanying hint text, kept together since they
// share the same inputs: a default calendar and a calendar assigned to an active
// role can never be deactivated, and only an active calendar can become the default.
// Independent conditions -- a calendar can be both the default and assigned to an
// active role at once, in which case both hints show together.
function getCalendarHints(item: Calendar, inUseByActiveRole: boolean): string[] {
  const hints: string[] = [];
  if (inUseByActiveRole) hints.push("Assigné à un rôle actif");
  if (!item.is_default && !item.is_active) hints.push("Seul un calendrier actif peut être défini par défaut");
  if (item.is_default) hints.push(item.is_active ? "Calendrier par défaut" : "Calendrier par défaut (inactif)");
  return hints;
}

function renderActionsCell(item: Calendar, props: CalendarsTableProps) {
  const editing = props.editingId === item.id;
  const inUseByActiveRole = item.is_active && props.calendarIdsInUseByActiveRoles.has(item.id);
  const toggleDisabled = props.busy || inUseByActiveRole || (item.is_active && item.is_default);
  const hints = getCalendarHints(item, inUseByActiveRole);
  return (
    <div className="flex gap-2">
      {editing ? (
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
      )}
      <Button size="sm" variant="outline" type="button" disabled={toggleDisabled} onClick={() => props.onToggle(item)}>
        {item.is_active ? "Désactiver" : "Réactiver"}
      </Button>
      {!item.is_default ? (
        <Button size="sm" variant="outline" type="button" disabled={props.busy || !item.is_active} onClick={() => props.onSetDefault(item)}>
          Définir par défaut
        </Button>
      ) : null}
      {hints.map((hint) => (
        <span key={hint} className="text-xs text-muted-foreground">
          {hint}
        </span>
      ))}
    </div>
  );
}

function buildColumns(props: CalendarsTableProps): ColumnDef<Calendar>[] {
  const weekdayColumns: ColumnDef<Calendar>[] = WEEKDAY_ORDER.map(({ dayType, label }) => ({
    id: `weekday-${dayType}`,
    header: label,
    cell: ({ row }) => renderWeekdayCell(row.original, dayType, label, props),
  }));

  return [
    {
      accessorKey: "code",
      header: "Code",
      meta: { sortColumn: "code" },
      cell: ({ row }) => renderCodeCell(row.original, props),
    },
    {
      accessorKey: "name",
      header: "Nom",
      meta: { sortColumn: "name" },
      cell: ({ row }) => renderNameCell(row.original, props),
    },
    {
      id: "weeksPerYear",
      header: "Semaines/an",
      cell: ({ row }) => renderWeeksPerYearCell(row.original, props),
    },
    ...weekdayColumns,
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => renderActionsCell(row.original, props),
    },
  ];
}

function renderPinnedRow(props: CalendarsTableProps) {
  return (
    <TableRow>
      <TableCell>
        <Input aria-label="Code du nouveau calendrier" value={props.code} onChange={(event) => props.onCodeChange(event.target.value)} required />
      </TableCell>
      <TableCell>
        <Input aria-label="Nom du nouveau calendrier" value={props.name} onChange={(event) => props.onNameChange(event.target.value)} required />
      </TableCell>
      <TableCell>
        <Input
          aria-label="Semaines par an du nouveau calendrier"
          type="number"
          min="1"
          max="53"
          value={props.weeksPerYear}
          onChange={(event) => props.onWeeksPerYearChange(event.target.value)}
          required
        />
      </TableCell>
      {WEEKDAY_ORDER.map(({ dayType, label }) => {
        const value = props.weekdays.find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0.00";
        return (
          <TableCell key={dayType}>
            <Input
              aria-label={`Heures du ${label} pour le nouveau calendrier`}
              type="number"
              min="0"
              max="24"
              step="0.25"
              className="w-16"
              value={value}
              onChange={(event) => props.onWeekdayChange(dayType, event.target.value)}
            />
          </TableCell>
        );
      })}
      <TableCell>
        <Button size="sm" disabled={props.busy} type="submit">
          Ajouter
        </Button>
      </TableCell>
    </TableRow>
  );
}

export function CalendarsTable(props: CalendarsTableProps) {
  const columns = buildColumns(props);

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Calendriers de travail</CardTitle></CardHeader>
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
            search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un calendrier" }}
            pinnedRow={renderPinnedRow(props)}
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
