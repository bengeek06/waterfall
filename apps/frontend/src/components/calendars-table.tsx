"use client";

import type { FormEventHandler } from "react";
import { forwardRef, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, STICKY_RIGHT_CELL_CLASSNAME, type DataTablePaginationState } from "@/components/ui/data-table";
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
// Wrapped in `forwardRef` (the one exception to this codebase's usual "no
// forwardRef" style) so callers can hold a live `HTMLInputElement` for this
// field, to call native validation (`checkValidity`/`reportValidity`) on it,
// e.g. from the "Enregistrer" handler below, which can't rely on the shared
// `<form>`'s submit-time validation (see that handler's comment for why).
// `forwardRef` is required here, not the plain React 19 ref-as-prop shortcut:
// `eslint-plugin-react-hooks`'s static analysis treats any prop literally
// named `ref` on a plain (non-`forwardRef`) component as a ref value and
// flags every other prop read alongside it in the same JSX element as
// "accessed during render" -- `forwardRef` is the pattern its ref-safety
// analysis actually recognizes.
const CalendarEditableField = forwardRef<
  HTMLInputElement,
  {
    ariaLabel: string;
    type?: string;
    min?: string;
    max?: string;
    step?: string;
    className?: string;
    initialValue: string;
    required?: boolean;
    onChange: (value: string) => void;
  }
>(function CalendarEditableField(props, ref) {
  const [value, setValue] = useState(props.initialValue);
  return (
    <Input
      ref={ref}
      aria-label={props.ariaLabel}
      type={props.type}
      min={props.min}
      max={props.max}
      step={props.step}
      className={props.className}
      value={value}
      required={props.required}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange(event.target.value);
      }}
    />
  );
});

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
              step="0.01"
              className="w-16"
              value={value}
              onChange={(event) => props.onWeekdayChange(dayType, event.target.value)}
            />
          </TableCell>
        );
      })}
      <TableCell className={STICKY_RIGHT_CELL_CLASSNAME}>
        <Button size="sm" disabled={props.busy || props.editingId !== null} type="submit">
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

  // Live DOM refs for the constrained fields (`min`/`max`/`step`, now also
  // `required` -- an empty `<input type="number" min="1">` passes
  // `checkValidity()` on its own, HTML5 only rejects blank via `required`, not
  // `min`/`max`, so without it clearing the field and clicking "Enregistrer"
  // would still slip an empty string through) of whichever row is currently
  // being edited, so "Enregistrer" can run native HTML5 validation on just
  // that row before calling `onSave` -- see that button's handler below for
  // why this can't go through the shared `<form>`'s `onSubmit`/
  // `reportValidity` instead. `code`/`name` are free text with no HTML5
  // constraints on their editable fields (not even `required`, unlike their
  // pinned-row counterparts -- editing never leaves them blank without also
  // failing on `weeksPerYear`/the day-hours fields first, and adding
  // `required` there is a separate, non-#194 concern), so they're
  // intentionally excluded. Reset on every render of a given editing row (ref
  // callbacks re-run) and effectively cleared when `editingId` changes, since
  // the previous row's `<CalendarEditableField>`s unmount (calling their ref
  // callbacks with `null`) as the new row's mount.
  const editingFieldRefs = useRef<{
    weeksPerYear: HTMLInputElement | null;
    weekdays: Partial<Record<number, HTMLInputElement | null>>;
  }>({ weeksPerYear: null, weekdays: {} });

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
          required
          initialValue={props.draft.weeksPerYear}
          onChange={(value) => propsRef.current.onDraftChange("weeksPerYear", value)}
          ref={(el) => {
            editingFieldRefs.current.weeksPerYear = el;
          }}
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
          step="0.01"
          className="w-16"
          required
          initialValue={value}
          onChange={(next) => propsRef.current.onDraftWeekdayChange(dayType, next)}
          ref={(el) => {
            editingFieldRefs.current.weekdays[dayType] = el;
          }}
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
            <Button
              size="sm"
              type="button"
              disabled={props.busy}
              onClick={() => {
                // Can't be `type="submit"`: the create row and every edit row
                // share one `<form>` (see the `<form>` wrapping `DataTable`
                // below), so submitting it would run `props.onSubmit` (the
                // create handler) instead of saving this row. Can't call the
                // shared form's `.reportValidity()` either: the pinned create
                // row's `required` fields (`code`/`name`/`weeksPerYear`) are
                // normally empty while editing an unrelated existing row,
                // which would fail validation and block a valid save. So
                // native HTML5 validation is run manually, scoped to just
                // this row's constrained fields (`weeksPerYear` + the 7
                // day-hours inputs -- `code`/`name` are free text with no
                // HTML5 constraints, nothing to check there).
                const fields = [
                  editingFieldRefs.current.weeksPerYear,
                  ...WEEKDAY_ORDER.map(({ dayType }) => editingFieldRefs.current.weekdays[dayType] ?? null),
                ].filter((field): field is HTMLInputElement => field !== null);
                const firstInvalid = fields.find((field) => !field.checkValidity());
                if (firstInvalid) {
                  firstInvalid.reportValidity();
                  return;
                }
                propsRef.current.onSave(item);
              }}
            >
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
          meta: { sticky: "right" },
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
