import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CalendarsTable, defaultWeekdays } from "./calendars-table";

describe("CalendarsTable", () => {
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
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(onSave).toHaveBeenCalledWith(calendar);
  });
});
