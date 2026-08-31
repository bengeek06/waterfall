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
});
