import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CapacityTable } from "./capacity-table";

const nodeCodeById = new Map([[1, "IT"]]);

describe("CapacityTable", () => {
  afterEach(() => cleanup());

  it("updates a role draft and exposes its save action", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    render(
      <CapacityTable
        roles={[{ id: 1, name: "Développeur", node_id: 1 } as never]}
        drafts={{ 1: { personCount: "2.00", availableHours: "3200.00" } }}
        actionBusy={false}
        nodeCodeById={nodeCodeById}
        onDraftChange={onDraftChange}
        onSave={onSave}
      />,
    );

    fireEvent.change(screen.getByDisplayValue("2.00"), { target: { value: "3.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(onDraftChange).toHaveBeenCalledWith(1, { personCount: "3.00", availableHours: "3200.00" });
    expect(onSave).toHaveBeenCalledWith(1);
  });

  it("disambiguates two roles that share the same name but belong to different nodes", () => {
    const twoNodeCodeById = new Map([
      [1, "IT"],
      [2, "DTSI"],
    ]);
    render(
      <CapacityTable
        roles={[
          { id: 1, name: "Développeur", node_id: 1 } as never,
          { id: 2, name: "Développeur", node_id: 2 } as never,
        ]}
        drafts={{}}
        actionBusy={false}
        nodeCodeById={twoNodeCodeById}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByText("Développeur — IT")).toBeInTheDocument();
    expect(screen.getByText("Développeur — DTSI")).toBeInTheDocument();
  });
});
