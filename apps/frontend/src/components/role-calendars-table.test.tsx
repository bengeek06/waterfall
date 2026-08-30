import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RoleCalendarsTable } from "./role-calendars-table";

describe("RoleCalendarsTable", () => {
  afterEach(() => cleanup());

  it("updates a role's calendar draft and exposes its save action", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, code: "DEV", name: "Développeur", calendar_id: null } as never]}
        calendars={[{ id: 2, code: "PARTTIME", name: "Temps partiel", is_active: true } as never]}
        drafts={{}}
        actionBusy={false}
        onDraftChange={onDraftChange}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("option", { name: "PARTTIME - Temps partiel" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Calendrier de DEV"), { target: { value: "2" } });
    expect(onDraftChange).toHaveBeenCalledWith(1, "2");

    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(onSave).toHaveBeenCalledWith(1);
  });

  it("keeps a role's assigned calendar visible and selected even after it becomes inactive", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, code: "DEV", name: "Développeur", calendar_id: 2 } as never]}
        calendars={[{ id: 2, code: "REDUIT", name: "Calendrier réduit", is_active: false } as never]}
        drafts={{}}
        actionBusy={false}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "REDUIT - Calendrier réduit (inactif)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Calendrier de DEV")).toHaveValue("2");
  });
});
