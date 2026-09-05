import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CalendarsTable, defaultWeekdays } from "./calendars-table";

describe("CalendarsTable", () => {
  afterEach(() => cleanup());

  it("renders existing calendars and exposes the add form", () => {
    const onWeekdayChange = vi.fn();
    render(
      <CalendarsTable
        items={[
          {
            id: 1,
            code: "STANDARD",
            name: "Calendrier standard",
            weeks_per_year: 47,
            is_active: true,
            weekdays: [{ id: 1, calendar_id: 1, day_type: 2, hours_per_day: 7 } as never],
          } as never,
        ]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={onWeekdayChange}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    expect(screen.getByText("STANDARD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Heures du Lun pour le nouveau calendrier"), { target: { value: "8" } });
    expect(onWeekdayChange).toHaveBeenCalledWith(2, "8");
  });

  it("switches an existing calendar into edit mode and reports the save action", () => {
    const onStartEdit = vi.fn();
    const onSave = vi.fn();
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "STANDARD", name: "Calendrier standard", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={1}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={onStartEdit}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={onSave}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(onSave).toHaveBeenCalledWith(calendar);
  });

  it("reports the toggle action with the targeted calendar when deactivating", () => {
    const onToggle = vi.fn();
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={onToggle}
        onSetDefault={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    expect(onToggle).toHaveBeenCalledWith(calendar);
  });

  it("reports the toggle action with the targeted calendar when reactivating", () => {
    const onToggle = vi.fn();
    const calendar = { id: 2, code: "REDUIT", name: "Calendrier réduit", weeks_per_year: 40, is_active: false, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={onToggle}
        onSetDefault={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Réactiver" }));
    expect(onToggle).toHaveBeenCalledWith(calendar);
  });

  it("disables the deactivate button and shows a hint when the calendar is assigned to an active role", () => {
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set([1])}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByText("Assigné à un rôle actif")).toBeInTheDocument();
  });

  it("keeps the deactivate button enabled when the calendar is not assigned to an active role", () => {
    const onToggle = vi.fn();
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={onToggle}
        onSetDefault={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Désactiver" });
    expect(button).not.toBeDisabled();
    expect(screen.queryByText("Assigné à un rôle actif")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(calendar);
  });

  it("disables the deactivate button and shows the default badge and hint when the calendar is the system default", () => {
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, is_default: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByText("Calendrier par défaut")).toBeInTheDocument();
    expect(screen.getByText("Par défaut")).toBeInTheDocument();
  });

  it("disables the deactivate button and shows both hints when the calendar is both the system default and assigned to an active role", () => {
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, is_default: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set([1])}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByText("Assigné à un rôle actif")).toBeInTheDocument();
    expect(screen.getByText("Calendrier par défaut")).toBeInTheDocument();
    expect(screen.getByText("Par défaut")).toBeInTheDocument();
  });

  it("keeps the reactivate button enabled and shows an inactive-specific hint for an inactive calendar still flagged as default", () => {
    const onToggle = vi.fn();
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: false, is_default: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={onToggle}
        onSetDefault={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Réactiver" });
    expect(button).not.toBeDisabled();
    expect(screen.getByText("Calendrier par défaut (inactif)")).toBeInTheDocument();
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(calendar);
  });

  it("does not show the default calendar badge or hint for a non-default calendar", () => {
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, is_default: false, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Désactiver" })).not.toBeDisabled();
    expect(screen.queryByText("Calendrier par défaut")).not.toBeInTheDocument();
    expect(screen.queryByText("Par défaut")).not.toBeInTheDocument();
  });

  it("reports the set-default action with the targeted calendar for an active non-default calendar", () => {
    const onSetDefault = vi.fn();
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, is_default: false, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={onSetDefault}
      />,
    );

    const button = screen.getByRole("button", { name: "Définir par défaut" });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onSetDefault).toHaveBeenCalledWith(calendar);
  });

  it("disables the set-default action and shows a hint when the calendar is inactive", () => {
    const onSetDefault = vi.fn();
    const calendar = { id: 1, code: "REDUIT", name: "Calendrier réduit", weeks_per_year: 40, is_active: false, is_default: false, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={onSetDefault}
      />,
    );

    expect(screen.getByRole("button", { name: "Définir par défaut" })).toBeDisabled();
    expect(screen.getByText("Seul un calendrier actif peut être défini par défaut")).toBeInTheDocument();
  });

  it("does not show the set-default action for a calendar that is already the default", () => {
    const calendar = { id: 1, code: "STANDARD", name: "Calendrier standard", weeks_per_year: 47, is_active: true, is_default: true, weekdays: [] } as never;
    render(
      <CalendarsTable
        items={[calendar]}
        code=""
        name=""
        weeksPerYear="47"
        weekdays={defaultWeekdays()}
        draft={{ code: "", name: "", weeksPerYear: "47", weekdays: defaultWeekdays() }}
        editingId={null}
        busy={false}
        calendarIdsInUseByActiveRoles={new Set()}
        onSubmit={(event) => event.preventDefault()}
        onCodeChange={vi.fn()}
        onNameChange={vi.fn()}
        onWeeksPerYearChange={vi.fn()}
        onWeekdayChange={vi.fn()}
        onStartEdit={vi.fn()}
        onDraftChange={vi.fn()}
        onDraftWeekdayChange={vi.fn()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        onToggle={vi.fn()}
        onSetDefault={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Définir par défaut" })).not.toBeInTheDocument();
    expect(screen.getByText("Par défaut")).toBeInTheDocument();
  });
});
