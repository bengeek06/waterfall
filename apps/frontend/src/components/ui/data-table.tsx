"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowData,
} from "@tanstack/react-table";
import { ArrowDown, ArrowDownUp, ArrowUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// Marks a column as server-sortable and gives the exact column name the backend's
// `sort` query parameter expects. TanStack's own `accessorKey`/`id` may not always
// match that name, so sortability is declared explicitly via `meta.sortColumn`
// rather than inferred from `enableSorting`/`accessorKey`.
//
// `sticky: "right"` pins a column (typically "actions") to the right edge of the
// table's own `overflow-x-auto` scroll container (see `Table` in `ui/table.tsx`),
// so it stays reachable on wide tables instead of scrolling out of the viewport.
declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    sortColumn?: string;
    sticky?: "right";
  }
}

// Shared with the pinned create-row's own last cell (see e.g. `calendars-table.tsx`'s
// `renderPinnedRow`), which doesn't go through `columns`/`flexRender` and so can't
// pick up `meta.sticky` automatically -- it applies this exact class list directly.
export const STICKY_RIGHT_CELL_CLASSNAME = "sticky right-0 z-10 bg-background shadow-[-4px_0_4px_-4px_rgba(0,0,0,0.15)]";

const DEFAULT_SEARCH_DEBOUNCE_MS = 300;
const LOADING_SKELETON_ROWS = 3;

export type DataTablePaginationState = {
  total: number;
  limit: number;
  offset: number;
};

export type DataTableProps<TData> = {
  columns: ColumnDef<TData>[];
  data: TData[];
  getRowId: (row: TData) => string;

  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;

  // Current sort as the exact string the `sort` query parameter expects (e.g. "name",
  // "-created_at", or null for none).
  sort: string | null;
  onSortChange: (nextSort: string | null) => void;

  search?: {
    value: string;
    onChange: (nextQuery: string) => void;
    placeholder?: string;
    debounceMs?: number;
  };

  // Rendered as its own row(s) above the data body, inside the same <form> the
  // caller wraps around <DataTable> for a create-row use case. Never affected by
  // pagination or search.
  pinnedRow?: ReactNode;

  // Optional class name for a data row's own <TableRow>, computed per row (e.g. a
  // dimmed/"opacity-55" style for an inactive item). Column `cell` renderers can
  // only style their own <TableCell>, not the row itself, so this is the only way
  // for a caller to affect row-level styling without DataTable hard-coding a
  // specific business meaning (like "is_active") into a shared component.
  getRowClassName?: (row: TData) => string | undefined;

  // Whole-row navigation (e.g. `projects-table.tsx`'s click-anywhere-on-the-row to
  // open a project), applied only to data rows, never `pinnedRow` (a pinned
  // create-row has its own inputs/submit button, not a "thing to navigate to").
  // Adds a `cursor-pointer` affordance automatically so the click target is
  // visually obvious without every caller re-deriving that class itself. A cell
  // that renders its own interactive control inside a clickable row (a checkbox, a
  // `next/link`) must call `event.stopPropagation()` in its own handler, or the
  // click bubbles up and fires both actions -- see `projects-table.tsx`'s
  // selection checkbox and "Nom" link for the pattern.
  //
  // The `<TableRow>` itself gets no `tabIndex`/`role`/`onKeyDown` -- there is no
  // native keyboard equivalent for "click this row" here. A caller that sets
  // `onRowClick` must therefore make sure at least one genuinely focusable
  // element inside the row (typically a `next/link`, as in `projects-table.tsx`'s
  // "Nom" column) leads to the exact same destination, so the row's action stays
  // reachable via Tab + Enter even without the whole-row click.
  onRowClick?: (row: TData) => void;

  isEditing?: boolean;
  editingReason?: string;

  isLoading?: boolean;
  emptyState?: ReactNode;
  noResultsState?: ReactNode;
};

function getNextSort(columnId: string, currentSort: string | null): string | null {
  if (currentSort === columnId) {
    return `-${columnId}`;
  }
  if (currentSort === `-${columnId}`) {
    return null;
  }
  return columnId;
}

function getSortDirection(columnId: string, currentSort: string | null): "ascending" | "descending" | "none" {
  if (currentSort === columnId) {
    return "ascending";
  }
  if (currentSort === `-${columnId}`) {
    return "descending";
  }
  return "none";
}

function SortIcon({ direction }: { direction: "ascending" | "descending" | "none" }) {
  if (direction === "ascending") {
    return <ArrowUp aria-hidden="true" />;
  }
  if (direction === "descending") {
    return <ArrowDown aria-hidden="true" />;
  }
  return <ArrowDownUp aria-hidden="true" />;
}

