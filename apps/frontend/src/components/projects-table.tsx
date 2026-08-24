"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  flexRender,
  functionalUpdate,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDownUp, CircleCheck, CircleDot, CirclePlus, CircleX, LoaderCircle, Send } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

type ProjectsTableProps = {
  projects: Project[];
  selectedIds: Set<number>;
  onSelectedIdsChange: (projectIds: Set<number>) => void;
  onProjectOpen: (projectId: number) => void;
};

function SortableHeader({ label, column }: { label: string; column: { toggleSorting: (descending?: boolean) => void; getIsSorted: () => false | "asc" | "desc" } }) {
  const direction = column.getIsSorted();

  return (
    <Button variant="ghost" size="sm" className="-ml-2" onClick={() => column.toggleSorting(direction === "asc")}>
      {label}
      <ArrowDownUp aria-hidden="true" />
    </Button>
  );
}

export function ProjectsTable({
  projects,
  selectedIds,
  onSelectedIdsChange,
  onProjectOpen,
}: ProjectsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const rowSelection = useMemo(
    () => Object.fromEntries([...selectedIds].map((projectId) => [String(projectId), true])),
    [selectedIds],
  );
  const columns = useMemo<ColumnDef<Project>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        header: ({ table }) => (
          <Checkbox
            aria-label="Tout sélectionner"
            checked={table.getIsAllPageRowsSelected()}
            onCheckedChange={(checked) => table.toggleAllPageRowsSelected(Boolean(checked))}
          />
        ),
        cell: ({ row }) => (
          <div onClick={(event) => event.stopPropagation()}>
            <Checkbox
              aria-label={`Sélectionner ${row.original.name}`}
              checked={row.getIsSelected()}
              disabled={!row.getCanSelect()}
              onCheckedChange={(checked) => row.toggleSelected(Boolean(checked))}
            />
          </div>
        ),
      },
      {
        accessorKey: "code",
        header: ({ column }) => <SortableHeader label="Code" column={column} />,
        cell: ({ row }) => row.original.code ?? "-",
      },
      {
        accessorKey: "name",
        header: ({ column }) => <SortableHeader label="Nom" column={column} />,
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
        accessorKey: "status",
        header: "Statut",
        cell: ({ row }) => {
          const status = PROJECT_STATUS_DETAILS[row.original.status];
          const isReadOnly = ARCHIVED_STATUSES.has(row.original.status);

          return (
            <div className="flex items-center gap-2">
              <Badge variant={status.variant} className="gap-1.5">
                <status.Icon aria-label={`Statut : ${status.label}`} title={status.label} />
                {status.label}
              </Badge>
              {isReadOnly ? <span className="text-xs text-muted-foreground">Lecture seule</span> : null}
            </div>
          );
        },
      },
      {
        accessorKey: "short_description",
        header: "Description",
        cell: ({ row }) => (
          <span className="block max-w-sm truncate text-muted-foreground">
            {row.original.short_description ?? "-"}
          </span>
        ),
      },
    ],
    [],
  );
  const table = useReactTable({
    data: projects,
    columns,
    getRowId: (project) => String(project.id),
    enableRowSelection: (row) => !ARCHIVED_STATUSES.has(row.original.status),
    onRowSelectionChange: (updater) => {
      const nextSelection = functionalUpdate(updater, rowSelection);
      onSelectedIdsChange(
        new Set(
          Object.entries(nextSelection)
            .filter(([, selected]) => selected)
            .map(([projectId]) => Number(projectId)),
        ),
      );
    },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    state: { rowSelection, sorting },
  });

  return (
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <TableHead key={header.id}>
                {header.isPlaceholder
                  ? null
                  : flexRender(header.column.columnDef.header, header.getContext())}
              </TableHead>
            ))}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow
            key={row.id}
            data-state={row.getIsSelected() ? "selected" : undefined}
            className="cursor-pointer"
            onClick={() => onProjectOpen(row.original.id)}
          >
            {row.getVisibleCells().map((cell) => (
              <TableCell key={cell.id}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}