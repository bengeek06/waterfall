"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { CircleCheck, CircleDot, CirclePlus, CircleX, LoaderCircle, Send } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import type { Project } from "@/lib/backend";

const ARCHIVED_STATUSES = new Set<Project["status"]>(["perdu", "termine", "abandonne"]);
const PROJECT_STATUS_DETAILS: Record<
  Project["status"],
  { label: string; Icon: LucideIcon; variant: "secondary" | "destructive" | "outline" }
> = {
  cree: { label: "Créé", Icon: CirclePlus, variant: "outline" },
  initialise: { label: "Initialisé", Icon: LoaderCircle, variant: "secondary" },
  en_reponse_appel_offre: { label: "En réponse à appel d'offre", Icon: Send, variant: "secondary" },
  perdu: { label: "Perdu", Icon: CircleX, variant: "destructive" },
  en_cours: { label: "En cours", Icon: CircleDot, variant: "secondary" },
  termine: { label: "Terminé", Icon: CircleCheck, variant: "outline" },
  abandonne: { label: "Abandonné", Icon: CircleX, variant: "destructive" },
};

export type ProjectsTableProps = {
  projects: Project[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  // Server-sortable columns are limited to what the backend's `sort` query
  // parameter accepts (`openapi/spec/paths/projects.yaml`: name, -name, status,
  // -status, id, -id) -- there is no server-side equivalent for "Code", which the
  // pre-DataTable version of this table did sort client-side. That client-only
  // sort is deliberately dropped rather than kept as a local, page-only sort that
  // would silently stop applying to rows on other pages: only `name`/`status`
  // declare `meta.sortColumn` below.
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  selectedIds: Set<number>;
  onSelectedIdsChange: (projectIds: Set<number>) => void;
  onProjectOpen: (projectId: number) => void;
};

export function ProjectsTable(props: ProjectsTableProps) {
  const { projects, selectedIds, onSelectedIdsChange } = props;

  // "Select all" only ever applies to the rows currently rendered by this table --
  // i.e. the current server page, since `projects` here is exactly one page, never
  // the full dataset. It reads/writes `selectedIds` by merging/subtracting just
  // this page's selectable ids, rather than replacing the whole set, so a caller
  // that happened to keep a selection across an unrelated re-render wouldn't lose
  // selections made on another page. In practice the parent page currently resets
  // `selectedIds` on every reload (pagination included), but this table shouldn't
  // rely on that to behave correctly.
  const selectableProjects = projects.filter((project) => !ARCHIVED_STATUSES.has(project.status));
  const allSelected = selectableProjects.length > 0 && selectableProjects.every((project) => selectedIds.has(project.id));

  function toggleProject(projectId: number, checked: boolean) {
    const next = new Set(selectedIds);
    if (checked) {
      next.add(projectId);
    } else {
      next.delete(projectId);
    }
    onSelectedIdsChange(next);
  }

  function toggleAllOnPage(checked: boolean) {
    const next = new Set(selectedIds);
    for (const project of selectableProjects) {
      if (checked) {
        next.add(project.id);
      } else {
        next.delete(project.id);
      }
    }
    onSelectedIdsChange(next);
  }

  const columns: ColumnDef<Project>[] = [
    {
      id: "select",
      header: () => (
        <Checkbox
          aria-label="Tout sélectionner sur cette page"
          checked={allSelected}
          onCheckedChange={(checked) => toggleAllOnPage(Boolean(checked))}
        />
      ),
      cell: ({ row }) => (
        // Stops the click from also bubbling up to DataTable's own `onRowClick`
        // (whole-row navigation), which would otherwise both toggle the checkbox
        // and navigate to the project on the same click.
        <div onClick={(event) => event.stopPropagation()}>
          <Checkbox
            aria-label={`Sélectionner ${row.original.name}`}
            checked={selectedIds.has(row.original.id)}
            disabled={ARCHIVED_STATUSES.has(row.original.status)}
            onCheckedChange={(checked) => toggleProject(row.original.id, Boolean(checked))}
          />
        </div>
      ),
    },
    {
      id: "code",
      header: "Code",
      cell: ({ row }) => row.original.code ?? "-",
    },
    {
      id: "name",
      header: "Nom",
      meta: { sortColumn: "name" },
      cell: ({ row }) => (
        <Link
          href={`/projects/${row.original.id}`}
          className="font-medium hover:underline"
          onClick={(event) => event.stopPropagation()}
        >
          {row.original.name}
        </Link>
      ),
    },
    {
      id: "status",
      header: "Statut",
      meta: { sortColumn: "status" },
      cell: ({ row }) => {
        const status = PROJECT_STATUS_DETAILS[row.original.status];
        const isReadOnly = ARCHIVED_STATUSES.has(row.original.status);

        return (
          <div className="flex items-center gap-2">
            <Badge variant={status.variant} className="gap-1.5">
              <status.Icon aria-hidden="true" />
              {status.label}
            </Badge>
            {isReadOnly ? <span className="text-xs text-muted-foreground">Lecture seule</span> : null}
          </div>
        );
      },
    },
    {
      id: "description",
      header: "Description",
      cell: ({ row }) => (
        <span className="block max-w-sm truncate text-muted-foreground">
          {row.original.short_description ?? "-"}
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      data={projects}
      getRowId={(project) => String(project.id)}
      pagination={props.pagination}
      onPaginationChange={props.onPaginationChange}
      sort={props.sort}
      onSortChange={props.onSortChange}
      search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un projet" }}
      isLoading={props.isLoading}
      onRowClick={(project) => props.onProjectOpen(project.id)}
      // `DataTable` never sets `data-state` itself (unlike the old direct
      // `useReactTable` render, which set `data-state="selected"` from TanStack's
      // own row-selection model) -- `ui/table.tsx`'s `data-[state=selected]:bg-muted`
      // styling only ever applies via an explicit class, so the selected-row
      // highlight has to come through `getRowClassName` instead, same idiom as
      // `calendars-table.tsx`/`cost-types-table.tsx` use for `is_active`.
      getRowClassName={(project) => (selectedIds.has(project.id) ? "bg-muted" : undefined)}
      emptyState="Aucun projet importé."
    />
  );
}
