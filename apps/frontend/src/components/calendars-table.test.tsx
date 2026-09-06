import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CalendarsTable, defaultWeekdays, type CalendarsTableProps } from "./calendars-table";
import type { Calendar } from "@/lib/backend";

afterEach(() => cleanup());

const calendar = (overrides: Partial<Calendar> = {}): Calendar =>
  ({
    id: 1,
    code: "STANDARD",
    name: "Calendrier standard",
    weeks_per_year: 47,
    is_active: true,
    is_default: false,
    weekdays: [],
    ...overrides,
  }) as never;

function renderTable(overrides: Partial<CalendarsTableProps> = {}) {
  const props: CalendarsTableProps = {
    items: [calendar({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    code: "",
    name: "",
    weeksPerYear: "47",
    weekdays: defaultWeekdays(),
    draft: { code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() },
    editingId: null,
    busy: false,
    calendarIdsInUseByActiveRoles: new Set(),
    onSubmit: (event) => event.preventDefault(),
    onCodeChange: vi.fn(),
    onNameChange: vi.fn(),
    onWeeksPerYearChange: vi.fn(),
    onWeekdayChange: vi.fn(),
    onStartEdit: vi.fn(),
    onDraftChange: vi.fn(),
    onDraftWeekdayChange: vi.fn(),
    onSave: vi.fn(),
    onCancel: vi.fn(),
    onToggle: vi.fn(),
    onSetDefault: vi.fn(),
    ...overrides,
  };
  return render(<CalendarsTable {...props} />);
}

describe("CalendarsTable", () => {
  it("renders existing calendars and exposes the add form", () => {
    const onWeekdayChange = vi.fn();
    renderTable({ onWeekdayChange });

    expect(screen.getByText("STANDARD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Heures du Lun pour le nouveau calendrier"), { target: { value: "8" } });
    expect(onWeekdayChange).toHaveBeenCalledWith(2, "8");
  });

  it("switches an existing calendar into edit mode and reports the save action", () => {
    const onSave = vi.fn();
    const item = calendar({});
    renderTable({
      items: [item],
      draft: { code: "STANDARD", name: "Calendrier standard", weeksPerYear: "47", weekdays: defaultWeekdays() },
      editingId: 1,
      onSave,
    });

    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(onSave).toHaveBeenCalledWith(item);
  });

  it("shows an input in place of the weekday cell while that row is being edited", () => {
    const onDraftWeekdayChange = vi.fn();
    renderTable({
      editingId: 1,
      draft: { code: "STANDARD", name: "Calendrier standard", weeksPerYear: "47", weekdays: defaultWeekdays() },
      onDraftWeekdayChange,
    });

    fireEvent.change(screen.getByLabelText("Heures du Lun de STANDARD"), { target: { value: "8" } });
    expect(onDraftWeekdayChange).toHaveBeenCalledWith(2, "8");
  });

  it("reports the toggle action with the targeted calendar when deactivating", () => {
    const onToggle = vi.fn();
    const item = calendar({});
    renderTable({ items: [item], onToggle });

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    expect(onToggle).toHaveBeenCalledWith(item);
  });

  it("reports the toggle action with the targeted calendar when reactivating", () => {
    const onToggle = vi.fn();
    const item = calendar({ id: 2, code: "REDUIT", name: "Calendrier réduit", weeks_per_year: 40, is_active: false });
    renderTable({ items: [item], onToggle });

    fireEvent.click(screen.getByRole("button", { name: "Réactiver" }));
    expect(onToggle).toHaveBeenCalledWith(item);
  });

  it("disables the deactivate button and shows a hint when the calendar is assigned to an active role", () => {
    renderTable({ items: [calendar({})], calendarIdsInUseByActiveRoles: new Set([1]) });

    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByText("Assigné à un rôle actif")).toBeInTheDocument();
  });

  it("keeps the deactivate button enabled when the calendar is not assigned to an active role", () => {
    const onToggle = vi.fn();
    const item = calendar({});
    renderTable({ items: [item], onToggle });

    const button = screen.getByRole("button", { name: "Désactiver" });
    expect(button).not.toBeDisabled();
    expect(screen.queryByText("Assigné à un rôle actif")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(item);
  });

  it("disables the deactivate button and shows the default badge and hint when the calendar is the system default", () => {
    renderTable({ items: [calendar({ is_default: true })] });

    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByText("Calendrier par défaut")).toBeInTheDocument();
    expect(screen.getByText("Par défaut")).toBeInTheDocument();
  });

  it("disables the deactivate button and shows both hints when the calendar is both the system default and assigned to an active role", () => {
    renderTable({ items: [calendar({ is_default: true })], calendarIdsInUseByActiveRoles: new Set([1]) });

    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByText("Assigné à un rôle actif")).toBeInTheDocument();
    expect(screen.getByText("Calendrier par défaut")).toBeInTheDocument();
    expect(screen.getByText("Par défaut")).toBeInTheDocument();
  });

  it("keeps the reactivate button enabled and shows an inactive-specific hint for an inactive calendar still flagged as default", () => {
    const onToggle = vi.fn();
    const item = calendar({ is_active: false, is_default: true });
    renderTable({ items: [item], onToggle });

    const button = screen.getByRole("button", { name: "Réactiver" });
    expect(button).not.toBeDisabled();
    expect(screen.getByText("Calendrier par défaut (inactif)")).toBeInTheDocument();
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(item);
  });

  it("does not show the default calendar badge or hint for a non-default calendar", () => {
    renderTable({ items: [calendar({ is_default: false })] });

    expect(screen.getByRole("button", { name: "Désactiver" })).not.toBeDisabled();
    expect(screen.queryByText("Calendrier par défaut")).not.toBeInTheDocument();
    expect(screen.queryByText("Par défaut")).not.toBeInTheDocument();
  });

  it("reports the set-default action with the targeted calendar for an active non-default calendar", () => {
    const onSetDefault = vi.fn();
    const item = calendar({ is_default: false });
    renderTable({ items: [item], onSetDefault });

    const button = screen.getByRole("button", { name: "Définir par défaut" });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onSetDefault).toHaveBeenCalledWith(item);
  });

  it("disables the set-default action and shows a hint when the calendar is inactive", () => {
    const onSetDefault = vi.fn();
    const item = calendar({ code: "REDUIT", name: "Calendrier réduit", weeks_per_year: 40, is_active: false, is_default: false });
    renderTable({ items: [item], onSetDefault });

    expect(screen.getByRole("button", { name: "Définir par défaut" })).toBeDisabled();
    expect(screen.getByText("Seul un calendrier actif peut être défini par défaut")).toBeInTheDocument();
  });

  it("does not show the set-default action for a calendar that is already the default", () => {
    renderTable({ items: [calendar({ is_default: true })] });

    expect(screen.queryByRole("button", { name: "Définir par défaut" })).not.toBeInTheDocument();
    expect(screen.getByText("Par défaut")).toBeInTheDocument();
  });

  it("dims inactive rows", () => {
    renderTable({ items: [calendar({ is_active: false })] });
    const row = screen.getByText("STANDARD").closest("tr");
    expect(row).toHaveClass("opacity-55");
  });

  it("renders an active row with no dimming class", () => {
    renderTable({ items: [calendar({ is_active: true })] });
    const row = screen.getByText("STANDARD").closest("tr");
    expect(row).not.toHaveClass("opacity-55");
  });

  it("calls onSortChange with the server column name when the code header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Code" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("code");
  });

  it("calls onSortChange with the server column name when the name header is clicked", () => {
    const onSortChange = vi.fn();
    renderTable({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Nom" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("name");
  });

  it("freezes the DataTable (search and pagination) while a row is being edited", () => {
    renderTable({
      editingId: 1,
      pagination: { total: 40, limit: 20, offset: 20 },
    });
    expect(screen.getByLabelText("Rechercher un calendrier")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
  });

  it("submits the pinned create row through the wrapping form", () => {
    const onSubmit = vi.fn((event) => event.preventDefault());
    renderTable({ onSubmit, code: "REDUIT", name: "Calendrier réduit" });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
