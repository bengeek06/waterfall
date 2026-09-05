import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RoleCalendarsTable } from "./role-calendars-table";

const nodeCodeById = new Map([[1, "IT"]]);

describe("RoleCalendarsTable", () => {
  afterEach(() => cleanup());

  it("updates a role's calendar draft and exposes its save action", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never]}
        calendars={[{ id: 2, code: "PARTTIME", name: "Temps partiel", is_active: true } as never]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={onDraftChange}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("option", { name: "PARTTIME - Temps partiel" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Calendrier de Développeur — IT (#1)"), { target: { value: "2" } });
    expect(onDraftChange).toHaveBeenCalledWith(1, "2");

    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(onSave).toHaveBeenCalledWith(1);
  });

  it("keeps a role's assigned calendar visible and selected even after it becomes inactive", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: 2 } as never]}
        calendars={[{ id: 2, code: "REDUIT", name: "Calendrier réduit", is_active: false } as never]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "REDUIT - Calendrier réduit (inactif)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Calendrier de Développeur — IT (#1)")).toHaveValue("2");
  });

  it("disables the calendar select while an action is in flight", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never]}
        calendars={[{ id: 2, code: "PARTTIME", name: "Temps partiel", is_active: true } as never]}
        drafts={{}}
        actionBusy={true}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Calendrier de Développeur — IT (#1)")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  });

  it("disambiguates two roles that share the same name but belong to different nodes", () => {
    const twoNodeCodeById = new Map([
      [1, "IT"],
      [2, "DTSI"],
    ]);
    render(
      <RoleCalendarsTable
        roles={[
          { id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never,
          { id: 2, name: "Développeur", node_id: 2, calendar_id: null } as never,
        ]}
        calendars={[{ id: 3, code: "PARTTIME", name: "Temps partiel", is_active: true } as never]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={twoNodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Calendrier de Développeur — IT (#1)")).toBeInTheDocument();
    expect(screen.getByLabelText("Calendrier de Développeur — DTSI (#2)")).toBeInTheDocument();
  });

  it("disambiguates two roles that share the same name within the same node using role id", () => {
    render(
      <RoleCalendarsTable
        roles={[
          { id: 5, name: "Développeur", node_id: 1, calendar_id: null } as never,
          { id: 6, name: "Développeur", node_id: 1, calendar_id: null } as never,
        ]}
        calendars={[{ id: 3, code: "PARTTIME", name: "Temps partiel", is_active: true } as never]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    // Both roles share the same name AND the same node code ("IT"), so only the
    // trailing "(#<role.id>)" discriminant can tell them apart. If that suffix were
    // dropped, both labels would collapse to "Calendrier de Développeur — IT" and
    // getByLabelText would throw "multiple elements found".
    expect(screen.getByLabelText("Calendrier de Développeur — IT (#5)")).toBeInTheDocument();
    expect(screen.getByLabelText("Calendrier de Développeur — IT (#6)")).toBeInTheDocument();
  });

  it("names the effective default calendar in the empty option when an active default calendar exists", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never]}
        calendars={[
          { id: 2, code: "PARTTIME", name: "Temps partiel", is_active: true, is_default: false } as never,
          {
            id: 3,
            code: "STANDARD",
            name: "Calendrier standard",
            is_active: true,
            is_default: true,
            weekdays: [{ day_type: 2, hours_per_day: "7.00" }],
          } as never,
        ]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "Calendrier par défaut (STANDARD - Calendrier standard)" })).toBeInTheDocument();
  });

  it("signals the implicit wall-clock fallback in the empty option when the active default calendar has no working day", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never]}
        calendars={[
          {
            id: 3,
            code: "STANDARD",
            name: "Calendrier standard",
            is_active: true,
            is_default: true,
            weekdays: [],
          } as never,
        ]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("option", {
        name: "Calendrier implicite (24h/24, 7j/7) — le calendrier par défaut configuré n'a aucun jour travaillé",
      }),
    ).toBeInTheDocument();
  });

  it("also signals the implicit wall-clock fallback when the active default calendar's weekdays are all at zero hours", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never]}
        calendars={[
          {
            id: 3,
            code: "STANDARD",
            name: "Calendrier standard",
            is_active: true,
            is_default: true,
            weekdays: [
              { day_type: 2, hours_per_day: "0.00" },
              { day_type: 3, hours_per_day: "0" },
            ],
          } as never,
        ]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("option", {
        name: "Calendrier implicite (24h/24, 7j/7) — le calendrier par défaut configuré n'a aucun jour travaillé",
      }),
    ).toBeInTheDocument();
  });

  it("signals the absence of a default calendar in the empty option when none is active and flagged as default", () => {
    render(
      <RoleCalendarsTable
        roles={[{ id: 1, name: "Développeur", node_id: 1, calendar_id: null } as never]}
        calendars={[{ id: 2, code: "PARTTIME", name: "Temps partiel", is_active: true, is_default: false } as never]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "Aucun calendrier par défaut défini" })).toBeInTheDocument();
  });
});
