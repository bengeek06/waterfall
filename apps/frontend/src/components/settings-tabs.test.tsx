import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsTabs, type SettingsTab } from "./settings-tabs";

describe("SettingsTabs", () => {
  it("renders the three settings sections and reports tab changes", () => {
    const onChange = vi.fn<(tab: SettingsTab) => void>();

    render(<SettingsTabs activeTab="costs" onChange={onChange} />);

    expect(screen.getByRole("tab", { name: "Coûts" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Ressources" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "Utilisateurs" })).toHaveAttribute("aria-selected", "false");

    fireEvent.click(screen.getByRole("tab", { name: "Ressources" }));

    expect(onChange).toHaveBeenCalledWith("resources");
  });
});