// Keeps the search input's displayed value locally controlled and responsive on
// every keystroke, while debouncing the call to `onChange` so the server request
// only fires once typing pauses. Resyncs from `value` when it changes externally
// (e.g. the caller clears the search elsewhere), using the React-documented
// "adjust state during render" pattern instead of a setState-in-effect.
// `onChange` is read through a ref rather than an effect dependency: a caller that
// resets pagination alongside the search value (`onChange: (v) => { setQuery(v);
// setOffset(0); }`, an entirely idiomatic pattern) creates a new `onChange` identity
// every render. If it were a dependency, any unrelated re-render during the debounce
// window would cancel and reschedule the pending timeout, and typing would appear to
// do nothing -- verified empirically, not just in theory. Reading the latest
// `onChange` via a ref removes the need for callers to memoize it at all.
// `suspend`, when true, cancels any pending debounce timer (via the effect's own
// cleanup re-running on the dependency change below) and skips scheduling a new one,
// without touching `localValue` -- the caller (`DataTable`, via `isEditing`) keeps the
// typed text visible in the disabled input. See `abandonedValue` below for what
// happens to a search that was pending when `suspend` became true.
function useDebouncedSearchValue(value: string, delay: number, onChange: (next: string) => void, suspend = false) {
  const [localValue, setLocalValue] = useState(value);
  const [previousValue, setPreviousValue] = useState(value);
  if (value !== previousValue) {
    setPreviousValue(value);
    setLocalValue(value);
  }

  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  // Tracks the `localValue` a pending search was cancelled at when `suspend` last
  // became true (e.g. the user started editing a row mid-debounce, see
  // `CalendarsTable`'s "Modifier" flow). That particular search is abandoned for
  // good rather than resumed once `suspend` goes back to `false`: firing it late,
  // after editing ends, could load a filtered page that no longer contains the row
  // being edited -- unreachable "Enregistrer"/"Annuler" buttons, exactly the bug
  // this parameter exists to prevent. Silent abandonment is deliberate and simpler
  // than replaying it: typing further characters once `suspend` clears schedules a
  // fresh, non-abandoned debounce as normal.
  //
  // Captured and consumed in state (not a ref: reading/writing a ref during render is
  // disallowed by this codebase's lint rules, and a plain effect can't call setState
  // synchronously either, per react-hooks/set-state-in-effect), using the same
  // "adjust state during render" pattern as `previousValue` above, right on the
  // `suspend` transition. `localValue` cannot change while `suspend` is true (the
  // input is disabled, see `DataTable`), so capturing it synchronously here, instead
  // of in an effect, cannot miss a later keystroke. Consuming the abandonment (right
  // when `suspend` clears, if nothing was retyped since) also resyncs the visible
  // input onto `value`: the abandoned text was never applied, so leaving it displayed
  // would silently mislead the user into thinking their search is still in effect.
  const [abandonedValue, setAbandonedValue] = useState<string | null>(null);
  const [previousSuspend, setPreviousSuspend] = useState(suspend);
  if (suspend !== previousSuspend) {
    setPreviousSuspend(suspend);
    if (suspend) {
      setAbandonedValue(localValue);
    } else if (localValue === abandonedValue) {
      setAbandonedValue(null);
      if (localValue !== value) {
        setLocalValue(value);
      }
    }
  }

  useEffect(() => {
    if (suspend || localValue === value || localValue === abandonedValue) {
      return;
    }
    const timeoutId = setTimeout(() => onChangeRef.current(localValue), delay);
    return () => clearTimeout(timeoutId);
  }, [localValue, value, delay, suspend, abandonedValue]);

  return [localValue, setLocalValue] as const;
}

function noop() {
  // Used as the debounce hook's onChange when no `search` prop is supplied, so the
  // hook can still be called unconditionally on every render.
}

