import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProjectTabs } from "./project-tabs";

describe("ProjectTabs", () => {
  it("renders all project sections and changes the active tab", () => {
    const onChange = vi.fn();
    render(<ProjectTabs activeTab="planning" onChange={onChange} />);

    expect(screen.getByRole("tab", { name: "Planning" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Devis" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Reste à engager" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Analytique" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Analytique" }));
    expect(onChange).toHaveBeenCalledWith("analytics");
  });
});