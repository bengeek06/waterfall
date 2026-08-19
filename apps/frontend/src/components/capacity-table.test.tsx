import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CapacityTable } from "./capacity-table";

describe("CapacityTable", () => {
  it("updates a role draft and exposes its save action", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    render(<CapacityTable roles={[{ id: 1, code: "DEV", name: "Développeur" } as never]} drafts={{ 1: { personCount: "2.00", availableHours: "3200.00" } }} actionBusy={false} onDraftChange={onDraftChange} onSave={onSave} />);

    fireEvent.change(screen.getByDisplayValue("2.00"), { target: { value: "3.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(onDraftChange).toHaveBeenCalledWith(1, { personCount: "3.00", availableHours: "3200.00" });
    expect(onSave).toHaveBeenCalledWith(1);
  });
});