"use client";

import type { FormEventHandler } from "react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
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

// A stable-identity input for one editable field of one calendar's edit row.
// `columns` in `CalendarsTable` below is memoized (deps: `editingId`/`busy`/
// `calendarIdsInUseByActiveRoles`, not `draft`) so TanStack Table's
// `flexRender` keeps passing the *same* component type across renders while
// the user types -- otherwise (a fresh `cell` closure on every keystroke,
// since it closed over `draft`) React would unmount/remount the input after
// every character, dropping focus (same bug class found in the parallel EPIC
// E8 migrations #123/#124). Since the memo doesn't depend on `draft`, the
// value displayed while typing can't be read fresh from it either -- this
// component owns its value as local state instead, seeded once when the row
// enters edit mode (which *is* a memo dependency, via `editingId`, so the seed
// is always the value at that transition), reporting every keystroke upward
// via `onChange` for `draft`/"Enregistrer" to use.
function CalendarEditableField(props: {
  ariaLabel: string;
  type?: string;
  min?: string;
  max?: string;
  step?: string;
  className?: string;
  initialValue: string;
  onChange: (value: string) => void;
}) {
  const [value, setValue] = useState(props.initialValue);
  return (
    <Input
      aria-label={props.ariaLabel}
      type={props.type}
      min={props.min}
      max={props.max}
      step={props.step}
      className={props.className}
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange(event.target.value);
      }}
    />
  );
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
  // Kept fresh on every render via `useLayoutEffect` (React forbids writing to
  // a ref during render, `react-hooks/refs`) rather than read directly, so the
  // cell renderers below -- built once per `columns` memoization, not every
  // render -- can still reach the *current* mutation callbacks at the moment
  // they're actually invoked (an event handler firing always runs after the
  // most recent commit's layout effect has already flushed, so there's no
  // staleness risk there, unlike reading the ref for a value used in the
  // render output itself -- see `CalendarEditableField` for that case).
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  function renderCodeCell(item: Calendar) {
    if (props.editingId === item.id) {
      return (
        <CalendarEditableField
          ariaLabel={`Code de ${item.code}`}
          initialValue={props.draft.code}
          onChange={(value) => propsRef.current.onDraftChange("code", value)}
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

  function renderNameCell(item: Calendar) {
    if (props.editingId === item.id) {
      return (
        <CalendarEditableField
          ariaLabel={`Nom de ${item.code}`}
          initialValue={props.draft.name}
          onChange={(value) => propsRef.current.onDraftChange("name", value)}
        />
      );
    }
    return item.name;
  }

  function renderWeeksPerYearCell(item: Calendar) {
    if (props.editingId === item.id) {
      return (
        <CalendarEditableField
          ariaLabel={`Semaines par an de ${item.code}`}
          type="number"
          min="1"
          max="53"
          initialValue={props.draft.weeksPerYear}
          onChange={(value) => propsRef.current.onDraftChange("weeksPerYear", value)}
        />
      );
    }
    return item.weeks_per_year;
  }

  function renderWeekdayCell(item: Calendar, dayType: number, label: string) {
    if (props.editingId === item.id) {
      const value = props.draft.weekdays.find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0.00";
      return (
        <CalendarEditableField
          ariaLabel={`Heures du ${label} de ${item.code}`}
          type="number"
          min="0"
          max="24"
          step="0.25"
          className="w-16"
          initialValue={value}
          onChange={(next) => propsRef.current.onDraftWeekdayChange(dayType, next)}
        />
      );
    }
    return (item.weekdays ?? []).find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0";
  }

  function renderActionsCell(item: Calendar) {
    const editing = props.editingId === item.id;
    const inUseByActiveRole = item.is_active && props.calendarIdsInUseByActiveRoles.has(item.id);
    const toggleDisabled = props.busy || inUseByActiveRole || (item.is_active && item.is_default);
    const hints = getCalendarHints(item, inUseByActiveRole);
    return (
      <div className="flex gap-2">
        {editing ? (
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
        )}
        <Button size="sm" variant="outline" type="button" disabled={toggleDisabled} onClick={() => propsRef.current.onToggle(item)}>
          {item.is_active ? "Désactiver" : "Réactiver"}
        </Button>
        {!item.is_default ? (
          <Button size="sm" variant="outline" type="button" disabled={props.busy || !item.is_active} onClick={() => propsRef.current.onSetDefault(item)}>
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

  // Memoized so cell renderers keep a stable identity across renders -- see
  // `CalendarEditableField`'s comment for why (otherwise every keystroke while
  // editing a row remounts that field's `<Input>`, dropping focus).
  // Deliberately excludes `props.draft` (changes per keystroke) from the
  // dependency array; includes `editingId`/`busy`/`calendarIdsInUseByActiveRoles`
  // since those govern which mode each cell renders in or whether an action is
  // disabled, and change far less often (only on explicit user actions, not
  // per keystroke). The render functions above are recreated every render (so
  // they always close over the current `props` for these dependency-tracked
  // reads) but are only actually *called* from within this memo's cells, whose
  // own identity is what matters for TanStack/React -- see the comment on
  // `propsRef` for why the callbacks they invoke stay fresh regardless.
  const columns = useMemo<ColumnDef<Calendar>[]>(
    () => {
      const weekdayColumns: ColumnDef<Calendar>[] = WEEKDAY_ORDER.map(({ dayType, label }) => ({
        id: `weekday-${dayType}`,
        header: label,
        cell: ({ row }) => renderWeekdayCell(row.original, dayType, label),
      }));

      return [
        {
          accessorKey: "code",
          header: "Code",
          meta: { sortColumn: "code" },
          cell: ({ row }) => renderCodeCell(row.original),
        },
        {
          accessorKey: "name",
          header: "Nom",
          meta: { sortColumn: "name" },
          cell: ({ row }) => renderNameCell(row.original),
        },
        {
          id: "weeksPerYear",
          header: "Semaines/an",
          cell: ({ row }) => renderWeeksPerYearCell(row.original),
        },
        ...weekdayColumns,
        {
          id: "actions",
          header: "Actions",
          cell: ({ row }) => renderActionsCell(row.original),
        },
      ];
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.editingId, props.busy, props.calendarIdsInUseByActiveRoles],
  );

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
