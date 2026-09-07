import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectsTable, type ProjectsTableProps } from "./projects-table";
import type { Project } from "@/lib/backend";

afterEach(() => cleanup());

const project = (overrides: Partial<Project>): Project =>
  ({
    id: 1,
    name: "Projet test",
    status: "en_cours",
    code: "TEST-1",
    short_description: null,
    ...overrides,
  }) as Project;

function renderTable(overrides: Partial<ProjectsTableProps> = {}) {
  const props: ProjectsTableProps = {
    projects: [project({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    selectedIds: new Set(),
    onSelectedIdsChange: vi.fn(),
    onProjectOpen: vi.fn(),
    ...overrides,
  };
  return render(<ProjectsTable {...props} />);
}

describe("ProjectsTable", () => {
  it("renders code, name link, status badge, and truncated description", () => {
    renderTable({
      projects: [project({ code: "PRJ-1", name: "Projet pilote", short_description: "Une description" })],
    });

    expect(screen.getByText("PRJ-1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Projet pilote" })).toHaveAttribute("href", "/projects/1");
    expect(screen.getByText("En cours")).toBeInTheDocument();
    expect(screen.getByText("Une description")).toBeInTheDocument();
  });

  it("shows a dash for a missing code or description instead of blank cells", () => {
    renderTable({ projects: [project({ code: null, short_description: null })] });
    expect(screen.getAllByText("-").length).toBeGreaterThanOrEqual(2);
  });

  it("marks archived-status projects as read-only and disables their selection checkbox", () => {
    renderTable({ projects: [project({ status: "perdu", name: "Projet perdu" })] });

    expect(screen.getByText("Lecture seule")).toBeInTheDocument();
    expect(screen.getByText("Perdu")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Sélectionner Projet perdu" })).toHaveAttribute("aria-disabled", "true");
  });

  it("does not mark an active project as read-only", () => {
    renderTable({ projects: [project({ status: "en_cours" })] });
    expect(screen.queryByText("Lecture seule")).not.toBeInTheDocument();
  });

  it("has no clickable sort control for the Code column, only Nom and Statut", () => {
    renderTable();
    expect(screen.getByText("Code").closest("th")?.querySelector("button")).toBeNull();
    expect(screen.getByRole("button", { name: "Nom" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Statut" })).toBeInTheDocument();
  });

  it("requests the server column name when Nom or Statut headers are clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });

    fireEvent.click(screen.getByRole("button", { name: "Nom" }));
    expect(onSortChange).toHaveBeenLastCalledWith("name");

    fireEvent.click(screen.getByRole("button", { name: "Statut" }));
    expect(onSortChange).toHaveBeenLastCalledWith("status");
  });

  it("navigates when a data row is clicked outside of its checkbox or name link", () => {
    const onProjectOpen = vi.fn();
    renderTable({ projects: [project({ id: 42, name: "Projet cliquable" })], onProjectOpen });

    fireEvent.click(screen.getByText("En cours"));

    expect(onProjectOpen).toHaveBeenCalledExactlyOnceWith(42);
  });

  it("does not navigate when the selection checkbox is clicked", () => {
    const onProjectOpen = vi.fn();
    const onSelectedIdsChange = vi.fn();
    renderTable({
      projects: [project({ id: 42, name: "Projet cliquable" })],
      onProjectOpen,
      onSelectedIdsChange,
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet cliquable" }));

    expect(onProjectOpen).not.toHaveBeenCalled();
    expect(onSelectedIdsChange).toHaveBeenCalledExactlyOnceWith(new Set([42]));
  });

  it("does not navigate when the name link is clicked", () => {
    const onProjectOpen = vi.fn();
    renderTable({ projects: [project({ id: 42, name: "Projet cliquable" })], onProjectOpen });

    fireEvent.click(screen.getByRole("link", { name: "Projet cliquable" }));

    expect(onProjectOpen).not.toHaveBeenCalled();
  });

  it("toggles a single project's selection on and off", () => {
    const onSelectedIdsChange = vi.fn();
    const { rerender } = renderTable({
      projects: [project({ id: 1 }), project({ id: 2, name: "Autre projet" })],
      selectedIds: new Set([2]),
      onSelectedIdsChange,
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Projet test" }));
    expect(onSelectedIdsChange).toHaveBeenCalledExactlyOnceWith(new Set([2, 1]));

    onSelectedIdsChange.mockClear();
    rerender(
      <ProjectsTable
        projects={[project({ id: 1 }), project({ id: 2, name: "Autre projet" })]}
        pagination={{ total: 2, limit: 20, offset: 0 }}
        onPaginationChange={vi.fn()}
        sort={null}
        onSortChange={vi.fn()}
        search=""
        onSearchChange={vi.fn()}
        isLoading={false}
        selectedIds={new Set([2])}
        onSelectedIdsChange={onSelectedIdsChange}
        onProjectOpen={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Sélectionner Autre projet" }));
    expect(onSelectedIdsChange).toHaveBeenCalledExactlyOnceWith(new Set());
  });

  it("scopes 'select all' to the projects on this page: checking it selects only visible, non-archived rows", () => {
    const onSelectedIdsChange = vi.fn();
    renderTable({
      projects: [
        project({ id: 1, name: "Actif un" }),
        project({ id: 2, name: "Actif deux" }),
        project({ id: 3, name: "Perdu", status: "perdu" }),
      ],
      selectedIds: new Set(),
      onSelectedIdsChange,
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Tout sélectionner sur cette page" }));

    expect(onSelectedIdsChange).toHaveBeenCalledExactlyOnceWith(new Set([1, 2]));
  });

  it("shows 'select all' as checked only when every selectable row on this page is selected", () => {
    const { rerender } = renderTable({
      projects: [project({ id: 1 }), project({ id: 2, name: "Autre projet" })],
      selectedIds: new Set([1]),
    });
    expect(screen.getByRole("checkbox", { name: "Tout sélectionner sur cette page" })).not.toBeChecked();

    rerender(
      <ProjectsTable
        projects={[project({ id: 1 }), project({ id: 2, name: "Autre projet" })]}
        pagination={{ total: 2, limit: 20, offset: 0 }}
        onPaginationChange={vi.fn()}
        sort={null}
        onSortChange={vi.fn()}
        search=""
        onSearchChange={vi.fn()}
        isLoading={false}
        selectedIds={new Set([1, 2])}
        onSelectedIdsChange={vi.fn()}
        onProjectOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "Tout sélectionner sur cette page" })).toBeChecked();
  });

  it("unchecking 'select all' deselects only this page's selectable rows, leaving other selections untouched", () => {
    const onSelectedIdsChange = vi.fn();
    renderTable({
      projects: [project({ id: 1 }), project({ id: 2, name: "Autre projet" })],
      selectedIds: new Set([1, 2, 99]),
      onSelectedIdsChange,
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Tout sélectionner sur cette page" }));

    expect(onSelectedIdsChange).toHaveBeenCalledExactlyOnceWith(new Set([99]));
  });

  it("passes search through to the underlying DataTable search input", () => {
    const onSearchChange = vi.fn();
    renderTable({ search: "abc", onSearchChange });
    expect(screen.getByLabelText("Rechercher un projet")).toHaveValue("abc");
  });

  it("shows a loading skeleton instead of rows while isLoading is true", () => {
    renderTable({ isLoading: true });
    expect(screen.getByRole("status", { name: "Chargement des données" })).toBeInTheDocument();
  });

  it("shows the position label from the pagination prop", () => {
    renderTable({
      projects: [project({ id: 1 }), project({ id: 2, name: "Autre projet" })],
      pagination: { total: 5, limit: 2, offset: 0 },
    });
    expect(screen.getByText("1 à 2 sur 5")).toBeInTheDocument();
  });

  it("highlights a selected row with bg-muted, matching ui/table.tsx's data-state=selected styling", () => {
    renderTable({
      projects: [project({ id: 1 }), project({ id: 2, name: "Autre projet" })],
      selectedIds: new Set([1]),
    });

    expect(screen.getByText("Projet test").closest("tr")).toHaveClass("bg-muted");
    expect(screen.getByText("Autre projet").closest("tr")).not.toHaveClass("bg-muted");
  });

  it("renders every project row passed in props", () => {
    renderTable({
      projects: [project({ id: 1, name: "A" }), project({ id: 2, name: "B" }), project({ id: 3, name: "C" })],
      pagination: { total: 3, limit: 20, offset: 0 },
    });
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    within(rows[0]).getByText("A");
    within(rows[1]).getByText("B");
    within(rows[2]).getByText("C");
  });
});