export function DataTable<TData>({
  columns,
  data,
  getRowId,
  pagination,
  onPaginationChange,
  sort,
  onSortChange,
  search,
  pinnedRow,
  getRowClassName,
  onRowClick,
  isEditing = false,
  editingReason,
  isLoading = false,
  emptyState,
  noResultsState,
}: DataTableProps<TData>) {
  // TanStack Table's own row/column helpers are known-incompatible with React Compiler
  // memoization (they return new function identities on every call). This component
  // runs in manual mode and never reads TanStack's own sorting/filtering/pagination row
  // models, so referential stability of anything derived from `table` isn't relied on.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    rowCount: pagination.total,
  });

  const [searchValue, setSearchValue] = useDebouncedSearchValue(
    search?.value ?? "",
    search?.debounceMs ?? DEFAULT_SEARCH_DEBOUNCE_MS,
    search?.onChange ?? noop,
    isEditing,
  );

  const rows = table.getRowModel().rows;
  const leafColumnCount = table.getVisibleLeafColumns().length;
  const hasActiveSearch = Boolean(search?.value);
  // While isLoading, `data`/`pagination` may still describe the page being replaced
  // (a caller keeping the previous page mounted during a background refetch, to
  // avoid a flash of empty content) rather than the page about to be shown. Freezing
  // the position label and pagination controls here, once, avoids each of the 8
  // upcoming table migrations independently guessing at (and likely disagreeing on)
  // what to display in that gap.
  const canGoPrevious = !isEditing && !isLoading && pagination.offset > 0;
  const canGoNext = !isEditing && !isLoading && pagination.offset + data.length < pagination.total;
  const positionLabel =
    !isLoading && data.length
      ? `${pagination.offset + 1} à ${pagination.offset + data.length} sur ${pagination.total}`
      : "";

  return (
    <div className="space-y-3">
      {search ? (
        <Input
          type="search"
          aria-label={search.placeholder ?? "Rechercher"}
          placeholder={search.placeholder}
          value={searchValue}
          disabled={isEditing}
          onChange={(event) => setSearchValue(event.target.value)}
          onKeyDown={(event) => {
            // A caller commonly wraps the whole DataTable (search input included) in
            // a <form> for the pinned create-row's own submit button. Per the HTML
            // implicit-submission algorithm, Enter in any single-line text input
            // inside that form -- including this one -- submits it. Search is
            // already debounced on every keystroke, so Enter isn't needed to trigger
            // it, and swallowing it here avoids an unrelated Enter-to-search
            // keystroke accidentally submitting a filled-in create-row.
            if (event.key === "Enter") {
              event.preventDefault();
            }
          }}
          className="max-w-xs"
        />
      ) : null}
      <p aria-live="polite" className="text-sm text-muted-foreground">
        {isEditing ? editingReason : null}
      </p>
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const sortColumn = header.column.columnDef.meta?.sortColumn;
                const sticky = header.column.columnDef.meta?.sticky;
                const stickyClassName = sticky === "right" ? STICKY_RIGHT_CELL_CLASSNAME : undefined;
                const content = header.isPlaceholder
                  ? null
                  : flexRender(header.column.columnDef.header, header.getContext());

                if (!sortColumn) {
                  return (
                    <TableHead key={header.id} className={stickyClassName}>
                      {content}
                    </TableHead>
                  );
                }

                const direction = getSortDirection(sortColumn, sort);

                return (
                  <TableHead key={header.id} aria-sort={direction} className={stickyClassName}>
                    <Button
                      variant="ghost"
                      size="sm"
                      type="button"
                      className="-ml-2"
                      disabled={isEditing}
                      onClick={() => onSortChange(getNextSort(sortColumn, sort))}
                    >
                      {content}
                      <SortIcon direction={direction} />
                    </Button>
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {pinnedRow}
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={leafColumnCount}>
                <div role="status" aria-label="Chargement des données" className="flex flex-col gap-2 py-2">
                  {Array.from({ length: LOADING_SKELETON_ROWS }).map((_, index) => (
                    <Skeleton key={index} className="h-6 w-full" />
                  ))}
                </div>
              </TableCell>
            </TableRow>
          ) : rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={leafColumnCount} className="h-24 text-center text-muted-foreground">
                {hasActiveSearch
                  ? (noResultsState ?? "Aucun résultat pour cette recherche.")
                  : (emptyState ?? "Aucune donnée.")}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow
                key={row.id}
                className={cn(getRowClassName?.(row.original), onRowClick ? "cursor-pointer" : undefined)}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
              >
                {row.getVisibleCells().map((cell) => {
                  const sticky = cell.column.columnDef.meta?.sticky;
                  return (
                    <TableCell key={cell.id} className={sticky === "right" ? STICKY_RIGHT_CELL_CLASSNAME : undefined}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm text-muted-foreground">{positionLabel}</span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            type="button"
            disabled={!canGoPrevious}
            onClick={() =>
              onPaginationChange({
                offset: Math.max(0, pagination.offset - pagination.limit),
                limit: pagination.limit,
              })
            }
          >
            Précédent
          </Button>
          <Button
            variant="outline"
            type="button"
            disabled={!canGoNext}
            onClick={() =>
              onPaginationChange({
                offset: pagination.offset + pagination.limit,
                limit: pagination.limit,
              })
            }
          >
            Suivant
          </Button>
        </div>
      </div>
    </div>
  );
}
