import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CostTypesTable } from "./cost-types-table";

describe("CostTypesTable", () => {
  it("renders the behavior selector and existing type actions", () => {
    render(<CostTypesTable items={[{ id: 1, code: "MO", name: "Main d'œuvre", kind: "labor", is_active: true } as never]} code="" name="" kind="other" draft="" editingId={null} busy={false} labels={{ labor: "Main d'œuvre", supply: "Fourniture", other: "Autres" }} onSubmit={(event) => event.preventDefault()} onCodeChange={vi.fn()} onNameChange={vi.fn()} onKindChange={vi.fn()} onStartEdit={vi.fn()} onDraftChange={vi.fn()} onSave={vi.fn()} onCancel={vi.fn()} onToggle={vi.fn()} />);
    expect(screen.getByRole("option", { name: "Main d'œuvre" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Modifier" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
  });
});